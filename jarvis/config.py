"""Jarvis Lite configuration: config.yaml (documented defaults) + settings.local.yaml (changes made in the GUI)."""
from __future__ import annotations

import copy
import logging
import os
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOCAL_SETTINGS = PROJECT_ROOT / "settings.local.yaml"

DEFAULTS: dict[str, Any] = {
    "assistant": {"name": "Джарвис", "user_name": "Флоки", "mode": "wake", "wake_reply": "Слушаю",
                  "greeting": "{hello}, мистер {user_name}, чего желаете?", "greeting_time_of_day": False,
                  "greet_on_start": True, "follow_up_seconds": 0, "extra_wake_words": [],
                  "conversation": {"enabled": True, "idle_s": 22},
                  "noname": {"enabled": True, "groups": {g: True for g in (
                      "media", "youtube", "nav", "browser", "windows", "explorer", "keys", "dictation", "apps",
                      "music", "smarthome", "search")}},
                  "request_timeout_s": 6, "request_silence_ms": 1200, "max_request_s": 15, "tts_tail_ms": 500,
                  "ack_after_s": 2.5},
    "stt": {"model": "small", "device": "cpu", "compute_type": "int8", "language": "ru", "beam_size": 1,
            "download_root": "models/whisper", "initial_prompt": "", "vad_filter": True},
    "audio": {"input_device": None, "output_device": None, "sample_rate": 16000, "vad": "webrtc",
              "vad_aggressiveness": 2, "energy_threshold": 0.015, "frame_ms": 30, "silence_ms": 500,
              "min_speech_ms": 250, "max_utterance_s": 15, "pre_roll_ms": 300},
    "tts": {"engine": "piper", "piper_voice": "ru_RU-denis-medium", "voices_dir": "voices", "length_scale": 1.1,
            "fx": {"enabled": True, "intensity": 0.35},
            "volume": 1.0, "pyttsx3_rate": 180, "pyttsx3_voice": "", "speak_in_text_mode": True},
    "tools": {"enabled": True, "websites": {}, "apps": {}},
    "windows": {"enabled": True, "never_close": []},
    "explorer": {"enabled": True},
    "view": {"enabled": True},                 # 1.0.9 «полный экран», «кинотеатр», «субтитры»
    "hotkeys": {"enabled": True},
    "nav": {"enabled": True},
    "smalltalk": {"enabled": True, "suggest": True},    # offline canned chat (jokes, facts, «как дела»)
    "keys": {"enabled": True},
    "gui": {"enabled": True, "always_on_top": False, "start_minimized": False, "close_to_tray": True,
            "hotkey_show": "ctrl+alt+j", "hotkey_ptt": "ctrl+alt+space", "hotkey_game": "ctrl+alt+g", "hotkey_stop": "ctrl+alt+x", "fps": None},
    "load": {"preset": "balanced", "log_every_s": 300},
    "autostart": {"enabled": True},
    "logging": {"level": "INFO", "file": "logs/jarvis.log"},
}


def deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def resolve_path(p: str | os.PathLike) -> Path:
    """Relative paths in the config are relative to the project root."""
    path = Path(os.path.expandvars(str(p))).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


CONFIG_VERSION = 1
MIGRATION_NOTICES: list[str] = []      # shown once by the assistant after start
# Jarvis Lite has no AI: sections of the full Jarvis that make no sense here are dropped from a copied
# settings.local.yaml (someone may copy the file over from the full version).
AI_SECTIONS = ("llm", "ollama", "chat", "translator", "code", "cad", "lumo", "google", "face_image")


def migrate_local(data) -> tuple[dict, bool]:
    """Clean a settings.local.yaml. Returns (data, changed)."""
    if not isinstance(data, dict):
        return {}, True
    changed = False
    for sec in AI_SECTIONS:
        if sec in data:
            data.pop(sec)
            changed = True
    stt = data.get("stt")
    if isinstance(stt, dict):
        if str(stt.get("device", "cpu")).strip().lower() != "cpu":
            stt.pop("device")                     # Lite always recognises on the processor
            changed = True
        if str(stt.get("compute_type", "")).strip().lower() in ("float16", "int8_float16", "bfloat16", "auto"):
            stt.pop("compute_type")
            changed = True
    gui = data.get("gui")
    if isinstance(gui, dict) and str(gui.get("face_style", "")).strip() not in ("", "2d"):
        gui.pop("face_style")
        changed = True
    if data.get("config_version") != CONFIG_VERSION:
        data["config_version"] = CONFIG_VERSION
        changed = True
    return data, changed


