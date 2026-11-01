"""Suggest saved templates for a document. Suggestions only - the user's choice is never changed."""
from __future__ import annotations

import re

from . import model as M
from .templates import normalize

LEVEL_WORDS = {
    "beginner": ["beginner", "starter", "a1", "kids", "boshlang"],
    "elementary": ["elementary", "a2"],
    "pre_intermediate": ["pre-intermediate", "pre intermediate", "b1"],
    "certificate": ["certificate", "cefr", "ielts", "national", "milliy", "sertifikat", "b2", "c1"],
    "listening": ["listening", "listen", "audio", "tinglash", "tinglang"],
    "reading": ["reading", "read the text", "passage", "o'qish", "oʻqish"],
    "general_english": ["general english", "grammar", "vocabulary"],
}


def features(doc: dict) -> dict:
    st = M.stats(doc)
    text = " ".join(" ".join(M.block_texts(b)) for b in doc.get("blocks", [])[:80]).lower()
    title = (doc.get("title") or "").lower()
    layouts = [b.get("layout") for b in doc.get("blocks", []) if b["type"] == "section"]
    return {**st, "text": title + " " + text, "orientation": doc.get("meta", {}).get("orientation", "portrait"),
            "listening_sections": layouts.count("listening"), "reading_sections": layouts.count("reading"),
            "passage_ratio": st["paragraphs"] / max(1, st["blocks"])}


def recommend(doc: dict, templates: list[dict], limit: int = 3) -> list[dict]:
    f = features(doc)
    out = []
    for t in templates:
        cfg = normalize(t["config"])
        cat = cfg.get("category") or "custom"
        tags = [x.lower() for x in cfg.get("tags", [])]
        score, why = 0.0, []
        for w in LEVEL_WORDS.get(cat, []) + tags:
            if w and re.search(r"(?<!\w)" + re.escape(w) + r"(?!\w)", f["text"]):
                score += 3
                why.append(f"mentions “{w}”")
                break
        if cat == "listening" and f["listening_sections"]:
            score += 4
            why.append("has listening sections")
        if cat == "reading" and (f["reading_sections"] or f["passage_ratio"] > 0.25):
            score += 3
            why.append("contains reading passages")
        if f["questions"] >= 60 and cfg["pagination"]["density"] == "compact":
            score += 2
            why.append(f"{f['questions']} questions - compact layout saves paper")
        if f["questions"] <= 15 and cfg["pagination"]["density"] == "spacious":
            score += 1.5
            why.append("short test - spacious layout")
        if f["questions"] <= 25 and cfg["page"]["columns"] == 2 and f["images"] == 0 and f["tables"] == 0:
            score += 1
            why.append("short text-only quiz fits two columns")
        if (f["images"] or f["maps"]) and cfg["page"]["columns"] == 2:
            score -= 2
        if f["tables"] and cfg["page"]["columns"] == 2:
            score -= 2
        if f["orientation"] == "landscape" and cfg["page"]["orientation"] == "landscape":
            score += 2
            why.append("landscape pages")
        if t.get("is_default"):
            score += 0.5
            why.append("your default template")
        out.append({"template_id": t["id"], "name": t["name"], "score": round(score, 2), "reasons": why[:3]})
    out.sort(key=lambda r: -r["score"])
    return out[:limit]
