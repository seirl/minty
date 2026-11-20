"""Printable A4 PDF booklet generator (ReportLab fallback when Typst is absent)."""

from __future__ import annotations

import glob
import os
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from minty.compiler import compute_hint, format_grams


def _find_ttf_font_family() -> dict[str, str] | None:
    search_dirs = [
        "/usr/share/fonts/truetype/dejavu",
        "/usr/share/fonts/TTF",
        "/run/current-system/sw/share/fonts/truetype",
    ]
    nix_matches = sorted(
        glob.glob("/nix/store/*-dejavu-fonts-2.*/share/fonts/truetype")
    )
    if nix_matches:
        search_dirs.append(nix_matches[-1])

    for d in search_dirs:
        reg = os.path.join(d, "DejaVuSans.ttf")
        bold = os.path.join(d, "DejaVuSans-Bold.ttf")
        ital = os.path.join(d, "DejaVuSans-Oblique.ttf")
        mono = os.path.join(d, "DejaVuSansMono-Bold.ttf")
        if all(os.path.exists(p) for p in (reg, bold, ital, mono)):
            return {"reg": reg, "bold": bold, "ital": ital, "mono": mono}
    return None


def render_pdf_reportlab(
    pdf_path: Path,
    ingredients_catalog: dict[str, dict[str, Any]],
    bases: list[dict[str, Any]],
    recipes: list[dict[str, Any]],
) -> None:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import (
        KeepTogether,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    fonts = _find_ttf_font_family()
    if fonts:
        pdfmetrics.registerFont(TTFont("BodySans", fonts["reg"]))
        pdfmetrics.registerFont(TTFont("BodySans-Bold", fonts["bold"]))
        pdfmetrics.registerFont(TTFont("BodySans-Ital", fonts["ital"]))
        pdfmetrics.registerFont(TTFont("BodyMono-Bold", fonts["mono"]))
        pdfmetrics.registerFontFamily(
            "BodySans",
            normal="BodySans",
            bold="BodySans-Bold",
            italic="BodySans-Ital",
            boldItalic="BodySans-Bold",
        )
        f_reg, f_bold, f_ital, f_mono = (
            "BodySans",
            "BodySans-Bold",
            "BodySans-Ital",
            "BodyMono-Bold",
        )
    else:
        f_reg, f_bold, f_ital, f_mono = (
            "Helvetica",
            "Helvetica-Bold",
            "Helvetica-Oblique",
            "Courier-Bold",
        )

    c_espresso = colors.HexColor("#1C1917")
    c_cocoa = colors.HexColor("#57534E")
    c_surface = colors.HexColor("#F6F1E7")
    c_cream = colors.HexColor("#FFFDF9")
    c_border = colors.HexColor("#DED6C3")
    c_amber = colors.HexColor("#B45309")
    c_amber_border = colors.HexColor("#F59E0B")
    c_green = colors.HexColor("#15803D")

    s_h1 = ParagraphStyle(
        "H1", fontName=f_bold, fontSize=17, leading=21, textColor=c_espresso
    )
    s_sub = ParagraphStyle(
        "Sub", fontName=f_reg, fontSize=9.2, leading=12, textColor=c_cocoa
    )
    s_card_title = ParagraphStyle(
        "CardTitle",
        fontName=f_bold,
        fontSize=12.5,
        leading=15,
        textColor=c_espresso,
    )
    s_note = ParagraphStyle(
        "Note", fontName=f_ital, fontSize=8.3, leading=11, textColor=c_cocoa
    )
    s_kicker = ParagraphStyle(
        "Kicker", fontName=f_bold, fontSize=7.5, leading=10, textColor=c_cocoa
    )
    s_cell = ParagraphStyle(
        "Cell",
        fontName=f_reg,
        fontSize=8.3,
        leading=10.8,
        textColor=c_espresso,
    )
    s_amt = ParagraphStyle(
        "Amt",
        fontName=f_mono,
        fontSize=8.2,
        leading=10.5,
        alignment=2,
        textColor=c_espresso,
    )
    s_step = ParagraphStyle(
        "Step",
        fontName=f_reg,
        fontSize=8.4,
        leading=11.2,
        textColor=c_espresso,
    )

    reviewed_cnt = sum(1 for r in recipes if r["reviewed"])
    unreviewed_cnt = len(recipes) - reviewed_cnt

    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title="1.2L Ice Cream & Sorbet Canonical Book",
    )
    avail_w = A4[0] - 28 * mm
    story: list[Any] = []

    banner = Table(
        [
            [Paragraph("1.2L Ice Cream &amp; Sorbet Canonical Book", s_h1)],
            [
                Paragraph(
                    f"All ingredients normalized to grams • {reviewed_cnt} Reviewed • {unreviewed_cnt} Unreviewed Drafts",
                    s_sub,
                )
            ],
        ],
        colWidths=[avail_w],
    )
    banner.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), c_surface),
                ("BOX", (0, 0), (-1, -1), 0.8, c_border),
                ("LEFTPADDING", (0, 0), (-1, -1), 12),
                ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                ("TOPPADDING", (0, 0), (0, 0), 10),
                ("BOTTOMPADDING", (0, -1), (0, -1), 10),
            ]
        )
    )
    story.append(banner)
    story.append(Spacer(1, 5 * mm))

    def fmt_pdf_amt(grams_fmt: str, hint: str, bold_grams: bool = True) -> str:
        g_part = (
            f"<b>{escape(grams_fmt)}</b>" if bold_grams else escape(grams_fmt)
        )
        if hint:
            return f"{g_part}<br/><font size='7' color='#57534E'>{escape(hint)}</font>"
        return g_part

    for b in bases:
        rows: list[list[Any]] = [
            [
                Paragraph("<b>Master White Base Ingredient</b>", s_cell),
                Paragraph("<b>1× Tub</b>", s_amt),
                Paragraph("<b>2× Tubs</b>", s_amt),
                Paragraph("<b>3× Tubs</b>", s_amt),
                Paragraph("<b>4× Tubs</b>", s_amt),
            ]
        ]
        for ing in b["ingredients"]:
            meta = ingredients_catalog[ing["item"]]
            rows.append(
                [
                    Paragraph(escape(ing["name"]), s_cell),
                    *[
                        Paragraph(
                            fmt_pdf_amt(
                                format_grams(ing["grams"] * m),
                                compute_hint(meta, ing["grams"] * m),
                            ),
                            s_amt,
                        )
                        for m in (1, 2, 3, 4)
                    ],
                ]
            )
        rows.append(
            [
                Paragraph(
                    f"<b>Total Base ({escape(b['yield_scales'][1])} / tub)</b>",
                    s_cell,
                ),
                Paragraph(f"<b>{escape(b['yield_scales'][1])}</b>", s_amt),
                Paragraph(f"<b>{escape(b['yield_scales'][2])}</b>", s_amt),
                Paragraph(f"<b>{escape(b['yield_scales'][3])}</b>", s_amt),
                Paragraph(f"<b>{escape(b['yield_scales'][4])}</b>", s_amt),
            ]
        )

        bt = Table(
            rows,
            colWidths=[
                avail_w * 0.40,
                avail_w * 0.15,
                avail_w * 0.15,
                avail_w * 0.15,
                avail_w * 0.15,
            ],
        )
        bt.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), c_surface),
                    ("BACKGROUND", (0, -1), (-1, -1), c_surface),
                    ("GRID", (0, 0), (-1, -1), 0.4, c_border),
                    ("BOX", (0, 0), (-1, -1), 0.8, c_border),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ]
            )
        )
        story.append(KeepTogether([bt, Spacer(1, 5 * mm)]))

    for r in recipes:
        status_html = (
            f'<font color="{c_green.hexval()}">[REVIEWED]</font>'
            if r["reviewed"]
            else f'<font color="{c_amber.hexval()}">[UNREVIEWED]</font>'
        )
        base_tag = (
            "White Base"
            if r["base"] == "white-base"
            else (r["base_name"] or "Standalone")
        )
        header_left = Paragraph(
            f"{escape(r['name'])} &nbsp; <font size='8.5' color='#57534E'>"
            f"({escape(r['category'])} • {escape(base_tag)})</font> &nbsp; "
            f"<font size='8'>{status_html}</font>",
            s_card_title,
        )
        header_right = Paragraph(
            f"Batch: {escape(r['total_grams_fmt'])}", s_amt
        )
        inner_w = avail_w - 18
        header_tbl = Table(
            [[header_left, header_right]],
            colWidths=[inner_w * 0.78, inner_w * 0.22],
        )
        header_tbl.setStyle(
            TableStyle(
                [
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ]
            )
        )

        ing_rows: list[list[Any]] = [
            [Paragraph("INGREDIENTS", s_kicker), Paragraph("", s_kicker)]
        ]
        for ing in r["ingredients"]:
            opt_txt = " (optional)" if ing["optional"] else ""
            note_txt = (
                f"<br/><font size='7' color='#57534E'>{escape(ing['note'])}</font>"
                if ing["note"]
                else ""
            )
            ing_rows.append(
                [
                    Paragraph(
                        f"{escape(ing['name'])}{opt_txt}{note_txt}", s_cell
                    ),
                    Paragraph(
                        fmt_pdf_amt(ing["grams_fmt"], ing["hint"]), s_amt
                    ),
                ]
            )
        col_left_w = avail_w * 0.38 - 10
        ing_table = Table(
            ing_rows, colWidths=[col_left_w * 0.68, col_left_w * 0.32]
        )
        ing_table.setStyle(
            TableStyle(
                [
                    ("LINEBELOW", (0, 0), (-1, -2), 0.35, c_border),
                    ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )

        step_paras: list[Any] = [
            Paragraph("STEPS", s_kicker),
            Spacer(1, 1 * mm),
        ]
        for idx, st in enumerate(r["expanded_steps"], start=1):
            t_str = (
                f" <font size='7.5' color='#15803D'>[{escape(st['timer_label'])}]</font>"
                if st["timer_label"]
                else ""
            )
            in_str = (
                f" — <b>{escape(st['inputs_inline'])}</b>"
                if st["inputs_inline"]
                else ""
            )
            step_paras.append(
                Paragraph(
                    f"<b>{idx}. {escape(st['title'])}</b>{t_str}{in_str}<br/>{escape(st['do'])}",
                    s_step,
                )
            )
            step_paras.append(Spacer(1, 1.4 * mm))

        card_rows: list[list[Any]] = [[header_tbl, ""]]
        if r["notes"]:
            card_rows.append([Paragraph(escape(r["notes"]), s_note), ""])
        card_rows.append([ing_table, step_paras])

        border_col = c_border if r["reviewed"] else c_amber_border
        card_tbl = Table(card_rows, colWidths=[avail_w * 0.39, avail_w * 0.61])
        style_cmds = [
            ("BACKGROUND", (0, 0), (-1, -1), c_cream),
            ("BOX", (0, 0), (-1, -1), 0.85, border_col),
            ("SPAN", (0, 0), (1, 0)),
            ("LINEBELOW", (0, 0), (-1, 0), 0.5, c_border),
            ("LEFTPADDING", (0, 0), (-1, -1), 9),
            ("RIGHTPADDING", (0, 0), (-1, -1), 9),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]
        if r["notes"]:
            style_cmds.append(("SPAN", (0, 1), (1, 1)))
            style_cmds.append(("TOPPADDING", (0, 1), (1, 1), 2))
            style_cmds.append(("BOTTOMPADDING", (0, 1), (1, 1), 2))
        card_tbl.setStyle(TableStyle(style_cmds))

        story.append(KeepTogether([card_tbl, Spacer(1, 3.8 * mm)]))

    def draw_footer(canvas: Any, doc_obj: Any) -> None:
        canvas.saveState()
        canvas.setFont(f_reg, 8)
        canvas.setFillColor(c_cocoa)
        canvas.drawString(
            14 * mm,
            8 * mm,
            f"1.2L Canonical Ice Cream Book • Reviewed: {reviewed_cnt}/{len(recipes)}",
        )
        canvas.drawRightString(A4[0] - 14 * mm, 8 * mm, f"Page {doc_obj.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=draw_footer, onLaterPages=draw_footer)
