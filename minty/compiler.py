"""YAML loading, schema validation, and gram/timer canonicalization."""

from __future__ import annotations

import re
from fractions import Fraction
from pathlib import Path
from typing import Any

import yaml

VALID_PHASES = {"prep", "flavor", "chill", "churn", "mix_in", "pack"}
CATEGORY_ORDER = {"Dairy": 0, "Fruit Cream": 1, "Sorbet": 2}

AMOUNT_RE = re.compile(
    r"^\s*(?P<num>\d+(?:\.\d+)?|\d+/\d+|\d+\s+\d+/\d+)\s*(?P<unit>g|grams?|tsp|tbsp|drops?)\s*$",
    re.IGNORECASE,
)

TIMER_RE = re.compile(
    r"^\s*(?:(?P<h>\d+)\s*h)?\s*(?:(?P<m>\d+)\s*m)?\s*(?:(?P<s>\d+)\s*s)?\s*$",
    re.IGNORECASE,
)


class RecipeValidationError(Exception):
    """Raised when a YAML data file violates the canonical recipe schema."""


def parse_number(raw: str) -> float:
    raw = raw.strip()
    if " " in raw and "/" in raw:
        whole, frac = raw.split(None, 1)
        return float(int(whole) + Fraction(frac))
    if "/" in raw:
        return float(Fraction(raw))
    return float(raw)


def format_grams(grams: float) -> str:
    if grams >= 10:
        return f"{round(grams)} g"
    rounded = round(grams, 2)
    if rounded == int(rounded):
        return f"{int(rounded)} g"
    return f"{rounded:g} g"


def format_tsp_hint(tsp_val: float) -> str:
    if tsp_val >= 3 and abs((tsp_val / 3) - round(tsp_val / 3)) < 0.08:
        return f"~{round(tsp_val / 3)} tbsp"
    eighths = round(tsp_val * 8)
    if eighths <= 0:
        return ""
    whole, rem = divmod(eighths, 8)
    frac_map = {
        1: "1/8",
        2: "1/4",
        3: "3/8",
        4: "1/2",
        5: "5/8",
        6: "3/4",
        7: "7/8",
    }
    frac = frac_map.get(rem, "")
    if whole and frac:
        return f"~{whole} {frac} tsp"
    if whole:
        return f"~{whole} tsp"
    return f"~{frac} tsp"


def compute_hint(ing_meta: dict[str, Any], grams: float) -> str:
    if ing_meta.get("g_per_drop"):
        drops = max(1, round(grams / ing_meta["g_per_drop"]))
        return f"~{drops} drop{'s' if drops != 1 else ''}"
    if ing_meta.get("g_per_tsp"):
        tsp = grams / ing_meta["g_per_tsp"]
        if tsp <= 3.2:
            return format_tsp_hint(tsp)
    return ""


def format_grams_with_hint(ing_meta: dict[str, Any], grams: float) -> str:
    g_str = format_grams(grams)
    hint = compute_hint(ing_meta, grams)
    return f"{g_str} ({hint})" if hint else g_str