def apply_load_preset(cfg: dict) -> dict:
    """Fill the «Нагрузка» preset into keys the user did not set explicitly."""
    from .resources import preset
    pr = preset(cfg)
    stt, gui = cfg.setdefault("stt", {}), cfg.setdefault("gui", {})
    stt["device"] = "cpu"
    if stt.get("cpu_threads") in (None, "", 0):
        stt["cpu_threads"] = pr["threads"]
    if not gui.get("fps"):
        gui["fps"] = pr["face_fps"]
    return cfg


def raw_config(path: str | os.PathLike | None = None, use_local: bool = True) -> dict[str, Any]:
    """Merged config WITHOUT placeholder substitution (for the Settings window)."""
    cfg_path = Path(path) if path else PROJECT_ROOT / "config.yaml"
    if not cfg_path.exists():
        log.warning("Config %s not found, using defaults", cfg_path)
    try:
        user = _read_yaml(cfg_path)
    except Exception as e:      # broken config.yaml must not kill startup
        log.error("config.yaml повреждён (%s) — беру значения по умолчанию", e)
        user = {}
    cfg = deep_merge(DEFAULTS, user)
    if use_local:
        try:
            local, changed = migrate_local(_read_yaml(LOCAL_SETTINGS)) if LOCAL_SETTINGS.exists() else ({}, False)
            if changed:
                try:
                    with open(LOCAL_SETTINGS, "w", encoding="utf-8") as f:
                        yaml.safe_dump(local, f, allow_unicode=True, sort_keys=False)
                    log.info("settings.local.yaml обновлён до версии %d", CONFIG_VERSION)
                except OSError as e:
                    log.warning("Не удалось сохранить миграцию настроек: %s", e)
            cfg = deep_merge(cfg, local)
        except Exception as e:
            log.error("settings.local.yaml повреждён (%s) — игнорирую", e)
    for sec in AI_SECTIONS:                      # an old config.yaml copied from the full Jarvis
        cfg.pop(sec, None)
    return cfg


def update_inplace(base: dict, changes: dict) -> None:
    """Deep-update a live config dict so skills holding sub-dicts see new values."""
    for k, v in (changes or {}).items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            update_inplace(base[k], v)
        else:
            base[k] = copy.deepcopy(v)


def load_config(path: str | os.PathLike | None = None, use_local: bool = True) -> dict[str, Any]:
    cfg = raw_config(path, use_local)
    a = cfg["assistant"]
    # 1.0.7: the name goes to Whisper as a HOTWORD. Until 1.0.6 «{name}, привет.» was prepended to initial_prompt and
    # Whisper echoed it on noise -> phantom «Джарвис, привет.» commands (seen in users' logs).
    if a.get("name") and not cfg["stt"].get("hotwords"):
        cfg["stt"]["hotwords"] = str(a["name"])
    apply_load_preset(cfg)
    return cfg


def save_local_settings(changes: dict) -> None:
    """Merge `changes` into settings.local.yaml (keeps config.yaml with its comments untouched)."""
    try:
        current = _read_yaml(LOCAL_SETTINGS)
        if not isinstance(current, dict):
            raise ValueError("not a mapping")
    except Exception as e:
        log.error("settings.local.yaml повреждён (%s) — сохраняю копию и начинаю заново", e)
        try:
            LOCAL_SETTINGS.replace(LOCAL_SETTINGS.with_suffix(".yaml.broken"))
        except OSError:
            pass
        current = {}
    merged = deep_merge(current, changes)
    merged["config_version"] = CONFIG_VERSION
    tmp = LOCAL_SETTINGS.with_suffix(".yaml.tmp")
    with open(tmp, "w", encoding="utf-8") as f:     # atomic: a crash never leaves half a file
        yaml.safe_dump(merged, f, allow_unicode=True, sort_keys=False)
    os.replace(tmp, LOCAL_SETTINGS)
