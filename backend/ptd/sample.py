"""A small realistic exam used to preview templates."""
from __future__ import annotations

from . import model as M


def sample_document() -> dict:
    B = []
    B.append(M.block("section", title="Part 1. Grammar", layout="standard"))
    B.append(M.block("instruction", text="Choose the correct answer A, B, C or D."))
    qs = [
        ("She ___ to school every day.", ["go", "goes", "going", "gone"]),
        ("Oʻquvchilar “kitob” soʻzini qanday tarjima qilishadi — book or look?", ["book", "look", "cook", "hook"]),
        ("I have lived in Tashkent ___ 2015.", ["for", "since", "from", "at"]),
        ("If it ___ tomorrow, we will stay at home and read the long story about the ancient city of Samarkand.",
         ["rains", "will rain", "rained", "is raining"]),
    ]
    for i, (t, opts) in enumerate(qs, start=1):
        B.append(M.question(t, number=str(i), qtype="mcq", options=[M.option("ABCD"[k], o) for k, o in enumerate(opts)]))
    B.append(M.block("section", title="Part 2. Reading", layout="reading"))
    B.append(M.block("instruction", text="Read the text and decide if the statements are True or False."))
    B.append(M.block("paragraph", text=(
        "Mirzo Ulugbek was a fifteenth-century astronomer and mathematician. He built a famous observatory in "
        "Samarkand, where scholars measured the positions of more than a thousand stars. His star catalogue was "
        "one of the most accurate of its time — and it is still admired by scientists today.")))
    for i, t in enumerate(["Ulugbek built an observatory in Bukhara.", "His catalogue was very accurate."], start=5):
        B.append(M.question(t, number=str(i), qtype="true_false", options=[M.option("A", "True"), M.option("B", "False")]))
    B.append(M.block("table", rows=[["Word", "Meaning", "Example"], ["observatory", "rasadxona", "The observatory is old."],
                                    ["catalogue", "katalog", "A catalogue of stars."]], header_rows=1))
    d = M.new_document("Sample English Examination", B)
    return d
