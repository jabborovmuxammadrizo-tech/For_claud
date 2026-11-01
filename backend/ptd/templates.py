"""Template schema, defaults and the built-in sample template library."""
from __future__ import annotations

from .util import deep_merge

DEFAULT_BRANDING = {
    "org_name": "MIRZO ULUGBEK NTM",
    "logo_asset": None,
    "secondary_logo_asset": None,
    "watermark": {"type": "text", "text": "MIRZO ULUGBEK NTM", "asset": None, "opacity": 0.06, "angle": 45,
                  "size": 54, "layer": "under"},
    "colors": {"primary": "#1E3A8A", "secondary": "#0F172A", "accent": "#DC2626", "text": "#111827",
               "muted": "#64748B", "page_bg": "#FFFFFF", "panel_bg": "#FFFFFF"},
    "header_text": "",
    "footer_text": "MIRZO ULUGBEK NTM — Examination materials",
    "teacher_name": "",
    "exam_title": "",
    "contact": "",
    "background_asset": None,
}

# branding fields a linked branding profile provides (colours only when the template inherits them)
IDENTITY_KEYS = ("org_name", "logo_asset", "secondary_logo_asset", "watermark", "header_text", "footer_text",
                 "teacher_name", "exam_title", "contact", "background_asset")

DEFAULT_TEMPLATE = {
    "schema": 1,
    "name": "Untitled template",
    "category": "custom",
    "tags": [],
    "description": "",
    "branding_profile_id": None,
    "branding": DEFAULT_BRANDING,
    "page": {"size": "A4", "orientation": "portrait", "width_mm": 210, "height_mm": 297,
             "margins_mm": {"top": 30, "bottom": 22, "left": 18, "right": 18},
             "background": {"color": None, "image_asset": None, "image_opacity": 0.15},
             "content_panel": False, "columns": 1, "column_gap_mm": 8},
    "fonts": {"body": "DejaVu Sans", "heading": "DejaVu Sans", "body_size": 10.5, "question_size": 10.5,
              "option_size": 10, "heading_sizes": [16, 13, 11.5], "line_spacing": 1.3},
    "header": {"enabled": True, "style": "line", "show_logo": True, "show_org": True, "show_title": True,
               "height_mm": 16, "text": ""},
    "footer": {"enabled": True, "text": None, "show_page_numbers": True, "page_number_format": "Page {page} of {total}",
               "align": "center", "number_cover": False},
    "cover": {"enabled": True, "style": "classic", "title": None, "subtitle": "", "show_logo": True,
              "fields": ["Full name", "Class / Group", "Date", "Score"], "instructions": "",
              "show_stats": True},
    "questions": {"numbering": "preserve", "number_format": "{n}.", "bold_number": True, "number_color": None,
                  "option_layout": "auto", "option_label_format": "{L})", "option_label_case": "preserve",
                  "keep_together": True, "box": False, "box_color": "#F1F5F9", "answer_lines": 0,
                  "show_points": True, "space_between_mm": 3},
    "sections": {"style": "bar", "uppercase": True, "page_break_before": False, "color": None},
    "instructions": {"style": "box", "italic": True},
    "tables": {"header_bg": None, "header_color": "#FFFFFF", "border_color": "#94A3B8", "stripe": True,
               "stripe_color": "#F1F5F9", "font_size": 9, "repeat_header": True, "min_font_size": 6.5},
    "images": {"max_width_pct": 90, "max_height_pct": 55, "align": "center", "full_width_maps": True,
               "border": False},
    "layouts": {
        "standard": {"columns": None, "badge": None},
        "listening": {"columns": 1, "badge": "LISTENING"},
        "reading": {"columns": 1, "badge": "READING"},
        "writing": {"columns": 1, "badge": "WRITING"},
        "instructions": {"columns": 1, "badge": "INSTRUCTIONS"},
        "answer_sheet": {"columns": 1, "badge": "ANSWER SHEET"},
        "results": {"columns": 1, "badge": "RESULTS"},
    },
    "pagination": {"density": "standard", "keep_options_with_question": True, "avoid_orphan_headings": True,
                   "widow_orphan_control": True, "preserve_source_page_breaks": False,
                   "section_layout_page_breaks": True},
    "answer_sheet": {"enabled": False, "options": 4},
    "export": {"quality": "print", "grayscale": False, "compressed_copy": True, "thumbnails": True,
               "page_images": False, "pdf_title_from_document": True},
}

DENSITY = {
    "compact": {"space": 0.65, "leading": 1.18},
    "standard": {"space": 1.0, "leading": 1.3},
    "spacious": {"space": 1.45, "leading": 1.45},
}


def normalize(cfg: dict | None) -> dict:
    """Fill missing keys from defaults so partially specified/imported templates always work."""
    t = deep_merge(DEFAULT_TEMPLATE, cfg or {})
    p = t["page"]
    if p.get("size") == "A4":
        w, h = 210, 297
        if p.get("orientation") == "landscape":
            w, h = h, w
        p["width_mm"], p["height_mm"] = w, h
    elif p.get("size") == "A5":
        w, h = 148, 210
        if p.get("orientation") == "landscape":
            w, h = h, w
        p["width_mm"], p["height_mm"] = w, h
    p["width_mm"] = max(70, min(1200, float(p["width_mm"])))
    p["height_mm"] = max(70, min(1200, float(p["height_mm"])))
    if t["pagination"]["density"] not in DENSITY:
        t["pagination"]["density"] = "standard"
    return t


