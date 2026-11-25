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
# NPU_SR_ENABLE=1 loads the Vulkan layer into this game only: its manifest has enable_environment, so KWin, mpv,
# Steam and other programs never get it (a global layer crashed KWin's device enumeration).
NPUSR_LAUNCH_ENV = "NPU_SR_ENABLE=1 radv_enable_unified_heap_on_apu=false"
_NPUSR_ENV_RE = re.compile(r"(?<!\S)(?:radv_enable_unified_heap_on_apu|NPU_SR_ENABLE)=\S+\s*")
NPUSR_MANIFESTS = (
    Path("/usr/share/vulkan/implicit_layer.d/VkLayer_zz_npu_sr.json"),
    Path("/etc/vulkan/implicit_layer.d/VkLayer_zz_npu_sr.json"),
)
NPUSR_RELEASES_API = "https://api.github.com/repos/davnozdu/Decky-FrameGen-Hub/releases?per_page=5"


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
            expected = rec.get("sha256") if isinstance(rec, dict) else rec
            if hashlib.sha256(data).hexdigest() != expected:
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
            if "flow" in path.name.lower() or "180x320x25" in path.name or "900p" in path.name.lower():
                continue
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
        keys = ("in", "out", "frames", "npu_frames", "fallback_frames", "npu_ms", "connected",
                "fg_mult", "fg_active", "fg_engine", "fg_frames", "fg_flow_ms", "fg_free_fps", "fg_step_ms")
        return {k: stats.get(k) for k in keys}

    def _npusr_user_manifest(self) -> Path:
        return self._home() / ".local" / "share" / "vulkan" / "implicit_layer.d" / "VkLayer_zz_npu_sr.json"

    def _npusr_layer_registered(self) -> bool:
        return self._npusr_user_manifest().is_file() or any(p.is_file() for p in NPUSR_MANIFESTS)

    def _npusr_status(self, appid: str) -> dict:
        missing = []
        if not (self._npusr_dir() / "libVkLayer_npu_sr.so").is_file():
            missing.append("Vulkan layer")
        if not self._npusr_layer_registered():
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
            "fg": self._npusr_fg(),
            "fg_engine": self._npusr_fg_engine(),
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
        layer_registered = self._npusr_layer_registered()
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
        # Remove obsolete .onnx models that are no longer part of the imported package.
        keep_models = {Path(name).name for name in payload if name.startswith("models/") and name.endswith(".onnx")}
        if keep_models:
            for old in (dest / "models").glob("*.onnx"):
                if old.name not in keep_models:
                    try:
                        old.unlink()
                    except OSError:
                        pass
        # Register the implicit Vulkan layer in ~/.local/share/vulkan/implicit_layer.d (no sudo / Desktop Mode needed).
        user_manifest = self._npusr_user_manifest()
        user_manifest.parent.mkdir(parents=True, exist_ok=True)
        user_manifest.write_bytes(payload["VkLayer_zz_npu_sr.json"])
        (dest / "package.json").write_text(json.dumps({"version": manifest.get("version"), "files": sorted(payload)},
                                                      indent=2), encoding="utf-8")
        unit = self._npusr_unit_file()
        unit.parent.mkdir(parents=True, exist_ok=True)
        unit.write_bytes(payload["npu-sr.service"])
        self._npusr_systemctl("daemon-reload")
        self._npusr_systemctl("enable", "--now", NPUSR_UNIT)
        restarted = False
        models = self._npusr_models()
        current = self._npusr_model()
        if models and current not in {m["file"] for m in models}:
            self._npusr_set_model(models[0]["file"])  # default model = first in the catalog
            restarted = True
        models_x2 = self._npusr_models(x2=True)
        current_x2 = self._npusr_model("NPU_SR_MODEL_X2")
        if models_x2 and current_x2 not in {m["file"] for m in models_x2}:
            self._npusr_set_model(models_x2[0]["file"])
            restarted = True
        if not restarted and self._npusr_systemctl("is-active", NPUSR_UNIT)[0] == 0:
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

    def _import_all_in_one_bundle(self, archive: str) -> dict:
        src = Path(archive).expanduser()
        if not src.is_file():
            raise ValueError(f"Archive not found: {src}")
        done: list[str] = []
        errors: list[str] = []
        with tempfile.TemporaryDirectory(prefix="fghub-bundle-") as temp:
            stage = Path(temp)
            with zipfile.ZipFile(src, "r") as z:
                names = z.namelist()
                meta = {}
                if "bundle.json" in names:
                    meta = json.loads(z.read("bundle.json").decode("utf-8"))
                comps = meta.get("components", {}) if isinstance(meta, dict) else {}

                def extract_member(member: str) -> Path:
                    out = stage / Path(member).name
                    out.write_bytes(z.read(member))
                    return out

                # 1. NPU-SR package
                npu_entry = comps.get("npu_sr") or next(
                    (n for n in names if n.lower().endswith(".zip") and "npu-sr" in Path(n).name.lower()), None
                )
                if npu_entry and npu_entry in names:
                    try:
                        r = self._npusr_import_package(str(extract_member(npu_entry)))
                        done.append(f"NPU-SR ({r.get('models', '?')} models)")
                    except Exception as exc:  # noqa: BLE001
                        errors.append(f"NPU-SR: {exc}")

                # 2. FSR 4 libraries ZIP
                fsr4_entry = comps.get("fsr4") or next(
                    (n for n in names if n.lower().endswith(".zip") and "fsr4" in Path(n).name.lower()), None
                )
                if fsr4_entry and fsr4_entry in names:
                    try:
                        r = self._import_fsr4_zip(str(extract_member(fsr4_entry)))
                        r = self._apply_import_to_lite_games(r)
                        ver = r.get("version") or "OK"
                        done.append(f"FSR 4 ({ver})")
                    except Exception as exc:  # noqa: BLE001
                        errors.append(f"FSR 4: {exc}")

                # 3. Lossless Scaling DLL
                lsfg_entry = comps.get("lsfg") or next(
                    (n for n in names if Path(n).name.lower() in ("lsfg-vk.dll", "lossless.dll")), None
                )
                if lsfg_entry and lsfg_entry in names:
                    try:
                        self._import_lsfg_library(str(extract_member(lsfg_entry)))
                        done.append("Lossless Scaling")
                    except Exception as exc:  # noqa: BLE001
                        errors.append(f"Lossless: {exc}")

        if not done and not errors:
            return {"status": "error", "message": "Archive contains no NPU-SR, FSR 4, or Lossless Scaling packages."}
        if not done:
            return {"status": "error", "message": "; ".join(errors)}
        msg = "Imported: " + ", ".join(done) + "."
        if errors:
            msg += " Warnings: " + "; ".join(errors)
        return {"status": "success", "message": msg, "imported": done, "warnings": errors}

    async def import_all_in_one_bundle(self, archive: str) -> dict:
        try:
            async with self._generator_lock():
                return await asyncio.to_thread(self._import_all_in_one_bundle, str(archive))
        except (zipfile.BadZipFile, json.JSONDecodeError):
            return {"status": "error", "message": "Not a valid bundle ZIP."}
        except Exception as exc:  # noqa: BLE001
            decky.logger.error(f"[Bundle] import: {exc}")
            return {"status": "error", "message": str(exc)}

    def _find_local_bundle(self) -> Path | None:
        candidates: list[Path] = []
        for folder in (self._home() / "Downloads", self._home()):
            if folder.is_dir():
                candidates.extend(folder.glob("FrameGen-Hub-Full-Bundle-*.zip"))
        if not candidates:
            return None
        candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return candidates[0]

    async def find_local_bundle(self) -> dict:
        try:
            p = await asyncio.to_thread(self._find_local_bundle)
            return {"status": "success", "path": str(p) if p else None, "name": p.name if p else None}
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "path": None, "message": str(exc)}

    def _npusr_install_from_github(self) -> dict:
        raw = self._http_get(NPUSR_RELEASES_API, "application/vnd.github+json")
        releases = json.loads(raw.decode("utf-8", "replace"))
        if not isinstance(releases, list):
            raise ValueError("Unexpected GitHub releases response.")
        zip_url = sha_url = tag = None
        for rel in releases:
            if not isinstance(rel, dict) or rel.get("draft"):
                continue
            assets = rel.get("assets") or []
            z_asset = next((a for a in assets if str(a.get("name", "")).startswith("npu-sr-package-") and str(a.get("name", "")).endswith(".zip")), None)
            if z_asset:
                zip_url = z_asset.get("browser_download_url")
                s_asset = next((a for a in assets if str(a.get("name", "")).endswith(".sha256")), None)
                sha_url = s_asset.get("browser_download_url") if s_asset else None
                tag = rel.get("tag_name") or ""
                break
        if not zip_url:
            raise ValueError("No npu-sr package asset found on GitHub.")
        data = self._http_get(zip_url)
        if sha_url:
            expected = self._http_get(sha_url).decode("utf-8", "replace").split()[0].strip().lower()
            actual = hashlib.sha256(data).hexdigest().lower()
            if expected and actual != expected:
                raise ValueError("Downloaded npu-sr package failed SHA-256 verification.")
        with tempfile.TemporaryDirectory(prefix="npusr-dl-") as temp:
            dst = Path(temp) / f"npu-sr-package-{tag or 'latest'}.zip"
            dst.write_bytes(data)
            return self._npusr_import_package(str(dst))

    async def install_npu_from_github(self) -> dict:
        try:
            async with self._generator_lock():
                return await asyncio.to_thread(self._npusr_install_from_github)
        except Exception as exc:  # noqa: BLE001
            decky.logger.error(f"[NPU-SR] GitHub install: {exc}")
            return {"status": "error", "message": str(exc)}

    async def _npusr_auto_bootstrap(self) -> None:
        """Best-effort autonomous setup on plugin startup: offline local bundle first, then GitHub NPU-SR if NPU hardware is present."""
        await asyncio.sleep(3)
        try:
            state = await asyncio.to_thread(self._npusr_package_state)
            fsr4_ok = bool(await asyncio.to_thread(self._local_fsr4_source))
            lsfg_ok = bool(await asyncio.to_thread(self._lsfg_library_path))
            need_npu = bool(state.get("npu_device")) and (not state.get("installed") or not state.get("layer_registered"))
            if not need_npu and fsr4_ok and lsfg_ok:
                return
            bundle = await asyncio.to_thread(self._find_local_bundle)
            if bundle and (need_npu or not fsr4_ok or not lsfg_ok):
                decky.logger.info(f"[Bootstrap] Found local bundle {bundle.name}; restoring missing components offline")
                async with self._generator_lock():
                    res = await asyncio.to_thread(self._import_all_in_one_bundle, str(bundle))
                decky.logger.info(f"[Bootstrap] Local bundle result: {res.get('message')}")
                return
            if need_npu:
                decky.logger.info("[Bootstrap] Ryzen AI NPU detected; downloading latest npu-sr package from GitHub")
                async with self._generator_lock():
                    res = await asyncio.to_thread(self._npusr_install_from_github)
                decky.logger.info(f"[Bootstrap] GitHub NPU-SR result: {res.get('message')}")
        except Exception as exc:  # noqa: BLE001
            decky.logger.info(f"[Bootstrap] Skipped (offline or unavailable): {exc}")

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
            return 0.5

    async def set_npu_aa(self, value: float) -> dict:
        """Directional edge anti-aliasing after the NPU (0 = off .. 1); a running game picks it up within a second."""
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

    def _npusr_fg_file(self) -> Path:
        return self._home() / ".config" / "npu-sr" / "fg"

    def _npusr_fg(self) -> int:
        try:
            tok = self._npusr_fg_file().read_text().split()[0].strip().lower()
            if tok.startswith("auto"):
                return 0
            return max(0, min(3, int(round(float(tok)))))
        except (OSError, ValueError, IndexError):
            return 1

    async def set_npu_fg(self, value: int) -> dict:
        """Async Frame Generation mode (0 = auto, 1 = off, 2 = x2, 3 = x3); applies within a second."""
        try:
            if isinstance(value, str) and value.strip().lower().startswith("auto"):
                v = 0
            else:
                v = max(0, min(3, int(round(float(value)))))
            f = self._npusr_fg_file()
            f.parent.mkdir(parents=True, exist_ok=True)
            tmp = f.with_suffix(".tmp")
            tmp.write_text("auto\n" if v == 0 else f"{v}\n", encoding="utf-8")
            os.replace(tmp, f)
            return {"status": "success", "fg": v}
        except (OSError, ValueError) as exc:
            return {"status": "error", "message": str(exc)}

    def _npusr_fg_engine_file(self) -> Path:
        return self._home() / ".config" / "npu-sr" / "fg-engine"

    def _npusr_fg_engine(self) -> str:
        try:
            v = self._npusr_fg_engine_file().read_text().strip().lower()
            return "cpu" if v == "cpu" else "npu"
        except OSError:
            return "npu"

    async def set_npu_fg_engine(self, engine: str) -> dict:
        """Choose optical flow engine for Frame Generation: 'npu' (FlowNet v2, default) or 'cpu' (block-matching)."""
        try:
            v = "cpu" if str(engine).lower() == "cpu" else "npu"
            f = self._npusr_fg_engine_file()
            f.parent.mkdir(parents=True, exist_ok=True)
            tmp = f.with_suffix(".tmp")
            tmp.write_text(f"{v}\n", encoding="utf-8")
            os.replace(tmp, f)
            return {"status": "success", "fg_engine": v}
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
                    "message": "NPU upscaling enabled. Set the game to 1600×900, 1280×720, or 1024×576; applies on next launch."}
        decky.logger.info(f"[NPU-SR] disabled for {appid}")
        return {"status": "success", "message": "NPU upscaling disabled. It applies on the next game start."}
