"""Speech-to-text with faster-whisper (offline after the model is downloaded).

Jarvis Lite: ALWAYS on the processor (CPU, int8) — CUDA is never probed or initialised, no GPU libraries are
loaded. Whisper runs only on phrases the VAD passed (audio.py) and only above a minimum loudness, so an idle
Jarvis Lite does not run the model at all."""
from __future__ import annotations

import logging
import re
from typing import Any, Callable, Optional
import threading
import time
from pathlib import Path

import numpy as np

from .config import resolve_path

log = logging.getLogger(__name__)

GPU_ONLY_COMPUTE = ("float16", "int8_float16", "bfloat16", "int8_bfloat16")


def pick_device(device: str = "cpu", compute_type: str = "auto") -> tuple[str, str]:
    """Jarvis Lite: the device is always the CPU; the compute type int8 unless a CPU type was set explicitly."""
    if not compute_type or compute_type == "auto" or compute_type in GPU_ONLY_COMPUTE:
        compute_type = "int8"
    return "cpu", compute_type


def _whisper(cls, model: str, **kw):
    """Load from the local cache first (fully offline, no Hugging Face requests); download only if missing."""
    try:
        return cls(model, local_files_only=True, **kw)
    except Exception:
        log.info("Модель Whisper '%s' не найдена локально — скачиваю (один раз).", model)
        return cls(model, **kw)


def probe(model, language: Optional[str] = "ru") -> None:
    """Run encoder + decoder once (faster-whisper's transcribe() is lazy)."""
    noise = (np.random.default_rng(0).standard_normal(16000) * 1e-3).astype(np.float32)
    segments, _ = model.transcribe(noise, language=language, beam_size=1, without_timestamps=True,
                                   condition_on_previous_text=False, vad_filter=False)
    for _ in segments:
        pass


class SpeechToText:
    def __init__(self, cfg: dict, on_notice: Optional[Callable[[str], None]] = None):
        self.cfg = cfg
        self._lock = threading.RLock()
        self.relocated = False
        self.on_notice = on_notice
        self.gpu_error: Optional[str] = None      # kept for the diagnostics API; Lite never uses the GPU
        self.language = cfg.get("language", "ru")
        self.beam_size = int(cfg.get("beam_size", 1))
        self.initial_prompt = cfg.get("initial_prompt") or None
        self.vad_filter = bool(cfg.get("vad_filter", True))
        self.hotwords = str(cfg.get("hotwords") or "") or None
        self.min_level = float(cfg.get("min_level", MIN_LEVEL))
        self.requested = "cpu"
        device, compute = pick_device("cpu", cfg.get("compute_type", "auto"))
        try:
            import ctranslate2
            import faster_whisper
            vers = f"faster-whisper {faster_whisper.__version__}, ctranslate2 {ctranslate2.__version__}"
        except Exception:
            vers = "?"
        model = cfg.get("model", "small")
        log.info("Whisper '%s': %s/%s, потоков %s (%s)", model, device, compute, cfg.get("cpu_threads") or "авто", vers)
        t0 = time.time()
        self.model: Any = self._load(device, compute)
        self.device, self.compute_type = device, compute
        log.info("Whisper '%s' загружен (%s/%s) за %.1f с", model, device, compute, time.time() - t0)

    def _load(self, device: str, compute: str):
        from faster_whisper import WhisperModel
        root = self.cfg.get("download_root")
        root = str(resolve_path(root)) if root else None
        return _whisper(WhisperModel, self.cfg.get("model", "small"), device="cpu", compute_type=compute,
                        download_root=root, cpu_threads=int(self.cfg.get("cpu_threads", 0) or 0))

    def relocate(self, target) -> None:
        """Game mode: None — unload Whisper to free RAM (reloaded on the next phrase); 'restore' — reload now."""
        with self._lock:
            try:
                if target == "restore":
                    if self.model is None:
                        self.model = self._load("cpu", self.compute_type)
                    self.relocated = False
                    return
                if target is None:
                    self.model = None
                    import gc
                    gc.collect()
                    self.relocated = True
                    log.info("Whisper: выгружен")
            except Exception as e:
                log.error("Whisper relocate: %s", e)

    last_conf: Optional[tuple] = None

    def transcribe(self, audio, language: str | None = "default") -> str:
        self.last_conf = None
        with self._lock:
            if self.model is None:          # unloaded in game mode -> reload on demand
                self.model = self._load("cpu", self.compute_type)
            return self._transcribe(audio, language)

    def _transcribe(self, audio, language: str | None = "default") -> str:
        """audio: float32 numpy array at 16 kHz, or a path to an audio file."""
        if isinstance(audio, np.ndarray):
            audio = audio.astype(np.float32, copy=False)
            if audio.size < 1600:  # < 0.1 s
                return ""
            loud = speech_level(audio)
            if loud < getattr(self, "min_level", MIN_LEVEL):
                log.debug("STT пропущено: тихо/шум (уровень %.4f < %.4f), Whisper не запускаю", loud,
                          getattr(self, "min_level", MIN_LEVEL))
                return ""
        elif isinstance(audio, Path):
            audio = str(audio)
        t0 = time.time()
        kw = dict(language=self.language if language == "default" else language,   # None = auto-detect
                  beam_size=self.beam_size,
                  initial_prompt=self.initial_prompt if language in ("default", "ru") else None,
                  hotwords=getattr(self, "hotwords", None) if language in ("default", "ru") else None,
                  condition_on_previous_text=False,          # no carry-over of earlier (possibly phantom) text
                  no_speech_threshold=NO_SPEECH_MAX, log_prob_threshold=LOGPROB_MIN,
                  compression_ratio_threshold=2.4, without_timestamps=True)
        if self.vad_filter:
            kw.update(vad_filter=True, vad_parameters=VAD_PARAMS)   # Silero VAD: no speech -> no decoding at all
        try:
            segments, _info = self.model.transcribe(audio, **kw)
            segs = list(segments)
        except Exception as e:
            if not self.vad_filter or "vad" not in str(e).lower() and "onnx" not in str(e).lower():
                raise
            log.warning("Silero VAD недоступен (%s) — распознаю без него", e)
            self.vad_filter = False
            kw.pop("vad_parameters", None)
            kw["vad_filter"] = False
            segments, _info = self.model.transcribe(audio, **kw)
            segs = list(segments)
        text = accept(segs, self.initial_prompt, getattr(self, "hotwords", None))
        self.last_conf = utterance_conf(segs) if text else None     # no-name commands need a confident STT
        log.debug("STT %.2f с: %r conf=%s", time.time() - t0, text, self.last_conf)
        return text


