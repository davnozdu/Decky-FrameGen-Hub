"""NPU super-resolution per game: the npu-sr Vulkan layer + the Ryzen AI service (user systemd unit).

The layer (~/AsusNPU/npu-sr) is an implicit Vulkan layer that is inert unless the game's Steam AppId is
listed in ~/.config/npu-sr/enabled-apps. It takes the game's 1280x720 swapchain, sends luma to the NPU
service and presents 1920x1080. The list is read when the game creates its Vulkan device, so changes
apply on the next game start. This mixin only manages that list and the service; it never touches
game files, so it combines with OptiScaler/FSR 4 (render below 720p, FSR to 720p, NPU to 1080p).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path

import decky

NPUSR_UNIT = "npu-sr.service"
# RADV's RDR2 profile turns on the APU unified heap, which hides the CPU-cached memory types the layer needs for
# fast staging copies (~2.6 ms -> 0.1 ms per frame). Harmless for games without that profile.
NPUSR_LAUNCH_ENV = "radv_enable_unified_heap_on_apu=false"
_NPUSR_ENV_RE = re.compile(r"(?<!\S)radv_enable_unified_heap_on_apu=\S+\s*")
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

    def _npusr_models(self) -> list[dict]:
        """Selectable models: *.onnx in the models folder (sub-folders such as archive/ are ignored).
        Optional models/catalog.json: {"file.onnx": {"label": "...", "note": "..."}} gives friendly names."""
        folder = self._npusr_dir() / "models"
        try:
            catalog = json.loads((folder / "catalog.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            catalog = {}
        models = []
        for path in sorted(folder.glob("*.onnx")):
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

    def _npusr_model(self) -> str | None:
        conf = self._npusr_env_conf()
        try:
            for line in conf.read_text(encoding="utf-8").splitlines():
                if line.startswith("NPU_SR_MODEL="):
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
        if model not in {m["file"] for m in self._npusr_models()}:
            return {"status": "error", "message": "Unknown NPU model."}
        path = self._npusr_dir() / "models" / model
        conf = self._npusr_env_conf()
        try:
            conf.parent.mkdir(parents=True, exist_ok=True)
            tmp = conf.with_suffix(".tmp")
            tmp.write_text(f"NPU_SR_MODEL={path}\n", encoding="utf-8")
            os.replace(tmp, conf)
        except OSError as exc:
            return {"status": "error", "message": f"Could not save the NPU model: {exc}"}
        self._npusr_systemctl("set-environment", f"NPU_SR_MODEL={path}")
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
            decky.logger.info(f"[NPU-SR] enabled for {appid}")
            return {"status": "success",
                    "message": "NPU upscaling enabled. Set the game to 1280×720; it applies on the next game start."}
        decky.logger.info(f"[NPU-SR] disabled for {appid}")
        return {"status": "success", "message": "NPU upscaling disabled. It applies on the next game start."}
