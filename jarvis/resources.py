"""System load control («Нагрузка»): Jarvis Lite must stay light on any PC.

* BELOW_NORMAL process priority;
* limited threads for Whisper (CTranslate2) / ONNX (Piper) / OpenMP;
* one resource line (own CPU %, own RAM, free RAM) in the log every 5 minutes.
No language model and no video card are ever used.
"""
from __future__ import annotations

import logging
import os
import sys
import time
from typing import Any, Optional

log = logging.getLogger("jarvis.res")
IS_WIN = sys.platform == "win32"

# presets: Settings → «Нагрузка». Explicit values in the config sections always win over the preset.
PRESETS: dict[str, dict[str, Any]] = {
    # default: Whisper on 4 threads, face 15 fps, lower process priority
    "balanced": {"threads": 4, "face_fps": 15, "priority": "below_normal"},
    # weak PC / next to a game: 2 threads, face 10 fps
    "light": {"threads": 2, "face_fps": 10, "priority": "below_normal"},
    # fastest recognition: all cores, normal priority
    "max": {"threads": 0, "face_fps": 30, "priority": "normal"},
}
PRESET_NAMES = {"balanced": "Обычная (по умолчанию)", "light": "Минимальная — для слабого ПК",
                "max": "Максимальная скорость распознавания"}


def preset(cfg: dict) -> dict:
    name = str(((cfg or {}).get("load") or {}).get("preset") or "balanced")
    return dict(PRESETS.get(name, PRESETS["balanced"]), name=name if name in PRESETS else "balanced")


def thread_env(n: int) -> dict:
    """Thread caps for OpenMP/MKL/ONNX (set BEFORE numpy / ctranslate2 / onnxruntime are imported)."""
    if n <= 0:
        return {}
    v = str(n)
    return {"OMP_NUM_THREADS": v, "MKL_NUM_THREADS": v, "OPENBLAS_NUM_THREADS": v, "NUMEXPR_NUM_THREADS": v,
            "ORT_NUM_THREADS": v}


def apply_env(cfg: dict) -> None:
    for k, v in thread_env(int(preset(cfg)["threads"])).items():
        os.environ.setdefault(k, v)


def _kernel32():
    """kernel32 with typed prototypes: the pseudo-handles (-1 / -2) are 64-bit HANDLEs; with ctypes' default int
    conversion they were truncated to 32 bits and SetPriorityClass failed (seen under Wine, possible on x64)."""
    import ctypes
    from ctypes import wintypes as w
    k = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    k.GetCurrentProcess.restype = k.GetCurrentThread.restype = w.HANDLE
    k.SetPriorityClass.argtypes, k.SetPriorityClass.restype = [w.HANDLE, w.DWORD], w.BOOL
    k.GetPriorityClass.argtypes, k.GetPriorityClass.restype = [w.HANDLE], w.DWORD
    k.SetThreadPriority.argtypes, k.SetThreadPriority.restype = [w.HANDLE, ctypes.c_int], w.BOOL
    return k


def lower_priority(cfg: Optional[dict] = None) -> bool:
    if cfg is not None and preset(cfg)["priority"] == "normal":
        return False
    try:
        if IS_WIN:
            k = _kernel32()
            return bool(k.SetPriorityClass(k.GetCurrentProcess(), 0x00004000))   # BELOW_NORMAL_PRIORITY_CLASS
        os.nice(5)
        return True
    except Exception as e:                                # noqa: BLE001
        log.debug("priority: %s", e)
        return False


def lowest_thread_priority() -> None:
    """For background indexing threads (call inside the thread)."""
    if not IS_WIN:
        return
    try:
        k = _kernel32()
        k.SetThreadPriority(k.GetCurrentThread(), -2)       # THREAD_PRIORITY_LOWEST
    except Exception as e:                                # noqa: BLE001
        log.debug("thread priority: %s", e)


# ------------------------------------------------------------------ memory
def free_ram_gb() -> Optional[float]:
    try:
        import psutil
        return round(psutil.virtual_memory().available / 2**30, 2)
    except Exception:                                     # noqa: BLE001
        pass
    try:
        with open("/proc/meminfo", encoding="ascii") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return round(int(line.split()[1]) / 2**20, 2)
    except Exception:                                     # noqa: BLE001
        pass
    return None


# ------------------------------------------------------------------ periodic log line
class Monitor:
    def __init__(self, period_s: float = 300.0):
        self.period = period_s
        self._last_cpu: Optional[tuple[float, float]] = None

    def own_cpu_percent(self) -> Optional[float]:
        try:
            t = sum(os.times()[:2])
            now = time.monotonic()
            prev, self._last_cpu = self._last_cpu, (now, t)
            if prev is None or now - prev[0] <= 0:
                return None
            return round(100.0 * (t - prev[1]) / (now - prev[0]) / (os.cpu_count() or 1), 1)
        except Exception:                                 # noqa: BLE001
            return None

    @staticmethod
    def own_rss_mb() -> Optional[float]:
        try:
            import psutil
            return round(psutil.Process().memory_info().rss / 2**20)
        except Exception:                                 # noqa: BLE001
            return None

    def line(self) -> str:
        parts = []
        cpu = self.own_cpu_percent()
        if cpu is not None:
            parts.append(f"CPU Джарвиса Лайт {cpu:.1f}%")
        rss = self.own_rss_mb()
        if rss is not None:
            parts.append(f"RAM {rss:.0f} МБ")
        fr = free_ram_gb()
        if fr is not None:
            parts.append(f"свободно RAM {fr:.1f} ГБ")
        return "Ресурсы: " + ", ".join(parts)

    def run(self, stop) -> None:
        self.own_cpu_percent()
        while not stop.wait(self.period):
            try:
                log.info(self.line())
            except Exception as e:                        # noqa: BLE001
                log.debug("monitor: %s", e)
