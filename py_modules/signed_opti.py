"""Per-game, reversible use of an official signed OptiScaler core.

The archive is pinned to the publisher's GitHub asset SHA-256. No game binaries,
user-imported libraries or other games' profiles are replaced. The signed core's
FSR 4 backend uses SDK libraries extracted from the same pinned archive.
"""
import asyncio
import copy
import hashlib
import os
from pathlib import Path, PurePosixPath
import struct
import subprocess
from fsr4_extract import find_7zip

VERSION = "0.9.4"
URL = "https://github.com/optiscaler/OptiScaler/releases/download/v0.9.4/Optiscaler_0.9.4-final.20260718._MM.7z"
SHA256 = "575cb4df866116093df75af607e37fd70e10f5163e0f23fd5c804142e80ef0ad"


def has_certificate(data):
    try:
        if data[:2] != b"MZ": return False
        pe = struct.unpack_from("<I", data, 0x3c)[0]
        if data[pe:pe + 4] != b"PE\0\0": return False
        optional = pe + 24
        magic = struct.unpack_from("<H", data, optional)[0]
        if magic not in (0x10b, 0x20b): return False
        table = optional + (112 if magic == 0x20b else 96)
        offset, size = struct.unpack_from("<II", data, table + 32)
        return bool(offset and size >= 8 and offset + size <= len(data))
    except (struct.error, ValueError):
        return False


