"""Jarvis Lite guarantees: no AI anywhere (no Ollama / LLM import or HTTP), CPU-only Whisper, offline small talk
without repeats, «не понял» + «загуглить?», and an identity that never collides with the full Jarvis."""
from __future__ import annotations

import ast
import random
import re
import socket
import subprocess
import sys
import types
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "jarvis"
FULL_JARVIS_APPID = "7C4D2A9E-5B1F-4E8A-9F3C-1A2B3C4D5E6F"
AI_MODULES = ("ollama", "jarvis.llm", "jarvis.ollama_setup", "jarvis.cuda_libs", "jarvis.lumo", "jarvis.google_auth",
              "torch", "openai", "langchain", "transformers", "llama_cpp")


# ---------------------------------------------------------------- no AI code at all
def test_no_ai_modules_in_the_package():
    names = {p.stem for p in PKG.rglob("*.py")}
    assert not names & {"llm", "ollama_setup", "cuda_libs", "lumo", "google_auth", "faceimage", "facecalib",
                        "head3d", "translator_skill", "chat_skill", "code_skill", "cad_skill", "screen_skill"}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            out |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            out.add(("." * n.level) + (n.module or ""))
    return out


@pytest.mark.parametrize("path", sorted(PKG.rglob("*.py")), ids=lambda p: str(p.relative_to(ROOT)))
def test_no_ai_imports_anywhere(path):
    bad = {m for m in _imports(path) if m.lstrip(".").split(".")[0] in ("ollama", "torch", "openai", "llama_cpp")
           or m.lstrip(".") in ("llm", "jarvis.llm", "ollama_setup", "cuda_libs", "lumo")}
    assert not bad, bad


def test_no_ollama_port_or_api_in_code():
    for p in PKG.rglob("*.py"):
        src = p.read_text(encoding="utf-8")
        assert "11434" not in src and "/api/chat" not in src and "/api/generate" not in src, p


def test_importing_the_whole_app_loads_no_ai_and_no_heavy_libs():
    """Lazy imports: the app modules load without Ollama/LLM, and without Whisper/CTranslate2 until STT starts."""
    code = ("import sys, os; os.environ['QT_QPA_PLATFORM']='offscreen';"
            "import jarvis.main, jarvis.assistant, jarvis.router, jarvis.offline, jarvis.gui.app, jarvis.gui.settings;"
            "print(sorted(m for m in sys.modules))")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    mods = set(ast.literal_eval(out.stdout.strip().splitlines()[-1]))
    assert not {m for m in mods if m.split(".")[0] in ("ollama", "torch", "openai") or m in AI_MODULES}
    assert not {m for m in mods if m.split(".")[0] in ("faster_whisper", "ctranslate2", "onnxruntime")}, \
        "Whisper / CTranslate2 must load lazily (only when the voice loop starts)"
    assert "PySide6.QtWebEngineWidgets" not in mods and "PySide6.QtWebEngineCore" not in mods


@pytest.fixture()
def assistant(monkeypatch):
    from jarvis.assistant import Assistant
    from jarvis.config import load_config
    cfg = load_config(use_local=False)
    cfg["alerts"]["enabled"] = False
    events: list = []
    a = Assistant(cfg, speak=False, need_stt=False, on_event=lambda ev, **d: events.append((ev, d)))
    a.events = events
    yield a
    a.stop_event.set()


def test_assistant_has_no_llm_and_never_connects_to_ollama(assistant, monkeypatch):
    seen: list = []
    real_connect = socket.socket.connect

    def connect(self, addr):
        seen.append(addr)
        raise OSError("network disabled in test")
    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket, "create_connection", lambda addr, *a, **k: (seen.append(addr), connect(None, addr)))
    assert not hasattr(assistant, "llm")
    for phrase in ("как дела", "расскажи анекдот", "расскажи интересный факт", "давай поболтаем", "что такое квазар",
                   "почему небо голубое", "сделай мне бутерброд пожалуйста", "что ты умеешь", "привет", "спасибо"):
        assistant.respond(phrase)
        assistant.router.pending_confirm = None
    assert not any(isinstance(x, tuple) and len(x) > 1 and x[1] == 11434 for x in seen)
    assert seen == []                                  # offline answers need no network at all
    assert real_connect is not None
    assert {"ollama", "jarvis.llm"}.isdisjoint(sys.modules)


# ---------------------------------------------------------------- offline small talk
def test_smalltalk_file_has_no_duplicate_lines_and_enough_material():
    from jarvis.offline import SmallTalk
    lines = SmallTalk().lines
    for topic, pool in lines.items():
        assert len(pool) == len(set(pool)), f"повтор в [{topic}]"
    assert len(lines["joke"]) >= 30 and len(lines["fact"]) >= 40 and len(lines["how"]) >= 5


