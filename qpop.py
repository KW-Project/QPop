"""
QPop - push a notification to your phone when a queue pops.

Supports:
  * League of Legends / TFT  (via the League client's local API)
  * Deadlock                 (via console.log, needs the -condebug launch option)

Notifications go through ntfy (https://ntfy.sh) - install the ntfy app on your
phone (iPhone or Android) and subscribe to the topic shown in the setup window.

Usage:
  python qpop.py            run the watcher
  python qpop.py --test     send a test notification and exit
  python qpop.py --debug    also print raw Deadlock GC/matchmaking log lines
  python qpop.py --install  start with Windows + Start menu entry (done automatically on first run)
  python qpop.py --uninstall  undo --install
  python qpop.py --stop     stop the background copy
  python qpop.py --no-tray  don't show the system tray icon
  python qpop.py --show     open the setup / status window
"""

import base64
import ctypes
import json
import queue
import os
import re
import secrets
import shutil
import signal
import ssl
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime

from winutil import process_name, process_running

__version__ = "0.1.0"

# GitHub repo that publishes QPop releases, as "owner/name". Leave empty to turn update checks off.
UPDATE_REPO = "KW-Project/QPop"

# FROZEN = running as the packaged QPop.exe (PyInstaller) rather than as a .py script.
FROZEN = getattr(sys, "frozen", False)
HERE = os.path.dirname(sys.executable if FROZEN else os.path.abspath(__file__))
# Installed by QPop-Setup.exe (Inno Setup puts its uninstaller next to the app). The installer
# then owns the Start menu entry and the "start with Windows" choice.
INSTALLED = FROZEN and os.path.exists(os.path.join(HERE, "unins000.exe"))
# Per-user files live in %APPDATA%\QPop, never next to the program: an installed exe's
# folder may not be writable, and the config holds the user's private topic.
DATA_DIR = os.path.join(os.environ.get("APPDATA") or HERE, "QPop")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
LOG_PATH = os.path.join(DATA_DIR, "qpop.log")
PID_PATH = os.path.join(DATA_DIR, "qpop.pid")
ICON_PATH = os.path.join(DATA_DIR, "icon.ico")
# Older installs, checked in order when there's no config yet: the app's pre-rename name
# ("Game Notify", 0.1.0), then pre-0.1.0 which kept config.json next to the script.
LEGACY_CONFIGS = [
    os.path.join(os.path.dirname(DATA_DIR), "GameNotify", "config.json"),
    os.path.join(HERE, "config.json"),
]


def visible_data_dir():
    """DATA_DIR as Explorer sees it. Microsoft Store Python silently redirects AppData writes
    into its own package folder, so when running as a script under it, open that instead.
    (The packaged exe isn't affected.)"""
    if not FROZEN and "WindowsApps" in sys.executable:
        import glob
        hits = glob.glob(os.path.join(os.environ.get("LOCALAPPDATA", ""), "Packages",
                                      "PythonSoftwareFoundation.Python.*", "LocalCache", "Roaming", "QPop"))
        if hits:
            return hits[0]
    return DATA_DIR
_PROGRAMS = os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs")
STARTUP_LNK = os.path.join(_PROGRAMS, "Startup", "QPop.lnk")
START_MENU_LNK = os.path.join(_PROGRAMS, "QPop.lnk")
OLD_SHORTCUTS = [os.path.join(_PROGRAMS, "Startup", "Game Notify.lnk"), os.path.join(_PROGRAMS, "Game Notify.lnk")]
SHOW_EVENT = r"Local\QPopShowWindow"

