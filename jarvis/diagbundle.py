"""«Джарвис, собери диагностику»: one zip on the Desktop with everything needed to debug remotely —
jarvis.log (+ rotations), system info, the process load and the local settings with secrets redacted. Nothing is sent anywhere: the user decides what to do with it."""
from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import platform
import re
import zipfile
from pathlib import Path
from typing import Any, Optional

from . import __version__
from . import platform_utils as pu
from .config import LOCAL_SETTINGS, resolve_path

log = logging.getLogger(__name__)

SECRET_RE = re.compile(r"(token|hash|password|passwd|secret|api_?key|api_id|session|cookie|auth)", re.I)
MAX_FILE = 25_000_000


def desktop_dir() -> Path:
    home = Path(os.environ.get("USERPROFILE") or Path.home())
    for c in (home / "Desktop", home / "OneDrive" / "Desktop", home / "OneDrive" / "Рабочий стол", home / "Рабочий стол"):
        if c.is_dir():
            return c
    return pu.data_dir("")


def jarvis_logs(cfg: dict) -> list[Path]:
    f = (cfg.get("logging") or {}).get("file") or "logs/jarvis.log"
    p = resolve_path(f)
    return [x for x in [p] + [Path(f"{p}.{i}") for i in range(1, 4)] if x.is_file()]


def redact(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: ("***" if SECRET_RE.search(str(k)) and v not in (None, "", [], {}) else redact(v))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(x) for x in obj]
    return obj


def collect(cfg: dict, assistant: Any = None, dest: Optional[Path] = None,
            now: Optional[_dt.datetime] = None) -> Path:
    now = now or _dt.datetime.now()
    dest = dest or desktop_dir()
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / f"JarvisLite-диагностика-{now:%Y%m%d-%H%M}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in jarvis_logs(cfg):
            if p.stat().st_size <= MAX_FILE:
                z.write(p, f"jarvis/{p.name}")
        info: dict[str, Any] = {"jarvis_lite": __version__, "python": platform.python_version(), "os": platform.platform(),
                                "cpu": platform.processor(), "cores": os.cpu_count(), "time": now.isoformat(timespec="seconds")}
        try:
            import psutil
            vm = psutil.virtual_memory()
            info["ram_gb"] = {"total": round(vm.total / 2**30, 1), "free": round(vm.available / 2**30, 1)}
            me = psutil.Process()
            info["process"] = {"rss_mb": round(me.memory_info().rss / 2**20), "threads": me.num_threads()}
        except Exception:                                      # noqa: BLE001
            pass
        stt = getattr(assistant, "stt", None)
        if stt is not None:
            info["stt"] = {"device": getattr(stt, "device", "?"), "compute": getattr(stt, "compute_type", "?"),
                           "threads": (cfg.get("stt") or {}).get("cpu_threads")}
        z.writestr("system.json", json.dumps(info, ensure_ascii=False, indent=1))
        try:
            import yaml
            local = yaml.safe_load(Path(LOCAL_SETTINGS).read_text(encoding="utf-8")) or {}
            z.writestr("settings.local.yaml", yaml.safe_dump(redact(local), allow_unicode=True, sort_keys=False))
        except Exception as e:                                 # noqa: BLE001
            z.writestr("settings.local.yaml", f"# нет файла или ошибка: {e}\n")
    log.info("Диагностика собрана: %s", out)
    return out
