"""Per-game, reversible use of an official signed OptiScaler core.

The archive is pinned to the publisher's GitHub asset SHA-256. No game binaries,
upscaler libraries or other games' profiles are replaced.
"""
import asyncio
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
    def _signed_opti_source(self):
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
            if path.name.lower() == "optiscaler.dll" and not path.is_absolute() and ".." not in path.parts:
                members.append(name)
        if len(members) != 1: raise ValueError("Official archive must contain one OptiScaler.dll")
        result = subprocess.run([tool, "x", "-so", str(archive), members[0]], capture_output=True, timeout=90, env=env)
        if result.returncode or not has_certificate(result.stdout):
            raise ValueError("Official OptiScaler DLL has no certificate table")
        dest = cache / "OptiScaler.dll"
        dest.write_bytes(result.stdout)
        return dest

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
            if not has_certificate(replacement): raise ValueError("Official OptiScaler DLL has no certificate table")
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
        except Exception:
            temporary.write_bytes(current); os.replace(temporary, proxy)
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
