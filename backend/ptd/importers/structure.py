"""Turn a reading-order stream of extracted items into document blocks.

Items (produced by the format-specific extractors):
  {"kind": "line", "text", "size", "bold", "italic", "page", "bbox", "new_para", "style"}
  {"kind": "image", "asset", "width", "height", "page", "bbox", "area_ratio"}
  {"kind": "table", "rows", "header_rows", "page", "bbox"}

The detector only *classifies and groups* text. It never rewrites, corrects, translates or
drops words: every character of every line ends up in exactly one block.
"""
from __future__ import annotations

import re
from collections import Counter

from .. import model

# "1. text", "12) text", "Question 3: text", "Savol 4. text"
Q_RE = re.compile(r"^\s*(?:(?:Question|Savol|Q)\s*)?(\d{1,3})\s*[.)]\s*(\S.*)?$", re.I)
Q_WORD_RE = re.compile(r"^\s*(?:Question|Savol)\s+(\d{1,3})\s*[:.)\-–]?\s*(.*)$", re.I)
OPT_RE = re.compile(r"^\s*\(?([A-Ha-h])\s*[).]\s*(.*)$")
INLINE_OPT_RE = re.compile(r"(?:(?<=\s)|^)\(?([A-Ha-h])\s?[).]\s+")
SECTION_RE = re.compile(
    r"^\s*(Part|Section|Task|Exercise|Unit|Listening|Reading|Writing|Speaking|Grammar|Vocabulary|"
    r"Use of English|Bo[ʻ'‘’`]?lim|Qism|Topshiriq|Mashq|Tinglash|O[ʻ'‘’`]?qish|Yozish|Gapirish)\b", re.I)
INSTR_RE = re.compile(
    r"^\s*(Choose|Circle|Read|Listen|Write|Complete|Answer|Match|Fill|Put|Underline|Tick|Mark|Decide|"
    r"Translate|Rewrite|Look|Find|Use|Select|Instructions?|Note|Directions?|"
    r"Tanlang|O[ʻ'‘’`]?qing|Tinglang|Yozing|To[ʻ'‘’`]?ldiring|Javob|Belgilang|Moslang|Tarjima)\b", re.I)
TF_WORDS = {"true", "false", "not given", "t", "f", "ng", "to'g'ri", "noto'g'ri", "yes", "no"}
GAP_RE = re.compile(r"_{3,}|\.{4,}|…{2,}|\(\s*\)")
MAP_WORDS = re.compile(r"\b(map|xarita|diagram|chart|graph|plan|scheme|sxema)\b", re.I)

LAYOUT_BY_WORD = {"listening": "listening", "tinglash": "listening", "reading": "reading",
                  "o'qish": "reading", "oqish": "reading", "writing": "writing", "yozish": "writing"}


def _layout_for(title: str) -> str:
    t = title.lower().replace("ʻ", "'").replace("‘", "'").replace("’", "'")
    for w, lay in LAYOUT_BY_WORD.items():
        if w in t:
            return lay
    return "standard"


def split_inline_options(text: str) -> tuple[str, list[dict]] | None:
    """'She ___ here. A) is B) are C) am' -> ('She ___ here.', [A..C]).
    Only splits when >= 2 consecutive labels (A,B,...) are found, to avoid false positives."""
    matches = list(INLINE_OPT_RE.finditer(text))
    if len(matches) < 2:
        return None
    # find the longest run of consecutive letters
    best: list[re.Match] = []
    for i in range(len(matches)):
        run = [matches[i]]
        for m in matches[i + 1:]:
            if ord(m.group(1).lower()) == ord(run[-1].group(1).lower()) + 1 and m.group(1).isupper() == run[0].group(1).isupper():
                run.append(m)
        if len(run) > len(best):
            best = run
    if len(best) < 2 or best[0].group(1).lower() not in "ab":
        return None
    # drop matches between run members that broke the chain: keep text attached to preceding option
    head = text[: best[0].start()].rstrip()
    opts = []
    for i, m in enumerate(best):
        end = best[i + 1].start() if i + 1 < len(best) else len(text)
        opts.append(model.option(m.group(1), text[m.end():end].strip()))
    return head, opts


_OCR_NUM = re.compile(r"^([0-9oOlI]{1,3})(\s*[.)]\s)")


