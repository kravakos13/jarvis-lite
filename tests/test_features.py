"""Notes, scheduler, smart home dispatch, Steam/Epic parsing, web answers, Telegram confirm, config migration."""
import datetime as dt
import json
import threading
import time
from pathlib import Path


from jarvis.config import load_config




# ------------------------------------------------------------------ notes
def test_notes_save_and_dictation(tmp_path):
    from jarvis.notes import Notes
    n = Notes({"dir": str(tmp_path)})
    p = n.save("купить хлеб", now=dt.datetime(2026, 10, 17, 9, 5))
    assert p.exists() and "купить хлеб" in p.read_text(encoding="utf-8")
    n.start_dictation()
    n.add_dictation("первая строка")
    n.add_dictation("вторая")
    p2 = n.finish_dictation()
    assert p2 and "вторая" in p2.read_text(encoding="utf-8")
    assert len(n.latest(5)) == 2


# ------------------------------------------------------------------ reminders scheduler
def test_scheduler_fires_once(tmp_path):
    from jarvis.planner import Planner
    pl = Planner({}, db_path=tmp_path / "p.sqlite3")
    pl.add("выключить чайник", dt.datetime.now() - dt.timedelta(minutes=1))
    pl.add("потом", dt.datetime.now() + dt.timedelta(days=1))
    fired = []
    ev = threading.Event()
    pl.start_scheduler(lambda t: (fired.append(t.text), ev.set()), interval_s=0.05)
    assert ev.wait(3)
    time.sleep(0.3)
    pl.stop()
    assert fired == ["выключить чайник"]


def test_planner_crud_and_find(tmp_path):
    from jarvis.planner import Planner
    pl = Planner({}, db_path=tmp_path / "p.sqlite3")
    t = pl.add("позвонить в сервис", dt.datetime(2026, 10, 18, 10, 0))
    assert pl.find("сервис").id == t.id
    assert pl.set_done(t.id) and pl.list() == []
    assert pl.delete(t.id)
    assert pl.conn.execute("select count(*) from tombstones").fetchone()[0] == 1


# ------------------------------------------------------------------ smart home
def test_smarthome_dispatch(tmp_path, monkeypatch):
    from jarvis import smarthome
    (tmp_path / "devices.yaml").write_text("""
devices:
  lamp: {name: Свет в комнате, type: light, protocol: tasmota, host: 192.168.1.50, aliases: [свет, лампа]}
  relay2: {name: Реле 2, type: switch, protocol: esphome, host: esp.local, entity: relay_2}
  ha_tv: {name: Телевизор, type: switch, protocol: homeassistant, entity_id: switch.tv}
  sensor: {name: Датчик, type: sensor, protocol: http, state_url: http://esp.local/json,
           fields: {temperature: dht.t, humidity: dht.h}}
homeassistant: {url: http://ha.local:8123, token: TKN}
""", encoding="utf-8")
    calls = []

    class R:
        def __init__(self, data=None):
            self.data = data or {}

        def raise_for_status(self):
            pass

        def json(self):
            return self.data
    def fake(method, url, timeout=None, **kw):
        calls.append((method, url, kw))
        return R({"dht": {"t": 21.5, "h": 40}})
    monkeypatch.setattr(smarthome.requests, "request", fake)
    sh = smarthome.SmartHome(tmp_path / "devices.yaml")
    lamp = sh.find("свет в комнате")
    assert lamp and lamp.id == "lamp"
    sh.set_state(lamp, True)
    sh.set_state(sh.find("реле 2"), False)
    sh.set_state(sh.find("телевизор"), True)
    assert calls[0][1] == "http://192.168.1.50/cm" and calls[0][2]["params"] == {"cmnd": "Power1 On"}
    assert calls[1][1] == "http://esp.local/switch/relay_2/turn_off"
    assert calls[2][1] == "http://ha.local:8123/api/services/switch/turn_on"
    assert calls[2][2]["headers"]["Authorization"] == "Bearer TKN"
    vals = sh.read(sh.find("датчик", want_sensor=True))
    assert vals == {"temperature": 21.5, "humidity": 40}
    assert "21" in smarthome.spoken_reading(sh.find("датчик", want_sensor=True), vals)


