"""Properly count truly empty msgstr entries (handles multi-line literals)."""
import re
from pathlib import Path

PO = Path(__file__).resolve().parent.parent / "horilla" / "locale" / "zh_Hant" / "LC_MESSAGES" / "django.po"
src = PO.read_text(encoding="utf-8")
blocks = src.split("\n\n")

STR_LITERAL = r'"(?:[^"\\]|\\.)*"'
MSGID_RE = re.compile(rf'msgid ({STR_LITERAL})((?:\n{STR_LITERAL})*)')
MSGSTR_RE = re.compile(rf'msgstr ({STR_LITERAL})((?:\n{STR_LITERAL})*)')
PART_RE = re.compile(rf'"((?:[^"\\]|\\.)*)"')


def join_parts(text: str) -> str:
    return "".join(PART_RE.findall(text))


truly_empty = []
for b in blocks[1:]:
    ms = MSGSTR_RE.search(b)
    mi = MSGID_RE.search(b)
    if not (ms and mi):
        continue
    msgstr = join_parts(ms.group(1) + ms.group(2))
    msgid = join_parts(mi.group(1) + mi.group(2))
    if msgstr == "" and msgid != "":
        truly_empty.append(msgid)

print(f"Truly untranslated: {len(truly_empty)}")
for u in truly_empty:
    print(" -", repr(u))