@pytest.mark.parametrize("seed", range(5))
def test_smalltalk_never_repeats_until_exhausted_and_never_twice_in_a_row(seed):
    from jarvis.offline import SmallTalk
    st = SmallTalk(rng=random.Random(seed))
    n = len(st.lines["joke"])
    first = [st.pick("joke") for _ in range(n)]
    assert len(set(first)) == n                                       # whole bag before any repeat
    nxt = st.pick("joke")
    assert nxt != first[-1]                                           # not twice in a row across a refill
    seq = first + [nxt] + [st.pick("joke") for _ in range(3 * n)]
    assert all(a != b for a, b in zip(seq, seq[1:]))


def _brain(cfg=None):
    from jarvis.offline import OfflineBrain
    calls = {"web": [], "cmd": []}
    b = OfflineBrain(cfg or {"assistant": {"name": "Джарвис"}},
                     web_search=lambda q: calls["web"].append(q) or types.SimpleNamespace(reply=f"ищу {q}"),
                     run_command=lambda c: calls["cmd"].append(c) or types.SimpleNamespace(reply=c))
    return b, calls


@pytest.mark.parametrize("phrase", ["как дела", "Джарвис, как дела?", "расскажи анекдот", "расскажи что-нибудь",
                                    "интересный факт", "привет", "кто ты", "спасибо", "мне скучно", "пока"])
def test_canned_chat_is_instant_and_offline(phrase):
    b, calls = _brain()
    r = b.answer(phrase)
    assert r.reply and r.confirm is None and "{" not in r.reply and calls == {"web": [], "cmd": []}


def test_question_offers_to_google():
    b, calls = _brain()
    r = b.answer("что такое квазар")
    assert r.reply == "" and r.confirm is not None and "загуглить" in r.confirm.prompt.lower()
    assert "квазар" in r.confirm.prompt and "без ИИ" in r.confirm.prompt
    r.confirm.on_yes()
    assert calls["web"] and "квазар" in calls["web"][0]


def test_unknown_phrase_short_hint_plus_google():
    b, calls = _brain()
    r = b.answer("сделай мне бутерброд с сыром")
    assert r.confirm is not None and r.confirm.prompt.startswith("Не понял команду")
    assert "что ты умеешь" in r.confirm.prompt and "загуглить" in r.confirm.prompt.lower()
    assert len(r.confirm.prompt) < 140                                   # short
    r.confirm.on_yes()
    assert calls["web"] == ["сделай мне бутерброд с сыром"]
    one = b.answer("абырвалг")                                           # one word: just the hint
    assert one.confirm is None and one.reply.startswith("Не понял команду")


def test_typo_suggests_the_closest_command():
    b, calls = _brain()
    r = b.answer("закрой хромм")
    assert r.confirm is not None and "Может" in r.confirm.prompt
    r.confirm.on_yes()
    assert calls["cmd"]


def test_assistant_routes_unknown_to_offline_with_confirm(assistant):
    assistant.respond("сделай мне бутерброд с сыром")
    assert assistant.router.last_skill == "offline" and assistant.router.pending_confirm is not None
    assistant.router.pending_confirm = None
    assistant.respond("как дела")
    assert assistant.router.last_skill == "offline" and assistant.router.pending_confirm is None


def test_no_name_commands_never_get_small_talk(assistant):
    said: list = []
    assistant.say = lambda text, **k: said.append(text)                  # type: ignore[method-assign]
    assistant._respond_silent("как дела")
    assistant._respond_silent("расскажи анекдот")
    assert said == [] and assistant.router.pending_confirm is None


# ---------------------------------------------------------------- CPU-only speech recognition, load control
def test_whisper_is_always_cpu_int8_with_thread_cap(monkeypatch):
    from jarvis import stt as S
    made: list = []

    class WM:
        def __init__(self, model, **kw):
            made.append((model, kw))

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=WM, __version__="x"))
    s = S.SpeechToText({"model": "small", "device": "cuda", "compute_type": "float16", "cpu_threads": 3})
    model, kw = made[-1]
    assert model == "small" and kw["device"] == "cpu" and kw["compute_type"] == "int8" and kw["cpu_threads"] == 3
    assert s.device == "cpu"
    assert S.pick_device("cuda", "auto") == ("cpu", "int8")


def test_quiet_audio_never_reaches_whisper():
    from jarvis import stt as S
    calls: list = []
    s = S.SpeechToText.__new__(S.SpeechToText)
    s.model = types.SimpleNamespace(transcribe=lambda *a, **k: calls.append(1))
    s.language, s.beam_size, s.initial_prompt, s.vad_filter = "ru", 1, "", True
    assert s._transcribe(np.full(16000, 0.001, np.float32)) == "" and calls == []