DEFAULT_CONFIG = {
    "ntfy_server": "https://ntfy.sh",
    "ntfy_topic": "",  # generated on first run
    "league": {
        "enabled": True,
        "notify_ready_check": True,   # the Accept / Decline screen
        "notify_champ_select": False, # everyone accepted
        "notify_game_start": False,   # loading screen
    },
    "deadlock": {
        "enabled": True,
        "console_log": "",  # empty = find it automatically from your Steam libraries
        # Any line matching one of these regexes counts as "match found".
        "match_patterns": [
            # The menu "hideout" is its own map, so any other map = a real match.
            r'\[Client\] Map: "(?!dl_hideout|<empty>)',
            r"CHostStateMgr::QueueNewRequest\( Loading \((?!dl_hideout)",
            r"k_EMsgGCToClient\w*Match\w*(Found|Ready)",
        ],
        "cooldown_seconds": 120,  # avoid several pings for one match
    },
    "phone": "iphone",       # which setup instructions the window shows: iphone | android
    "setup_shown": False,    # the window opens by itself until it has been shown once
    "check_updates": True,   # look for a newer release on startup and once a day
    "skipped_update": "",    # a version the user chose to ignore
}

DEBUG = "--debug" in sys.argv

# Shared state, shown in the tray menu.
STATUS = {"League": "starting...", "Deadlock": "starting..."}
UPDATE = {}  # {"version": "0.2.0", "url": "..."} once a newer release is found
PAUSED = threading.Event()
TRAY = None  # set when the tray icon is running


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #

def merge(defaults, override):
    out = dict(defaults)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(CONFIG_PATH):
        for old in LEGACY_CONFIGS:
            if os.path.exists(old):
                shutil.copy2(old, CONFIG_PATH)  # keep the existing topic when upgrading
                break
    saved = {}
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, encoding="utf-8") as f:
            saved = json.load(f)
    # Round-trip through JSON so we never share (and mutate) DEFAULT_CONFIG's nested dicts.
    cfg = merge(json.loads(json.dumps(DEFAULT_CONFIG)), saved)
    if not cfg["ntfy_topic"]:
        cfg["ntfy_topic"] = new_topic()
    save_config(cfg)
    return cfg


def save_config(cfg):
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, CONFIG_PATH)


def new_topic():
    return "qpop-" + secrets.token_hex(8)


def replace_topic(cfg):
    """Move to a brand-new private topic, e.g. when replacing a phone.

    Phones subscribed to the old topic stop getting alerts. They get one last
    message saying so, sent in the background."""
    old = cfg["ntfy_topic"]
    cfg["ntfy_topic"] = new_topic()
    save_config(cfg)
    log(f"Switched to a new topic: {cfg['ntfy_topic']}")
    threading.Thread(
        target=notify,
        args=(cfg, "QPop moved to a new phone",
              "This phone won't get queue alerts anymore. You can delete this subscription."),
        kwargs={"priority": "default", "tags": "wave", "force": True, "topic": old},
        daemon=True,
    ).start()
    return cfg["ntfy_topic"]


# --------------------------------------------------------------------------- #
# Notifications
# --------------------------------------------------------------------------- #

def notify(cfg, title, message, priority="urgent", tags="video_game", force=False, topic=None):
    """Send a push. force=True is for tests/system messages: ignores pause, no orange bell."""
    if PAUSED.is_set() and not force:
        log(f"Paused, not sending: {title}")
        return False
    if TRAY and not force:
        TRAY.alert()
    url = f"{cfg['ntfy_server'].rstrip('/')}/{topic or cfg['ntfy_topic']}"
    req = urllib.request.Request(
        url,
        data=message.encode("utf-8"),
        headers={"Title": title, "Priority": priority, "Tags": tags},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=10).read()
        log(f"Notified: {title} - {message}")
        return True
    except Exception as e:
        log(f"Failed to send notification: {e}")
        return False


# --------------------------------------------------------------------------- #
# Windows helpers
# --------------------------------------------------------------------------- #

def acquire_single_instance():
    """Return False if another copy of QPop is already running."""
    global _mutex
    _mutex = ctypes.windll.kernel32.CreateMutexW(None, False, r"Local\QPopSingleInstance")
    return ctypes.windll.kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS


def launch_command(*args):
    """Command line that starts QPop without a console window."""
    if FROZEN:
        return [sys.executable, *args]
    # Prefer the pythonw on PATH: Microsoft Store Python's real exe folder can't be launched directly.
    pythonw = shutil.which("pythonw") or os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return [pythonw, os.path.abspath(__file__), *args]


def _make_shortcut(lnk, args=""):
    if not os.path.exists(ICON_PATH):
        try:
            draw_logo(COLORS["normal"]).save(ICON_PATH, sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])
        except ImportError:
            pass
    ps = (
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:LNK);"
        "$s.TargetPath=$env:EXE;$s.Arguments=$env:ARGS;$s.WorkingDirectory=$env:DIR;"
        "$s.Description='QPop';if(Test-Path $env:ICO){$s.IconLocation=$env:ICO};$s.Save()"
    )
    exe, *rest = launch_command(*([args] if args else []))
    arguments = " ".join(f'"{a}"' if " " in a else a for a in rest)
    env = dict(os.environ, LNK=lnk, EXE=exe, ARGS=arguments, DIR=HERE,
               ICO=ICON_PATH if not FROZEN else sys.executable)
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], env=env, check=True,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def startup_enabled():
    return os.path.exists(STARTUP_LNK)


def set_startup(on):
    if on:
        _make_shortcut(STARTUP_LNK)
        log("Enabled start with Windows")
    elif os.path.exists(STARTUP_LNK):
        os.remove(STARTUP_LNK)
        log("Disabled start with Windows")


def install_startup():
    set_startup(True)
    _make_shortcut(START_MENU_LNK, "--show")
    print("Installed: QPop starts hidden when you log in,")
    print("and 'QPop' in the Start menu opens its window.")
    subprocess.Popen(launch_command("--show"), cwd=HERE)
    print("Started it now too.")


def uninstall_startup():
    for lnk in (STARTUP_LNK, START_MENU_LNK):
        if os.path.exists(lnk):
            os.remove(lnk)
    print("Removed from startup and the Start menu.")
    stop_background()


def migrate_old_shortcuts():
    """Swap shortcuts left by the pre-rename "Game Notify" for QPop ones."""
    old_startup, old_menu = OLD_SHORTCUTS
    try:
        if os.path.exists(old_startup):
            os.remove(old_startup)
            set_startup(True)
        if os.path.exists(old_menu):
            os.remove(old_menu)
            _make_shortcut(START_MENU_LNK, "--show")
    except Exception as e:
        log(f"Couldn't update old shortcuts: {e}")


def first_run_setup():
    """On a brand-new install, start with Windows and add a Start menu entry.
    Both can be undone from the window (Start with Windows) or with --uninstall."""
    try:
        set_startup(True)
        _make_shortcut(START_MENU_LNK, "--show")
    except Exception as e:
        log(f"Couldn't create shortcuts: {e}")


def signal_show_window():
    """Ask an already-running copy to open its window."""
    h = ctypes.windll.kernel32.OpenEventW(0x0002, False, SHOW_EVENT)  # EVENT_MODIFY_STATE
    if h:
        ctypes.windll.kernel32.SetEvent(h)
        ctypes.windll.kernel32.CloseHandle(h)


def stop_background():
    try:
        with open(PID_PATH) as f:
            pid = int(f.read().strip())
    except (OSError, ValueError):
        print("No background copy running.")
        return
    # A leftover PID file (e.g. after a crash) may point at a recycled PID - only kill QPop
    # itself (python/pythonw when run as a script, QPop.exe when packaged).
    name = process_name(pid).lower()
    if not (name.startswith("python") or name == os.path.basename(sys.executable).lower()):
        print("No background copy running.")
    else:
        r = subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, text=True)
        print("Stopped." if r.returncode == 0 else "No background copy running.")
    try:
        os.remove(PID_PATH)
    except OSError:
        pass