class SignedOptiMixin:
    def _official_opti_asset(self, filename):
        cache = self._runtime_dir() / "official-optiscaler" / VERSION
        cache.mkdir(parents=True, exist_ok=True)
        archive = cache / "official.7z"
        if not archive.is_file() or self._file_sha256(archive) != SHA256:
            data = self._http_get(URL)
            if hashlib.sha256(data).hexdigest() != SHA256:
                raise ValueError("Official OptiScaler archive checksum mismatch")
            archive.write_bytes(data)
        tool = find_7zip(cache / "7zip")
        env = dict(os.environ); env.pop("LD_LIBRARY_PATH", None)
        listing = subprocess.run([tool, "l", "-slt", "-sccUTF-8", str(archive)], capture_output=True, text=True, timeout=60, env=env)
        if listing.returncode: raise ValueError("Cannot read official OptiScaler archive")
        members = []
        for line in listing.stdout.splitlines():
            if not line.startswith("Path = "): continue
            name = line[7:].replace("\\", "/")
            path = PurePosixPath(name)
            if path.name.lower() == filename.lower() and not path.is_absolute() and ".." not in path.parts:
                members.append(name)
        if len(members) != 1: raise ValueError(f"Official archive must contain one {filename}")
        result = subprocess.run([tool, "x", "-so", str(archive), members[0]], capture_output=True, timeout=90, env=env)
        if result.returncode or not has_certificate(result.stdout):
            raise ValueError("Official OptiScaler asset has no certificate table")
        dest = cache / filename
        dest.write_bytes(result.stdout)
        return dest

    def _signed_opti_source(self):
        return self._official_opti_asset("OptiScaler.dll")

    def _apply_signed_upscaler(self, appid, ini, choice, watermark):
        """The signed upstream core uses the SDK backend, not ANR's ffx/model keys.

        Keep SDK files separate from the ANR package and user-imported driver DLLs.
        Upstream 0.9.4 requires ForceEnableInt8 for RDNA 3/3.5 integrated GPUs.
        """
        ini = ini.resolve()
        state = self._load_state()
        state_before = copy.deepcopy(state)
        ini_before = ini.read_bytes()
        replacements = []
        entry = state["games"][str(appid)]
        managed = entry.setdefault("managed_files", [])
        fsr4 = choice in ("fsr4", "fsr4lite")
        values = {
            ("Upscalers", "Dx12Upscaler"): {
                "package": "auto", "fsr31": "fsr31", "fsr4": "fsr31",
                "fsr4lite": "fsr31", "xess": "xess",
            }[choice],
            ("FSR", "UpscalerIndex"): "0" if fsr4 else "1",
            ("FSR", "Fsr4Update"): "false",
            ("FSR", "Fsr4ForceEnableInt8"): "true" if fsr4 and not self._gpu_is_rdna4() else "false",
            ("FSR", "Fsr4EnableWatermark"): "true" if fsr4 and watermark else "false",
            ("Log", "LogLevel"): "2", ("Log", "LogToFile"): "true",
        }
        if fsr4:
            folder = ini.parent / "OptiScaler" / "OfficialFSR4"
            # Resolve before mkdir and do not follow a directory redirected outside the game.
            if not folder.resolve().is_relative_to(ini.parent.resolve()):
                raise ValueError("Official SDK directory is outside the game folder")
            names = ("amd_fidelityfx_dx12.dll", "amd_fidelityfx_upscaler_dx12.dll")
            for name in names:
                dest = folder / name
                record = next((m for m in managed if m.get("path") == str(dest)), None)
                if dest.is_symlink() or (dest.exists() and (not record or self._file_sha256(dest) != record.get("sha256"))):
                    raise ValueError(f"{name} is not managed or was modified; it was not overwritten")
            sources = [self._official_opti_asset(name) for name in names]
            folder.mkdir(parents=True, exist_ok=True)
        try:
            if fsr4:
                for name, source in zip(names, sources):
                    dest = folder / name
                    original = dest.read_bytes() if dest.exists() else None
                    temp = dest.with_suffix(".fghub-new")
                    try:
                        temp.write_bytes(source.read_bytes()); os.replace(temp, dest)
                    finally:
                        temp.unlink(missing_ok=True)
                    replacements.append((dest, original))
                    managed[:] = [m for m in managed if m.get("path") != str(dest)]
                    managed.append({"path": str(dest), "sha256": self._file_sha256(dest)})
                # Wine Z: paths are independent of the launcher's working directory.
                sdk_path = "Z:" + str(folder).replace("/", "\\")
                values[("Libraries", "FfxDx12Path")] = sdk_path
                values[("Libraries", "FfxDx12SRPath")] = sdk_path
            self._set_ini_sections(ini, values)
            entry.update(upscaler=choice, upscaler_watermark=bool(watermark))
            self._save_state(state)
        except Exception:
            for dest, original in reversed(replacements):
                if original is None:
                    dest.unlink(missing_ok=True)
                else:
                    temp = dest.with_suffix(".fghub-new")
                    temp.write_bytes(original); os.replace(temp, dest)
            ini.write_bytes(ini_before)
            self._save_state(state_before)
            raise
        return {"status": "success", "message": "Signed OptiScaler: " +
                ("official FSR 4 SDK selected (INT8 on non-RDNA4 GPUs)." if fsr4 else self.UPSCALERS[choice] + " selected.") +
                " Restart the game; confirm the active backend in the OptiScaler overlay/log."}

    def _set_signed_optiscaler(self, appid, enabled, reapply=False):
        appid = str(appid)
        game = self._game(appid)
        if not game or self._is_running(game): raise ValueError("Close the game first.")
        entry = self._load_state()["games"].get(appid, {})
        if entry.get("mode") != "full" or not entry.get("proxy"):
            raise ValueError("This fix needs a full managed OptiScaler install.")
        target = Path(entry["target_dir"]).resolve()
        root = Path(game["install_path"]).resolve()
        if target != root and root not in target.parents: raise ValueError("The folder is outside the game's install folder.")
        proxy = target / entry["proxy"]
        if proxy.is_symlink() or not proxy.is_file(): raise ValueError("OptiScaler proxy file is missing or is a symbolic link")
        current = proxy.read_bytes(); digest = hashlib.sha256(current).hexdigest()
        state_before = copy.deepcopy(self._load_state())
        ini = self._optiscaler_ini(target, self._describe_dir(target))
        ini_before = ini.read_bytes() if ini and ini.exists() else None
        record = entry.get("signed_optiscaler") or {}
        backup = self._runtime_dir() / "optiscaler-compat-backups" / appid / "original.dll"
        if enabled:
            if record and digest == record.get("installed_sha256"):
                return {"status": "success", "message": "Official signed OptiScaler is already active for this game."}
            package = self._package_dir(entry.get("version") or self._active_version(), "full")
            originals = [p for p in package.rglob("*.dll") if p.name.lower() in ("optiscaler.dll", "dxgi.dll")]
            if not any(self._file_sha256(p) == digest for p in originals):
                raise ValueError("The OptiScaler proxy was modified outside this plugin; it was not overwritten.")
            if record and not reapply: raise ValueError("The OptiScaler proxy changed; disable or reinstall the fix first.")
            source = self._signed_opti_source()
            replacement = source.read_bytes()
            if not has_certificate(replacement): raise ValueError("Official OptiScaler asset has no certificate table")
            if self._is_running(game): raise ValueError("Close the game first.")
            backup.parent.mkdir(parents=True, exist_ok=True); backup.write_bytes(current)
            new_record = {"version": VERSION, "installed_sha256": hashlib.sha256(replacement).hexdigest(),
                          "original_sha256": digest, "archive_sha256": SHA256}
        else:
            if not record: return {"status": "success", "message": "Signed OptiScaler fix is already off for this game."}
            if digest != record.get("installed_sha256") or not backup.is_file() or self._file_sha256(backup) != record.get("original_sha256"):
                raise ValueError("The OptiScaler proxy or backup changed; no files were overwritten.")
            replacement = backup.read_bytes(); new_record = None
        temporary = proxy.with_name(proxy.name + ".fghub-new")
        temporary.write_bytes(replacement); os.replace(temporary, proxy)
        try:
            state = self._load_state(); latest = state["games"][appid]
            if new_record:
                latest["signed_optiscaler"] = new_record; latest["dxgi_fix"] = False
            else: latest.pop("signed_optiscaler", None)
            self._save_state(state)
            choice = latest.get("upscaler")
            if choice and ini:
                if not enabled:
                    self._set_ini_sections(ini, {
                        ("Libraries", "FfxDx12Path"): "auto", ("Libraries", "FfxDx12SRPath"): "auto",
                        ("FSR", "Fsr4ForceEnableInt8"): "auto", ("FSR", "Fsr4Update"): "auto",
                    })
                applied = self._apply_upscaler(appid, target, choice, bool(latest.get("upscaler_watermark")))
                if applied.get("status") != "success": raise ValueError(applied.get("message", "Could not restore the upscaler"))
        except Exception:
            temporary.write_bytes(current); os.replace(temporary, proxy)
            if ini_before is not None: ini.write_bytes(ini_before)
            self._save_state(state_before)
            raise
        return {"status": "success", "message": "Official signed OptiScaler enabled for this game. Upscaler and generator settings are preserved." if enabled
                else "Original OptiScaler restored for this game."}

    async def set_signed_optiscaler(self, appid: str, enabled: bool, current: str):
        try:
            async with self._generator_lock():
                result = await asyncio.to_thread(self._set_signed_optiscaler, str(appid), bool(enabled))
                launch = await self.recommended_launch_options(str(appid), current)
                if launch.get("status") == "success": result["launch_options"] = launch["launch_options"]
                return result
        except Exception as exc:
            return {"status": "error", "message": str(exc)}
