"""Latency tracing (Trace / Timings), «Секунду» acknowledgement, diagnostics load section — Jarvis Lite (no AI)."""
from __future__ import annotations

import threading
import time
import types

import pytest

from jarvis.timing import Timings, Trace


# ---------------------------------------------------------------- timing
def test_trace_stages_and_summary():
    clock = types.SimpleNamespace(t=100.0)
    tr = Trace("расскажи анекдот", "voice", clock=lambda: clock.t)
    tr.add("stt", 0.35)
    clock.t = 100.4
    tr.add("route", 0.002)
    tr.path = "offline"
    clock.t = 101.3
    tr.mark("first_audio")
    tr.mark("first_audio")                                               # first time only
    clock.t = 104.0
    t = Timings()
    t.finish(tr)
    assert tr.get("first_audio") == pytest.approx(1.3) and tr.get("total") == pytest.approx(4.0)
    s = tr.summary()
    assert "болталка" in s and "распознавание 0.35 с" in s
    assert "до звука 1.30 с" in s and "маршрут 2 мс" in s
    assert "ИИ" not in s and "модел" not in s


def test_timings_report_for_diagnostics():
    t = Timings()
    for path, fa in [("system", 0.4), ("media", 0.6), ("offline", 0.5)]:
        tr = Trace("x", clock=lambda: 0.0)
        tr.path, tr.marks = path, {"stt": 0.3, "first_audio": fa}
        t.items.append(tr)
    r = t.report()
    assert "распознавание ~0.30 с" in r and "команды ~0.5 с" in r and "ИИ" not in r


def test_assistant_records_route_and_path():
    from jarvis.assistant import Assistant
    from jarvis.skills.base import ToolResult
    a = Assistant.__new__(Assistant)
    a.emit = lambda *x, **k: None                                       # type: ignore[method-assign]
    a._trace = tr = Trace("громче")
    a.router = types.SimpleNamespace(handle=lambda t: ToolResult(""), last_skill="system")
    a._run_result = lambda r: None                                       # type: ignore[method-assign]
    a.respond("громче")
    assert tr.path == "system" and tr.get("route") is not None


def test_diagnostics_load_section():
    from jarvis import diagnostics as D
    t = Timings()
    tr = Trace("x")
    tr.path, tr.marks = "system", {"first_audio": 0.4}
    t.items.append(tr)
    checks = {x.id: x for x in D._load(types.SimpleNamespace(timings=t))}
    assert "видеокарта не используется" in checks["load"].detail and "МБ" in checks["load"].detail
    assert "команды" in checks["speed"].detail

# ---------------------------------------------------------------- «Секунду» + early first clause
class _Speaker:
    def __init__(self):
        self.said = []

    def say(self, text, **k):
        self.said.append(text)


def _ack_assistant(after):
    from jarvis.assistant import Assistant
    a = Assistant.__new__(Assistant)
    a.cfg = {"assistant": {"ack_after_s": after}}
    a.speaker = _Speaker()
    a._ack_text = ""
    return a


def test_ack_only_when_slow():
    a = _ack_assistant(0.05)
    tr = Trace("найди курс доллара", "voice")
    a._trace = tr
    t = a._start_ack(tr, "voice")
    time.sleep(0.15)
    t.cancel()
    assert a.speaker.said == ["Секунду."]
    # «Секунду» is not counted as the answer
    a.emit = lambda *x, **k: None                                         # type: ignore[method-assign]
    a._on_tts("speech_start", text="Секунду.")
    assert tr.get("first_audio") is None
    a._on_tts("speech_start", text="Доллар стоит 41 гривну.")
    assert tr.get("first_audio") is not None


def test_no_ack_when_answer_came_fast_or_text_mode():
    a = _ack_assistant(0.05)
    tr = Trace("громче", "voice")
    a._trace = tr
    tr.mark("first_audio")
    t = a._start_ack(tr, "voice")
    time.sleep(0.15)
    assert a.speaker.said == []
    assert a._start_ack(Trace("x", "text"), "text") is None              # typed: nothing spoken
    assert _ack_assistant(0)._start_ack(tr, "voice") is None
    if t:
        t.cancel()


def test_thread_safety_of_trace():
    tr = Trace("x")
    ths = [threading.Thread(target=tr.mark, args=("first_audio",)) for _ in range(20)]
    [t.start() for t in ths]
    [t.join() for t in ths]
    assert "first_audio" in tr.marks
