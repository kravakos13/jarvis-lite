"""Idle load of Jarvis Lite: real app (Whisper small CPU int8, Piper, router, 2D face), mocked microphone that
only delivers room noise (nobody talks). Usage:
    python tests/smoke/measure_idle.py [--gui [--tray]] [--warmup 40] [--seconds 60]
Prints own CPU (% of one core and % of the whole PC), RAM (RSS) and threads, averaged over --seconds."""
import argparse
import os
import sys
import threading
import time
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--gui", action="store_true", help="with the window and the animated 2D face (offscreen)")
ap.add_argument("--tray", action="store_true", help="with --gui: window hidden in the tray (autostart)")
ap.add_argument("--warmup", type=float, default=40)
ap.add_argument("--seconds", type=float, default=60)
args = ap.parse_args()
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))
os.chdir(ROOT)
from jarvis.config import load_config  # noqa: E402

cfg = load_config()
from jarvis import resources  # noqa: E402

resources.apply_env(cfg)                     # same as jarvis.main: thread caps before numpy / ctranslate2
resources.lower_priority(cfg)
import psutil  # noqa: E402

import fakeaudio  # noqa: E402

fakeaudio.FILES[:] = []
fakeaudio.START_DELAY = 1
fakeaudio.install()
from jarvis.main import setup_logging  # noqa: E402

cfg["logging"]["level"] = "WARNING"
setup_logging(cfg["logging"], False)
me = psutil.Process()
result = {}


def measure(stop_cb):
    time.sleep(args.warmup)
    t0, c0 = time.monotonic(), sum(me.cpu_times()[:2])
    peak_rss, samples = 0, []
    while time.monotonic() - t0 < args.seconds:
        time.sleep(1)
        peak_rss = max(peak_rss, me.memory_info().rss)
        samples.append(me.cpu_percent(None))
    dt, dc = time.monotonic() - t0, sum(me.cpu_times()[:2]) - c0
    one = 100 * dc / dt
    result.update(cpu_one_core=round(one, 1), cpu_whole_pc=round(one / psutil.cpu_count(), 2),
                  rss_mb=round(me.memory_info().rss / 2**20), peak_rss_mb=round(peak_rss / 2**20),
                  threads=me.num_threads(), cores=psutil.cpu_count(), nice=me.nice(),
                  omp=os.environ.get("OMP_NUM_THREADS"), stt_threads=cfg["stt"].get("cpu_threads"))
    print("IDLE_LOAD", result, flush=True)
    stop_cb()


if args.gui:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    import jarvis.gui.app as G
    app = QApplication(sys.argv)
    ctl = G.Controller(app, cfg, demo=False, speak=True)
    ctl.apply_ui()
    ctl.window.hide() if args.tray else ctl.window.show()
    ctl.start_assistant()
    done = threading.Event()
    threading.Thread(target=measure, args=(done.set,), daemon=True).start()
    tm = QTimer()
    tm.timeout.connect(lambda: app.quit() if done.is_set() else None)
    tm.start(200)
    app.exec()
else:
    from jarvis.assistant import Assistant
    a = Assistant(cfg, speak=True, need_stt=True)
    threading.Thread(target=a.run_voice, daemon=True).start()
    measure(lambda: None)
print("stt loaded:", "faster_whisper" in sys.modules, "| ollama/llm modules:",
      [m for m in sys.modules if "ollama" in m or m == "jarvis.llm"], flush=True)
os._exit(0)
