"""CLI entry point (`minty` / `python -m minty`)."""

from __future__ import annotations

import argparse
import glob
import json
import shutil
import subprocess
import sys
from pathlib import Path

import jinja2

from minty.compiler import RecipeValidationError, compile_catalog
from minty.pdf import render_pdf_reportlab
from minty.pwa import write_pwa_assets

PKG_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = PKG_DIR / "templates"
APP_TS_PATH = PKG_DIR / "app.ts"


def _find_node22_plus() -> str | None:
    node = shutil.which("node")
    if node:
        return node
    matches = sorted(glob.glob("/nix/store/*-nodejs-2[24]*/bin/node"))
    return matches[-1] if matches else None


def compile_typescript(
    ts_path: Path, root_dir: Path, check_only: bool = False
) -> tuple[str, str]:
    """Bundle `minty/app.ts` via esbuild (preferred) or Node's built-in stripTypeScriptTypes."""
    tsc_bin = shutil.which("tsc")
    tsconfig = root_dir / "tsconfig.json"
    if tsc_bin and tsconfig.exists():
        subprocess.run([tsc_bin, "--noEmit", "-p", str(tsconfig)], check=True)

    if check_only:
        return "", "tsc" if tsc_bin else "syntax"

    esbuild_bin = shutil.which("esbuild")
    if esbuild_bin:
        res = subprocess.run(
            [
                esbuild_bin,
                str(ts_path),
                "--bundle",
                "--format=iife",
                "--target=es2022",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return res.stdout, "esbuild"

    node_bin = _find_node22_plus()
    if node_bin:
        res = subprocess.run(
            [
                node_bin,
                "--no-warnings",
                "-e",
                (
                    "const fs = require('node:fs');"
                    "const { stripTypeScriptTypes } = require('node:module');"
                    "process.stdout.write(stripTypeScriptTypes(fs.readFileSync(process.argv[1], 'utf8')));"
                ),
                str(ts_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return res.stdout, "node"

    raise RuntimeError(
        "Neither `esbuild` nor `node` (>=22.6) was found to compile minty/app.ts. "
        "Enter `nix-shell` or install `esbuild`."
    )


def build_project(root_dir: Path, check_only: bool = False) -> None:
    data_dir = root_dir / "data"
    dist_dir = root_dir / "dist"

    catalog = compile_catalog(data_dir)
    recipes = catalog["recipes"]
    bases = catalog["bases"]
    reviewed = catalog["reviewed_recipes"]
    unreviewed = catalog["unreviewed_recipes"]

    if check_only:
        compile_typescript(APP_TS_PATH, root_dir, check_only=True)
        print(
            f"✓ Validated {len(recipes)} recipes "
            f"({len(reviewed)} reviewed, {len(unreviewed)} unreviewed), "
            f"{len(bases)} base(s), {len(catalog['ingredients'])} ingredients, and app.ts."
        )
        return

    app_js, ts_engine = compile_typescript(
        APP_TS_PATH, root_dir, check_only=False
    )
    dist_dir.mkdir(parents=True, exist_ok=True)

    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=False,
        keep_trailing_newline=True,
    )

    payload = {
        "reviewed_count": catalog["reviewed_count"],
        "unreviewed_count": catalog["unreviewed_count"],
        "ingredients": catalog["ingredients"],
        "bases": bases,
        "recipes": recipes,
    }

    # 1. JSON export
    (dist_dir / "recipes.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # 2. Canonical Markdown
    md_out = env.get_template("ice_cream.md.j2").render(
        recipes=recipes,
        reviewed_recipes=reviewed,
        unreviewed_recipes=unreviewed,
        reviewed_count=len(reviewed),
        unreviewed_count=len(unreviewed),
        bases=bases,
    )
    (dist_dir / "ice_cream.md").write_text(md_out, encoding="utf-8")

    # 3. Web App (Desktop + Phone + Print)
    safe_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    html_out = env.get_template("app.html.j2").render(
        payload_json=safe_json,
        app_js=app_js,
    )
    (dist_dir / "index.html").write_text(html_out, encoding="utf-8")

    # 4. Typst + PDF Booklet
    typ_out = env.get_template("booklet.typ.j2").render(
        recipes=recipes,
        reviewed_count=len(reviewed),
        unreviewed_count=len(unreviewed),
        bases=bases,
    )
    typ_path = dist_dir / "ice_cream.typ"
    pdf_path = dist_dir / "ice_cream.pdf"
    typ_path.write_text(typ_out, encoding="utf-8")

    typst_bin = shutil.which("typst")
    if typst_bin:
        subprocess.run(
            [typst_bin, "compile", str(typ_path), str(pdf_path)], check=True
        )
        pdf_engine = "typst"
    else:
        render_pdf_reportlab(pdf_path, catalog["ingredients"], bases, recipes)
        pdf_engine = "reportlab"

    # 5. PWA manifest, icons, and offline service worker
    write_pwa_assets(dist_dir, html_out)

    print(
        f"✓ Built {len(recipes)} recipes "
        f"({len(reviewed)} reviewed, {len(unreviewed)} unreviewed):\n"
        f"  • dist/ice_cream.md\n"
        f"  • dist/index.html + PWA (TS via {ts_engine})\n"
        f"  • dist/recipes.json\n"
        f"  • dist/ice_cream.typ\n"
        f"  • dist/ice_cream.pdf (via {pdf_engine})"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="minty",
        description="Compile canonical 1.2L ice cream recipes to Markdown, Web, JSON, and PDF.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Project root containing data/ (defaults to current working directory).",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate YAML data and TypeScript without writing output files.",
    )
    args = parser.parse_args()
    try:
        build_project(args.root.resolve(), check_only=args.check)
    except RecipeValidationError as exc:
        print(f"✗ Validation error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
