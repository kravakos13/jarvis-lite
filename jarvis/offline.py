"""Jarvis Lite (no AI): what Jarvis says when no command matched. There is no language model at all.

* small talk (greetings, «как дела», jokes, facts, «расскажи что-нибудь»…) — canned Russian lines from
  jarvis/data/smalltalk_ru.txt, picked from a shuffled bag per topic, never the same line twice in a row;
* a real question («что такое…», «почему…», «сколько стоит…») — «Я без ИИ, на такое не отвечаю. Загуглить?»,
  «да» opens the search in the browser;
* a command-like phrase close to a known command — «Не понял команду. Может, «закрой хром»?» («да» runs it);
* anything else — a short hint + «Загуглить?» (one word: only the hint).
Pure Python, no network, no model: it always answers instantly (never hangs)."""
from __future__ import annotations

import difflib
import logging
import random
import re
from pathlib import Path
from typing import Callable, Optional

from .skills.base import Confirm, ToolResult
from .wake import normalize

log = logging.getLogger(__name__)

DATA = Path(__file__).resolve().parent / "data" / "smalltalk_ru.txt"
UNKNOWN = "Не понял команду. Скажи «что ты умеешь»."
UNKNOWN_GOOGLE = "Не понял команду — скажи «что ты умеешь». Или загуглить «{q}»?"
QUESTION = "Я без ИИ, на такие вопросы не отвечаю. Загуглить «{q}»?"

# topic -> pattern over the normalize()d phrase (the name and filler are already stripped)
TOPICS: list[tuple[str, re.Pattern]] = [(k, re.compile(p)) for k, p in (
    ("chat", r"^(?:ну |а |слушай |давай )*(?:давай )?(?:поболтаем|поговорим|побеседуем|потрещим|поболтать|поговорить)"
             r"(?: со мной| немного| просто| о чем нибудь| о чем то| за жизнь)*$|^(?:поговори|поболтай) со мной"
             r"|^(?:включи |режим )?(?:режим беседы|беседа)$"),
    ("joke", r"\b(?:анекдот\w*|шутк\w*|пошути\w*|рассмеши\w*|прикол\w*|что нибудь смешное|смешное)\b"),
    ("fact", r"\b(?:факт\w*|что нибудь интересное|интересное|удиви\w*|что нибудь познавательное)\b"),
    ("story", r"^расскажи(?: мне)?(?: что нибудь| что то| чего нибудь| историю| байку| сказку)?(?: интересное| новенькое)?$"),
    ("how", r"^(?:ну )?как (?:дела|ты|жизнь|поживаешь|настроение|сам|у тебя дела|оно|делишки)(?: вообще| сегодня| у тебя)*$"
            r"|^что нового$|^как ты там$"),
    ("doing", r"^(?:что|чем) (?:делаешь|занят|занимаешься)(?: сейчас)?$"),
    ("greet", r"^(?:привет\w*|здравствуй\w*|здорово|здорова|хай|хеллоу|салют|приветствую|добрый (?:день|вечер)|"
              r"доброе утро|доброй ночи|йо)(?: \w+)?$"),
    ("thanks", r"^(?:спасибо|спасиб|благодарю|спс|пасиб\w*)(?: тебе| большое| огромное| друг)*$|^(?:ты )?(?:молодец|"
               r"красава|красавчик|умница|умничка|лучший|крут|супер|класс|огонь)$|^(?:ты )?(?:просто )?(?:лучший|"
               r"молодец|крутой)(?: помощник| ассистент)?$"),
    ("who", r"^(?:кто ты|ты кто|кто ты такой|как тебя зовут|что ты такое|ты кто такой|представься|кто ты есть)$"),
    ("bye", r"^(?:пока|пока пока|до свидания|до встречи|до завтра|спокойной ночи|споки|бывай|увидимся)$"),
    ("bored", r"^(?:мне )?(?:скучно|скукота|нечем заняться)$"),
    ("sad", r"^(?:мне )?(?:грустно|плохо|тоскливо|одиноко|хреново|паршиво)$|^я (?:устал|устала|грущу)$"),
    ("love", r"^я тебя (?:люблю|обожаю)$|^ты мне нравишься$|^люблю тебя$"),
    ("rude", r"^(?:ты )?(?:тупой|тупица|дурак|идиот|глупый|бестолковый|бесполезный|дебил|придурок)$"),
    ("ok", r"^(?:ок|окей|понятно|ясно|ладно|хорошо|угу|ага|понял|поняла)$"),
)]

QUESTION_RE = re.compile(
    r"^(?:а |слушай |скажи(?: мне)? |подскажи(?: мне)? |расскажи(?: мне)? |объясни(?: мне)? |ты знаешь )*"
    r"(?:что так\w+|что значит|что означает|что будет если|кто так\w+|кто (?:такой|такая|такие|был|была|изобрел|"
    r"придумал|написал|создал|открыл)|почему|зачем|отчего|как (?:сделать|приготовить|работает|устроен\w*|"
    r"называется|правильно|лучше|научиться|избавиться|стать|выучить|быстро|можно|долго)|сколько (?:стоит|весит|"
    r"лет|живет|живут|длится|километров|метров|людей|человек)|где (?:находится|живет|живут|купить|найти)|"
    r"когда (?:был|была|было|были|будет|начал\w*|появил\w*)|какой|какая|какое|какие|чем отличается|"
    r"в чем разница|правда ли|можно ли|нужно ли|стоит ли|есть ли|про |о |об )\b.*")