def test_load_preset_defaults():
    from jarvis import resources as R
    from jarvis.config import load_config
    cfg = load_config(use_local=False)
    p = R.preset(cfg)
    assert p["priority"] == "below_normal" and p["threads"] == 4
    assert cfg["stt"]["cpu_threads"] == 4 and cfg["stt"]["vad_filter"] is True
    assert R.thread_env(2)["OMP_NUM_THREADS"] == "2" and R.thread_env(0) == {}


def test_camera_and_face_features_off_by_default():
    from jarvis.config import load_config
    cfg = load_config(use_local=False)
    flat = repr(cfg).lower()
    assert "face_image" not in flat and "facecalib" not in flat
    for sec in ("camera", "presence", "gestures"):
        assert not (cfg.get(sec) or {}).get("enabled", False), sec
    assert cfg["gui"].get("face_style", "2d") == "2d"


def test_no_face_reference_image_shipped():
    imgs = [p for p in ROOT.rglob("*") if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".glb", ".obj")
            and "build" not in p.parts and ".git" not in p.parts]
    assert [p.relative_to(ROOT).as_posix() for p in imgs] == ["assets/jarvis-lite.png"]
    assert not (ROOT / "faces").exists()


# ---------------------------------------------------------------- identity: never collides with the full Jarvis
def test_identity_strings():
    from jarvis import __version__
    from jarvis import platform_utils as pu
    from jarvis.gui import app
    assert __version__ == "1.0.0"
    assert app.APP_TITLE == "Jarvis Lite" and not app.APP_TITLE.startswith("Джарвис")
    assert pu.DATA_DIR_NAME == "JarvisLite" and pu.RUN_VALUE == "JarvisLite" and pu.VBS_NAME == "JarvisLite.vbs"
    assert (ROOT / "JarvisLite.vbs").exists() and not (ROOT / "Jarvis.vbs").exists()
    wd = (PKG / "watchdog.py").read_text(encoding="utf-8")
    assert "JarvisLiteWatchdog" in wd


def test_data_dir_is_localappdata_jarvislite(monkeypatch, tmp_path):
    from jarvis import platform_utils as pu
    monkeypatch.delenv("JARVIS_DATA_DIR", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(pu, "IS_WIN", True)
    d = pu.data_dir("Notes")
    assert d == tmp_path / "JarvisLite" / "Notes"


def test_installer_identity():
    iss = (ROOT / "installer" / "jarvis.iss").read_text(encoding="utf-8")
    appid = re.search(r"^AppId=\{\{([0-9A-F-]+)\}", iss, re.M).group(1)
    assert appid != FULL_JARVIS_APPID
    assert "DefaultDirName={localappdata}\\Programs\\JarvisLite" in iss
    assert "OutputBaseFilename=JarvisLiteSetup" in iss and '#define AppName "Джарвис Лайт"' in iss
    assert 'ValueName: "JarvisLite"' in iss and "JarvisLite.vbs" in iss
    assert "WINDOWTITLE eq Jarvis Lite*" in iss and "WINDOWTITLE eq Джарвис" not in iss
    assert "{localappdata}\\JarvisLite" in iss and "{userdocs}\\Jarvis" not in iss
    assert "ollama" not in iss.lower() and "6–7 ГБ" not in iss
    sh = (ROOT / "scripts" / "build_installer.sh").read_text(encoding="utf-8")
    assert "JarvisLiteSetup.exe" in sh and "OAUTH" not in sh


def test_sleeping_face_uses_few_frames():
    """Idle CPU: a sleeping/muted face repaints at most 8 fps (half the preset), awake at the preset fps."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from jarvis.gui.face import HologramFace
    QApplication.instance() or QApplication([])
    for fps, idle in ((15, 7), (10, 5), (30, 8)):
        f = HologramFace(fps=fps)
        f.set_state("sleeping")
        assert f.timer.interval() == int(1000 / idle)
        f.set_state("listening")
        assert f.timer.interval() == int(1000 / fps)
        f.show()
        f.hide()
        assert not f.timer.isActive()             # hidden window (tray) = no repaints at all


def test_lone_russian_letter_after_modifier():
    """Whisper writes «контрол шифт Т»: a bare consonant after a modifier is the Latin letter it names."""
    from jarvis import keyspeech as k
    assert k.parse("нажми контрол шифт т").combo == "ctrl+shift+t"
    assert k.parse("нажми альт ф").combo == "alt+f"
    assert k.parse("нажми контрол п").combo == "ctrl+p"
    assert k.parse("нажми т").text == "т"                 # alone it is still typed as a Russian letter
    assert k.parse("нажми контрол шифт тэ").combo == "ctrl+shift+t"