MIN_LEVEL = 0.004              # RMS of the loudest 10% of 30 ms frames; speech is ~0.02-0.3, room noise < 0.003


def speech_level(audio) -> float:
    """Cheap energy gate before Whisper: noise that fooled the webrtc VAD costs 2-3 s of CPU per phrase."""
    n = 480
    k = audio.size // n
    if k == 0:
        return float(np.sqrt(np.mean(audio * audio))) if audio.size else 0.0
    rms = np.sqrt(np.mean(audio[: k * n].reshape(k, n) ** 2, axis=1))
    return float(np.percentile(rms, 90))


NO_SPEECH_MAX = 0.6            # whisper's own "silence" probability; above -> segment dropped
LOGPROB_MIN = -1.0             # average token log-probability; below = whisper is guessing
LOGPROB_HARD = -1.4            # always dropped below this, even if no_speech is low
VAD_PARAMS = {"threshold": 0.5, "min_speech_duration_ms": 200, "min_silence_duration_ms": 500, "speech_pad_ms": 200}
# whole-phrase hallucinations: dropped when the phrase is ONLY this and whisper is not confident about it
STANDALONE = {"привет", "спасибо", "спасибо большое", "спасибо за внимание", "пока", "да", "угу", "ага", "ну",
              "так", "всё", "все", "хорошо", "окей", "ок", "здравствуйте", "до свидания", "ммм", "м", "а", "о",
              "аплодисменты", "музыка", "смех", "тишина", "you", "thank you", "thanks for watching", "bye"}
STANDALONE_CONF = -0.45        # «привет» must be clearly heard (avg_logprob above this) to pass
STANDALONE_NOSPEECH = 0.25


def _plain(s: str) -> str:
    import re as _re
    return " ".join(_re.sub(r"[^\w\s]", " ", (s or "").lower().replace("ё", "е")).split())


def utterance_conf(segments) -> Optional[tuple]:
    """(worst avg_logprob, worst no_speech_prob) over the segments with text; None if there are none."""
    lp = [float(getattr(sg, "avg_logprob", 0.0) or 0.0) for sg in segments if (getattr(sg, "text", "") or "").strip()]
    ns = [float(getattr(sg, "no_speech_prob", 0.0) or 0.0) for sg in segments if (getattr(sg, "text", "") or "").strip()]
    return (min(lp), max(ns)) if lp else None