# ------------------------------------------------------------------ Steam / Epic
def test_steam_epic_parsing(tmp_path):
    from jarvis.launcher import Launcher, epic_games, steam_games
    steam = tmp_path / "Steam"
    lib2 = tmp_path / "D" / "SteamLibrary"
    (steam / "steamapps").mkdir(parents=True)
    (lib2 / "steamapps").mkdir(parents=True)
    (steam / "steamapps" / "libraryfolders.vdf").write_text(
        '"libraryfolders"\n{\n "0" { "path" "%s" }\n "1" { "path" "%s" }\n}' % (steam, lib2), encoding="utf-8")
    (steam / "steamapps" / "appmanifest_730.acf").write_text('"AppState"\n{\n "appid" "730"\n "name" "Counter-Strike 2"\n}', encoding="utf-8")
    (lib2 / "steamapps" / "appmanifest_570.acf").write_text('"AppState"\n{\n "appid" "570"\n "name" "Dota 2"\n}', encoding="utf-8")
    (lib2 / "steamapps" / "appmanifest_228980.acf").write_text('"AppState"\n{\n "appid" "228980"\n "name" "Steamworks Common Redistributables"\n}', encoding="utf-8")
    games = {e.name: e.target for e in steam_games(steam)}
    assert games == {"Counter-Strike 2": "steam://rungameid/730", "Dota 2": "steam://rungameid/570"}
    man = tmp_path / "Manifests"
    man.mkdir()
    (man / "a.item").write_text(json.dumps({"AppName": "Fortnite", "DisplayName": "Fortnite", "CatalogNamespace": "fn",
                                            "CatalogItemId": "4fe7", "bIsIncompleteInstall": False}), encoding="utf-8")
    (man / "b.item").write_text(json.dumps({"AppName": "Half", "bIsIncompleteInstall": True}), encoding="utf-8")
    (man / "c.item").write_text("{broken", encoding="utf-8")
    ep = epic_games(man)
    assert [e.name for e in ep] == ["Fortnite"] and "fn%3A4fe7%3AFortnite" in ep[0].target
    lz = Launcher({"min_score": 0.6})
    lz.entries = steam_games(steam) + ep
    from jarvis.launcher import phonetic
    for e in lz.entries:
        e.key = e.key or phonetic(e.name)
    (tmp_path / "aliases.yaml").write_text("кс: Counter-Strike 2\nдота: Dota 2\n", encoding="utf-8")
    lz.aliases_path = tmp_path / "aliases.yaml"
    lz.load_aliases()
    assert lz.find("кс")[0].name == "Counter-Strike 2"
    assert lz.find("дота")[0].name == "Dota 2"
    assert lz.find("фортнайт")[0].name == "Fortnite"


# ------------------------------------------------------------------ web answers
def test_web_answer_pipeline(monkeypatch):
    """Lite: no AI — the best snippet is said (two sentences max), pages are fetched only if snippets are useless."""
    from jarvis.websearch import Source, WebSearch
    ws = WebSearch({"fetch_pages": 2})
    fetched = []
    monkeypatch.setattr(ws, "search", lambda q: [
        Source("Rockstar", "https://rockstargames.com/VI", "коротко"),
        Source("Wiki", "https://wiki.example/gta6", "GTA 6 выходит осенью 2026 года. Игру делает Rockstar. Третье.")])
    monkeypatch.setattr(ws, "_fetch", lambda s: fetched.append(s) or s)
    a = ws.answer("когда выйдет gta 6")
    assert a.ok and a.answer == "GTA 6 выходит осенью 2026 года. Игру делает Rockstar." and len(a.sources) == 2
    assert fetched == []                                                        # a good snippet: no page downloads
    assert ws.answer("когда выйдет gta 6") is a                                 # cached

    ws3 = WebSearch({"fetch_pages": 2})
    monkeypatch.setattr(ws3, "search", lambda q: [Source("A", "https://a.example", "мало"),
                                                  Source("B", "https://b.example", "")])

    def fetch(s):
        s.text = f"Страница {s.title} рассказывает о квазарах подробно и понятно. Вторая фраза. Третья."
        return s
    monkeypatch.setattr(ws3, "_fetch", fetch)
    assert ws3.answer("что такое квазар").answer == "Страница A рассказывает о квазарах подробно и понятно. Вторая фраза."

    def boom(q):
        raise ConnectionError("offline")
    ws2 = WebSearch({})
    monkeypatch.setattr(ws2, "search", boom)
    off = ws2.answer("погода")
    assert not off.ok and "интернет" in off.answer