def keep_running(name, fn):
    """Run a watcher forever: if it crashes, log why and restart it instead of going silent."""
    while True:
        try:
            fn()
        except Exception as e:
            log(f"{name} watcher crashed ({type(e).__name__}: {e}); restarting in 5s")
            STATUS[name] = "restarting..."
            time.sleep(5)


# --------------------------------------------------------------------------- #
# Updates
# --------------------------------------------------------------------------- #

def parse_version(v):
    """'v1.2.3' -> (1, 2, 3); anything unparseable sorts lowest."""
    try:
        return tuple(int(x) for x in v.strip().lstrip("vV").split("-")[0].split("."))
    except ValueError:
        return ()


def check_for_update(cfg):
    """Ask GitHub for the latest release. Returns {"version", "url"} if it's newer than us."""
    if not UPDATE_REPO or not cfg.get("check_updates", True):
        return None
    req = urllib.request.Request(
        f"https://api.github.com/repos/{UPDATE_REPO}/releases/latest",
        headers={"Accept": "application/vnd.github+json", "User-Agent": f"QPop/{__version__}"},
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        release = json.loads(r.read())
    latest = release.get("tag_name", "")
    if parse_version(latest) > parse_version(__version__) and latest.lstrip("vV") != cfg.get("skipped_update"):
        return {"version": latest.lstrip("vV"), "url": release.get("html_url", "")}
    return None


def update_loop(cfg):
    """Check on startup and then once a day; tell the user once per new version."""
    announced = None
    while True:
        try:
            found = check_for_update(cfg)
            UPDATE.clear()
            if found:
                UPDATE.update(found)
                if found["version"] != announced:
                    announced = found["version"]
                    log(f"Update available: {found['version']}")
                    if TRAY:
                        TRAY.toast("QPop update available",
                                   f"Version {found['version']} is out. Right-click the tray bell to download it.")
        except Exception as e:
            log(f"Update check failed: {e}")
        time.sleep(24 * 3600)


# --------------------------------------------------------------------------- #
# League of Legends / TFT
# --------------------------------------------------------------------------- #

PHASE_LABELS = {
    "None": "in client", "Lobby": "in lobby", "Matchmaking": "in queue",
    "ReadyCheck": "MATCH FOUND", "ChampSelect": "champ select",
    "GameStart": "loading", "InProgress": "in game", "EndOfGame": "post game",
}


class LeagueWatcher:
    # The LCU uses a self-signed cert on localhost.
    _ssl = ssl._create_unverified_context()

    def __init__(self, cfg):
        self.cfg = cfg
        self.port = None
        self.auth = None
        self.last_phase = None

    def find_client(self):
        """Read port + auth token from the LeagueClientUx.exe command line."""
        if not process_running("LeagueClientUx.exe"):
            return False
        ps = (
            "Get-CimInstance Win32_Process -Filter \"Name='LeagueClientUx.exe'\" "
            "| Select-Object -ExpandProperty CommandLine"
        )
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps],
                capture_output=True, text=True, timeout=15,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            ).stdout
        except Exception:
            return False
        port = re.search(r"--app-port=(\d+)", out)
        token = re.search(r"--remoting-auth-token=([\w-]+)", out)
        if not (port and token):
            return False
        self.port = port.group(1)
        self.auth = base64.b64encode(f"riot:{token.group(1)}".encode()).decode()
        return True

    def get(self, path):
        req = urllib.request.Request(
            f"https://127.0.0.1:{self.port}{path}",
            headers={"Authorization": f"Basic {self.auth}", "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, context=self._ssl, timeout=5) as r:
            return json.loads(r.read() or "null")

    def game_name(self):
        try:
            session = self.get("/lol-gameflow/v1/session")
            mode = session["gameData"]["queue"]["gameMode"]
            return "TFT" if mode == "TFT" else "League"
        except Exception:
            return "League"

    def on_phase(self, phase):
        lc = self.cfg["league"]
        if phase == "ReadyCheck" and lc["notify_ready_check"]:
            notify(self.cfg, f"{self.game_name()}: Match found!", "Accept the queue pop now.")
        elif phase == "ChampSelect" and lc["notify_champ_select"]:
            notify(self.cfg, f"{self.game_name()}: Everyone accepted", "You're in champ select.", priority="high")
        elif phase == "GameStart" and lc["notify_game_start"]:
            notify(self.cfg, f"{self.game_name()}: Game starting", "Loading into the game.", priority="default")

    def run(self):
        while True:
            if not self.port:
                if self.find_client():
                    log(f"League client found (port {self.port})")
                    self.last_phase = None
                else:
                    STATUS["League"] = "client not running"
                    time.sleep(5)
                    continue
            try:
                phase = self.get("/lol-gameflow/v1/gameflow-phase")
            except Exception:
                # Client closed, or still starting up and not answering yet.
                log("League client not responding, retrying...")
                STATUS["League"] = "connecting..."
                self.port = None
                time.sleep(3)
                continue
            if phase != self.last_phase:
                log(f"League phase: {self.last_phase} -> {phase}")
                STATUS["League"] = PHASE_LABELS.get(phase, phase)
                self.on_phase(phase)
                self.last_phase = phase
            time.sleep(1)


# --------------------------------------------------------------------------- #
# Deadlock
# --------------------------------------------------------------------------- #

class DeadlockWatcher:
    def __init__(self, cfg):
        self.cfg = cfg
        dc = cfg["deadlock"]
        if dc["console_log"]:
            self.path = dc["console_log"]
        else:
            import steam_setup
            self.path = steam_setup.deadlock_console_log()
        self.patterns = [re.compile(p) for p in dc["match_patterns"]]
        self.cooldown = dc["cooldown_seconds"]
        self.last_fired = 0.0

    def handle(self, line):
        if DEBUG and re.search(r"GCClient|Matchmak|HostStateManager|Connected to", line):
            log(f"[deadlock] {line.rstrip()[:200]}")
        if any(p.search(line) for p in self.patterns):
            if time.time() - self.last_fired > self.cooldown:
                self.last_fired = time.time()
                notify(self.cfg, "Deadlock: Match found!", "Your match is loading.")

    def run(self):
        warned = False
        pos = None  # start at end of file so old sessions don't trigger
        ident = None
        while True:
            try:
                st = os.stat(self.path)
            except FileNotFoundError:
                if not warned:
                    log(f"Deadlock console.log not found at {self.path} (add -condebug to launch options)")
                    warned = True
                STATUS["Deadlock"] = "no console.log (add -condebug)"
                time.sleep(5)
                continue
            # Deadlock rewrites console.log on each launch - detect that.
            new_ident = (st.st_ctime, )
            if pos is None:
                pos = st.st_size
                ident = new_ident
                log("Watching Deadlock console.log")
                STATUS["Deadlock"] = "watching"
            elif st.st_size < pos or new_ident != ident:
                pos = 0
                ident = new_ident
                log("Deadlock log restarted (game launched)")
            if st.st_size > pos:
                with open(self.path, "r", encoding="utf-8", errors="replace") as f:
                    f.seek(pos)
                    chunk = f.read()
                    pos = f.tell()
                for line in chunk.splitlines():
                    self.handle(line)
            time.sleep(1)


# --------------------------------------------------------------------------- #
# Tray icon
# --------------------------------------------------------------------------- #

COLORS = {"normal": (91, 91, 247), "alert": (255, 140, 0), "paused": (120, 120, 120)}


def draw_logo(bg, size=64):
    """A white bell on a rounded square, drawn at 4x then scaled down for smooth edges."""
    from PIL import Image, ImageDraw
    S = 256
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, S - 1, S - 1], radius=56, fill=bg + (255,))
    w = (255, 255, 255, 255)
    d.ellipse([118, 34, 138, 54], fill=w)                     # top knob
    d.pieslice([66, 46, 190, 170], 180, 360, fill=w)          # dome
    d.rectangle([66, 107, 190, 172], fill=w)                  # body
    d.polygon([(66, 160), (190, 160), (214, 190), (42, 190)], fill=w)  # flared rim
    d.ellipse([106, 196, 150, 228], fill=w)                   # clapper
    return img.resize((size, size), Image.LANCZOS)