def accept(segments, prompt: str | None = None, hotwords: str | None = None) -> str:
    """Whisper segments -> text, without the usual phantom output on silence/noise. Drops are logged at debug."""
    kept, conf, nos = [], [], []
    for sg in segments:
        t = (getattr(sg, "text", "") or "").strip()
        ns = float(getattr(sg, "no_speech_prob", 0.0) or 0.0)
        lp = float(getattr(sg, "avg_logprob", 0.0) or 0.0)
        if not t:
            continue
        if ns > NO_SPEECH_MAX and lp < LOGPROB_MIN or ns > 0.8 or lp < LOGPROB_HARD:
            log.debug("STT отброшено (no_speech=%.2f, logprob=%.2f): %r", ns, lp, t)
            continue
        kept.append(t)
        conf.append(lp)
        nos.append(ns)
    text = strip_sound_tags(" ".join(kept).strip())
    if not text:
        return ""
    plain = _plain(text)
    if any(h in plain for h in _HALLUCINATIONS):
        log.debug("STT отброшено (типичная галлюцинация): %r", text)
        return ""
    if plain in STANDALONE and (min(conf) < STANDALONE_CONF or max(nos) > STANDALONE_NOSPEECH):
        log.debug("STT отброшено (одно слово, неуверенно: logprob=%.2f): %r", min(conf), text)
        return ""
    if hotwords and plain in _plain(hotwords).split() and (min(conf) < STANDALONE_CONF or max(nos) > STANDALONE_NOSPEECH):
        log.debug("STT отброшено (эхо hotword, неуверенно): %r", text)
        return ""
    if prompt and len(plain) >= 4 and plain in _plain(prompt):
        log.debug("STT отброшено (эхо подсказки initial_prompt): %r", text)
        return ""
    return text


# Typical Whisper hallucinations on silence/noise in Russian (training data = subtitled videos); substrings
_HALLUCINATIONS = (
    "продолжение следует", "субтитры сделал", "субтитры создавал", "субтитры подготовил", "субтитры делал",
    "редактор субтитров", "корректор субтитров", "диматор", "dimatorzok", "диматорзок", "спасибо за просмотр",
    "подписывайтесь на канал", "подпишись на канал", "подписывайтесь на наш канал", "ставьте лайк",
    "ставьте лайки", "до новых встреч", "amara org", "субтитры от", "игорь негода", "а семкин", "с вами был",
    "спасибо что смотрите", "всем пока", "благодарю за внимание",
)


_TAG_WORDS = ("музык", "аплодисмент", "смех", "шум", "тишин", "мелоди", "песн", "вздох", "кашл", "звонок",
              "динамичн", "спокойн", "весел", "грустн", "напряж", "торжествен", "рингтон", "стук", "крик", "плач",
              "гудок", "сигнал", "играет", "звучит", "music", "applause", "laughter", "noise", "silence")


def strip_sound_tags(text: str) -> str:
    """1.0.9: subtitle sound tags Whisper hallucinates on noise/music: «[МУЗЫКА]», «(смех)», «ДИНАМИЧНАЯ МУЗЫКА»,
    «АПЛОДИСМЕНТЫ». Bracketed tags are removed; an ALL-CAPS utterance (people's speech never comes out in caps)
    or a phrase made only of tag words is dropped."""
    t = re.sub(r"[\[(*♪♫][^\])*♪♫]{0,40}[\])*♪♫]", " ", text)
    t = re.sub(r"[♪♫]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip(" .,!?-—")
    letters = re.sub(r"[^A-Za-zА-Яа-яЁё]", "", t)
    words = re.findall(r"[a-zа-яё]+", t.lower())
    tagged = [w for w in words if w.startswith(_TAG_WORDS)]
    if len(letters) >= 4 and letters.isupper() and (len(words) >= 2 or tagged):
        return ""                                    # «ДИНАМИЧНАЯ МУЗЫКА», «АПЛОДИСМЕНТЫ»
    glue = ("в", "зале", "за", "кадром", "на", "фоне")
    if words and all(w in tagged or w in glue for w in words):
        if len(words) >= 2 or words[0].startswith(("аплодисмент", "смех", "тишин", "шум", "applause", "laughter")):
            return ""                                # «динамичная музыка», «смех в зале»; «музыка» alone stays
    return t if t != text.strip(" .,!?-—") else text


def _drop_hallucinations(text: str) -> str:
    plain = _plain(text)
    return "" if any(h in plain for h in _HALLUCINATIONS) else text
