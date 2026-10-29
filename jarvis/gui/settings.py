"""Full graphical Settings window (Russian, holographic style). The user never edits config files.

All values are written to settings.local.yaml (config.yaml stays as the commented default).
Controller.apply_settings() applies what can change live; the rest asks for a restart."""
from __future__ import annotations

import copy
import logging
import sys
import threading
from pathlib import Path
from typing import Any, Optional

import yaml
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout,
                               QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSlider, QSpinBox,
                               QTabWidget, QVBoxLayout, QWidget)

from .. import __version__
from .. import platform_utils as pu
from ..config import LOCAL_SETTINGS, PROJECT_ROOT, raw_config, save_local_settings
from .widgets import HotkeyEdit, KeyValueTable, hotkey_conflicts

log = logging.getLogger(__name__)

VOICES = ["ru_RU-denis-medium", "ru_RU-dmitri-medium", "ru_RU-ruslan-medium", "ru_RU-irina-medium"]
WHISPER = ["tiny", "base", "small", "medium", "large-v3"]
OBLASTS = ["Сумська область", "Харківська область", "Чернігівська область", "Полтавська область", "Київська область",
           "м. Київ", "Дніпропетровська область", "Запорізька область", "Одеська область", "Львівська область"]
THEMES = {"Мята (Лайт, по умолчанию)": "#5cf2b0", "Голограмма (голубая)": "#46dcff", "Марк (красно-золотая)": "#ffb347", "Изумруд": "#4dffb0",
          "Фиолетовая": "#b28cff", "Белая": "#e8f6ff"}
MODULES = [("memory", "Долговременная память"), ("planner", "Задачи и напоминания"), ("notes", "Заметки"),
           ("timers", "Таймеры"), ("media", "YouTube / YouTube Music"), ("apps", "Игры и программы"),
           ("system", "Система (громкость, питание)"), ("windows", "Окна (закрыть/свернуть)"), ("weather", "Погода"), ("web_search", "Ответы из интернета"),
           ("game", "Помощь в играх (ответы из интернета)"), ("smalltalk", "Болталка без ИИ (шутки, факты, «как дела»)"),
           ("smarthome", "Умный дом"), ("telegram", "Telegram"),
           ("dictate", "Диктовка в любое окно"), ("monitor", "Температура ПК"), ("alerts", "Воздушные тревоги"),
           ("profiles", "Режимы (игровой/ночной)"), ("audio_devices", "Переключение аудиоустройств"),
           ("files", "Поиск файлов"), ("calc", "Калькулятор"), ("clipboard", "Буфер обмена"),
           ("diagnostics", "Самодиагностика"), ("view", "Полный экран / кинотеатр / субтитры в YouTube")]

# changes under these keys need a restart
RESTART_KEYS = ("sync.", "stt.", "audio.", "tts.piper_voice", "tts.engine", "telegram.", "alerts.backend",
                "alerts.oblast", "alerts.raions", "files.roots", "gui.fps", "smarthome.", "media.") + tuple(
    f"{k}.enabled" for k, _ in MODULES)

STYLE = """
QDialog, QWidget#page { background: rgb(6, 18, 34); color: rgb(200, 240, 255); font: 12px 'Segoe UI'; }
QLabel { color: rgb(190, 235, 255); }
QGroupBox { border: 1px solid rgba(70,220,255,70); border-radius: 10px; margin-top: 14px; padding: 8px;
            color: rgb(120,230,255); font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
QTabWidget::pane { border: 1px solid rgba(70,220,255,80); border-radius: 10px; top: -1px; }
QTabBar::tab { background: rgba(20,60,100,120); color: rgb(160,220,250); padding: 6px 10px; margin: 1px;
               border-top-left-radius: 8px; border-top-right-radius: 8px; }
QTabBar::tab:selected { background: rgba(40,130,190,190); color: white; }
QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox, QListWidget, QTableWidget {
    color: white; background: rgba(10,40,70,190); border: 1px solid rgba(70,220,255,90); border-radius: 7px;
    padding: 4px; selection-background-color: rgb(30,120,200); }
QComboBox QAbstractItemView { background: rgb(10,30,55); color: white; }
QHeaderView::section { background: rgb(15,50,85); color: rgb(170,230,255); border: none; padding: 4px; }
QPushButton { color: rgb(150,235,255); background: rgba(20,70,110,150); border: 1px solid rgba(70,220,255,110);
              border-radius: 8px; padding: 5px 12px; }
QPushButton:hover { background: rgba(40,120,170,190); }
QCheckBox { color: rgb(200,240,255); }
QProgressBar { background: rgba(10,40,70,150); border: none; border-radius: 4px; height: 8px; color: transparent; }
QProgressBar::chunk { background: rgb(70,220,255); border-radius: 4px; }
QScrollArea { border: none; background: transparent; }
QSlider::groove:horizontal { height: 4px; background: rgba(70,220,255,80); border-radius: 2px; }
QSlider::handle:horizontal { width: 14px; margin: -6px 0; border-radius: 7px; background: rgb(110,230,255); }
"""


def get_path(d: dict, path: str, default=None):
    cur = d
    for k in path.split("."):
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def set_path(d: dict, path: str, value) -> None:
    keys = path.split(".")
    cur = d
    for k in keys[:-1]:
        cur = cur.setdefault(k, {})
    cur[keys[-1]] = value


def diff(new: dict, old: dict, prefix: str = "") -> list[str]:
    out = []
    for k, v in new.items():
        p = f"{prefix}{k}"
        if isinstance(v, dict):
            out += diff(v, old.get(k, {}) if isinstance(old.get(k), dict) else {}, p + ".")
        elif old.get(k) != v:
            out.append(p)
    return out


