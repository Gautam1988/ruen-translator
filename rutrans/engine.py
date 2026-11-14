"""Offline Russian -> English translation engine (Opus-MT model run by CTranslate2)."""
from __future__ import annotations

import os
import re
import sys
import threading
from pathlib import Path
from typing import Callable, Iterable

from . import legal

CYRILLIC = re.compile(r"[А-Яа-яЁё]")

# Common Russian abbreviations that end in a dot but do not end a sentence.
_ABBREV = {
    "т", "д", "п", "др", "пр", "см", "ср", "г", "гг", "в", "вв", "им", "ул", "д", "кв",
    "стр", "с", "рис", "табл", "гл", "т.е", "т.к", "т.д", "т.п", "и.о", "млн", "млрд",
    "тыс", "руб", "коп", "проф", "акад", "доц", "напр", "мин", "сек", "max", "min",
    "ок", "прим", "ред", "изд", "англ", "лат", "рус", "ст", "ч", "о", "оз", "р", "обл",
}

# A sentence ends at . ! ? … (optionally followed by quotes/brackets), then whitespace,
# then something that looks like a sentence start (capital letter, digit, quote, dash).
_SENT_END = re.compile(r'([.!?…]+["»”)\]]*)(\s+)(?=[«"“(\[]?[А-ЯЁA-Z0-9])')

# Abbreviations the model often mistranslates; expanded before translation.
_EXPAND = [
    (r"\bт\.\s?к\.", "так как"), (r"\bт\.\s?е\.", "то есть"), (r"\bт\.\s?д\.", "так далее"),
    (r"\bт\.\s?п\.", "тому подобное"), (r"\bв\s+т\.\s?ч\.", "в том числе"),
    (r"\bи\s+др\.", "и другие"), (r"\bи\s+пр\.", "и прочее"), (r"\bт\.\s?н\.", "так называемый"),
    (r"\bнапр\.", "например"),
]
_EXPAND = [(re.compile(p), r) for p, r in _EXPAND]

MAX_SENTENCE_CHARS = 600  # very long "sentences" get split further for the model

# Same punctuation normalisation the model was trained with (Moses replace-unicode-punctuation).
_PUNCT = str.maketrans({"«": '"', "»": '"', "„": '"', "“": '"', "”": '"', "‘": "'", "’": "'",
                        "´": "'", "–": "-", " ": " ", " ": " ", "，": ",", "：": ":"})


def normalize(s: str) -> str:
    s = s.translate(_PUNCT).replace("…", "...").replace("—", " - ")
    for pat, rep in _EXPAND:
        s = pat.sub(rep, s)
    return re.sub(r"\s+", " ", s).strip()


