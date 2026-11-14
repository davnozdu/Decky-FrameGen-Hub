"""Read non-Steam Proton games without changing Steam shortcuts or launch options."""
import json
import re
import shlex
from pathlib import Path
import nsl_vdf


def wine_path(value, prefix):
    value = str(value).replace("\\", "/")
    if value.lower().startswith("z:/"):
        return Path(value[2:])
    if re.match(r"^[a-zA-Z]:/", value):
        return prefix / "pfx/dosdevices" / (value[0].lower() + ":") / value[3:]
    return Path(value)


def launcher_installs(prefix):
    """Names and actual install folders for launcher-mediated game shortcuts."""
    installs = {}
    drive = prefix / "pfx/drive_c"
    for manifest in drive.glob("ProgramData/Epic/EpicGamesLauncher/Data/Manifests/*.item"):
        try:
            data = json.loads(manifest.read_text())
            installs[data["DisplayName"].casefold()] = wine_path(data["InstallLocation"], prefix)
        except (OSError, ValueError, KeyError):
            continue
    for config in drive.glob("users/*/AppData/Roaming/Battle.net/Battle.net.config"):
        try:
            data = json.loads(config.read_text())
            # Product paths are stored under different keys by client versions.
            for code, item in data.get("Games", {}).items():
                for key in ("InstallPath", "InstallDir", "Path", "Resumable"):
                    value = item.get(key)
                    if isinstance(value, str) and re.match(r"^[a-zA-Z]:[/\\]", value):
                        installs[code.casefold()] = wine_path(value, prefix)
        except (OSError, ValueError, AttributeError):
            continue
    return installs


def external_games(libraries, appid=None):
    games = {}
    cache = {}
    for library in libraries:
        for file in (Path(library) / "userdata").glob("*/config/shortcuts.vdf"):
            try:
                entries = nsl_vdf.binary_loads(file.read_bytes()).get("shortcuts", {}).values()
            except (OSError, ValueError, SyntaxError):
                continue
            for shortcut in entries:
                try:
                    sid = str(int(shortcut.get("appid", 0)) & 0xffffffff)
                    if sid == "0" or (appid is not None and sid != str(appid)):
                        continue
                    name = shortcut.get("appname") or shortcut.get("AppName") or ""
                    options = shortcut.get("LaunchOptions", "")
                    tokens = shlex.split(shortcut.get("exe") or shortcut.get("Exe") or "")
                    match = re.search(r"(?:STEAM_COMPAT_DATA_PATH|WINEPREFIX)=(?:\"([^\"]+)\"|'([^']+)'|([^ ;]+))", options)
                    prefix = Path(next(v for v in match.groups() if v)) if match else Path(library) / "steamapps/compatdata" / sid
                    root = None
                    for token in tokens:
                        if token.lower().endswith(".exe"):
                            target = wine_path(token, prefix)
                            if target.is_file():
                                root = target.parent
                    # A launcher exe is not the game's install directory.
                    launcher_target = any(word in " ".join(tokens).lower() for word in
                                          ("battle.net", "epicgameslauncher", "galaxyclient", "upc.exe", "eadesktop"))
                    if prefix not in cache:
                        cache[prefix] = launcher_installs(prefix)
                    mapped = cache[prefix].get(name.casefold())
                    code = re.search(r"launch ([A-Za-z0-9]+)", options)
                    if not mapped and code:
                        mapped = cache[prefix].get(code.group(1).casefold())
                    if mapped:
                        root = mapped
                    elif launcher_target:
                        continue
                    if not root or not root.is_dir() or not name:
                        continue
                    games[sid] = {"appid": sid, "name": name, "install_path": str(root.resolve()),
                                  "prefix_path": str(prefix), "non_steam": True}
                except (OSError, ValueError, TypeError):
                    continue
    return list(games.values())