def validate(cfg: dict) -> list[str]:
    t = normalize(cfg)
    errs = []
    m = t["page"]["margins_mm"]
    if any(v < 5 for v in m.values()):
        errs.append("Margins below 5 mm are not printable on most printers.")
    if m["left"] + m["right"] > t["page"]["width_mm"] - 60:
        errs.append("Left + right margins leave less than 60 mm for content.")
    if m["top"] + m["bottom"] > t["page"]["height_mm"] - 80:
        errs.append("Top + bottom margins leave less than 80 mm for content.")
    if t["header"]["enabled"] and t["header"]["height_mm"] > m["top"] - 4:
        errs.append("The header is taller than the top margin; increase the top margin.")
    if not (6 <= t["fonts"]["body_size"] <= 24):
        errs.append("Body font size must be between 6 and 24 pt.")
    return errs


def _t(name, category, desc, **over):
    return {"name": name, "category": category, "description": desc, **over}


NAVY, ROYAL, RED = "#0F1F4B", "#1D4ED8", "#DC2626"

BUILTIN = [
    _t("Mirzo Ulugbek NTM — Standard Examination", "standard",
       "Navy/royal-blue house style with red accents, cover page, keep-together questions.",
       tags=["standard", "exam", "general"], is_default=True,
       branding={"colors": {"primary": ROYAL, "secondary": NAVY, "accent": RED}},
       header={"style": "band"}, cover={"style": "band"}),
    _t("Beginner (A1) — Large Print", "beginner", "Larger fonts, spacious layout, boxed questions, two-column options.",
       tags=["beginner", "a1", "starter", "kids"],
       fonts={"body": "Open Sans", "heading": "Open Sans", "body_size": 12.5, "question_size": 12.5, "option_size": 12,
              "heading_sizes": [19, 15, 13]},
       questions={"box": True, "box_color": "#EFF6FF", "option_layout": "auto"},
       pagination={"density": "spacious"},
       branding={"colors": {"primary": "#2563EB", "secondary": NAVY, "accent": "#F59E0B"}}),
    _t("Elementary (A2)", "elementary", "Clean layout with underlined section headings.",
       tags=["elementary", "a2"], fonts={"body": "Roboto", "heading": "Roboto", "body_size": 11, "question_size": 11},
       sections={"style": "underline"}, branding={"colors": {"primary": "#0E7490", "secondary": NAVY, "accent": RED}}),
    _t("Pre-Intermediate (B1)", "pre_intermediate", "Standard density, line header, grid options.",
       tags=["pre-intermediate", "b1", "intermediate"], fonts={"body": "Liberation Sans", "heading": "Roboto"},
       branding={"colors": {"primary": "#4338CA", "secondary": NAVY, "accent": RED}}),
    _t("General English", "general_english", "Balanced house style for mixed-skill tests.",
       tags=["general", "english", "grammar", "vocabulary"], fonts={"body": "Open Sans", "heading": "Roboto", "body_size": 10.5},
       header={"style": "band"}, branding={"colors": {"primary": ROYAL, "secondary": NAVY, "accent": RED}}),
    _t("Certificate Examination", "certificate", "Formal certificate exam: classic cover, compact density, answer sheet.",
       tags=["certificate", "cefr", "ielts", "formal", "national"], fonts={"body": "Liberation Sans", "heading": "Liberation Sans", "body_size": 10},
       pagination={"density": "compact"}, cover={"style": "classic", "fields": ["Candidate name", "Candidate number", "Centre", "Date", "Signature"]},
       answer_sheet={"enabled": True, "options": 4},
       branding={"colors": {"primary": NAVY, "secondary": "#111827", "accent": RED},
                 "watermark": {"type": "text", "text": "CONFIDENTIAL", "opacity": 0.05}}),
    _t("Listening Test", "listening", "Listening layout with badge header and answer lines.",
       tags=["listening", "audio"], layouts={"standard": {"badge": "LISTENING"}},
       questions={"answer_lines": 0, "option_layout": "auto"},
       branding={"colors": {"primary": "#7C3AED", "secondary": NAVY, "accent": RED}}),
    _t("Reading Test", "reading", "Reading layout: justified passages, spacious line height.",
       tags=["reading", "passage", "comprehension"], fonts={"body": "Liberation Sans", "line_spacing": 1.4},
       layouts={"standard": {"badge": "READING"}},
       branding={"colors": {"primary": "#047857", "secondary": NAVY, "accent": RED}}),
    _t("Compact Two-Column Quiz", "custom", "Two-column compact layout for short quizzes (saves paper).",
       tags=["quiz", "compact", "short", "two-column"], page={"columns": 2, "margins_mm": {"top": 26, "bottom": 18, "left": 14, "right": 14}},
       pagination={"density": "compact"}, cover={"enabled": False},
       branding={"colors": {"primary": "#B91C1C", "secondary": NAVY, "accent": ROYAL}}),
]