def parse_amount_spec(
    raw_spec: str | float,
    item_id: str,
    ing_meta: dict[str, Any],
    context: str,
) -> dict[str, Any]:
    """Parse `<qty><unit> [| note]` and canonicalize to exact grams."""
    spec_str = (
        f"{raw_spec}g" if isinstance(raw_spec, (int, float)) else str(raw_spec)
    )
    if "|" in spec_str:
        amt_part, note_part = spec_str.split("|", 1)
        note = note_part.strip()
    else:
        amt_part, note = spec_str, ""

    m = AMOUNT_RE.match(amt_part)
    if not m:
        raise RecipeValidationError(
            f"{context}: invalid amount '{spec_str}' for '{item_id}'. "
            "Expected e.g. '300g', '0.8g', '1.5 tsp', '4 drops', or '120g | note'."
        )

    qty = parse_number(m.group("num"))
    unit = m.group("unit").lower()

    if unit in ("g", "gram", "grams"):
        grams = qty
    elif unit in ("tsp", "tbsp"):
        g_per_tsp = ing_meta.get("g_per_tsp")
        if not g_per_tsp:
            raise RecipeValidationError(
                f"{context}: '{item_id}' uses '{amt_part.strip()}' but has no "
                "`g_per_tsp` in data/ingredients.yaml."
            )
        tsp_qty = qty * 3.0 if unit == "tbsp" else qty
        grams = round(tsp_qty * float(g_per_tsp), 3)
    elif unit in ("drop", "drops"):
        g_per_drop = ing_meta.get("g_per_drop")
        if not g_per_drop:
            raise RecipeValidationError(
                f"{context}: '{item_id}' uses '{amt_part.strip()}' but has no "
                "`g_per_drop` in data/ingredients.yaml."
            )
        grams = round(qty * float(g_per_drop), 3)
    else:
        raise RecipeValidationError(f"{context}: unsupported unit '{unit}'")

    optional = bool(re.search(r"\boptional\b", note, re.IGNORECASE))
    clean_note = re.sub(
        r"^\s*optional\s*,?\s*", "", note, flags=re.IGNORECASE
    ).strip()

    return {
        "item": item_id,
        "name": ing_meta["name"],
        "grams": grams,
        "grams_fmt": format_grams(grams),
        "hint": compute_hint(ing_meta, grams),
        "display": format_grams_with_hint(ing_meta, grams),
        "optional": optional,
        "note": clean_note,
    }


def parse_timer(
    raw_timer: str | int | None, context: str
) -> tuple[int | None, str | None]:
    if raw_timer is None:
        return None, None
    if isinstance(raw_timer, int):
        sec = raw_timer
    else:
        s = str(raw_timer).strip()
        m = TIMER_RE.match(s)
        if not m or not any(m.groups()):
            raise RecipeValidationError(
                f"{context}: invalid timer '{raw_timer}' (use e.g. '45s', '2m30s', '20m', '2h')."
            )
        h = int(m.group("h") or 0)
        mins = int(m.group("m") or 0)
        secs = int(m.group("s") or 0)
        sec = h * 3600 + mins * 60 + secs

    if sec >= 3600 and sec % 3600 == 0:
        label = f"{sec // 3600} hr"
    elif sec >= 60 and sec % 60 == 0:
        label = f"{sec // 60} min"
    else:
        mm, ss = divmod(sec, 60)
        label = f"{mm}:{ss:02d}"
    return sec, label


