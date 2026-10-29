"""Text helpers for speech output (Jarvis Lite: no language model; these only clean text before Piper)."""
from __future__ import annotations

import re

# CJK ideographs (+ext A, compat), kana, hangul, CJK/fullwidth punctuation
_CJK_RE = re.compile(r"[\u2E80-\u2FDF\u3000-\u303F\u3040-\u30FF\u3100-\u312F\u3130-\u318F\u31A0-\u31FF"
                     r"\u3200-\u32FF\u3400-\u4DBF\u4E00-\u9FFF\uA960-\uA97F\uAC00-\uD7AF\uF900-\uFAFF"
                     r"\uFE30-\uFE4F\uFF00-\uFF65]")
_CYR_RE = re.compile(r"[а-яёА-ЯЁ]")
_LETTER_RE = re.compile(r"[^\W\d_]")


def has_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(text or ""))


def strip_cjk(text: str) -> str:
    out = _CJK_RE.sub(" ", text or "")
    out = re.sub(r"\s+([,.!?…;:])", r"\1", out)
    return re.sub(r"[ \t]{2,}", " ", out).strip()



def clean_for_speech(text: str) -> str:
    """Remove markdown / emoji so TTS doesn't read symbols aloud."""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)      # [text](url)
    text = re.sub(r"https?://\S+", " ссылка ", text)
    text = re.sub(r"[*_#>|~]+", " ", text)
    text = re.sub(r"^\s*[-•]\s+", "", text, flags=re.M)
    text = re.sub(r"[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F]", "", text)  # emoji
    text = strip_cjk(text)                     # Piper cannot (and must not) speak hieroglyphs
    text = strip_mixed_junk(text)
    return re.sub(r"\s+", " ", text).strip()


_HOMO = str.maketrans("aeopcxykmtABEKMHOPCTXY", "аеорсхукмтАВЕКМНОРСТХУ")
_CYR = re.compile(r"[а-яё]", re.I)
_LAT = re.compile(r"[a-z]", re.I)


def _stutter(word: str) -> bool:
    """«systemsystsem», «httpshttps»: a Latin chunk of 4+ letters repeated inside one long word."""
    w = word.lower()
    return len(w) >= 8 and any(w.count(w[i:i + 4]) > 1 for i in range(len(w) - 3))


def strip_mixed_junk(text: str) -> str:
    """1.0.9: a broken generation glues Latin junk to Russian words («файловомуsystemsystsem»). In a Russian
    sentence: Latin glued onto a Cyrillic word is dropped, Latin homoglyphs inside a Cyrillic word are mapped to
    Cyrillic («фaйл»), stuttering Latin junk words are dropped. Real names (YouTube, Steam, Wi-Fi) stay."""
    words = text.split()
    if sum(1 for w in words if _CYR.search(w)) <= sum(1 for w in words if _LAT.search(w) and not _CYR.search(w)):
        return text                            # an English / code answer: leave it alone
    out = []
    for tok in re.split(r"(\s+)", text):
        if not tok or tok.isspace() or not _LAT.search(tok):
            out.append(tok)
            continue
        if _CYR.search(tok):
            letters = re.sub(r"[^a-zа-яё]", "", tok.lower())
            cyr = len(_CYR.findall(letters))
            fixed = tok.translate(_HOMO)
            if not _LAT.search(fixed):          # only homoglyphs: «фaйл» -> «файл»
                out.append(fixed)
                continue
            m = re.match(r"^(\W*[а-яё][а-яё\-]*?)([a-z][a-z\W]*)$", tok, re.I)
            if m and cyr >= 2:                  # «файловомуsystemsystsem» -> «файловому»
                tail = re.sub(r"[a-z]", "", m.group(2), flags=re.I)
                out.append(m.group(1) + tail)
                continue
            out.append(tok)
            continue
        if _stutter(re.sub(r"\W", "", tok)):
            out.append(re.sub(r"[a-z]+", "", tok, flags=re.I))
            continue
        out.append(tok)
    return "".join(out)