def resource_dir() -> Path:
    """Folder that holds bundled resources (works from source and from a PyInstaller build)."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def default_model_dir() -> Path:
    return resource_dir() / "models" / "opus-mt-ru-en"


def split_sentences(text: str) -> list[str]:
    """Split a paragraph into sentences. Joining the result with '' gives back the text."""
    pieces: list[str] = []
    start = 0
    for m in _SENT_END.finditer(text):
        # Look at the word right before the dot; skip known abbreviations and initials.
        before = text[start:m.start(1)]
        word = re.split(r"\s", before)[-1] if before else ""
        word_l = word.lower().strip("«\"(")
        if m.group(1).startswith(".") and (word_l in _ABBREV or len(word_l) == 1):
            # "в 2024 г. Проверка..." — a year abbreviation after a number ends the sentence.
            prev = re.split(r"\s+", before.rstrip()[: -len(word)].rstrip())[-1] if word else ""
            if not (word_l in ("г", "гг") and prev[-1:].isdigit()):
                continue
        pieces.append(text[start:m.end(2)])
        start = m.end(2)
    if start < len(text):
        pieces.append(text[start:])
    out: list[str] = []
    for p in pieces:
        out.extend(_split_long(p))
    return out


def _split_long(s: str) -> list[str]:
    if len(s) <= MAX_SENTENCE_CHARS:
        return [s]
    # Break at ; or , near the middle-ish, recursively.
    for sep in ("; ", ": ", ", ", " "):
        idx = s.rfind(sep, 0, MAX_SENTENCE_CHARS)
        if idx > MAX_SENTENCE_CHARS // 3:
            cut = idx + len(sep)
            return [s[:cut]] + _split_long(s[cut:])
    return [s[:MAX_SENTENCE_CHARS]] + _split_long(s[MAX_SENTENCE_CHARS:])


class Cancelled(Exception):
    pass


GLOSSARY_TEMPLATE = """\
# RuEn Translator glossary
# One term per line:   русский термин = English term
# Russian word endings are matched loosely, so "первый контур" also matches
# "первого контура", "первом контуре", etc. Lines starting with # are ignored.
# Click Save; the next translation uses the changes.
#
# Examples (remove the # to use them):
# первый контур = primary circuit
# активная зона = reactor core
# теплоноситель = coolant
# твэл = fuel rod
"""


def glossary_path() -> Path:
    base = Path(os.environ.get("APPDATA") or Path.home()) / "RuEnTranslator"
    return base / "glossary.txt"


def ensure_glossary() -> Path:
    p = glossary_path()
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(GLOSSARY_TEMPLATE, encoding="utf-8")
    return p


def _stem_pattern(word: str) -> str:
    if CYRILLIC.search(word) and len(word) >= 5:
        return re.escape(word[:-2]) + r"[а-яё]{0,4}"
    if CYRILLIC.search(word) and len(word) >= 4:
        return re.escape(word[:-1]) + r"[а-яё]{0,3}"
    return re.escape(word)


class Glossary:
    def __init__(self, path: Path | None = None):
        self.path = path or glossary_path()
        self._mtime = None
        self.entries: list[tuple[re.Pattern, str]] = []

    def refresh(self) -> bool:
        """Reload the file if it changed. Returns True when entries changed."""
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            mtime = None
        if mtime == self._mtime:
            return False
        self._mtime = mtime
        self.entries = []
        if mtime is None:
            return True
        pairs = []
        for line in self.path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            ru, en = (x.strip() for x in line.split("=", 1))
            if ru and en:
                pairs.append((ru, en))
        pairs.sort(key=lambda p: -len(p[0]))  # longest terms first
        for ru, en in pairs:
            pat = r"(?<![\w-])" + r"\s+".join(_stem_pattern(w) for w in ru.lower().split()) + r"(?![\w])"
            self.entries.append((re.compile(pat, re.IGNORECASE), en))
        return True

    def apply(self, text: str) -> str:
        for pat, en in self.entries:
            text = pat.sub(en, text)
        return text


class Translator:
    """Thread-safe wrapper around the CTranslate2 model with a translation cache."""

    def __init__(self, model_dir: str | os.PathLike | None = None, beam_size: int = 2,
                 threads: int | None = None):
        import ctranslate2
        import sentencepiece as spm

        model_dir = Path(model_dir or default_model_dir())
        if not (model_dir / "model.bin").exists():
            raise FileNotFoundError(f"Translation model not found in {model_dir}")
        threads = threads or max(1, (os.cpu_count() or 4))
        self._model = ctranslate2.Translator(
            str(model_dir), device="cpu", compute_type="int8",
            inter_threads=1, intra_threads=threads,
        )
        self._sp_src = spm.SentencePieceProcessor(model_file=str(model_dir / "source.spm"))
        self._sp_tgt = spm.SentencePieceProcessor(model_file=str(model_dir / "target.spm"))
        self.beam_size = beam_size
        self._cache: dict[str, str] = {}
        self._lock = threading.Lock()
        self.glossary = Glossary()

    # -- core -------------------------------------------------------------
    def _translate_core(self, sentences: list[str]) -> list[str]:
        tokens = [self._sp_src.encode(normalize(s), out_type=str) for s in sentences]
        with self._lock:
            results = self._model.translate_batch(
                tokens, beam_size=self.beam_size, max_batch_size=32,
                max_input_length=512, max_decoding_length=512,
                repetition_penalty=1.1, no_repeat_ngram_size=0,
            )
        return [legal.apply_target(self._sp_tgt.decode(r.hypotheses[0])) for r in results]

    def translate_sentences(self, sentences: list[str],
                            progress: Callable[[int, int], None] | None = None,
                            cancel: threading.Event | None = None,
                            chunk: int = 24) -> list[str]:
        """Translate stripped sentences. Non-Russian ones pass through unchanged.

        progress(done_chars, total_chars) is reported in characters, which track the work far
        better than a sentence count. Batches hold sentences of similar length (efficient), but
        are processed in a mixed order of short and long batches, so the speed measured early
        on is representative of the whole job (no time-left estimate that drifts up or down)."""
        self.glossary.refresh()
        sentences = [self.glossary.apply(legal.apply_source(s)) for s in sentences]
        todo = sorted({s for s in sentences if s not in self._cache and CYRILLIC.search(s)},
                      key=len)
        batches = [todo[i:i + chunk] for i in range(0, len(todo), chunk)]
        order = []
        lo, hi = 0, len(batches) - 1
        while lo <= hi:                     # longest, shortest, 2nd longest, 2nd shortest...
            order.append(hi)
            if lo != hi:
                order.append(lo)
            lo, hi = lo + 1, hi - 1
        total = sum(len(s) for s in todo)
        done = 0
        if progress:
            progress(0, total)
        for b in order:
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            batch = batches[b]
            for src, tgt in zip(batch, self._translate_core(batch)):
                self._cache[src] = tgt
            done += sum(len(s) for s in batch)
            if progress:
                progress(done, total)
        # A sentence fully covered by the glossary has no Russian left and is returned as is.
        return [self._cache.get(s, s) for s in sentences]

    def translate_texts(self, texts: Iterable[str],
                        progress: Callable[[int, int], None] | None = None,
                        cancel: threading.Event | None = None) -> list[str]:
        """Translate whole paragraphs, keeping their leading/trailing whitespace and line breaks."""
        texts = list(texts)
        # Each text -> lines -> sentences; each sentence keeps its surrounding whitespace.
        plans: list[list[list[tuple[str, str, str]]]] = []
        needed: list[str] = []
        for t in texts:
            lines_plan = []
            for line in t.split("\n"):
                sent_plan = []
                for s in split_sentences(line) if CYRILLIC.search(line) else [line]:
                    core = s.strip()
                    lead = s[:len(s) - len(s.lstrip())]
                    trail = s[len(s.rstrip()):]
                    sent_plan.append((lead, core, trail))
                    if core and CYRILLIC.search(core):
                        needed.append(core)
                lines_plan.append(sent_plan)
            plans.append(lines_plan)

        mapping = dict(zip(needed, self.translate_sentences(needed, progress, cancel)))
        out = []
        for lines_plan in plans:
            lines = []
            for sent_plan in lines_plan:
                lines.append("".join(lead + mapping.get(core, core) + trail
                                     for lead, core, trail in sent_plan))
            out.append("\n".join(lines))
        return out

    def translate(self, text: str) -> str:
        return self.translate_texts([text])[0]
