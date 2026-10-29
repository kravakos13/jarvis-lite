"""Per-request latency trace: end of speech -> STT -> routing -> first sound.

One Trace per command. Stages are recorded as they happen, from any thread (TTS runs on its own).
On finish a single log line is written, e.g.

    ⏱ «открой ютуб» быстрый путь (media): распознавание 0.31 с · маршрут 1 мс · до звука 0.52 с · всего 1.4 с
    ⏱ «расскажи анекдот» болталка: распознавание 0.35 с · маршрут 2 мс · до звука 0.60 с · всего 3.1 с

and the trace is kept in a small ring buffer for diagnostics ("Скорость ответа")."""
from __future__ import annotations

import logging
import statistics
import threading
import time
from collections import deque
from typing import Callable, Optional

log = logging.getLogger("jarvis.timing")

LABELS = {"stt": "распознавание", "route": "маршрут", "first_audio": "до звука", "total": "всего"}


class Trace:
    def __init__(self, text: str = "", source: str = "text", clock: Callable[[], float] = time.monotonic,
                 t0: Optional[float] = None):
        self.clock = clock
        self.t0 = clock() if t0 is None else t0
        self.text, self.source = text, source
        self.path = ""                     # skill name, or "offline" (canned chat)
        self.marks: dict[str, float] = {}  # stage -> seconds since t0 (first time only)
        self._lock = threading.Lock()

    def mark(self, stage: str) -> None:
        with self._lock:
            if stage not in self.marks:
                self.marks[stage] = self.clock() - self.t0

    def add(self, stage: str, seconds: float) -> None:
        with self._lock:
            self.marks[stage] = max(0.0, float(seconds))

    def get(self, stage: str) -> Optional[float]:
        return self.marks.get(stage)

    def summary(self) -> str:
        def f(x: float) -> str:
            return f"{x * 1000:.0f} мс" if x < 0.1 else f"{x:.2f} с"
        parts = []
        for k in ("stt", "route", "first_audio", "total"):
            if k in self.marks:
                parts.append(f"{LABELS[k]} {f(self.marks[k])}")
        where = "болталка" if self.path == "offline" else (f"быстрый путь ({self.path})" if self.path else "—")
        return f"«{self.text[:40]}» {where}: " + " · ".join(parts)


class Timings:
    """Ring buffer of finished traces + aggregate for diagnostics."""

    def __init__(self, keep: int = 50):
        self.items: deque = deque(maxlen=keep)

    def finish(self, tr: Trace) -> Trace:
        tr.mark("total")
        self.items.append(tr)
        log.info("⏱ %s", tr.summary())
        return tr

    def report(self) -> Optional[str]:
        """Short Russian summary of recent commands (median), or None if nothing measured yet."""
        if not self.items:
            return None
        fast = [t for t in self.items if t.path and t.get("first_audio") is not None]
        stt = [t.get("stt") for t in self.items if t.get("stt") is not None]
        out = []
        if stt:
            out.append(f"распознавание ~{statistics.median(stt):.2f} с")
        if fast:
            out.append(f"команды ~{statistics.median(t.get('first_audio') for t in fast):.1f} с до ответа")
        return f"За последние {len(self.items)} команд: " + ", ".join(out) + "." if out else None
