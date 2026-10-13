# Developing QPop

## Layout

| File | What it does |
|---|---|
| `qpop.py` | Entry point. Config, notifications (ntfy), League + Deadlock watchers, tray icon, startup shortcuts, main loop. |
| `gui.py` | The setup/status window (tkinter): QR codes, Deadlock fix, options, re-link dialog. |
| `steam_setup.py` | Reads/writes Steam's `localconfig.vdf` (launch options) and finds Steam library folders. |
| `winutil.py` | Process helpers shared by the above (no subprocesses). |
| `build.bat` | Builds the installer `dist\QPop-Setup-<version>.exe` (PyInstaller + Inno Setup). |
| `packaging/build_assets.py` | Generates the icon, exe file properties and version string from `qpop.py`. |
| `packaging/QPop.iss` | Inno Setup script: per-user install, Start menu, autostart task, uninstaller. |
| `install.bat` / `uninstall.bat` / `start.bat` | Dev helpers for running from source with Python. |

## Run from source

```bat
python -m pip install --user -r requirements.txt
python qpop.py            :: tray + window (first run only)
python qpop.py --show     :: open the window
python qpop.py --debug    :: also log raw Deadlock matchmaking lines
python qpop.py --stop     :: stop the background copy
```

Only one copy runs at a time; launching again just opens the running copy's window.

## Build the installer

Needs [Inno Setup 6](https://jrsoftware.org/isinfo.php) (free): `winget install JRSoftware.InnoSetup`.

```bat
build.bat
```

Produces `dist\QPop-Setup-<version>.exe` (~14 MB). It installs per-user to
`%LOCALAPPDATA%\Programs\QPop` (no admin prompt), adds a Start menu entry, optionally starts with
Windows, and registers an uninstaller in Settings → Apps. Running a newer installer over an old one
stops QPop, upgrades it in place and keeps the user's settings. The app itself is built "one folder"
(`dist\QPop\`), which starts faster and trips antivirus less than a single-file exe.

When installed this way the app leaves shortcuts to the installer (it detects `unins000.exe` next to
itself). Run from source or as a bare exe, it creates them itself on first run.

## Releasing a new version

1. Bump `__version__` in `qpop.py` (the installer, exe properties and update check all read it).
2. Run `build.bat`.
3. Commit, then tag: `git tag v<version>`.
4. On GitHub, create a release for the tag and attach `dist\QPop-Setup-<version>.exe`.

### Update checks

Set `UPDATE_REPO = "owner/name"` in `qpop.py` once the GitHub repo exists. QPop then checks
`api.github.com/repos/<repo>/releases/latest` on startup and daily. If the release tag (e.g. `v0.2.0`)
is newer, it shows a Windows notification once, plus "Update available" in the tray menu and the window
footer, linking to the release page. Users can turn checks off with `"check_updates": false` in their
config. With `UPDATE_REPO` empty, no network request is made.

## Where things are stored

Per-user data lives in `%APPDATA%\QPop\`: `config.json` (includes the user's private ntfy
topic), `qpop.log`, `qpop.pid`, `icon.ico`. Nothing personal is ever written next to the
program or bundled into the exe. Versions before 0.1.0 kept `config.json` next to the script; it's copied
over automatically on first run.

**Microsoft Store Python gotcha:** Store Python silently redirects AppData writes to
`%LOCALAPPDATA%\Packages\PythonSoftwareFoundation.Python.*\LocalCache\Roaming\QPop`.
The tray's "Open settings folder" handles this; the packaged exe isn't affected.

## How detection works

- **League/TFT:** reads port + auth token from `LeagueClientUx.exe`'s command line, polls
  `/lol-gameflow/v1/gameflow-phase` every second, alerts on `ReadyCheck`. This uses Riot's unofficial
  local client API. Check Riot's developer policies before distributing widely.
- **Deadlock:** tails `game\citadel\console.log` (needs `-condebug`) and alerts when a map other than
  `dl_hideout` loads. Patterns live in `config.json` → `deadlock.match_patterns`; run with `--debug` to
  find new ones if Valve changes the log.
- Each watcher runs in a thread wrapped by `keep_running()`, which logs and restarts it if it crashes.

## Steam config safety

`steam_setup.py` only writes `localconfig.vdf` if it can parse and re-save the file byte-for-byte
identically first, writes a `.qpop.bak` backup, and requires Steam to be closed (the window
closes and reopens it).

## Phase 1 checklist (shipping to more people)

- [x] Single-file exe build (`build.bat`), version number, `requirements.txt`, `.gitignore`
- [x] Per-user data in `%APPDATA%`, no personal data in the build
- [x] First run: autostart + Start menu entry, setup window
- [x] Deadlock found in any Steam library
- [x] Real installer (Inno Setup): per-user install, Start menu, autostart task, uninstaller, in-place upgrades
- [x] Update check against GitHub Releases (turn on by setting `UPDATE_REPO`)
- [x] Source in git, releases tagged
- [x] GitHub repo (KW-Project/QPop), `UPDATE_REPO` set, v0.1.0 released
- [ ] Code signing (removes the SmartScreen warning) - skipped for now; Azure Trusted Signing is cheapest