class SettingsDialog(QDialog):
    _sig = Signal(str, object)          # thread -> UI (name, payload)

    def __init__(self, cfg: dict, memory=None, parent=None, controller=None):
        super().__init__(parent)
        self.cfg = cfg                  # live config (already rendered)
        self.memory = memory
        self.ctl = controller
        self.assistant = getattr(controller, "assistant", None)
        self.raw = raw_config()         # values as stored (prompt with {name} placeholders)
        self.fields: dict[str, tuple[QWidget, str]] = {}
        self.restart_needed = False
        self._mic_stream = None
        self._mic_level = 0.0
        self.setWindowTitle("Настройки — Джарвис Лайт")
        self.setStyleSheet(STYLE)
        self.resize(780, 680)
        self._sig.connect(self._on_sig)

        self.tabs = QTabWidget()
        self.tabs.setUsesScrollButtons(True)
        for title, builder in (("Основные", self._tab_general), ("Голос", self._tab_voice),
                               ("Микрофон", self._tab_mic), ("Память", self._tab_memory),
                               ("Интерфейс", self._tab_ui), ("Режимы", self._tab_modes),
                               ("Интеграции", self._tab_integrations), ("Игры", self._tab_games),
                               ("Аудиоустройства", self._tab_audio), ("Модули", self._tab_modules),
                               ("Бэкап и синхронизация", self._tab_backup), ("Что я умею", self._tab_help),
                               ("О программе", self._tab_about)):
            try:
                self.tabs.addTab(self._scroll(builder()), title)
            except Exception as e:      # one broken tab must not break the window
                log.exception("settings tab %s: %s", title, e)
                self.tabs.addTab(QLabel(f"Ошибка вкладки: {e}"), title)
        self.populate(self.raw)

        bottom = QHBoxLayout()
        b_def = QPushButton("По умолчанию")
        b_def.setToolTip("Вернуть значения из config.yaml (сохраняется только после «Сохранить»)")
        b_def.clicked.connect(self._defaults)
        self.err = QLabel("")
        self.err.setStyleSheet("color: rgb(255,130,120);")
        self.err.setWordWrap(True)
        b_cancel = QPushButton("Отмена")
        b_cancel.clicked.connect(self.reject)
        b_save = QPushButton("Сохранить")
        b_save.setDefault(True)
        b_save.clicked.connect(self._save)
        bottom.addWidget(b_def)
        bottom.addWidget(self.err, 1)
        bottom.addWidget(b_cancel)
        bottom.addWidget(b_save)
        lay = QVBoxLayout(self)
        lay.addWidget(self.tabs)
        lay.addLayout(bottom)

    # ================================================================ field helpers
    def _scroll(self, w: QWidget) -> QScrollArea:
        w.setObjectName("page")
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setWidget(w)
        return sa

    def _add(self, form: QFormLayout, path: str, label: str, kind: str = "text", **kw) -> QWidget:
        if kind == "text":
            w = QLineEdit()
            if kw.get("password"):
                w.setEchoMode(QLineEdit.Password)
            if kw.get("placeholder"):
                w.setPlaceholderText(kw["placeholder"])
        elif kind == "int":
            w = QSpinBox()
            w.setRange(kw.get("min", 0), kw.get("max", 100000))
            w.setSingleStep(kw.get("step", 1))
            if kw.get("suffix"):
                w.setSuffix(kw["suffix"])
        elif kind == "float":
            w = QDoubleSpinBox()
            w.setRange(kw.get("min", 0.0), kw.get("max", 100.0))
            w.setSingleStep(kw.get("step", 0.1))
            w.setDecimals(kw.get("decimals", 2))
            if kw.get("suffix"):
                w.setSuffix(kw["suffix"])
        elif kind == "bool":
            w = QCheckBox(label)
            label = ""
        elif kind == "combo":
            w = QComboBox()
            w.setEditable(bool(kw.get("editable")))
            for item in kw.get("options", []):
                if isinstance(item, tuple):
                    w.addItem(item[1], item[0])
                else:
                    w.addItem(str(item), item)
        elif kind == "list":
            w = QPlainTextEdit()
            w.setFixedHeight(kw.get("height", 70))
            w.setPlaceholderText("по одному на строку")
        elif kind == "hotkey":
            w = HotkeyEdit()
        elif kind == "slider":
            w = QSlider(Qt.Horizontal)
            w.setRange(0, 100)
            w._scale = kw.get("scale", (0.0, 1.0))
        elif kind == "color":
            w = QPushButton()
            w._color = "#46dcff"
            w.clicked.connect(lambda _=False, b=w: self._pick_color(b))
        elif kind == "path":
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(0, 0, 0, 0)
            w._edit = QLineEdit()
            w._edit.setPlaceholderText(kw.get("placeholder", "по умолчанию"))
            b = QPushButton("…")
            b.setFixedWidth(34)
            b.clicked.connect(lambda _=False, e=w._edit, f=kw.get("file"): self._browse(e, f))
            h.addWidget(w._edit, 1)
            h.addWidget(b)
        else:
            raise ValueError(kind)
        if kw.get("tip"):
            w.setToolTip(kw["tip"])
        form.addRow(label, w)
        self.fields[path] = (w, kind)
        return w

    def _set(self, path: str, value: Any) -> None:
        w, kind = self.fields[path]
        try:
            if kind == "text":
                w.setText("" if value is None else str(value))
            elif kind == "int":
                w.setValue(int(value or 0))
            elif kind == "float":
                w.setValue(float(value or 0))
            elif kind == "bool":
                w.setChecked(bool(value))
            elif kind == "combo":
                i = w.findData(value)
                if i < 0 and value is not None:
                    i = w.findText(str(value))
                if i >= 0:
                    w.setCurrentIndex(i)
                elif w.isEditable():
                    w.setEditText("" if value is None else str(value))
            elif kind == "list":
                w.setPlainText("\n".join(str(x) for x in (value or [])))
            elif kind == "hotkey":
                w.setText(str(value or ""))
            elif kind == "slider":
                lo, hi = w._scale
                w.setValue(int(round((float(value or 0) - lo) / (hi - lo) * 100)))
                w._orig = (w.value(), value)      # unmoved slider returns the exact stored value
            elif kind == "color":
                self._apply_color_btn(w, str(value or "#46dcff"))
            elif kind == "path":
                w._edit.setText(str(value or ""))
        except Exception as e:
            log.debug("set %s=%r: %s", path, value, e)

    def _get(self, path: str) -> Any:
        w, kind = self.fields[path]
        if kind == "text":
            return w.text().strip()
        if kind == "int":
            return w.value()
        if kind == "float":
            return round(w.value(), 4)
        if kind == "bool":
            return w.isChecked()
        if kind == "combo":
            i = w.currentIndex()
            if i >= 0 and w.currentText() == w.itemText(i):
                d = w.itemData(i)
                return d if (d is not None or w.itemText(i) != str(d)) else w.itemText(i)
            return w.currentText().strip() or None
        if kind == "list":
            return [l.strip() for l in w.toPlainText().splitlines() if l.strip()]
        if kind == "hotkey":
            return w.text().strip()
        if kind == "slider":
            orig = getattr(w, "_orig", None)
            if orig and orig[0] == w.value():
                return orig[1]
            lo, hi = w._scale
            return round(lo + (hi - lo) * w.value() / 100.0, 2)
        if kind == "color":
            return w._color
        if kind == "path":
            return w._edit.text().strip()

    def _browse(self, edit: QLineEdit, file_filter: Optional[str]) -> None:
        if file_filter:
            p, _ = QFileDialog.getOpenFileName(self, "Выбери файл", edit.text() or str(Path.home()), file_filter)
        else:
            p = QFileDialog.getExistingDirectory(self, "Выбери папку", edit.text() or str(Path.home()))
        if p:
            edit.setText(p)

    def _apply_color_btn(self, b: QPushButton, color: str) -> None:
        c = QColor(color)
        if not c.isValid():
            c = QColor("#46dcff")
        b._color = c.name()
        b.setText(c.name())
        b.setStyleSheet(f"background: {c.name()}; color: black; border-radius: 8px;")

    def _pick_color(self, b: QPushButton) -> None:
        c = QColorDialog.getColor(QColor(b._color), self, "Цвет голограммы")
        if c.isValid():
            self._apply_color_btn(b, c.name())
            self._preview_ui()

    def _group(self, parent_layout, title: str) -> QFormLayout:
        g = QGroupBox(title)
        f = QFormLayout(g)
        f.setLabelAlignment(Qt.AlignRight)
        parent_layout.addWidget(g)
        return f

    # ================================================================ tabs
    def _tab_general(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        f = self._group(v, "Ассистент")
        self._add(f, "assistant.name", "Имя (слово-активатор)", tip="Падежи и варианты распознавания генерируются сами")
        self._add(f, "assistant.extra_wake_words", "Доп. варианты имени", "list", height=60)
        b = QPushButton("Показать все распознаваемые варианты")
        b.clicked.connect(self._show_variants)
        f.addRow("", b)
        self._add(f, "assistant.user_name", "Как обращаться (мистер …)")
        self._add(f, "assistant.greet_on_start", "Приветствовать при запуске", "bool")
        self._add(f, "assistant.greeting", "Приветствие", tip="{hello} = «Добрый день», {user_name} = имя")
        self._add(f, "assistant.greeting_time_of_day", "Приветствие по времени суток (утро/день/вечер/ночь)", "bool")
        self._add(f, "assistant.wake_reply", "Ответ на одно имя")
        self._add(f, "assistant.follow_up_seconds", "Слушать без имени после ответа (0 — выкл.)", "int", max=60, suffix=" с",
                  tip="По умолчанию 0: после ответа Джарвис засыпает до следующего «Джарвис»")
        self._add(f, "assistant.request_timeout_s", "После «Слушаю» ждать просьбу", "int", min=2, max=30, suffix=" с",
                  tip="Если за это время ничего не сказать, Джарвис молча засыпает")
        self._add(f, "assistant.ack_after_s", "Сказать «Секунду», если ответ дольше", "float", min=0.0, max=10.0,
                  step=0.5, decimals=1, suffix=" с", tip="0 — никогда")
        from ..noname import GROUPS
        fn = self._group(v, "Команды без имени")
        self._add(fn, "assistant.noname.enabled", "Команды без имени (короткие команды без «Джарвис»)", "bool",
                  tip="Только целая короткая фраза-команда, чётко распознанная, не во время речи Джарвиса. "
                      "Выполняется молча. Разговор, поиск, заметки, выключение ПК — только с именем.")
        for gid, title in GROUPS:
            self._add(fn, f"assistant.noname.groups.{gid}", title, "bool")
        fs = self._group(v, "Болталка без ИИ")
        self._add(fs, "smalltalk.suggest", "Не понял команду — предложить похожую («Может, «закрой хром»?»)", "bool",
                  tip="Джарвис Лайт не думает сам: шутки, факты и ответы на «как дела» — заготовленные фразы без повторов. "
                      "На вопросы, которых он не знает, он предложит поискать в Google.")
        fw = self._group(v, "Закрытие окон")
        self._add(fw, "windows.never_close", "Не закрывать (exe или слово из заголовка, по одному в строке)", "list",
                  height=60, tip="«Закрой» без названия закрывает активное окно. Игры не закрываются никогда "
                                 "(Steam/Epic/GOG/Riot/Battle.net, полноэкранные, игровой режим); сюда добавь, что ещё "
                                 "не трогать, например obs64.exe или Ableton.")
        from ..resources import PRESET_NAMES
        fl = self._group(v, "Нагрузка на компьютер")
        self._add(fl, "load.preset", "Нагрузка", "combo", options=list(PRESET_NAMES.items()),
                  tip="Обычная: распознавание речи в 4 потока, лицо 15 кадров/с, приоритет ниже обычного. "
                      "Минимальная: 2 потока и 10 кадров/с — для слабого ПК или рядом с игрой. "
                      "Максимальная: все ядра и обычный приоритет — быстрее распознаёт, но сильнее грузит ПК.")
        f2 = self._group(v, "Запуск")
        self._add(f2, "autostart.enabled", "Запускать вместе с Windows", "bool")
        self._add(f2, "gui.start_minimized", "Запускаться свёрнутым в трей", "bool")
        self._add(f2, "stt.language", "Язык распознавания", "combo",
                  options=[("ru", "Русский"), ("uk", "Українська"), ("en", "English"), (None, "Автоопределение")])
        self._add(f2, "profiles.default", "Режим по умолчанию", "combo",
                  options=[("work", "Рабочий"), ("game", "Игровой"), ("night", "Ночной")])
        v.addStretch(1)
        return w

    def _tab_voice(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        f = self._group(v, "Голос Piper")
        self._add(f, "tts.engine", "Движок", "combo", options=[("piper", "Piper (качественный)"),
                                                                ("pyttsx3", "Голос Windows (SAPI)"), ("none", "Без голоса")])
        self._add(f, "tts.piper_voice", "Голос", "combo", options=VOICES, editable=True)
        self._add(f, "tts.length_scale", "Темп (больше = медленнее)", "float", min=0.6, max=1.8, step=0.05)
        self._add(f, "tts.pitch_semitones", "Высота / тембр", "float", min=-6, max=6, step=0.5, suffix=" пт")
        self._add(f, "tts.volume", "Громкость голоса", "slider", scale=(0.1, 1.5))
        f2 = self._group(v, "Стилизация голоса (как в «Железном человеке»)")
        self._add(f2, "tts.fx.enabled", "Включить обработку голоса", "bool")
        self._add(f2, "tts.fx.intensity", "Интенсивность", "slider", scale=(0.0, 1.0))
        row = QHBoxLayout()
        self.preview_text = QLineEdit("Добрый день, мистер Флоки. Все системы в норме.")
        b = QPushButton("▶ Прослушать")
        b.clicked.connect(self._preview_voice)
        row.addWidget(self.preview_text, 1)
        row.addWidget(b)
        f2.addRow("Тест", row)
        self.voice_status = QLabel("")
        f2.addRow("", self.voice_status)
        v.addStretch(1)
        return w

    def _tab_mic(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        f = self._group(v, "Микрофон")
        opts = [(None, "По умолчанию (Windows)")]
        outs = [(None, "По умолчанию (Windows)")]
        try:
            import sounddevice as sd
            for i, d in enumerate(sd.query_devices()):
                if d["max_input_channels"] > 0:
                    opts.append((d["name"], f"{i}: {d['name']}"))
                if d["max_output_channels"] > 0:
                    outs.append((d["name"], f"{i}: {d['name']}"))
        except Exception as e:
            opts.append((None, f"(список недоступен: {e})"))
        self._add(f, "audio.input_device", "Устройство ввода", "combo", options=opts)
        self._add(f, "audio.output_device", "Устройство вывода (голос)", "combo", options=outs)
        row = QHBoxLayout()
        self.level = QProgressBar()
        self.level.setRange(0, 100)
        self.btn_level = QPushButton("Проверить уровень")
        self.btn_level.setCheckable(True)
        self.btn_level.toggled.connect(self._toggle_meter)
        row.addWidget(self.level, 1)
        row.addWidget(self.btn_level)
        f.addRow("Уровень", row)
        self._add(f, "audio.vad", "Детектор речи", "combo", options=[("webrtc", "WebRTC VAD"), ("energy", "По громкости")])
        self._add(f, "audio.vad_aggressiveness", "Строгость к шуму (0–3)", "int", max=3)
        self._add(f, "audio.energy_threshold", "Порог громкости", "float", min=0.001, max=0.2, step=0.002, decimals=3)
        self._add(f, "audio.silence_ms", "Пауза конца фразы", "int", min=300, max=3000, step=50, suffix=" мс")
        f2 = self._group(v, "Распознавание (Whisper)")
        self._add(f2, "stt.model", "Модель", "combo", options=WHISPER, tip="Больше = точнее и медленнее. small — оптимум")
        self._add(f2, "stt.compute_type", "Точность", "combo",
                  options=[("int8", "int8 — быстро, мало памяти (по умолчанию)"), ("int8_float32", "int8_float32"),
                           ("float32", "float32 — медленнее")],
                  tip="Джарвис Лайт распознаёт речь только на процессоре — видеокарта не используется.")
        self._add(f2, "stt.cpu_threads", "Потоков для распознавания (0 — из «Нагрузки»)", "int", min=0, max=16,
                  tip="Меньше потоков — меньше нагрузка на ПК, но фраза распознаётся чуть дольше.")
        f3 = self._group(v, "Активация и горячие клавиши")
        self._add(f3, "assistant.mode", "Как слушать", "combo",
                  options=[("wake", "По имени (слово-активатор)"), ("ptt", "Push-to-talk (держать клавишу)")])
        self._add(f3, "gui.hotkey_ptt", "Говорить (удерживать)", "hotkey")
        self._add(f3, "gui.hotkey_mic", "Пауза микрофона", "hotkey")
        self._add(f3, "gui.hotkey_show", "Показать/скрыть окно", "hotkey")
        self._add(f3, "gui.hotkey_stop", "Остановить (замолчать, бросить ответ)", "hotkey")
        self._add(f3, "gui.hotkey_game", "Вопрос по игре (удерживать)", "hotkey")
        self._add(f3, "dictate.hotkey", "Диктовка в окно", "hotkey")
        v.addStretch(1)
        return w

    def _tab_memory(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        f = self._group(v, "Настройки памяти")
        self._add(f, "memory.enabled", "Долговременная память", "bool")
        g = QGroupBox("Что Джарвис о тебе знает")
        gl = QVBoxLayout(g)
        self.mem_filter = QLineEdit()
        self.mem_filter.setPlaceholderText("Фильтр…")
        self.mem_filter.textChanged.connect(self._mem_reload)
        self.mem_list = QListWidget()
        self.mem_list.setMinimumHeight(260)
        gl.addWidget(self.mem_filter)
        gl.addWidget(self.mem_list)
        row = QHBoxLayout()
        for text, fn in (("Добавить", self._mem_add), ("Изменить", self._mem_edit), ("Удалить", self._mem_del)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        gl.addLayout(row)
        v.addWidget(g)
        self._mem_reload()
        return w

    def _tab_ui(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        f = self._group(v, "Окно")
        self._add(f, "gui.width", "Ширина", "int", min=320, max=1600, suffix=" px")
        self._add(f, "gui.height", "Высота", "int", min=420, max=1600, suffix=" px")
        self._add(f, "gui.opacity", "Непрозрачность", "slider", scale=(0.3, 1.0))
        self._add(f, "gui.always_on_top", "Поверх всех окон", "bool")
        self._add(f, "gui.close_to_tray", "Крестик сворачивает в трей", "bool")
        f2 = self._group(v, "Голограмма")
        theme = QComboBox()
        theme.addItem("— выбрать тему —")
        theme.addItems(list(THEMES))
        theme.currentTextChanged.connect(lambda t: (self._set("gui.color", THEMES[t]), self._preview_ui()) if t in THEMES else None)
        f2.addRow("Тема", theme)
        self._add(f2, "gui.color", "Цвет", "color")
        self._add(f2, "gui.animations", "Анимации", "combo",
                  options=[("full", "Полные"), ("lite", "Облегчённые (по умолчанию)"), ("off", "Почти без анимации")])
        self._add(f2, "gui.subtitles", "Показывать субтитры / журнал", "bool")
        self.fields["gui.opacity"][0].valueChanged.connect(lambda _: self._preview_ui())
        v.addStretch(1)
        return w

    def _tab_modes(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        f = self._group(v, "Игровой режим")
        self._add(f, "profiles.auto_game_mode", "Включать сам при полноэкранной игре / игре Steam", "bool")
        self._add(f, "vram.release_in_game", "Освобождать память в игре", "bool")
        self._add(f, "vram.whisper_in_game", "Распознавание в игре", "combo", options=[("cpu", "Оставить как есть"),
                                                                                         ("unload", "Выгрузить (−0,5 ГБ RAM)")])
        self._add(f, "profiles.game_reminders_voice", "Напоминания вслух", "bool")
        self._add(f, "profiles.game_notifications", "Второстепенные уведомления", "bool")
        f2 = self._group(v, "Ночной режим")
        self._add(f2, "profiles.night_volume", "Громкость ночью", "slider", scale=(0.1, 1.0))
        self._add(f2, "profiles.night_reminders_voice", "Напоминания вслух (иначе только уведомление)", "bool")
        self._add(f2, "profiles.night_notifications", "Второстепенные уведомления", "bool")
        self._add(f2, "profiles.night_schedule.enabled", "Включать по расписанию", "bool")
        self._add(f2, "profiles.night_schedule.start", "С", placeholder="23:00")
        self._add(f2, "profiles.night_schedule.end", "До", placeholder="07:00")
        f2.addRow("", QLabel("Воздушные тревоги и перегрев озвучиваются всегда, в любом режиме."))
        f3 = self._group(v, "Температура ПК")
        self._add(f3, "monitor.enabled", "Следить за температурой", "bool")
        self._add(f3, "monitor.gpu_temp_warn", "Видеокарта: предупреждать от", "int", min=50, max=110, suffix=" °C")
        self._add(f3, "monitor.cpu_temp_warn", "Процессор: предупреждать от", "int", min=50, max=110, suffix=" °C")
        self._add(f3, "monitor.cooldown_min", "Не повторять чаще", "int", min=1, max=240, suffix=" мин")
        self._add(f3, "monitor.lhm_url", "LibreHardwareMonitor URL", tip="Для температуры процессора: LHM → Options → Remote Web Server")
        f4 = self._group(v, "Telegram")
        self._add(f4, "telegram.notify_new_messages", "Озвучивать новые сообщения сразу", "bool")
        self._add(f4, "telegram.notify_whitelist", "Только от", "list", height=50)
        v.addStretch(1)
        return w

    def _tab_integrations(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        f = self._group(v, "Погода")
        row = QHBoxLayout()
        self._add(f, "weather.city", "Город")
        b = QPushButton("Найти координаты")
        b.clicked.connect(self._geocode)
        f.addRow("", b)
        self._add(f, "weather.latitude", "Широта", "float", min=-90, max=90, decimals=4, step=0.01)
        self._add(f, "weather.longitude", "Долгота", "float", min=-180, max=180, decimals=4, step=0.01)
        self._add(f, "weather.timezone", "Часовой пояс")
        f2 = self._group(v, "Воздушные тревоги")
        self._add(f2, "alerts.enabled", "Включено", "bool")
        self._add(f2, "alerts.backend", "Источник", "combo", options=[
            ("auto", "Авто: alerts.in.ua (с токеном) → siren.pp.ua → ubilling.net.ua"),
            ("siren", "siren.pp.ua (без ключа), запасные — остальные"),
            ("ubilling", "ubilling.net.ua (без ключа, только область)"),
            ("alerts_in_ua", "alerts.in.ua (нужен токен)")],
            tip="Если источник недоступен, Джарвис сам переключается на запасной.")
        self._add(f2, "alerts.oblast", "Область", "combo", options=OBLASTS, editable=True)
        self._add(f2, "alerts.raions", "Только районы", "list", height=50, tip="Пусто = вся область. Напр. «Сумський район»")
        from ..alerts_sources import TOKEN_SECRET, stored_token
        from ..secrets import mask as _mask
        self.alerts_token = QLineEdit()
        self.alerts_token.setEchoMode(QLineEdit.Password)
        tok = stored_token(self.cfg.get("alerts") or {})
        self.alerts_token.setPlaceholderText(f"сохранён ({_mask(tok)}) — оставь пустым, чтобы не менять" if tok
                                             else "необязательно — бесплатно: alerts.in.ua/api-request")
        self.alerts_token.setToolTip("Хранится зашифрованно (диспетчер учётных данных Windows), не в файле настроек.")
        f2.addRow("Токен alerts.in.ua", self.alerts_token)
        self._alerts_secret = TOKEN_SECRET
        b_al = QPushButton("Проверить источники")
        b_al.clicked.connect(self._alerts_test)
        f2.addRow("", b_al)
        self._add(f2, "alerts.interval_s", "Опрос каждые", "int", min=10, max=300, suffix=" с")
        f3 = self._group(v, "Telegram")
        self._add(f3, "telegram.enabled", "Включено", "bool")
        self._add(f3, "telegram.api_id", "api_id", "int", max=999999999, tip="my.telegram.org → API development tools")
        self._add(f3, "telegram.api_hash", "api_hash", password=True)
        row = QHBoxLayout()
        b_in = QPushButton("Войти…")
        b_in.clicked.connect(self._tg_login)
        b_out = QPushButton("Выйти (удалить сессию)")
        b_out.clicked.connect(self._tg_logout)
        self.tg_status = QLabel(self._tg_state())
        row.addWidget(b_in)
        row.addWidget(b_out)
        row.addWidget(self.tg_status, 1)
        f3.addRow("", row)
        f4 = self._group(v, "Умный дом (devices.yaml)")
        self.devices_edit = QPlainTextEdit()
        self.devices_edit.setMinimumHeight(180)
        self._devices_path = PROJECT_ROOT / (get_path(self.raw, "smarthome.devices_file") or "devices.yaml")
        try:
            self.devices_edit.setPlainText(self._devices_path.read_text(encoding="utf-8"))
        except Exception:
            self.devices_edit.setPlainText("devices: {}\n")
        f4.addRow(self.devices_edit)
        b = QPushButton("Проверить YAML")
        b.clicked.connect(lambda: self._flash(self._check_yaml(self.devices_edit.toPlainText()) or "YAML в порядке ✓"))
        f4.addRow("", b)
        f5 = self._group(v, "YouTube / YouTube Music")
        self._add(f5, "media.chrome_path", "chrome.exe", "path", file="Программы (*.exe)", placeholder="найти автоматически")
        self._add(f5, "media.youtube_app.shortcut", "Ярлык YouTube", "path", file="Ярлыки (*.lnk)", placeholder="Chrome Apps\\YouTube.lnk")
        self._add(f5, "media.ytmusic_app.shortcut", "Ярлык YouTube Music", "path", file="Ярлыки (*.lnk)", placeholder="Chrome Apps\\YouTube Music.lnk")
        f6 = self._group(v, "Папки")
        self._add(f6, "notes.dir", "Заметки", "path", placeholder="%LOCALAPPDATA%\\JarvisLite\\Notes")
        self._add(f6, "screen.tesseract_path", "Tesseract OCR (чтение экрана)", "path", file="tesseract.exe (*.exe)",
                  placeholder="найти автоматически")
        self._add(f6, "files.roots", "Где искать файлы", "list", height=90)
        f7 = self._group(v, "Поиск в интернете")
        self._add(f7, "web_search.backend", "Поисковик", "combo", options=[("duckduckgo", "DuckDuckGo"), ("searxng", "SearXNG")])
        self._add(f7, "web_search.searxng_url", "SearXNG URL", placeholder="http://localhost:8080")
        v.addStretch(1)
        return w

    def _tab_games(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        g = QGroupBox("Найденные игры и программы")
        gl = QVBoxLayout(g)
        self.games_filter = QLineEdit()
        self.games_filter.setPlaceholderText("Фильтр…")
        self.games_filter.textChanged.connect(self._games_fill)
        self.games_list = QListWidget()
        self.games_list.setMinimumHeight(220)
        row = QHBoxLayout()
        b = QPushButton("Пересканировать")
        b.clicked.connect(self._games_rescan)
        self.games_status = QLabel("")
        row.addWidget(b)
        row.addWidget(self.games_status, 1)
        gl.addWidget(self.games_filter)
        gl.addWidget(self.games_list)
        gl.addLayout(row)
        v.addWidget(g)
        g2 = QGroupBox("Псевдонимы (что говоришь → название игры/программы)")
        g2l = QVBoxLayout(g2)
        self._aliases_path = PROJECT_ROOT / "aliases.yaml"
        try:
            data = yaml.safe_load(self._aliases_path.read_text(encoding="utf-8")) or {}
        except Exception:
            data = {}
        self.aliases_table = KeyValueTable("Говорю", "Запускать", {k: v for k, v in data.items() if v})
        self.aliases_table.setMinimumHeight(220)
        g2l.addWidget(self.aliases_table)
        v.addWidget(g2)
        f = self._group(v, "Поиск")
        self._add(f, "apps.min_score", "Строгость совпадения", "slider", scale=(0.5, 0.95))
        self._games_entries: list = []
        QTimer.singleShot(300, self._games_load)
        return w

    def _tab_audio(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        g = QGroupBox("Псевдонимы аудиоустройств («переключи на наушники»)")
        gl = QVBoxLayout(g)
        self.audio_aliases = KeyValueTable("Говорю", "Часть имени устройства в Windows",
                                           get_path(self.raw, "audio_devices.aliases") or {})
        self.audio_aliases.setMinimumHeight(200)
        gl.addWidget(self.audio_aliases)
        v.addWidget(g)
        g2 = QGroupBox("Устройства сейчас")
        g2l = QVBoxLayout(g2)
        lst = QListWidget()
        try:
            from ..skills.audio_devices_skill import list_endpoints
            for _, n in list_endpoints(False):
                lst.addItem("🔊 " + n)
            for _, n in list_endpoints(True):
                lst.addItem("🎤 " + n)
        except Exception:
            try:
                import sounddevice as sd
                for d in sd.query_devices():
                    lst.addItem(("🎤 " if d["max_input_channels"] else "🔊 ") + d["name"])
            except Exception as e:
                lst.addItem(f"Список недоступен: {e}")
        lst.itemDoubleClicked.connect(lambda it: self.audio_aliases.add_row("", it.text()[2:]))
        g2l.addWidget(QLabel("Двойной щелчок — добавить псевдоним"))
        g2l.addWidget(lst)
        v.addWidget(g2)
        return w

    def _tab_modules(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        f = self._group(v, "Модули (выключенный модуль не загружается)")
        failed = getattr(getattr(self.assistant, "router", None), "failed", {}) if self.assistant else {}
        for key, label in MODULES:
            cb = self._add(f, f"{key}.enabled", label, "bool")
            if key in failed:
                cb.setText(f"{label}  ⚠ не загрузился")
                cb.setToolTip(failed[key])
        v.addStretch(1)
        return w

    def _tab_backup(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        f = self._group(v, "Автоматический бэкап (заметки, задачи, память, настройки)")
        self._add(f, "backup.enabled", "Ежедневный бэкап", "bool")
        self._add(f, "backup.dir", "Папка", "path", placeholder="%LOCALAPPDATA%\\JarvisLite\\Backups")
        self._add(f, "backup.keep", "Хранить последних", "int", min=1, max=100)
        self._add(f, "backup.include_telegram", "Включать сессию Telegram (это ключ входа!)", "bool")
        g = QGroupBox("Бэкапы")
        gl = QVBoxLayout(g)
        self.backup_list = QListWidget()
        gl.addWidget(self.backup_list)
        row = QHBoxLayout()
        for text, fn in (("Сделать бэкап", self._backup_now), ("Восстановить выбранный", self._restore),
                         ("Восстановить из файла…", self._restore_file), ("Открыть папку", self._open_backups)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        gl.addLayout(row)
        v.addWidget(g)
        self._backup_reload()
        fs = self._group(v, "Синхронизация между ПК (общая папка в облаке, сети или на флешке)")
        self._add(fs, "sync.folder", "Общая папка", "path", placeholder="не выбрана — синхронизация выключена")
        try:
            from ..sync import suggest_folders
            sug = suggest_folders()
        except Exception:
            sug = []
        if sug:
            row = QHBoxLayout()
            for p in sug[:4]:
                b = QPushButton(p.name or str(p))
                b.setToolTip(str(p))
                b.clicked.connect(lambda _=False, pp=str(p): self.fields["sync.folder"][0]._edit.setText(pp))
                row.addWidget(b)
            row.addStretch(1)
            fs.addRow("Найдены", row)
        self._add(fs, "sync.device_name", "Имя этого ПК", placeholder="имя компьютера")
        self._add(fs, "sync.auto_on_start", "Синхронизировать при запуске", "bool")
        self._add(fs, "sync.auto_on_exit", "Синхронизировать при выходе", "bool")
        self._add(fs, "sync.interval_min", "И каждые (0 = выкл.)", "int", max=1440, suffix=" мин")
        self.sync_status = QLabel(self._sync_state())
        self.sync_status.setWordWrap(True)
        b = QPushButton("Синхронизировать сейчас")
        b.clicked.connect(self._sync_now)
        row = QHBoxLayout()
        row.addWidget(b)
        row.addWidget(self.sync_status, 1)
        fs.addRow(row)
        fs.addRow(QLabel("Синхронизируются: заметки, задачи, память, псевдонимы игр, цвет голограммы, режимы.\n"
                         "Не синхронизируются: микрофон/звук, потоки, горячие клавиши, Telegram, токены и ключи.\n"
                         "Перед каждой синхронизацией делается бэкап."))
        return w

    def _tab_help(self) -> QWidget:
        from PySide6.QtWidgets import QTextBrowser

        from ..helpinfo import as_html
        w = QWidget()
        v = QVBoxLayout(w)
        tb = QTextBrowser()
        tb.setOpenExternalLinks(True)
        tb.setHtml(as_html())
        tb.setMinimumHeight(520)
        v.addWidget(tb)
        return w

    def _tab_about(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        f = self._group(v, "О программе")
        f.addRow("Версия", QLabel(f"Джарвис Лайт {__version__} (без ИИ)  •  Python {sys.version.split()[0]}"))
        f.addRow("Программа", QLabel(str(PROJECT_ROOT)))
        f.addRow("Данные", QLabel(str(pu.data_dir(""))))
        f2 = self._group(v, "Обновления")
        self._add(f2, "update.check_on_start", "Проверять при запуске (раз в сутки)", "bool")
        self._add(f2, "update.github_repo", "Репозиторий GitHub", placeholder="owner/repo")
        row = QHBoxLayout()
        b = QPushButton("Проверить обновления")
        b.clicked.connect(lambda: self.ctl.check_updates(manual=True) if self.ctl else None)
        row.addWidget(b)
        row.addStretch(1)
        f2.addRow(row)
        f3 = self._group(v, "Обслуживание")
        row = QHBoxLayout()
        for text, fn in (("Самодиагностика", lambda: self.ctl.run_diagnostics() if self.ctl else None),
                         ("Открыть логи", self._open_logs), ("Экспорт настроек…", self._export),
                         ("Импорт настроек…", self._import)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        f3.addRow(row)
        self._add(f3, "logging.level", "Подробность логов", "combo", options=["INFO", "DEBUG", "WARNING"])
        v.addStretch(1)
        return w

    # ================================================================ populate / defaults / save
    def populate(self, cfg: dict) -> None:
        for path in self.fields:
            self._set(path, get_path(cfg, path))

    def _defaults(self) -> None:
        if QMessageBox.question(self, "По умолчанию", "Вернуть все значения по умолчанию? "
                                "(Применится после «Сохранить».)") != QMessageBox.Yes:
            return
        d = raw_config(use_local=False)
        self.populate(d)
        self.audio_aliases.set_data(get_path(d, "audio_devices.aliases") or {})
        self._reset_all = True
        self._preview_ui()

    def collect(self) -> dict:
        out: dict = {}
        for path in self.fields:
            set_path(out, path, self._get(path))
        out.setdefault("audio_devices", {})["aliases"] = self.audio_aliases.data()
        return out

    def validate(self, ch: dict) -> list[str]:
        errs = []
        if not get_path(ch, "assistant.name"):
            errs.append("Имя ассистента не может быть пустым")
        import re
        for p in ("profiles.night_schedule.start", "profiles.night_schedule.end"):
            val = get_path(ch, p) or ""
            if val and not re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", val):
                errs.append(f"Время «{val}» — нужно ЧЧ:ММ")
        repo = get_path(ch, "update.github_repo") or ""
        if repo and not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
            errs.append("Репозиторий обновлений: формат owner/repo")
        url = get_path(ch, "web_search.searxng_url") or ""
        if url and not url.startswith(("http://", "https://")):
            errs.append("SearXNG URL должен начинаться с http://")
        if get_path(ch, "telegram.enabled") and (not get_path(ch, "telegram.api_id") or not get_path(ch, "telegram.api_hash")):
            errs.append("Telegram: укажи api_id и api_hash или выключи модуль")
        if get_path(ch, "alerts.backend") == "alerts_in_ua" and not (
                self.alerts_token.text().strip() or self._alerts_stored_token()):
            errs.append("alerts.in.ua: нужен токен (или выбери «Авто»)")
        hk = {"Говорить": get_path(ch, "gui.hotkey_ptt"), "Пауза микрофона": get_path(ch, "gui.hotkey_mic"),
              "Показать окно": get_path(ch, "gui.hotkey_show"), "Вопрос по игре": get_path(ch, "gui.hotkey_game"),
              "Диктовка": get_path(ch, "dictate.hotkey"), "Остановить": get_path(ch, "gui.hotkey_stop")}
        errs += hotkey_conflicts(hk)
        y = self._check_yaml(self.devices_edit.toPlainText())
        if y:
            errs.append("devices.yaml: " + y)
        return errs

    @staticmethod
    def _check_yaml(text: str) -> str:
        try:
            data = yaml.safe_load(text)
            if data is not None and not isinstance(data, dict):
                return "ожидается словарь"
            return ""
        except Exception as e:
            return str(e).splitlines()[0]

    def _save(self) -> None:
        ch = self.collect()
        errs = self.validate(ch)
        if errs:
            self.err.setText("⚠ " + "; ".join(errs[:4]))
            return
        changed = diff(ch, self.raw)
        try:
            if getattr(self, "_reset_all", False):
                LOCAL_SETTINGS.unlink(missing_ok=True)
            save_local_settings(ch)
            from ..secrets import set_secret
            if self.alerts_token.text().strip():
                set_secret(self._alerts_secret, self.alerts_token.text().strip())
                self.alerts_token.clear()
                changed.append("alerts.backend")        # provider is rebuilt on restart
            new_dev = self.devices_edit.toPlainText()
            if new_dev != (self._devices_path.read_text(encoding="utf-8") if self._devices_path.exists() else ""):
                self._devices_path.write_text(new_dev, encoding="utf-8")
                changed.append("smarthome.devices")
            aliases = self.aliases_table.data()
            self._aliases_path.write_text(
                "# Псевдонимы игр и программ: что говоришь -> название (или steam://, путь к .exe/.lnk)\n"
                + yaml.safe_dump(aliases, allow_unicode=True, sort_keys=False), encoding="utf-8")
        except Exception as e:
            QMessageBox.critical(self, "Настройки", f"Не удалось сохранить: {e}")
            return
        self.restart_needed = any(c.startswith(RESTART_KEYS) for c in changed)
        self.changes, self.changed_keys = ch, changed
        self._stop_meter()
        self.accept()

    def reject(self) -> None:
        self._stop_meter()
        if self.ctl:                    # undo live previews
            self.ctl.preview_ui(self.cfg["gui"])
        super().reject()

    # ================================================================ live previews
    def _preview_ui(self) -> None:
        if self.ctl:
            self.ctl.preview_ui({"opacity": self._get("gui.opacity"), "color": self._get("gui.color")})

    def _preview_voice(self) -> None:
        t = copy.deepcopy(self.cfg["tts"])
        t.update({"piper_voice": self._get("tts.piper_voice"), "length_scale": self._get("tts.length_scale"),
                  "pitch_semitones": self._get("tts.pitch_semitones"), "volume": self._get("tts.volume"),
                  "fx": {"enabled": self._get("tts.fx.enabled"), "intensity": self._get("tts.fx.intensity")}})
        text = self.preview_text.text().strip() or "Проверка голоса."
        self.voice_status.setText("Синтезирую…")

        def work():
            try:
                from ..config import resolve_path
                from ..tts import PiperTTS, ensure_voice
                path = resolve_path(t.get("voices_dir", "voices")) / f"{t['piper_voice']}.onnx"
                if not path.exists():
                    self._sig.emit("voice", "Скачиваю голос…")
                    ensure_voice(t["piper_voice"], path.parent)
                audio, rate = PiperTTS(t).synthesize(text)
                import sounddevice as sd
                sd.play(audio, rate)
                self._sig.emit("voice", "")
            except Exception as e:
                self._sig.emit("voice", f"Не получилось: {e}")
        threading.Thread(target=work, daemon=True).start()

    def _toggle_meter(self, on: bool) -> None:
        if not on:
            self._stop_meter()
            return
        try:
            import numpy as np
            import sounddevice as sd
            from ..audio import resolve_device
            dev = resolve_device(self._get("audio.input_device"), "input")

            def cb(indata, frames, t, status):
                self._mic_level = float(np.sqrt(np.mean(indata[:, 0] ** 2)))
            self._mic_stream = sd.InputStream(device=dev, channels=1, samplerate=16000, callback=cb)
            self._mic_stream.start()
            self._meter = QTimer(self)
            self._meter.timeout.connect(lambda: self.level.setValue(min(100, int(self._mic_level * 800))))
            self._meter.start(50)
            self.btn_level.setText("Стоп")
        except Exception as e:
            self.btn_level.setChecked(False)
            self._flash(f"Микрофон не открылся: {e}")

    def _stop_meter(self) -> None:
        if self._mic_stream is not None:
            try:
                self._mic_stream.stop()
                self._mic_stream.close()
            except Exception:
                pass
            self._mic_stream = None
        if getattr(self, "_meter", None):
            self._meter.stop()
        if hasattr(self, "level"):
            self.level.setValue(0)
            self.btn_level.setText("Проверить уровень")

    # ================================================================ helpers for tabs
    def _flash(self, text: str) -> None:
        self.err.setText(text)
        QTimer.singleShot(6000, lambda: self.err.setText("") if self.err.text() == text else None)

    def _on_sig(self, name: str, payload) -> None:
        if name == "voice":
            self.voice_status.setText(payload)
        elif name == "geo":
            if isinstance(payload, dict):
                self._set("weather.latitude", payload["latitude"])
                self._set("weather.longitude", payload["longitude"])
                self._set("weather.timezone", payload.get("timezone", ""))
                self._flash(f"Нашёл: {payload.get('name')}, {payload.get('country', '')}")
            else:
                self._flash(str(payload))
        elif name == "games":
            self._games_entries = payload
            self._games_fill()
        elif name == "syncstate":
            self.sync_status.setText(self._sync_state())
        elif name == "flash":
            self._flash(payload)

    def _geocode(self) -> None:
        city = self._get("weather.city")

        def work():
            try:
                import requests
                r = requests.get("https://geocoding-api.open-meteo.com/v1/search",
                                 params={"name": city, "count": 1, "language": "ru"}, timeout=10).json()
                res = (r.get("results") or [None])[0]
                self._sig.emit("geo", res or f"Город «{city}» не найден")
            except Exception as e:
                self._sig.emit("geo", f"Нет связи: {e}")
        threading.Thread(target=work, daemon=True).start()

    def _show_variants(self) -> None:
        from ..wake import generate_variants
        vs = generate_variants(self._get("assistant.name") or "Джарвис", self._get("assistant.extra_wake_words"))
        QMessageBox.information(self, "Варианты имени", ", ".join(vs))

    # --- telegram
    def _tg_session(self) -> Path:
        return pu.data_dir("", get_path(self.raw, "telegram.dir") or "") / "telegram.session"

    def _tg_state(self) -> str:
        return "вход выполнен ✓" if self._tg_session().exists() else "не выполнен вход"

    def _tg_login(self) -> None:
        if not self._get("telegram.api_id") or not self._get("telegram.api_hash"):
            self._flash("Сначала укажи api_id и api_hash и нажми «Сохранить»")
            return
        save_local_settings({"telegram": {"api_id": self._get("telegram.api_id"), "api_hash": self._get("telegram.api_hash")}})
        from .. import diagnostics
        self._flash(diagnostics.fix("telegram_login", self.cfg))

    def _tg_logout(self) -> None:
        s = self._tg_session()
        if not s.exists():
            self._flash("Сессии нет")
            return
        if QMessageBox.question(self, "Telegram", "Удалить сессию Telegram с этого ПК? Потом нужно будет войти снова.") == QMessageBox.Yes:
            try:
                s.unlink()
                self.tg_status.setText(self._tg_state())
                self.restart_needed = True
            except Exception as e:
                self._flash(f"Не удалось удалить (перезапусти Джарвиса Лайт): {e}")

    def select_tab(self, key: str) -> None:
        names = {"integrations": "Интеграции", "ui": "Интерфейс", "backup": "Бэкап и синхронизация",
                 "help": "Что я умею"}
        title = names.get(key, key)
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i) == title:
                self.tabs.setCurrentIndex(i)
                return

    def _alerts_stored_token(self) -> str:
        from ..alerts_sources import stored_token
        return stored_token(self.cfg.get("alerts") or {})

    def _alerts_test(self) -> None:
        """Probe every alert source with the values in the dialog; short Russian result per source."""
        from .. import alerts_sources as asrc
        a = dict(self.cfg.get("alerts") or {})
        a.update(oblast=self._get("alerts.oblast"), raions=self._get("alerts.raions") or [])
        tok = self.alerts_token.text().strip() or self._alerts_stored_token()
        self._flash("Проверяю источники тревог…")

        def work():
            parts = []
            for key in asrc.DEFAULT_ORDER:
                cls = asrc.SOURCES[key]
                kw = {"token_getter": (lambda: tok)} if key == "alerts_in_ua" else {}
                src = cls(a.get("oblast", ""), a.get("raions") or [], **kw)
                if not src.available():
                    parts.append(f"{cls.title}: без токена")
                    continue
                try:
                    st = src.fetch()
                    parts.append(f"{cls.title}: ✓ {'ТРЕВОГА' if st.active else 'тревоги нет'}")
                except Exception as e:
                    parts.append(f"{cls.title}: ✗ {asrc.short_reason(e)}")
            self._sig.emit("flash", " · ".join(parts))
        threading.Thread(target=work, daemon=True).start()

    # --- games
    def _launcher(self):
        a = self.assistant
        sk = a.router.by_name.get("apps") if a else None
        if sk is not None and hasattr(sk, "launcher"):
            return sk.launcher
        from ..launcher import Launcher
        return Launcher(self.cfg.get("apps", {}), PROJECT_ROOT / "aliases.yaml")

    def _games_load(self, rebuild: bool = False) -> None:
        self.games_status.setText("Сканирую…")

        def work():
            try:
                lz = self._launcher()
                if rebuild or not getattr(lz, "entries", None):
                    lz.build()
                ents = sorted(((e.name, e.kind) for e in getattr(lz, "entries", [])), key=lambda x: (x[1] != "steam", x[0].lower()))
                self._sig.emit("games", ents)
            except Exception as e:
                self._sig.emit("flash", f"Сканирование не удалось: {e}")
                self._sig.emit("games", [])
        threading.Thread(target=work, daemon=True).start()

    def _games_rescan(self) -> None:
        self._games_load(rebuild=True)

    def _games_fill(self) -> None:
        flt = self.games_filter.text().lower().strip()
        self.games_list.clear()
        icons = {"steam": "🎮", "epic": "🎮", "shortcut": "▫", "start": "▫"}
        n = 0
        for name, kind in self._games_entries:
            if flt and flt not in name.lower():
                continue
            self.games_list.addItem(f"{icons.get(kind, '▫')} {name}   [{kind}]")
            n += 1
        games = sum(1 for _, k in self._games_entries if k in ("steam", "epic"))
        self.games_status.setText(f"Игр: {games}, всего: {len(self._games_entries)}")

    # --- memory
    def _mem_reload(self, *_):
        self.mem_list.clear()
        if not self.memory:
            self.mem_list.addItem("Модуль памяти выключен.")
            return
        flt = self.mem_filter.text().lower().strip() if hasattr(self, "mem_filter") else ""
        for it in self.memory.all():
            if flt and flt not in it.text.lower():
                continue
            item = QListWidgetItem(("📌 " if it.kind == "fact" else "🕘 ") + it.text)
            item.setData(256, it.id)
            self.mem_list.addItem(item)

    def _mem_add(self):
        if self.memory:
            text, ok = QInputDialog.getText(self, "Память", "Новый факт:")
            if ok and text.strip():
                self.memory.add(text.strip())
                self._mem_reload()

    def _mem_edit(self):
        item = self.mem_list.currentItem()
        if self.memory and item and item.data(256):
            text, ok = QInputDialog.getText(self, "Память", "Текст:", text=item.text()[2:].strip())
            if ok and text.strip():
                self.memory.update(item.data(256), text.strip())
                self._mem_reload()

    def _mem_del(self):
        item = self.mem_list.currentItem()
        if self.memory and item and item.data(256):
            self.memory.delete(item.data(256))
            self._mem_reload()

    # --- backup
    def _backup_reload(self):
        from ..backup import list_backups
        self.backup_list.clear()
        try:
            for p in list_backups(self.cfg):
                it = QListWidgetItem(f"{p.name}   ({p.stat().st_size // 1024} КБ)")
                it.setData(256, str(p))
                self.backup_list.addItem(it)
        except Exception as e:
            self.backup_list.addItem(f"Папка недоступна: {e}")

    def _backup_now(self):
        from ..backup import make_backup
        try:
            p = make_backup(self.cfg, "manual")
            self._backup_reload()
            self._flash(f"Бэкап создан: {p.name}")
        except Exception as e:
            self._flash(f"Бэкап не удался: {e}")

    def _do_restore(self, path: str):
        if QMessageBox.question(self, "Восстановление", f"Восстановить данные из\n{Path(path).name}?\n\n"
                                "Текущие заметки, задачи, память и настройки будут заменены. "
                                "Джарвис перезапустится.") != QMessageBox.Yes:
            return
        try:
            from ..backup import make_backup, stage_restore
            make_backup(self.cfg, "before-restore")       # safety net
            stage_restore(Path(path))
        except Exception as e:
            self._flash(f"Не удалось: {e}")
            return
        self.restart_needed = True
        self.changes, self.changed_keys = {}, []
        self._force_restart = True
        self.accept()

    def _restore(self):
        it = self.backup_list.currentItem()
        if it and it.data(256):
            self._do_restore(it.data(256))
        else:
            self._flash("Выбери бэкап в списке")

    def _restore_file(self):
        p, _ = QFileDialog.getOpenFileName(self, "Бэкап Джарвиса", str(Path.home()), "Бэкап (*.zip)")
        if p:
            self._do_restore(p)

    def _open_backups(self):
        from ..backup import backup_dir
        pu.open_path(backup_dir(self.cfg))

    # --- sync
    def _sync_state(self) -> str:
        try:
            import json
            st = json.loads((pu.data_dir("") / "sync_state.json").read_text(encoding="utf-8"))
            return f"Последняя: {str(st.get('last_sync', '—'))[:19].replace('T', ' ')} UTC, {st.get('last_result', '')}"
        except Exception:
            return "Ещё не синхронизировалось"

    def _sync_now(self) -> None:
        folder = self._get("sync.folder")
        if not folder:
            self._flash("Сначала выбери общую папку")
            return
        save_local_settings({"sync": {"folder": folder, "device_name": self._get("sync.device_name")}})
        self.cfg.setdefault("sync", {}).update({"folder": folder, "device_name": self._get("sync.device_name")})
        self.sync_status.setText("Синхронизирую…")

        def work():
            from ..sync import SyncEngine
            a = self.assistant
            r = a.sync_now() if a and getattr(a, "sync_engine", None) else SyncEngine(self.cfg).sync()
            self._sig.emit("flash", r.message)
            self._sig.emit("syncstate", None)
        threading.Thread(target=work, daemon=True).start()

    # --- about
    def _open_logs(self):
        from ..config import resolve_path
        pu.open_path(resolve_path(self.cfg["logging"].get("file", "logs/jarvis.log")).parent)

    def _export(self):
        p, _ = QFileDialog.getSaveFileName(self, "Экспорт настроек", str(Path.home() / "jarvis-settings.yaml"), "YAML (*.yaml)")
        if not p:
            return
        data = self.collect()
        # secrets are not exported
        for path in ("telegram.api_hash", "alerts.alerts_in_ua_token"):
            set_path(data, path, "")
        Path(p).write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        self._flash("Экспортировано (без токенов и ключей)")

    def _import(self):
        p, _ = QFileDialog.getOpenFileName(self, "Импорт настроек", str(Path.home()), "YAML (*.yaml *.yml)")
        if not p:
            return
        try:
            data = yaml.safe_load(Path(p).read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("файл не похож на настройки")
            from ..config import deep_merge
            self.populate(deep_merge(self.raw, data))
            self._flash("Загружено — проверь и нажми «Сохранить»")
        except Exception as e:
            self._flash(f"Ошибка импорта: {e}")