def _load_yaml(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_ingredients(data_dir: Path) -> dict[str, dict[str, Any]]:
    path = data_dir / "ingredients.yaml"
    raw = _load_yaml(path)
    if not isinstance(raw, dict):
        raise RecipeValidationError(
            "data/ingredients.yaml must be a YAML mapping."
        )

    catalog: dict[str, dict[str, Any]] = {}
    for item_id, val in raw.items():
        if isinstance(val, str):
            catalog[item_id] = {"id": item_id, "name": val}
        elif isinstance(val, dict) and "name" in val:
            catalog[item_id] = {
                "id": item_id,
                "name": str(val["name"]),
                "g_per_tsp": float(val["g_per_tsp"])
                if "g_per_tsp" in val
                else None,
                "g_per_drop": float(val["g_per_drop"])
                if "g_per_drop" in val
                else None,
            }
        else:
            raise RecipeValidationError(
                f"data/ingredients.yaml: invalid entry for '{item_id}'."
            )
    return catalog


def compile_steps(
    raw_steps: list[dict[str, Any]],
    ingredients_catalog: dict[str, dict[str, Any]],
    context: str,
) -> list[dict[str, Any]]:
    if not isinstance(raw_steps, list) or not raw_steps:
        raise RecipeValidationError(
            f"{context}: 'steps' must be a non-empty list."
        )

    compiled: list[dict[str, Any]] = []
    for idx, step in enumerate(raw_steps, start=1):
        step_ctx = f"{context} step #{idx}"
        phase = step.get("phase")
        if phase not in VALID_PHASES:
            raise RecipeValidationError(
                f"{step_ctx}: invalid phase '{phase}'. Must be one of {sorted(VALID_PHASES)}."
            )
        title = step.get("title")
        do = step.get("do")
        if not title or not do:
            raise RecipeValidationError(
                f"{step_ctx}: must include 'title' and 'do'."
            )

        timer_sec, timer_label = parse_timer(step.get("timer"), step_ctx)

        inputs: list[dict[str, Any]] = []
        raw_add = step.get("add") or {}
        if not isinstance(raw_add, dict):
            raise RecipeValidationError(
                f"{step_ctx}: 'add' must be a mapping of ingredient: amount."
            )

        for item_id, amt_spec in raw_add.items():
            if item_id not in ingredients_catalog:
                raise RecipeValidationError(
                    f"{step_ctx}: unknown ingredient '{item_id}'. "
                    "Add it to data/ingredients.yaml first."
                )
            inputs.append(
                parse_amount_spec(
                    amt_spec, item_id, ingredients_catalog[item_id], step_ctx
                )
            )

        inputs_inline = ", ".join(
            f"{inp['display']} {inp['name']}"
            + (f" ({inp['note']})" if inp["note"] else "")
            + (" [optional]" if inp["optional"] else "")
            for inp in inputs
        )

        compiled.append(
            {
                "phase": phase,
                "title": str(title),
                "emoji": str(step.get("emoji", "")),
                "timer_sec": timer_sec,
                "timer_label": timer_label,
                "inputs": inputs,
                "inputs_inline": inputs_inline,
                "do": str(do).strip(),
            }
        )
    return compiled


def aggregate_ingredients(
    steps: list[dict[str, Any]],
    ingredients_catalog: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, bool], dict[str, Any]] = {}
    for s in steps:
        for inp in s["inputs"]:
            key = (inp["item"], inp["optional"])
            if key not in grouped:
                grouped[key] = {
                    "item": inp["item"],
                    "name": inp["name"],
                    "grams": 0.0,
                    "parts": [],
                    "notes": [],
                    "optional": inp["optional"],
                }
            entry = grouped[key]
            entry["grams"] += inp["grams"]
            entry["parts"].append(inp["grams"])
            if inp["note"] and inp["note"] not in entry["notes"]:
                entry["notes"].append(inp["note"])

    result: list[dict[str, Any]] = []
    for entry in grouped.values():
        meta = ingredients_catalog[entry["item"]]
        grams = round(entry["grams"], 3)
        notes_list: list[str] = []
        if len(entry["parts"]) > 1:
            split_str = " + ".join(format_grams(p) for p in entry["parts"])
            notes_list.append(f"split: {split_str}")
            extra_notes = [
                n
                for n in entry["notes"]
                if not re.match(r"^part\s+\d+", n, re.IGNORECASE)
            ]
            notes_list.extend(extra_notes)
        else:
            notes_list.extend(entry["notes"])
        result.append(
            {
                "item": entry["item"],
                "name": entry["name"],
                "grams": grams,
                "grams_fmt": format_grams(grams),
                "hint": compute_hint(meta, grams),
                "display": format_grams_with_hint(meta, grams),
                "parts": entry["parts"],
                "optional": entry["optional"],
                "note": "; ".join(notes_list),
            }
        )
    return result


