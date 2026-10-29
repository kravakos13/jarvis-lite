from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from ..wake import normalize


@dataclass
class Confirm:
    """A pending action that runs only after the user says yes."""
    prompt: str
    on_yes: Callable[[], "ToolResult"]
    on_no_reply: str = "Окей, отменил."


@dataclass
class ToolResult:
    reply: str
    action: Optional[str] = None                 # "exit" | "reset" | "dictation" | None
    then: Optional[Callable[[], Optional[str]]] = None   # runs after the reply is spoken; may return extra reply
    confirm: Optional[Confirm] = None
    background: bool = False                     # run `then` in a thread without waiting
    expect: Optional[Callable[[str], "ToolResult"]] = None  # next user phrase goes to this callback
    links: list = field(default_factory=list)    # [(title, url)] shown in the GUI chat
    voice: Optional[str] = None                  # speak with another Piper voice
    noname_say: bool = False                     # 1.0.9: speak this reply even for a no-name command (rare hints)


class Skill:
    """Base class. Subclasses implement match(): a fast, deterministic keyword/regex path (no AI)."""

    name = "skill"

    def __init__(self, ctx: "SkillContext"):
        self.ctx = ctx

    def match(self, text: str, norm: str) -> Optional[ToolResult]:
        return None


@dataclass
class SkillContext:
    cfg: dict
    say: Callable[..., None]                     # say_async(text, priority="normal"|"critical"|"low")
    notify: Callable[[str, str], None]
    project_root: Any = None
    extra: dict = field(default_factory=dict)


YES_RE = re.compile(r"^(да|ага|угу|конечно|давай|подтверждаю|выполняй|делай|точно|ок|окей|yes|загружай|жми|го)\b")
NO_RE = re.compile(r"^(нет|не надо|не нужно|отмена|отмени|стоп|не|no)\b")


def is_yes(text: str) -> bool:
    return bool(YES_RE.match(normalize(text)))


def is_no(text: str) -> bool:
    return bool(NO_RE.match(normalize(text)))
