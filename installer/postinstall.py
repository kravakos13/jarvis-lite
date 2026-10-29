"""Run by JarvisLiteSetup.exe after copying files (with the bundled embeddable Python):

  1. pip (get-pip.py) + Python packages from requirements.txt (or the bundled wheels\\ folder)
  2. Piper voice (~60 MB) + Whisper «small» speech recognition (~0.5 GB) — scripts/download_models.py

Jarvis Lite has no AI: nothing else is downloaded (no Ollama, no language models, no GPU libraries).

Every step is logged to logs\\install.log; a failed step does not abort the others —
the app's self-diagnostics ("проверь себя") offers to fix whatever is missing later.
Usage: python installer\\postinstall.py [--core-only] [--no-models]
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = Path(sys.executable)
LOG = ROOT / "logs" / "install.log"
CORE = ["PyYAML>=6.0", "requests>=2.31", "numpy>=1.24", "psutil>=5.9", "keyring>=24", "dateparser>=1.2"]


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        print(line.encode("ascii", "replace").decode(), flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def run(argv: list, **kw) -> int:
    log("> " + " ".join(str(a) for a in argv))
    try:
        return subprocess.call([str(a) for a in argv], cwd=str(ROOT), **kw)
    except OSError as e:
        log(f"  ошибка запуска: {e}")
        return 1


def ensure_pip() -> bool:
    if run([PY, "-m", "pip", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0:
        return True
    gp = ROOT / "installer" / "get-pip.py"
    wheels = ROOT / "wheels"
    extra = ["--no-index", "--find-links", wheels] if wheels.is_dir() else []
    return run([PY, gp, "--no-warn-script-location", *extra]) == 0


def install_packages(core_only: bool) -> bool:
    base = [PY, "-m", "pip", "install", "--no-warn-script-location", "--disable-pip-version-check"]
    wheels = ROOT / "wheels"
    if wheels.is_dir():                      # offline install from bundled wheels
        base += ["--no-index", "--find-links", wheels]
    if core_only:
        return run(base + CORE) == 0
    if run(base + ["-r", ROOT / "requirements.txt"]) == 0:
        return True
    log("Полная установка пакетов не удалась — ставлю базовые, остальное можно докачать позже.")
    run(base + CORE)
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--core-only", action="store_true", help="только базовые пакеты (тест)")
    ap.add_argument("--no-models", action="store_true")
    ap.add_argument("--pause-on-error", action="store_true", help="интерактивная установка: ждать Enter при ошибках")
    a = ap.parse_args()
    log(f"=== Установка Джарвиса Лайт в {ROOT} (Python {sys.version.split()[0]}) ===")
    ok = True
    if not ensure_pip():
        log("[!] pip не установился — нужен интернет. Запусти установщик ещё раз.")
        return 1
    ok &= install_packages(a.core_only)
    if not a.no_models and not a.core_only:
        ok &= run([PY, ROOT / "scripts" / "download_models.py"]) == 0
    log("=== Готово ===" if ok else "=== Готово с предупреждениями (см. выше) ===")
    if not ok and a.pause_on_error:
        pause_with_help()
    return 0


def pause_with_help(timeout_s: float = 600.0) -> None:
    """1.0.9: plain words for beginners; the window waits (max 10 min) so the messages above can be read."""
    print()
    print("Что-то скачалось не до конца (обычно из-за интернета). Ничего страшного:")
    print("  * Джарвис Лайт сам докачает голос и распознавание при первом запуске;")
    print("  * или потом: Пуск -> Джарвис Лайт -> «Докачать компоненты».")
    print(f"Подробности записаны в файл: {ROOT / 'logs' / 'install.log'}")
    print()
    print("Нажми Enter, чтобы закрыть это окно и продолжить установку.")
    import threading
    t = threading.Thread(target=lambda: _safe_input(), daemon=True)
    t.start()
    t.join(timeout_s)


def _safe_input() -> None:
    try:
        input()
    except Exception:                            # noqa: BLE001 — no console (silent / redirected)
        pass


if __name__ == "__main__":
    sys.exit(main())
