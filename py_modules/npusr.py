"""NPU super-resolution per game: the npu-sr Vulkan layer + the Ryzen AI service (user systemd unit).

The layer (~/AsusNPU/npu-sr) is an implicit Vulkan layer that is inert unless the game's Steam AppId is
listed in ~/.config/npu-sr/enabled-apps. It takes the game's 1280x720 swapchain, sends luma to the NPU
service and presents 1920x1080. The list is read when the game creates its Vulkan device, so changes
apply on the next game start. This mixin only manages that list and the service; it never touches
game files except an existing OptiScaler.ini (in-game V-Sync off, no OptiScaler FPS cap), so it combines with
OptiScaler/FSR 4 (render below 720p, FSR to 720p, NPU to 1080p).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import subprocess
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import decky

NPUSR_UNIT = "npu-sr.service"
# RADV's RDR2 profile turns on the APU unified heap, which hides the CPU-cached memory types the layer needs for
# fast staging copies (~2.6 ms -> 0.1 ms per frame). Harmless for games without that profile.
# NPU_SR_ENABLE=1 loads the Vulkan layer into this game only: its manifest has enable_environment, so KWin, mpv,
# Steam and other programs never get it (a global layer crashed KWin's device enumeration).
NPUSR_LAUNCH_ENV = "NPU_SR_ENABLE=1 radv_enable_unified_heap_on_apu=false"
_NPUSR_ENV_RE = re.compile(r"(?<!\S)(?:radv_enable_unified_heap_on_apu|NPU_SR_ENABLE)=\S+\s*")
NPUSR_MANIFESTS = (
    Path("/usr/share/vulkan/implicit_layer.d/VkLayer_zz_npu_sr.json"),
    Path("/etc/vulkan/implicit_layer.d/VkLayer_zz_npu_sr.json"),
)


# Private NPU package (ZIP the user prepares; it is never downloaded): manifest.json + these files.
NPUSR_PACKAGE_FILES = ("libVkLayer_npu_sr.so", "npu-sr-service", "run-service.sh", "runtime.sh", "npu-sr.service",
                       "VkLayer_zz_npu_sr.json", "install-layer.sh")
NPUSR_EXECUTABLES = {"npu-sr-service", "run-service.sh", "runtime.sh", "install-layer.sh"}
_NPUSR_MEMBER_RE = re.compile(r"^(?:models/)?[A-Za-z0-9][A-Za-z0-9._-]*$")
NPUSR_PACKAGE_MAX = 64 * 1024 * 1024
# Optional download of the owner's own package from a PRIVATE GitHub repo: only when the user created
# ~/.config/npu-sr/package-repo ("owner/repo") and ~/.config/npu-sr/github-token (a read-only token).
# Nothing is configured by the plugin itself, so for everyone else the package stays a manual ZIP import.
NPUSR_ASSET_RE = re.compile(r"^npu-sr-package-([0-9A-Za-z._-]+)\.zip$")
_NPUSR_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
NPUSR_USER_AGENT = "decky-framegen-hub-npu"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        return None


def _version_key(version: str) -> tuple:
    return tuple(int(p) if p.isdigit() else p for p in re.split(r"[.-]", version or ""))


# AMD Ryzen AI 1.9 runtime + XRT are not redistributable: the user installs them under ~/AsusNPU.
NPUSR_RUNTIME_DIRS = ("runtime-1.9", "xrt-1.9", "sesr-env", "ubuntu-compat")


def read_npusr_package(path: Path) -> tuple[dict, dict[str, bytes]]:
    if path.stat().st_size > NPUSR_PACKAGE_MAX:
        raise ValueError("The NPU package is too large (over 64 MB).")
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if not n.endswith("/")]
        if "manifest.json" not in names:
            raise ValueError("Not an NPU package: manifest.json is missing.")
        manifest = json.loads(z.read("manifest.json"))
        files = manifest.get("files")
        if manifest.get("name") != "npu-sr" or not isinstance(files, dict):
            raise ValueError("Not an NPU package: wrong manifest.")
        payload: dict[str, bytes] = {}
        for name, rec in files.items():
            if not _NPUSR_MEMBER_RE.match(name) or name not in names:
                raise ValueError(f"Bad or missing file in the NPU package: {name}")
            data = z.read(name)
            if hashlib.sha256(data).hexdigest() != rec.get("sha256"):
                raise ValueError(f"Checksum mismatch in the NPU package: {name}")
            payload[name] = data
        extra = set(names) - set(files) - {"manifest.json"}
        if extra:
            raise ValueError("Unlisted files in the NPU package: " + ", ".join(sorted(extra)[:5]))
    missing = [n for n in NPUSR_PACKAGE_FILES if n not in payload]
    if missing:
        raise ValueError("The NPU package lacks: " + ", ".join(missing))
    if not any(n.startswith("models/") and n.endswith(".onnx") for n in payload):
        raise ValueError("The NPU package has no models.")
    return manifest, payload


class NpuSrMixin:
    # ── Paths ─────────────────────────────────────────────────────────────────

    def _npusr_dir(self) -> Path:
        return self._home() / "AsusNPU" / "npu-sr"

    def _npusr_apps_file(self) -> Path:
        base = os.environ.get("XDG_CONFIG_HOME") or str(self._home() / ".config")
        return Path(base) / "npu-sr" / "enabled-apps"

    def _npusr_stats_file(self) -> Path:
        return self._home() / ".cache" / "npu-sr" / "stats.json"

    def _npusr_unit_file(self) -> Path:
        return self._home() / ".config" / "systemd" / "user" / NPUSR_UNIT

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _npusr_systemctl(self, *args: str) -> tuple[int, str]:
        uid = os.getuid()
        env = dict(os.environ)
        env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{uid}")
        env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path=/run/user/{uid}/bus")
        try:
            proc = subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True, timeout=20, env=env)
            return proc.returncode, (proc.stdout + proc.stderr).strip()
        except (OSError, subprocess.SubprocessError) as exc:
            return 1, str(exc)

    def _npusr_apps(self) -> list[str]:
        try:
            lines = self._npusr_apps_file().read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        apps = []
        for line in lines:
            value = line.split("#", 1)[0].strip()
            if value and value not in apps:
                apps.append(value)
        return apps

    def _npusr_write_apps(self, apps: list[str]) -> None:
        path = self._npusr_apps_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text("".join(f"{a}\n" for a in apps), encoding="utf-8")
        os.replace(tmp, path)

    def _npusr_env_conf(self) -> Path:
        return self._home() / ".config" / "environment.d" / "npu-sr.conf"

    @staticmethod
    def _npusr_is_x2(name: str) -> bool:
        """x2 models (1024x576 input, 16 sub-pixels) are named *x2_*; everything else is x1.5 (1280x720)."""
        return "x2_" in name or "x2g" in name

    def _npusr_models(self, x2: bool = False) -> list[dict]:
        """Selectable models: *.onnx in the models folder (sub-folders such as archive/ are ignored).
        Optional models/catalog.json: {"file.onnx": {"label": "...", "note": "..."}} gives friendly names."""
        folder = self._npusr_dir() / "models"
        try:
            catalog = json.loads((folder / "catalog.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            catalog = {}
        models = []
        for path in sorted(folder.glob("*.onnx")):
            if self._npusr_is_x2(path.name) != x2:
                continue
            if "300x512" in path.name or "270x480" in path.name:  # 1024x600 / 960x540 twins loaded automatically
                continue
            info = catalog.get(path.name, {}) if isinstance(catalog, dict) else {}
            if info.get("hidden"):
                continue
            models.append({"file": path.name, "label": info.get("label") or path.stem, "note": info.get("note", ""),
                           "order": info.get("order", 100)})
        models.sort(key=lambda m: (m["order"], m["label"]))
        return models

    def _npusr_launch(self, current: str, enabled: bool) -> str:
        cur = _NPUSR_ENV_RE.sub("", (current or "").strip()).strip()
        if enabled:
            # Leading env assignment: it then reaches the game through any wrapper before %command%
            # (e.g. `bash grip-deck-launch %command%`), instead of becoming the wrapper's argument.
            cur = f"{NPUSR_LAUNCH_ENV} {cur}" if "%command%" in cur else f"{NPUSR_LAUNCH_ENV} %command% {cur}".strip()
        return "" if cur == "%command%" else cur

    def _npusr_model(self, var: str = "NPU_SR_MODEL") -> str | None:
        conf = self._npusr_env_conf()
        try:
            for line in conf.read_text(encoding="utf-8").splitlines():
                if line.startswith(var + "="):
                    return Path(line.split("=", 1)[1].strip()).name
        except OSError:
            pass
        return None

    def _npusr_live(self) -> dict | None:
        """Stats of a running game that uses the layer (None when no such process is alive)."""
        try:
            stats = json.loads(self._npusr_stats_file().read_text(encoding="utf-8"))
            pid = int(stats.get("pid", 0))
        except (OSError, ValueError, TypeError):
            return None
        if pid <= 0:
            return None
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return None
        except PermissionError:
            pass  # alive, owned by another user
        except OSError:
            return None
        keys = ("in", "out", "frames", "npu_frames", "fallback_frames", "npu_ms", "connected")
        return {k: stats.get(k) for k in keys}

    def _npusr_status(self, appid: str) -> dict:
        missing = []
        if not (self._npusr_dir() / "libVkLayer_npu_sr.so").is_file():
            missing.append("Vulkan layer")
        if not any(p.is_file() for p in NPUSR_MANIFESTS):
            missing.append("layer manifest")
        if not self._npusr_unit_file().is_file():
            missing.append("NPU service")
        rc, out = self._npusr_systemctl("is-active", NPUSR_UNIT)
        return {
            "status": "success",
            "available": not missing,
            "missing": missing,
            "enabled": str(appid) in self._npusr_apps(),
            "service": out.splitlines()[-1] if out else ("active" if rc == 0 else "unknown"),
            "model": self._npusr_model(),
            "models": self._npusr_models(),
            "model_x2": self._npusr_model("NPU_SR_MODEL_X2"),
            "sharpness": self._npusr_sharpness(),
            "aa": self._npusr_aa(),
            "models_x2": self._npusr_models(x2=True),
            "live": self._npusr_live(),
            "capture": self._npusr_capture_state(),
        }

    # ── Training-frame capture (native game frames for retraining the NPU models) ──────────────────────────────

    def _npusr_capture_script(self) -> Path:
        return self._home() / "AsusNPU" / "capture.sh"

    def _npusr_capture_state(self) -> dict:
        frames = list((self._home() / "AsusNPU" / "train-frames").glob("*/*.png"))
        rc, out = self._npusr_systemctl("is-active", "npu-capture.service")
        return {"available": self._npusr_capture_script().is_file(), "active": rc == 0, "frames": len(frames)}

    async def set_npu_capture(self, enabled: bool) -> dict:
        return await asyncio.to_thread(self._npusr_set_capture, bool(enabled))

    def _npusr_set_capture(self, enabled: bool) -> dict:
        if enabled and not self._npusr_capture_script().is_file():
            return {"status": "error", "message": "The frame capture script is not installed on this device."}
        self._npusr_systemctl("stop", "npu-capture.service")
        self._npusr_systemctl("reset-failed", "npu-capture.service")
        if enabled:
            script = self._npusr_capture_script()
            log = script.parent / "capture.log"
            rc, out = self._npusr_systemctl_run("npu-capture", ["bash", "-c", f"exec bash '{script}' 21600 4 >> '{log}' 2>&1"])
            if rc != 0:
                decky.logger.error(f"[NPU-SR] capture start: {out}")
                return {"status": "error", "message": "Frame capture did not start. See the plugin log."}
            return {"status": "success", "message": "Frame capture on: native frames are saved every few seconds."}
        return {"status": "success", "message": "Frame capture off."}

    def _npusr_systemctl_run(self, unit: str, cmd: list[str]) -> tuple[int, str]:
        uid = os.getuid()
        env = dict(os.environ)
        env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{uid}")
        env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path=/run/user/{uid}/bus")
        try:
            proc = subprocess.run(["systemd-run", "--user", f"--unit={unit}", "--collect", *cmd],
                                  capture_output=True, text=True, timeout=20, env=env)
            return proc.returncode, (proc.stdout + proc.stderr).strip()
        except (OSError, subprocess.SubprocessError) as exc:
            return 1, str(exc)

    # ── Private package import + device check ─────────────────────────────────

    def _npusr_package_state(self) -> dict:
        root = self._home() / "AsusNPU"
        info = {}
        try:
            info = json.loads((self._npusr_dir() / "package.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        installed = all((self._npusr_dir() / n).is_file() for n in ("libVkLayer_npu_sr.so", "npu-sr-service"))
        runtime_missing = [d for d in NPUSR_RUNTIME_DIRS if not (root / d).is_dir()]
        layer_registered = any(p.is_file() for p in NPUSR_MANIFESTS)
        npu_device = any(Path("/dev/accel").glob("accel*")) if Path("/dev/accel").is_dir() else False
        rc, out = self._npusr_systemctl("is-active", NPUSR_UNIT)
        return {
            "status": "success",
            "installed": installed,
            "version": info.get("version") or ("local build" if installed else None),
            "models": len(self._npusr_models()),
            "runtime_ok": not runtime_missing,
            "runtime_missing": [str(root / d) for d in runtime_missing],
            "layer_registered": layer_registered,
            "layer_command": f"sudo bash {self._npusr_dir() / 'install-layer.sh'}",
            "npu_device": npu_device,
            "service": out.splitlines()[-1] if out else ("active" if rc == 0 else "unknown"),
            "home": str(self._home()),
        }

    def _npusr_import_package(self, archive: str) -> dict:
        manifest, payload = read_npusr_package(Path(archive).expanduser())
        dest = self._npusr_dir()
        (dest / "models").mkdir(parents=True, exist_ok=True)
        # The layer manifest points at the library by absolute path: rewrite it for this user's home.
        layer = json.loads(payload["VkLayer_zz_npu_sr.json"])
        layer["layer"]["library_path"] = str(dest / "libVkLayer_npu_sr.so")
        payload["VkLayer_zz_npu_sr.json"] = (json.dumps(layer, indent=2) + "\n").encode()
        with tempfile.TemporaryDirectory(prefix=".import-", dir=dest) as temp:
            stage = Path(temp)
            for name, data in payload.items():
                tmp = stage / name.replace("/", "__")
                tmp.write_bytes(data)
                tmp.chmod(0o755 if name in NPUSR_EXECUTABLES else 0o644)
            for name in payload:  # atomic per file: a running game keeps its mapped library
                os.replace(stage / name.replace("/", "__"), dest / name)
        (dest / "package.json").write_text(json.dumps({"version": manifest.get("version"), "files": sorted(payload)},
                                                      indent=2), encoding="utf-8")
        unit = self._npusr_unit_file()
        unit.parent.mkdir(parents=True, exist_ok=True)
        unit.write_bytes(payload["npu-sr.service"])
        self._npusr_systemctl("daemon-reload")
        models = self._npusr_models()
        current = self._npusr_model()
        if models and current not in {m["file"] for m in models}:
            self._npusr_set_model(models[0]["file"])  # default model = first in the catalog
        elif self._npusr_systemctl("is-active", NPUSR_UNIT)[0] == 0:
            self._npusr_systemctl("restart", NPUSR_UNIT)
        state = self._npusr_package_state()
        msg = f"NPU package {manifest.get('version', '')} imported ({state['models']} models)."
        if not state["layer_registered"]:
            msg += f" One-time step in Desktop Mode (Konsole): {state['layer_command']}"
        if not state["runtime_ok"]:
            msg += " The Ryzen AI runtime is missing: see the NPU section."
        decky.logger.info(f"[NPU-SR] package {manifest.get('version')} imported")
        return {"status": "success", "message": msg, **{k: v for k, v in state.items() if k != "status"}}

    # ── Owner download from a private GitHub repo (opt-in via two files) ──────

    def _npusr_remote_config(self) -> tuple[str, str] | None:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or str(self._home() / ".config")) / "npu-sr"
        try:
            repo = (base / "package-repo").read_text(encoding="utf-8").strip()
            token = (base / "github-token").read_text(encoding="utf-8").strip()
        except OSError:
            return None
        if not _NPUSR_REPO_RE.match(repo) or not token or any(c.isspace() for c in token):
            return None
        return repo, token

    def _npusr_gh_get(self, url: str, token: str, accept: str) -> bytes:
        """GitHub API GET with the token. Release assets answer with a redirect to signed storage, which must be
        fetched WITHOUT the Authorization header (the storage rejects a second auth mechanism)."""
        headers = {"User-Agent": NPUSR_USER_AGENT, "Accept": accept, "Authorization": f"Bearer {token}",
                   "X-GitHub-Api-Version": "2022-11-28"}
        ctx = self._ssl_context()
        opener = urllib.request.build_opener(_NoRedirect, urllib.request.HTTPSHandler(context=ctx))
        try:
            with opener.open(urllib.request.Request(url, headers=headers), timeout=60) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            location = exc.headers.get("Location") if exc.code in (301, 302, 303, 307, 308) else None
            if not location:
                if exc.code in (401, 403, 404):
                    raise RuntimeError(f"GitHub refused the NPU package request ({exc.code}): check "
                                       "~/.config/npu-sr/package-repo and github-token.") from exc
                raise
        req = urllib.request.Request(location, headers={"User-Agent": NPUSR_USER_AGENT})
        with urllib.request.urlopen(req, timeout=300, context=ctx) as resp:
            return resp.read(NPUSR_PACKAGE_MAX + 1)

    def _npusr_remote_latest(self) -> dict | None:
        """Newest non-draft release (pre-releases included) that carries npu-sr-package-*.zip and its .sha256."""
        cfg = self._npusr_remote_config()
        if not cfg:
            return None
        repo, token = cfg
        releases = json.loads(self._npusr_gh_get(f"https://api.github.com/repos/{repo}/releases?per_page=10", token,
                                                 "application/vnd.github+json"))
        for rel in releases:
            if rel.get("draft"):
                continue
            assets = {a.get("name"): a for a in rel.get("assets") or []}
            for name, asset in assets.items():
                m = NPUSR_ASSET_RE.match(name or "")
                if not m:
                    continue
                sha = assets.get(name[:-4] + ".sha256") or assets.get(name + ".sha256")
                if sha:
                    return {"version": m.group(1), "tag": rel.get("tag_name"), "zip_url": asset["url"],
                            "sha_url": sha["url"], "size": asset.get("size") or 0}
        return None

    def _npusr_update_state(self) -> dict:
        if not self._npusr_remote_config():
            return {"status": "success", "configured": False}
        latest = self._npusr_remote_latest()
        installed = self._npusr_package_state()
        current = installed.get("version") if installed.get("installed") else None
        newer = bool(latest) and (not current or current == "local build"
                                  or _version_key(latest["version"]) > _version_key(current))
        return {"status": "success", "configured": True, "latest": latest["version"] if latest else None,
                "current": current, "update": newer}

    def _npusr_download_package(self) -> dict:
        cfg = self._npusr_remote_config()
        if not cfg:
            raise ValueError("No private package source configured (~/.config/npu-sr/package-repo, github-token).")
        latest = self._npusr_remote_latest()
        if not latest:
            raise ValueError("No release with an npu-sr package (.zip + .sha256) found.")
        if latest["size"] > NPUSR_PACKAGE_MAX:
            raise ValueError("The NPU package is too large (over 64 MB).")
        token = cfg[1]
        data = self._npusr_gh_get(latest["zip_url"], token, "application/octet-stream")
        expected = self._npusr_gh_get(latest["sha_url"], token, "application/octet-stream").decode("ascii", "replace")
        expected = (expected.split() or [""])[0].lower()
        if len(data) > NPUSR_PACKAGE_MAX or hashlib.sha256(data).hexdigest() != expected:
            raise ValueError("Downloaded NPU package failed the SHA-256 check.")
        dest = self._npusr_dir()
        dest.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".download-", suffix=".zip", dir=dest)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            result = self._npusr_import_package(tmp)
        finally:
            Path(tmp).unlink(missing_ok=True)
        decky.logger.info(f"[NPU-SR] package {latest['version']} downloaded from {cfg[0]} ({latest['tag']})")
        return result

    def _npusr_autoinstall(self) -> None:
        """Fresh install: when the owner configured a private source and no package is installed yet, fetch it."""
        if not self._npusr_remote_config() or self._npusr_package_state()["installed"]:
            return
        self._npusr_download_package()

    async def check_npu_package_update(self) -> dict:
        try:
            return await asyncio.to_thread(self._npusr_update_state)
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "message": str(exc), "configured": True}

    async def download_npu_package(self) -> dict:
        try:
            return await asyncio.to_thread(self._npusr_download_package)
        except (zipfile.BadZipFile, json.JSONDecodeError):
            return {"status": "error", "message": "The downloaded NPU package is not a valid ZIP."}
        except Exception as exc:  # noqa: BLE001
            decky.logger.error(f"[NPU-SR] package download: {exc}")
            return {"status": "error", "message": str(exc)}

    async def get_npu_package(self) -> dict:
        try:
            return await asyncio.to_thread(self._npusr_package_state)
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "message": str(exc)}

    async def import_npu_package(self, archive: str) -> dict:
        try:
            return await asyncio.to_thread(self._npusr_import_package, str(archive))
        except (zipfile.BadZipFile, json.JSONDecodeError):
            return {"status": "error", "message": "Not a valid NPU package ZIP."}
        except Exception as exc:  # noqa: BLE001
            decky.logger.error(f"[NPU-SR] package import: {exc}")
            return {"status": "error", "message": str(exc)}

    def _npusr_sharpness_file(self) -> Path:
        return self._home() / ".config" / "npu-sr" / "sharpness"

    def _npusr_sharpness(self) -> float:
        try:
            return max(0.0, min(1.0, float(self._npusr_sharpness_file().read_text().split()[0])))
        except (OSError, ValueError, IndexError):
            return 0.0

    async def set_npu_sharpness(self, value: float) -> dict:
        """Luma sharpening after the NPU (0 = off .. 1); a running game picks it up within a second."""
        try:
            v = max(0.0, min(1.0, round(float(value), 2)))
            f = self._npusr_sharpness_file()
            f.parent.mkdir(parents=True, exist_ok=True)
            tmp = f.with_suffix(".tmp")
            tmp.write_text(f"{v}\n", encoding="utf-8")
            os.replace(tmp, f)
            return {"status": "success", "sharpness": v}
        except (OSError, ValueError) as exc:
            return {"status": "error", "message": str(exc)}

    def _npusr_aa_file(self) -> Path:
        return self._home() / ".config" / "npu-sr" / "aa"

    def _npusr_aa(self) -> float:
        try:
            return max(0.0, min(1.0, float(self._npusr_aa_file().read_text().split()[0])))
        except (OSError, ValueError, IndexError):
            return 1.0  # the layer's default: FXAA-style edge AA, text-safe

    async def set_npu_aa(self, value: float) -> dict:
        """Edge anti-aliasing after the NPU (0 = off .. 1, layer default 1); a running game picks it up within a second."""
        try:
            v = max(0.0, min(1.0, round(float(value), 2)))
            f = self._npusr_aa_file()
            f.parent.mkdir(parents=True, exist_ok=True)
            tmp = f.with_suffix(".tmp")
            tmp.write_text(f"{v}\n", encoding="utf-8")
            os.replace(tmp, f)
            return {"status": "success", "aa": v}
        except (OSError, ValueError) as exc:
            return {"status": "error", "message": str(exc)}

    # ── API ───────────────────────────────────────────────────────────────────

    async def get_npu_sr(self, appid: str) -> dict:
        try:
            return await asyncio.to_thread(self._npusr_status, str(appid))
        except Exception as exc:  # noqa: BLE001
            decky.logger.error(f"[NPU-SR] status {appid}: {exc}")
            return {"status": "error", "message": str(exc)}

    async def set_npu_sr(self, appid: str, enabled: bool, current: str = "") -> dict:
        result = await asyncio.to_thread(self._npusr_set, str(appid), bool(enabled))
        if result.get("status") == "success":
            result["launch_options"] = self._npusr_launch(current, bool(enabled))
        return result

    async def set_npu_sr_model(self, model: str) -> dict:
        return await asyncio.to_thread(self._npusr_set_model, str(model))

    def _npusr_set_model(self, model: str) -> dict:
        x2 = self._npusr_is_x2(model)
        if model not in {m["file"] for m in self._npusr_models(x2=x2)}:
            return {"status": "error", "message": "Unknown NPU model."}
        var = "NPU_SR_MODEL_X2" if x2 else "NPU_SR_MODEL"
        path = self._npusr_dir() / "models" / model
        conf = self._npusr_env_conf()
        try:
            conf.parent.mkdir(parents=True, exist_ok=True)
            try:  # keep the other mode's model and any other lines
                lines = [l for l in conf.read_text(encoding="utf-8").splitlines() if not l.startswith(var + "=")]
            except OSError:
                lines = []
            lines.append(f"{var}={path}")
            tmp = conf.with_suffix(".tmp")
            tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
            os.replace(tmp, conf)
        except OSError as exc:
            return {"status": "error", "message": f"Could not save the NPU model: {exc}"}
        self._npusr_systemctl("set-environment", f"{var}={path}")
        rc, _ = self._npusr_systemctl("is-active", NPUSR_UNIT)
        if rc == 0:
            rc, out = self._npusr_systemctl("restart", NPUSR_UNIT)
            if rc != 0:
                decky.logger.error(f"[NPU-SR] restart for model {model}: {out}")
                return {"status": "error", "message": "NPU service did not start. See the plugin log."}
        decky.logger.info(f"[NPU-SR] model {model}")
        return {"status": "success", "message": "NPU model switched. A running game reconnects in a few seconds."}

    def _npusr_set(self, appid: str, enabled: bool) -> dict:
        status = self._npusr_status(appid)
        if enabled and not status["available"]:
            return {"status": "error", "message": "NPU upscaling is not installed on this device."}
        apps = [a for a in self._npusr_apps() if a != appid]
        if enabled:
            apps.append(appid)
        try:
            self._npusr_write_apps(apps)
        except OSError as exc:
            return {"status": "error", "message": f"Could not save the NPU game list: {exc}"}
        if enabled:
            rc, out = self._npusr_systemctl("enable", "--now", NPUSR_UNIT)
            if rc != 0:
                decky.logger.error(f"[NPU-SR] enable service: {out}")
                return {"status": "error", "message": "NPU service did not start. See the plugin log."}
            if hasattr(self, "_ensure_opti_no_caps"):
                self._ensure_opti_no_caps(appid)
            decky.logger.info(f"[NPU-SR] enabled for {appid}")
            return {"status": "success",
                    "message": "NPU upscaling enabled. Set the game to 1280×720; it applies on the next game start."}
        decky.logger.info(f"[NPU-SR] disabled for {appid}")
        return {"status": "success", "message": "NPU upscaling disabled. It applies on the next game start."}
