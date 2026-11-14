"""Built-in terminology for Russian legal and government texts.

The general-purpose model renders these terms inconsistently or with misleading English
equivalents (край and область both become "province", автономный округ "Autonomous
District", Генеральный прокурор "Procurator"/"Attorney"). The rules below use the
established English forms (as in the official English text of the Russian Constitution).

Every Russian rule fires only in an unambiguous context, so ordinary uses of the same words
("область знаний", "край стола") are left alone:
  * "автономный округ" / "автономная область" (always administrative units);
  * a region name + край / область ("Пермский край", "Московской области");
  * lists of unit types ("республики, края, области", "краев и областей").
The English rules only unify spellings of the same institution and repair copied terms.
"""
from __future__ import annotations

import re

_PL_ADJ = r"(?:ые|ых|ым|ыми)"          # plural adjective endings
_SG_ADJ = r"(?:ый|ий|ого|ому|ым|ом|ая|ой|ую|ою|ое)"


def _num(adj_ending: str, singular: str, plural: str) -> str:
    return plural if re.fullmatch(_PL_ADJ, adj_ending) else singular


SOURCE_RULES: list[tuple[re.Pattern, object]] = [
    # автономный округ / автономные округа ...
    (re.compile(r"\b[Аа]втономн(ый|ого|ому|ым|ом|ые|ых|ым|ыми)\s+округ\w*"),
     lambda m: _num(m.group(1), "autonomous okrug", "autonomous okrugs")),
    # автономная область / автономной области ...
    (re.compile(r"\b[Аа]втономн(ая|ой|ую|ою|ые|ых|ым|ыми)\s+област\w*"),
     lambda m: _num(m.group(1), "autonomous oblast", "autonomous oblasts")),
    # Region name + край: "Пермский край", "Алтайского края" -> "Пермский kray"
    (re.compile(r"\b([А-ЯЁ][а-яё]+(?:ий|ого|ому|им|ом))\s+кра(?:й|я|ю|ем|е)\b"),
     lambda m: f"{m.group(1)} kray"),
    # Region name + область: "Московская область", "Читинской области" -> "Московская oblast"
    (re.compile(r"\b([А-ЯЁ][а-яё]+(?:ая|ой|ую|ою))\s+област(?:ь|и|ью)\b"),
     lambda m: f"{m.group(1)} oblast"),
    # Lists of unit types: "республики, края, области", "краев, областей", "края и области"
    (re.compile(r"\bкра(я|ев|ям|ями|ях|й)(?=\s*(?:,|и)\s*област)"),
     lambda m: "kray" if m.group(1) == "й" else "krays"),
    (re.compile(r"(?<=kray,\s)област(ь|и|ей|ям|ями|ях)\b|(?<=krays,\s)област(ь|и|ей|ям|ями|ях)\b"
                r"|(?<=kray и\s)област(ь|и|ей|ям|ями|ях)\b|(?<=krays и\s)област(ь|и|ей|ям|ями|ях)\b"),
     lambda m: "oblast" if (m.group(1) or m.group(2) or m.group(3) or m.group(4)) == "ь" else "oblasts"),
    # (Генеральный прокурор is fixed on the English side: replacing it in the Russian
    #  sentence confused the model about the sentence structure.)
]

TARGET_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(?:the\s+)?Federation Council\b"), "the Council of the Federation"),
    (re.compile(r"\bCouncil of Federation\b"), "Council of the Federation"),
    (re.compile(r"\b(?:General Prosecutor|Procurator[- ]General|Prosecutor-General|"
                r"Prosecutor-in-Chief|Attorney[- ]General)\b"), "Prosecutor General"),
    (re.compile(r"\bPros\w{0,3}ctor General\b"), "Prosecutor General"),
    # The model sometimes misspells the English words it has to copy ("autonomus").
    (re.compile(r"\b[Aa]uton\w*(?=\s+(?:okrugs?|oblasts?)\b)"), "autonomous"),
    (re.compile(r"\b(?:Autonomous|autonomous) (?:District|Okrug|Area)\b"), "autonomous okrug"),
    (re.compile(r"\b(Okrug|Oblast|Kray|krai|Krai)(s?)\b"), lambda m: {"okrug": "okrug", "oblast": "oblast"}
     .get(m.group(1).lower(), "kray") + m.group(2)),
    (re.compile(r"\b(the|a|an) \1\b", re.I), r"\1"),
]


def apply_source(text: str) -> str:
    for pat, rep in SOURCE_RULES:
        text = pat.sub(rep, text)
    return text


def apply_target(text: str) -> str:
    for pat, rep in TARGET_RULES:
        text = pat.sub(rep, text)
    # "Council of the Federation" at the start of a sentence keeps its capital "The".
    return re.sub(r"(^|[.!?]\s+)the Council of the Federation", r"\1The Council of the Federation", text)