class Tray:
    def __init__(self, cfg, on_quit, on_open, on_relink):
        import pystray
        self.pystray = pystray
        self.cfg = cfg
        self.on_quit = on_quit
        self.on_open = on_open
        self.on_relink = on_relink
        self.alert_until = 0.0
        self.images = {k: draw_logo(c) for k, c in COLORS.items()}
        item = pystray.MenuItem
        self.icon = pystray.Icon(
            "QPop",
            self.images["normal"],
            "QPop",
            menu=pystray.Menu(
                item("Open QPop", lambda: self.on_open(), default=True),
                item(f"Version {__version__}", None, enabled=False),
                item(lambda _: f"Update available: v{UPDATE.get('version')} - download",
                     lambda: os.startfile(UPDATE["url"]), visible=lambda _: bool(UPDATE)),
                pystray.Menu.SEPARATOR,
                item(lambda _: f"League/TFT: {STATUS['League']}", None, enabled=False),
                item(lambda _: f"Deadlock: {STATUS['Deadlock']}", None, enabled=False),
                pystray.Menu.SEPARATOR,
                item("Pause notifications", self.toggle_pause, checked=lambda _: PAUSED.is_set()),
                item("Send test notification", self.test),
                item("Link a new phone...", lambda: self.on_relink()),
                item("Open log", lambda: os.startfile(os.path.join(visible_data_dir(), "qpop.log"))),
                item("Open settings folder", lambda: os.startfile(visible_data_dir())),
                pystray.Menu.SEPARATOR,
                item("Quit", self.quit),
            ),
        )

    def start(self):
        self.icon.run_detached()
        threading.Thread(target=self._refresh, daemon=True).start()

    def toast(self, title, message):
        try:
            self.icon.notify(message, title)
        except Exception:
            pass

    def _refresh(self):
        """Keep the icon colour and hover text in sync with the current state."""
        while True:
            if PAUSED.is_set():
                state = "paused"
            elif time.time() < self.alert_until:
                state = "alert"
            else:
                state = "normal"
            self.icon.icon = self.images[state]
            self.icon.title = (
                f"QPop{' (paused)' if state == 'paused' else ''}\n"
                f"League/TFT: {STATUS['League']}\nDeadlock: {STATUS['Deadlock']}"
            )[:127]
            self.icon.update_menu()
            time.sleep(1)

    def alert(self):
        self.alert_until = time.time() + 60

    def toggle_pause(self):
        if PAUSED.is_set():
            PAUSED.clear()
            log("Notifications resumed")
        else:
            PAUSED.set()
            log("Notifications paused")

    def test(self):
        threading.Thread(
            target=notify, args=(self.cfg, "QPop test", "If you can see this, you're all set!"),
            kwargs={"force": True}, daemon=True,
        ).start()

    def stop(self):
        try:
            self.icon.stop()
        except Exception:
            pass

    def quit(self):
        self.on_quit()