# ------------------------------------------------------------------ telegram confirm flow
def test_telegram_confirm_flow():
    from jarvis.router import Router
    from jarvis.skills.base import SkillContext
    from jarvis.skills.telegram_skill import TelegramSkill
    from jarvis.telegram_client import TgDialog

    class FakeSvc:
        def __init__(self):
            self.sent = []

        def dialogs(self):
            return [TgDialog(1, "Мама", 0), TgDialog(2, "Вася Петров", 2)]

        def send(self, did, text):
            self.sent.append((did, text))
    cfg = load_config(use_local=False)
    ctx = SkillContext(cfg=cfg, say=lambda *a: None, notify=lambda *a: None, project_root=Path("."))
    svc = FakeSvc()
    off = {k: {"enabled": False} for k, v in cfg.items() if isinstance(v, dict) and "enabled" in v}
    r = Router(SkillContext(cfg={**cfg, **off}, say=lambda *a: None, notify=lambda *a: None,
                            project_root=Path(".")))
    tg = TelegramSkill(ctx, service=svc)
    r.skills.insert(0, tg)
    r.by_name["telegram"] = tg
    res = r.handle("напиши маме в телеграм что буду через час")
    assert "Отправить Мама" in (res.reply or "") and svc.sent == []           # read back + ask
    res = r.handle("нет")
    assert svc.sent == [] and "Не отправляю" in res.reply
    r.handle("напиши маме в телеграм что буду через час")
    r.handle("да, отправляй")
    assert svc.sent == [(1, "буду через час")]


# ------------------------------------------------------------------ config migration
def test_config_migration(tmp_path, monkeypatch):
    """Lite: a settings.local.yaml copied from the full Jarvis loses its AI / GPU parts, the rest is kept."""
    import yaml
    import jarvis.config as c
    old = tmp_path / "settings.local.yaml"
    old.write_text(yaml.safe_dump({"assistant": {"name": "Пятница"}, "llm": {"model": "qwen2.5:7b"},
                                   "ollama": {"fast_kv": True}, "lumo": {"enabled": True},
                                   "stt": {"device": "cuda", "compute_type": "float16", "model": "small"},
                                   "gui": {"face_style": "3d", "color": "#123123"}}, allow_unicode=True),
                   encoding="utf-8")
    monkeypatch.setattr(c, "LOCAL_SETTINGS", old)
    cfg = c.load_config()
    assert cfg["assistant"]["name"] == "Пятница" and cfg["gui"]["color"] == "#123123"
    assert not {"llm", "ollama", "lumo"} & set(cfg)
    assert cfg["stt"]["device"] == "cpu" and cfg["stt"]["compute_type"] == "int8"
    assert cfg["gui"].get("face_style", "2d") == "2d"
    saved = yaml.safe_load(old.read_text(encoding="utf-8"))
    assert saved["config_version"] == c.CONFIG_VERSION and "llm" not in saved and "device" not in saved["stt"]
    old.write_text("{{{ broken", encoding="utf-8")
    cfg = c.load_config()                                                      # corrupted file -> defaults, no crash
    assert cfg["assistant"]["name"] == "Джарвис"
    c.save_local_settings({"gui": {"color": "#123456"}})
    assert yaml.safe_load(old.read_text(encoding="utf-8"))["gui"]["color"] == "#123456"
    assert (tmp_path / "settings.local.yaml.broken").exists()


def test_watchdog_no_crash_loop(monkeypatch):
    from jarvis import watchdog
    codes = iter([1, 75, 1, 1, 1, 1])
    calls = []
    monkeypatch.setattr(watchdog, "_single_instance", lambda: object())
    monkeypatch.setattr(watchdog, "_notify", lambda t: None)
    monkeypatch.setattr(watchdog.time, "sleep", lambda s: None)
    monkeypatch.setattr(watchdog.subprocess, "call", lambda argv, **kw: (calls.append(argv), next(codes))[1])
    assert watchdog.main([]) == 1
    assert len(calls) == 4          # crash, restart-request, crash, crash -> stop after 3 crashes
    assert "--minimized" in calls[-1]