def load_bases(
    data_dir: Path,
    ingredients_catalog: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    bases: dict[str, dict[str, Any]] = {}
    bases_dir = data_dir / "bases"
    if not bases_dir.exists():
        return bases

    for path in sorted(bases_dir.glob("*.yaml")):
        raw = _load_yaml(path)
        ctx = f"data/bases/{path.name}"
        base_id = raw.get("id")
        if base_id != path.stem:
            raise RecipeValidationError(
                f"{ctx}: 'id' ({base_id!r}) must match filename stem '{path.stem}'."
            )
        steps = compile_steps(raw.get("steps", []), ingredients_catalog, ctx)
        ings = aggregate_ingredients(steps, ingredients_catalog)
        yield_grams = round(
            sum(i["grams"] for i in ings if not i["optional"]), 3
        )

        for ing in ings:
            meta = ingredients_catalog[ing["item"]]
            ing["scales"] = {
                m: format_grams_with_hint(meta, ing["grams"] * m)
                for m in (1, 2, 3, 4)
            }

        bases[base_id] = {
            "id": base_id,
            "name": str(raw["name"]),
            "emoji": str(raw.get("emoji", "🥛")),
            "description": str(raw.get("description", "")),
            "steps": steps,
            "ingredients": ings,
            "yield_grams": yield_grams,
            "yield_scales": {
                m: format_grams(yield_grams * m) for m in (1, 2, 3, 4)
            },
            "used_by": [],
        }
    return bases


def load_recipes(
    data_dir: Path,
    ingredients_catalog: dict[str, dict[str, Any]],
    bases: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    recipes: list[dict[str, Any]] = []
    recipes_dir = data_dir / "recipes"

    for path in sorted(recipes_dir.glob("*.yaml")):
        raw = _load_yaml(path)
        ctx = f"data/recipes/{path.name}"
        recipe_id = raw.get("id")
        if recipe_id != path.stem:
            raise RecipeValidationError(
                f"{ctx}: 'id' ({recipe_id!r}) must match filename stem '{path.stem}'."
            )

        if not isinstance(raw.get("reviewed"), bool):
            raise RecipeValidationError(
                f"{ctx}: 'reviewed' must be explicitly set to true or false."
            )

        base_id = raw.get("base")
        base_obj = None
        if base_id:
            if base_id not in bases:
                raise RecipeValidationError(
                    f"{ctx}: unknown base '{base_id}'."
                )
            base_obj = bases[base_id]

        own_steps = compile_steps(
            raw.get("steps", []), ingredients_catalog, ctx
        )
        expanded_steps = (
            (base_obj["steps"] + own_steps) if base_obj else own_steps
        )
        ingredients = aggregate_ingredients(
            expanded_steps, ingredients_catalog
        )

        total_grams = round(
            sum(i["grams"] for i in ingredients if not i["optional"]), 3
        )
        optional_grams = round(
            sum(i["grams"] for i in ingredients if i["optional"]), 3
        )

        recipes.append(
            {
                "id": recipe_id,
                "name": str(raw["name"]),
                "emoji": str(raw.get("emoji", "🍨")),
                "category": str(raw["category"]),
                "reviewed": bool(raw["reviewed"]),
                "base": base_id,
                "base_name": base_obj["name"] if base_obj else None,
                "notes": str(raw.get("notes", "")).strip(),
                "own_steps": own_steps,
                "expanded_steps": expanded_steps,
                "ingredients": ingredients,
                "total_grams": total_grams,
                "total_grams_fmt": format_grams(total_grams),
                "optional_grams": optional_grams,
                "optional_grams_fmt": format_grams(optional_grams),
            }
        )

    recipes.sort(
        key=lambda r: (
            0 if r["reviewed"] else 1,
            CATEGORY_ORDER.get(r["category"], 99),
            r["name"],
        )
    )

    for r in recipes:
        if r["base"]:
            bases[r["base"]]["used_by"].append(r["name"])

    return recipes


def compile_catalog(data_dir: Path) -> dict[str, Any]:
    ingredients = load_ingredients(data_dir)
    bases = load_bases(data_dir, ingredients)
    recipes = load_recipes(data_dir, ingredients, bases)
    reviewed = [r for r in recipes if r["reviewed"]]
    unreviewed = [r for r in recipes if not r["reviewed"]]
    return {
        "reviewed_count": len(reviewed),
        "unreviewed_count": len(unreviewed),
        "ingredients": ingredients,
        "bases": list(bases.values()),
        "recipes": recipes,
        "reviewed_recipes": reviewed,
        "unreviewed_recipes": unreviewed,
    }