# --------------------------------------------------------------------------- #

def main():
    if "--install" in sys.argv:
        return install_startup()
    if "--uninstall" in sys.argv:
        return uninstall_startup()
    if "--stop" in sys.argv:
        return stop_background()

    if "--test" in sys.argv:
        notify(load_config(), "QPop test", "If you can see this, you're all set!")
        return

    # Check for a running copy before touching the log, so a second launch can't wipe its log.
    acquired = acquire_single_instance()
    if not acquired and "--replace" in sys.argv:
        # Used by the installer: take over from an older copy (e.g. a portable exe) still running.
        ctypes.windll.kernel32.CloseHandle(_mutex)
        stop_background()
        for _ in range(20):
            if acquire_single_instance():
                acquired = True
                break
            ctypes.windll.kernel32.CloseHandle(_mutex)
            time.sleep(0.5)
    if not acquired:
        log("QPop is already running - opening its window.")
        signal_show_window()
        return

    # Under pythonw / the windowed exe there is no console, so send output to a log file instead.
    os.makedirs(DATA_DIR, exist_ok=True)
    if sys.stdout is None:
        sys.stdout = sys.stderr = open(LOG_PATH, "w", encoding="utf-8", buffering=1)

    cfg = load_config()
    topic_url = f"{cfg['ntfy_server'].rstrip('/')}/{cfg['ntfy_topic']}"

    with open(PID_PATH, "w") as f:
        f.write(str(os.getpid()))

    print("=" * 60)
    print(f" QPop {__version__}")
    print(f" ntfy topic: {cfg['ntfy_topic']}")
    print(f" Subscribe in the ntfy phone app, or open: {topic_url}")
    print("=" * 60)

    threads = [threading.Thread(target=update_loop, args=(cfg,), daemon=True)] if UPDATE_REPO else []
    if cfg["league"]["enabled"]:
        threads.append(threading.Thread(target=keep_running, args=("League", LeagueWatcher(cfg).run), daemon=True))
    if cfg["deadlock"]["enabled"]:
        threads.append(threading.Thread(target=keep_running, args=("Deadlock", DeadlockWatcher(cfg).run), daemon=True))
    for t in threads:
        t.start()
    # The tk UI owns the main thread; other threads talk to it through this queue.
    commands = queue.Queue()
    root = None
    window = None
    try:
        import tkinter as tk
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # crisp text on high-DPI screens
        except Exception:
            pass
        # Own taskbar identity, so the window shows our logo rather than Python's.
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("QPop")
        root = tk.Tk()
        root.withdraw()
    except Exception as e:
        log(f"Window disabled ({e})")

    global TRAY
    if "--no-tray" not in sys.argv:
        try:
            TRAY = Tray(cfg, on_quit=lambda: commands.put("quit"), on_open=lambda: commands.put("show"),
                        on_relink=lambda: commands.put("relink"))
            TRAY.start()
        except ImportError:
            log("Tray icon disabled (run: python -m pip install pystray pillow)")

    show_event = ctypes.windll.kernel32.CreateEventW(None, False, False, SHOW_EVENT)
    signal.signal(signal.SIGINT, lambda *_: commands.put("quit"))

    migrate_old_shortcuts()
    if not cfg.get("setup_shown") and not INSTALLED:
        first_run_setup()
    if "--show" in sys.argv or not cfg.get("setup_shown"):
        commands.put("show")
        cfg["setup_shown"] = True
        save_config(cfg)

    log("Watching for queue pops... (Ctrl+C or tray > Quit to stop)")

    def pump():
        nonlocal window
        if ctypes.windll.kernel32.WaitForSingleObject(show_event, 0) == 0:
            commands.put("show")
        while not commands.empty():
            cmd = commands.get()
            if cmd in ("show", "relink") and root is not None:
                try:
                    if window is None:
                        import gui
                        window = gui.Window(root, sys.modules[__name__], cfg)
                    window.show()
                    if cmd == "relink":
                        window.start_relink()
                except Exception as e:
                    log(f"Couldn't open window: {e}")
            elif cmd == "quit":
                return False
        return True

    if root is not None:
        def loop():
            if pump():
                root.after(200, loop)
            else:
                root.destroy()
        loop()
        root.mainloop()
    else:
        while pump():
            time.sleep(0.2)

    if TRAY:
        TRAY.stop()
    log("Stopped.")
    try:
        os.remove(PID_PATH)
    except OSError:
        pass


if __name__ == "__main__":
    main()