def _ocr_number_fix(text: str) -> str:
    """OCR often reads '10.' as '1o.' - repair look-alike glyphs in the *number prefix only*."""
    m = _OCR_NUM.match(text)
    if not m or not any(c.isdigit() for c in m.group(1)):
        return text
    num = m.group(1).translate(str.maketrans("oOlI", "0011"))
    return num + m.group(2) + text[m.end():]


def merge_continued_tables(items: list[dict]) -> list[dict]:
    """A table interrupted only by a page break continues on the next page: merge it,
    dropping the repeated header row when it is identical."""
    out: list[dict] = []
    for it in items:
        if it["kind"] == "table":
            j = len(out) - 1
            while j >= 0 and out[j]["kind"] == "page_break":
                j -= 1
            prev = out[j] if j >= 0 else None
            if prev is not None and prev["kind"] == "table" and j < len(out) - 1 and \
                    max(map(len, prev["rows"])) == max(map(len, it["rows"])):
                rows = it["rows"]
                if rows and prev["rows"] and rows[0] == prev["rows"][0]:
                    prev.setdefault("dropped_rows", []).append(rows[0])
                    rows = rows[1:]
                prev["rows"] = prev["rows"] + rows
                prev["continued_pages"] = prev.get("continued_pages", 1) + 1
                continue
        out.append(it)
    return out


def _join(a: str, b: str, hard: bool = False) -> str:
    if not a:
        return b
    if hard:
        return a + "\n" + b
    if a.endswith("-") and b[:1].islower():
        return a + b  # keep the hyphen exactly as in the source
    return a + " " + b


class _State:
    def __init__(self):
        self.blocks: list[dict] = []
        self.q: dict | None = None
        self.q_paras = 0
        self.target: dict | None = None  # paragraph/instruction being extended

    def close_question(self):
        if self.q is not None:
            _finish_question(self.q)
        self.q = None
        self.q_paras = 0

    def push(self, b: dict):
        self.blocks.append(b)


def _finish_question(q: dict):
    opts = q.get("options", [])
    texts = {o["text"].strip().lower().rstrip(".") for o in opts}
    if opts and texts <= TF_WORDS:
        q["qtype"] = "true_false"
    elif len(opts) >= 2:
        q["qtype"] = "mcq"
    elif GAP_RE.search(q.get("text", "")):
        q["qtype"] = "gap_fill"
    elif re.search(r"\b(True|False)\s*/\s*(False|True)\b", q.get("text", ""), re.I):
        q["qtype"] = "true_false"