EXPLAIN_RE = re.compile(r"^(?:объясни|расскажи)(?: мне)? (?:про|о|об|что такое|как|почему) .+")
NAME_RE = re.compile(r"^(?:джарвис|jarvis)[\s,]*", re.I)


class SmallTalk:
    """Canned lines per topic; a shuffled bag each, so lines do not repeat until the bag is empty and the
    same line never comes twice in a row (also across refills)."""

    def __init__(self, path: Path = DATA, rng: Optional[random.Random] = None):
        self.rng = rng or random.Random()
        self.lines = self.load(path)
        self._bags: dict[str, list[str]] = {}
        self._last: dict[str, str] = {}

    @staticmethod
    def load(path: Path) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        topic = ""
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as e:
            log.warning("Нет файла фраз %s: %s", path, e)
            return {}
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            m = re.match(r"^\[(\w+)\]$", line)
            if m:
                topic = m.group(1)
                out.setdefault(topic, [])
            elif topic:
                out[topic].append(line)
        return out

    def topic(self, t: str) -> str:
        for name, rx in TOPICS:
            if rx.search(t):
                return name
        return ""

    def pick(self, topic: str) -> str:
        pool = self.lines.get(topic) or []
        if not pool:
            return ""
        bag = self._bags.get(topic)
        if not bag:
            bag = list(pool)
            self.rng.shuffle(bag)
            if len(bag) > 1 and bag[-1] == self._last.get(topic):
                bag[0], bag[-1] = bag[-1], bag[0]          # the next pop() is never the line said last
            self._bags[topic] = bag
        line = bag.pop()
        self._last[topic] = line
        return line


def _fill(line: str, cfg: dict) -> str:
    a = (cfg or {}).get("assistant") or {}
    return line.replace("{name}", str(a.get("name", "Джарвис"))).replace("{user_name}", str(a.get("user_name", "Флоки")))


def is_question(text: str, t: str) -> bool:
    if len(t.split()) < 2:
        return False
    return bool(QUESTION_RE.match(t) or EXPLAIN_RE.match(t) or (text.strip().endswith("?") and len(t.split()) >= 3))


def search_query(text: str) -> str:
    q = NAME_RE.sub("", (text or "").strip()).strip(" ,.!?")
    q = re.sub(r"^(?:а|слушай|скажи(?: мне)?|подскажи(?: мне)?|ты знаешь)[\s,]+", "", q, flags=re.I)
    return q


class OfflineBrain:
    """The no-AI answer for a phrase nothing else understood (the phrase had the name; no-name phrases never
    get here). cfg["smalltalk"]: enabled (canned chat), suggest (closest command)."""

    def __init__(self, cfg: dict, web_search: Callable[[str], ToolResult], run_command: Callable[[str], ToolResult],
                 examples: Optional[list[str]] = None, talk: Optional[SmallTalk] = None):
        self.cfg = cfg
        self.web_search = web_search
        self.run_command = run_command
        self.talk = talk or SmallTalk()
        self.examples = examples if examples is not None else self._examples()

    @staticmethod
    def _examples() -> list[str]:
        try:
            from .manual import COMMANDS
            seen: dict[str, None] = {}
            for row in COMMANDS:
                ex = normalize(row[1])
                if ex and row[2] != "offline":
                    seen.setdefault(ex, None)
            return list(seen)
        except Exception as e:                               # noqa: BLE001
            log.debug("examples: %s", e)
            return []

    def suggest(self, t: str) -> str:
        if not t or not self.examples:
            return ""
        best = difflib.get_close_matches(t, self.examples, n=1, cutoff=0.72)
        return best[0] if best and best[0] != t else ""

    @property
    def _opts(self) -> dict:
        return (self.cfg or {}).get("smalltalk") or {}

    def answer(self, text: str) -> ToolResult:
        from .router import clean_command
        t = clean_command(normalize(NAME_RE.sub("", text or ""))) or normalize(text or "")
        t = re.sub(r"\s+", " ", t.replace("-", " ")).strip()         # «что-нибудь» -> «что нибудь»
        topic = self.talk.topic(t) if self._opts.get("enabled", True) else ""
        if topic == "story":
            topic = self.talk.rng.choice(["fact", "joke", "story"]) if self.talk.lines.get("story") else "fact"
        if topic:
            line = self.talk.pick(topic)
            if line:
                return ToolResult(_fill(line, self.cfg))
        if is_question(text, t):
            return self._google(QUESTION, search_query(text))
        return self.unknown(t, text)

    def _google(self, prompt: str, q: str) -> ToolResult:
        return ToolResult("", confirm=Confirm(prompt.format(q=q), on_yes=lambda: self.web_search(q),
                                              on_no_reply="Ладно."))

    def unknown(self, t: str, text: str = "") -> ToolResult:
        s = self.suggest(t) if self._opts.get("suggest", True) else ""
        if s:
            return ToolResult("", confirm=Confirm(f"Не понял команду. Может, «{s}»? Скажи «да» — сделаю.",
                                                  on_yes=lambda: self.run_command(s),
                                                  on_no_reply="Тогда скажи «что ты умеешь» — расскажу, что могу."))
        q = search_query(text) if text else ""
        if len(t.split()) >= 2 and q:
            return self._google(UNKNOWN_GOOGLE, q)
        return ToolResult(UNKNOWN)
