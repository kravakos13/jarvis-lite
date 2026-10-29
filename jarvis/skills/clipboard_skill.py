"""Clipboard: read it aloud, open it in an online translator, read the screen text (OCR);
«переведи на английский <текст>» opens Google Translate with the text. No AI."""
from __future__ import annotations

import re
import urllib.parse
from typing import Optional

from .base import Skill, ToolResult

CLIP = r"(буфер\w*|буфер обмена|скопированн\w*|то что я скопировал)"
READ_RE = re.compile(rf"\b(прочитай|прочти|зачитай|что в)\b.*{CLIP}")
TRANSLATE_RE = re.compile(rf"\bпереведи\b.*{CLIP}(?:.*\bна (\w+))?")
EXPLAIN_RE = re.compile(rf"\b(объясни|перескажи|кратко|суммируй|что значит|исправь)\b.*{CLIP}")
SCREEN_RE = re.compile(r"\b(прочитай|прочти|зачитай)\b.*\b(текст )?(на|с) экран\w*")
LANG_W = r"(англ\w*|русск\w*|украин\w*|немец\w*|француз\w*|испан\w*|итальян\w*|польск\w*|китай\w*|японск\w*|турец\w*|португал\w*|корей\w*)"
PHRASE_RE = re.compile(rf"^переведи (?:на {LANG_W} (?:язык )?(.+)|(.+?) на {LANG_W}(?: язык)?)$")
SAY_RE = re.compile(rf"^как (?:будет|сказать|по) (.+?) (?:по[- ]?|на )?{LANG_W}(?: язык\w*)?$")
LANGS = {"англ": "en", "русск": "ru", "украин": "uk", "немец": "de", "француз": "fr", "испан": "es", "итальян": "it",
         "польск": "pl", "китай": "zh-CN", "японск": "ja", "турец": "tr", "португал": "pt", "корей": "ko"}


def get_clipboard() -> str:
    try:
        import pyperclip
        return pyperclip.paste() or ""
    except Exception:
        return ""


def lang_code(word: str) -> str:
    w = (word or "").lower()
    for stem, code in LANGS.items():
        if w.startswith(stem):
            return code
    return ""


def translate_url(text: str, target: str) -> str:
    return ("https://translate.google.com/?sl=auto&tl=" + target + "&op=translate&text="
            + urllib.parse.quote(text[:4000]))


class ClipboardSkill(Skill):
    name = "clipboard"

    def match(self, text: str, t: str) -> Optional[ToolResult]:
        if SCREEN_RE.search(t):
            from ..screen import read_text
            path = str((self.ctx.cfg.get("screen") or {}).get("tesseract_path", "") or "")
            return ToolResult("", then=lambda: read_text(path))
        if not re.search(CLIP, t):
            m = PHRASE_RE.match(t) or SAY_RE.match(t)
            if not m:
                return None
            g = [x for x in m.groups() if x]
            lang = next((x for x in g if lang_code(x) and x.split()[0] == x), "")
            phrase = next((x for x in g if x != lang), "")
            target = lang_code(lang)
            if not phrase or not target:
                return None
            import webbrowser
            url = translate_url(phrase, target)
            return ToolResult(f"Открываю переводчик: «{phrase}».", then=lambda: (webbrowser.open(url), None)[1])
        clip = get_clipboard().strip()
        if not clip and (READ_RE.search(t) or TRANSLATE_RE.search(t) or EXPLAIN_RE.search(t)):
            return ToolResult("Буфер обмена пуст.")
        m = TRANSLATE_RE.search(t)
        if m:
            target = lang_code(m.group(2) or "") or ("ru" if not re.search(r"[а-яё]", clip.lower()) else "en")
            import webbrowser
            url = translate_url(clip, target)
            return ToolResult("Открываю переводчик с текстом из буфера.", then=lambda: (webbrowser.open(url), None)[1])
        if EXPLAIN_RE.search(t):
            return ToolResult("Объяснять и пересказывать без ИИ не умею. Могу прочитать буфер вслух — скажи «прочитай буфер».")
        if READ_RE.search(t):
            return ToolResult(clip[:600] + ("... дальше слишком длинно." if len(clip) > 600 else ""))
        return None