def detect(items: list[dict]) -> tuple[list[dict], dict]:
    items = merge_continued_tables(items)
    lines =[it for it in items if it["kind"] == "line" and it.get("text", "").strip()]
    sizes = Counter()
    for ln in lines:
        sizes[round(ln.get("size") or 11, 1)] += len(ln["text"])
    body = sizes.most_common(1)[0][0] if sizes else 11.0
    st = _State()
    source_numbers: list[str] = []
    section_hint = ""

    for it in items:
        kind = it["kind"]
        src = {k: it[k] for k in ("page", "bbox", "ocr", "confidence") if k in it}
        if kind == "image":
            kind_ = "image"
            if it.get("area_ratio", 0) > 0.35 or MAP_WORDS.search(section_hint):
                kind_ = "map"
            img = {"asset": it["asset"], "width": it.get("width"), "height": it.get("height"),
                   "kind": kind_, "source": src}
            if it.get("embedded_text"):
                img["embedded_text"] = it["embedded_text"]
            if st.q is not None and not st.q.get("options"):
                st.q.setdefault("images", []).append(img)
            else:
                st.close_question()
                st.target = None
                st.push(model.block("image", layout="full" if kind_ == "map" else "center", caption=None, **img))
            continue
        if kind == "table":
            inside = st.q is not None
            if st.q is not None and st.q.get("options"):
                st.close_question()
                inside = False
            st.target = None
            tb = model.block("table", rows=it["rows"], header_rows=it.get("header_rows", 1),
                             keep_with_prev=inside, source=src)
            if it.get("dropped_rows"):
                tb["repeated_header_dropped"] = it["dropped_rows"]
            st.push(tb)
            if inside:
                st.close_question()
            continue
        if kind != "line":
            continue
        raw = it["text"].rstrip()
        text = raw.strip()
        if not text:
            continue
        if it.get("ocr"):
            text = _ocr_number_fix(text)
        new_para = it.get("new_para", True)
        size = it.get("size") or body
        bold = bool(it.get("bold"))
        style_name = (it.get("style") or "").lower()

        # ---- question start
        mq = Q_WORD_RE.match(text) or Q_RE.match(text)
        if mq and not (SECTION_RE.match(text) and not text[:1].isdigit()):
            num, rest = mq.group(1), (mq.group(2) or "").strip()
            st.close_question()
            st.target = None
            q = model.question(rest, number=num, source={**src, "number": num})
            source_numbers.append(num)
            split = split_inline_options(rest) if rest else None
            if split:
                q["text"], q["options"] = split[0], split[1]
            st.q = q
            st.push(q)
            continue

        # ---- option line (only meaningful inside a question)
        mo = OPT_RE.match(text)
        if st.q is not None and mo:
            split = split_inline_options(text)
            opts = split[1] if split and not split[0] else [model.option(mo.group(1), mo.group(2).strip())]
            st.q["options"].extend(opts)
            continue

        # ---- headings / sections
        is_big = size >= body * 1.18
        is_caps = len(text) <= 70 and text.upper() == text and sum(c.isalpha() for c in text) >= 3
        is_section_word = bool(SECTION_RE.match(text)) and len(text) <= 90
        is_heading_style = style_name.startswith(("heading", "title"))
        short = len(text) <= 90 and not text.endswith((",", ";"))
        if new_para and short and (is_heading_style or is_section_word or is_big or (bold and is_caps) or
                                   (bold and len(text) <= 60 and st.q is None and not INSTR_RE.match(text))):
            st.close_question()
            st.target = None
            if is_section_word or (is_heading_style and "1" in style_name) or (is_big and size >= body * 1.4):
                section_hint = text
                st.push(model.block("section", title=text, layout=_layout_for(text), source=src))
            else:
                level = 1 if size >= body * 1.4 else 2
                st.push(model.block("heading", level=level, text=text, source=src))
            continue

        # ---- continuation of an open question
        if st.q is not None:
            if not new_para:
                if st.q["options"]:
                    st.q["options"][-1]["text"] = _join(st.q["options"][-1]["text"], text)
                else:
                    st.q["text"] = _join(st.q["text"], text)
                continue
            if not st.q["options"] and st.q_paras < 2 and len(text) < 220 and not INSTR_RE.match(text):
                st.q["text"] = _join(st.q["text"], text, hard=bool(st.q["text"]))
                st.q_paras += 1
                continue
            st.close_question()

        # ---- instruction / paragraph
        is_instr = bool(INSTR_RE.match(text)) and len(text) < 400 and (
            not st.blocks or st.blocks[-1]["type"] in ("heading", "section", "instruction") or it.get("italic"))
        if is_instr and new_para:
            b = model.block("instruction", text=text, source=src)
            st.push(b)
            st.target = b
            continue
        if st.target is not None and not new_para:
            st.target["text"] = _join(st.target["text"], text)
            continue
        b = model.block("paragraph", text=text, source=src)
        st.push(b)
        st.target = b

    st.close_question()
    info = {"body_size": body, "source_numbers": source_numbers}
    _mark_matching(st.blocks)
    return st.blocks, info


def _mark_matching(blocks: list[dict]):
    """Questions under a 'Match ...' instruction are matching exercises."""
    matching = False
    for b in blocks:
        if b["type"] in ("section", "heading"):
            matching = False
        elif b["type"] == "instruction":
            matching = bool(re.match(r"\s*(Match|Moslang)", b["text"], re.I))
        elif b["type"] == "question" and matching and b.get("qtype") in ("open", "mcq") and len(b.get("options", [])) <= 1:
            b["qtype"] = "matching"


def numbering_report(numbers: list[str]) -> list[dict]:
    """Detect gaps/duplicates in the source numbering (reported, never 'fixed' silently)."""
    issues = []
    prev = None
    seen = Counter()
    jumps = []
    for n in numbers:
        v = int(n)
        seen[v] += 1
        if prev is not None and v != prev + 1 and v != 1:
            jumps.append(f"{prev}→{v}")
        prev = v
    if jumps:
        issues.append({"code": "source_numbering_jump", "level": "warning",
                       "message": f"Source numbering is not continuous ({', '.join(jumps[:8])}). "
                                  "Check the original for missing questions; nothing was added or removed."})
    dups = sorted(v for v, c in seen.items() if c > 1)
    if dups:
        issues.append({"code": "source_numbering_duplicate", "level": "info",
                       "message": f"Question numbers {', '.join(map(str, dups[:10]))} appear more than once "
                                  "(numbering probably restarts per section). Use automatic numbering in the template for continuous numbers."})
    return issues
