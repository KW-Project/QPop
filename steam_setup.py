"""
Add a launch option (e.g. -condebug) to a Steam game, the same as typing it into
Steam > game > Properties > Launch Options.

Launch options live in Steam/userdata/<account>/config/localconfig.vdf. Steam rewrites
that file when it exits, so Steam must be closed while we edit it.

Safety: the file is only written if our parser can re-save it byte-for-byte identical
before the change, and a backup is kept next to it.
"""

import glob
import os
import re
import shutil
import subprocess
import time

from winutil import process_running

DEADLOCK_APP_ID = "1422450"
DEFAULT_STEAM = r"C:\Program Files (x86)\Steam"


# --------------------------------------------------------------------------- #
# Minimal VDF (Valve KeyValues text) parser that round-trips exactly
# --------------------------------------------------------------------------- #
# Strings are kept in their raw escaped form so re-serialising is lossless.

_TOKEN = re.compile(r'"((?:[^"\\]|\\.)*)"|([{}])|(\s+)|(//[^\n]*)', re.S)


class VDFError(Exception):
    pass


def parse(text):
    """Return a list of (key, value) where value is a str or a nested list."""
    tokens = []
    pos = 0
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m:
            raise VDFError(f"unexpected character at {pos}")
        pos = m.end()
        if m.group(1) is not None:
            tokens.append(("str", m.group(1)))
        elif m.group(2):
            tokens.append((m.group(2), None))

    def block(i, top):
        items = []
        while i < len(tokens):
            kind, val = tokens[i]
            if kind == "}":
                if top:
                    raise VDFError("unbalanced }")
                return items, i + 1
            if kind != "str":
                raise VDFError("expected key")
            if i + 1 >= len(tokens):
                raise VDFError("key without value")
            nkind, nval = tokens[i + 1]
            if nkind == "str":
                items.append((val, nval))
                i += 2
            elif nkind == "{":
                child, i = block(i + 2, False)
                items.append((val, child))
            else:
                raise VDFError("unexpected }")
        if not top:
            raise VDFError("missing }")
        return items, i

    items, _ = block(0, True)
    return items


def dump(items, depth=0):
    """Serialise in Steam's own layout (tabs, two tabs between key and value)."""
    out = []
    ind = "\t" * depth
    for key, val in items:
        if isinstance(val, list):
            out.append(f'{ind}"{key}"\n{ind}{{\n')
            out.append(dump(val, depth + 1))
            out.append(f"{ind}}}\n")
        else:
            out.append(f'{ind}"{key}"\t\t"{val}"\n')
    return "".join(out)


def find(items, key):
    for k, v in items:
        if k.lower() == key.lower():
            return v
    return None


def get_or_create(items, key):
    v = find(items, key)
    if v is None:
        v = []
        items.append((key, v))
    return v


def set_value(items, key, value):
    for idx, (k, _) in enumerate(items):
        if k.lower() == key.lower():
            items[idx] = (k, value)
            return
    items.append((key, value))


# --------------------------------------------------------------------------- #
# Steam helpers
# --------------------------------------------------------------------------- #

def steam_dir():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
            return os.path.normpath(winreg.QueryValueEx(k, "SteamPath")[0])
    except OSError:
        return DEFAULT_STEAM


def _unescape(s):
    return s.replace("\\\\", "\\")


def library_folders():
    """Every Steam library folder (games can live on several drives)."""
    folders = [steam_dir()]
    path = os.path.join(steam_dir(), "steamapps", "libraryfolders.vdf")
    try:
        with open(path, encoding="utf-8", newline="") as f:
            items = parse(f.read())
        for _, lib in find(items, "libraryfolders") or []:
            p = find(lib, "path") if isinstance(lib, list) else None
            if p:
                folders.append(os.path.normpath(_unescape(p)))
    except (OSError, VDFError):
        pass
    return list(dict.fromkeys(os.path.normcase(f) for f in folders))


def deadlock_console_log():
    """Where Deadlock writes console.log (with -condebug), in whichever library it's installed."""
    rel = os.path.join("steamapps", "common", "Deadlock", "game", "citadel", "console.log")
    for lib in library_folders():
        if os.path.isdir(os.path.join(lib, "steamapps", "common", "Deadlock")):
            return os.path.join(lib, rel)
    return os.path.join(steam_dir(), rel)


def localconfigs():
    return glob.glob(os.path.join(steam_dir(), "userdata", "*", "config", "localconfig.vdf"))


def _app_section(items, app_id, create=False):
    """UserLocalConfigStore > Software > Valve > Steam > apps > <app_id>"""
    node = items
    for key in ("UserLocalConfigStore", "Software", "Valve", "Steam", "apps", app_id):
        nxt = get_or_create(node, key) if create else find(node, key)
        if not isinstance(nxt, list):
            return None
        node = nxt
    return node


def _load(path):
    with open(path, encoding="utf-8", newline="") as f:
        text = f.read()
    items = parse(text)
    if dump(items) != text:
        raise VDFError(f"{path} isn't in the expected format; not touching it")
    return items


def get_launch_options(app_id=DEADLOCK_APP_ID):
    """{account_folder: launch options string or None if the game isn't in that account}"""
    result = {}
    for path in localconfigs():
        account = os.path.basename(os.path.dirname(os.path.dirname(path)))
        try:
            app = _app_section(_load(path), app_id)
        except (OSError, VDFError):
            continue
        if app is not None:
            opts = find(app, "LaunchOptions")
            result[account] = opts if isinstance(opts, str) else ""
    return result


def current_account():
    """The account Steam wrote config for most recently = the one you play on."""
    paths = localconfigs()
    if not paths:
        return None
    newest = max(paths, key=os.path.getmtime)
    return os.path.basename(os.path.dirname(os.path.dirname(newest)))


def has_option(option, app_id=DEADLOCK_APP_ID):
    """True/False for the current account, or None if the game isn't found."""
    opts = get_launch_options(app_id)
    acct = current_account()
    if acct not in opts:
        return None
    return option in opts[acct].split()


def add_launch_option(option, app_id=DEADLOCK_APP_ID):
    """Add the option to every account that has the game. Steam must be closed."""
    changed = 0
    for path in localconfigs():
        items = _load(path)
        app = _app_section(items, app_id)
        if app is None:
            continue
        current = find(app, "LaunchOptions")
        current = current if isinstance(current, str) else ""
        if option in current.split():
            continue
        set_value(app, "LaunchOptions", f"{current} {option}".strip())
        shutil.copy2(path, path + ".qpop.bak")
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            f.write(dump(items))
        os.replace(tmp, path)
        changed += 1
    return changed


def steam_exe():
    return os.path.join(steam_dir(), "steam.exe")


def shutdown_steam(timeout=40):
    """Ask Steam to exit cleanly and wait for it. Returns True once it's closed."""
    if not process_running("steam.exe"):
        return True
    subprocess.Popen([steam_exe(), "-shutdown"])
    end = time.time() + timeout
    while time.time() < end:
        if not process_running("steam.exe"):
            time.sleep(1)  # let it finish writing its files
            return True
        time.sleep(0.5)
    return False


def start_steam():
    subprocess.Popen([steam_exe()], cwd=steam_dir())
