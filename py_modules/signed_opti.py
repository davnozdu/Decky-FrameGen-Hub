"""Per-game, reversible use of an official signed OptiScaler core.

The archive is pinned to the publisher's GitHub asset SHA-256. No game binaries,
user-imported libraries or other games' profiles are replaced. The signed core's
FSR 4 backend uses SDK libraries extracted from the same pinned archive.
"""
import asyncio
import copy
import hashlib
import os
import json
import re
from pathlib import Path, PurePosixPath
import struct
import subprocess
from fsr4_extract import find_7zip

VERSION = "0.9.4"
URL = "https://github.com/optiscaler/OptiScaler/releases/download/v0.9.4/Optiscaler_0.9.4-final.20260718._MM.7z"
SHA256 = "575cb4df866116093df75af607e37fd70e10f5163e0f23fd5c804142e80ef0ad"
NIGHTLY_VERSION = "10.0.0-pre1-20261115"
NIGHTLY_URL = "https://github.com/optiscaler/OptiScaler-nightly/releases/download/nightly-20261115/OptiScaler_v10.0.0-pre1_20261115.7z"
NIGHTLY_SHA256 = "61c722b3cc12d3873f2130a490c09a778539ab26796d2a76ca118f502f8b15d6"

SIGNED_LITE_VERSION = "0.9.5-pre5-20261111"
SIGNED_LITE_SHA256 = "3835c3a80847bae2a9bb5d873a42e43d7cf504b172650bb54b7659b67e7fdf27"


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
    def _official_opti_asset(self, filename, nightly=False, release=None):
        version, url, sha = (NIGHTLY_VERSION, NIGHTLY_URL, NIGHTLY_SHA256) if nightly else (VERSION, URL, SHA256)
        if release:
            version, url, sha = release["version"], release["url"], release["archive_sha256"]
        cache = self._runtime_dir() / "official-optiscaler" / version
        key = (version, filename)
        dest = cache / filename
        # Every apply needs up to three assets: reuse a file extracted from the verified
        # archive in this session instead of re-hashing and re-extracting it each time.
        extracted = self.__dict__.setdefault("_official_opti_extracted", {})
        if key in extracted and dest.is_file() and self._file_sha256(dest) == extracted[key]:
            return dest
        cache.mkdir(parents=True, exist_ok=True)
        archive = cache / "official.7z"
        if not archive.is_file() or self._file_sha256(archive) != sha:
            data = self._http_get(url)
            if hashlib.sha256(data).hexdigest() != sha:
                raise ValueError("Official OptiScaler archive checksum mismatch")
            partial = archive.with_suffix(".part")
            partial.write_bytes(data); os.replace(partial, archive)
        tool = find_7zip(self._runtime_dir() / "tools-cache")
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
        if result.returncode or (not nightly and not has_certificate(result.stdout)):
            raise ValueError("Official OptiScaler asset has no certificate table")
        partial = dest.with_name(dest.name + ".part")
        partial.write_bytes(result.stdout); os.replace(partial, dest)
        extracted[key] = hashlib.sha256(result.stdout).hexdigest()
        return dest

    def _signed_opti_source(self):
        return self._official_opti_asset("OptiScaler.dll")

    def _nightly_opti_source(self):
        local = self._runtime_dir() / "local-signed-optiscaler" / NIGHTLY_VERSION
        manifest = local / "signature.json"
        if manifest.is_file():
            record = json.loads(manifest.read_text())
            source = local / "OptiScaler.dll"
            if (record.get("archive_sha256") != NIGHTLY_SHA256 or source.is_symlink()
                    or not source.is_file() or self._file_sha256(source) != record.get("sha256")
                    or not has_certificate(source.read_bytes())):
                raise ValueError("Local signed Nightly changed; it was not installed")
            return source
        return self._official_opti_asset("OptiScaler.dll", nightly=True)

    def _signed_lite_opti_source(self):
        archive = self._runtime_dir() / "official-optiscaler" / SIGNED_LITE_VERSION / "official.7z"
        if not archive.is_file() or self._file_sha256(archive) != SIGNED_LITE_SHA256:
            raise ValueError("The verified signed 0.9.5 test archive is not installed on this device")
        return self._official_opti_asset("OptiScaler.dll", release={
            "version": SIGNED_LITE_VERSION, "url": "", "archive_sha256": SIGNED_LITE_SHA256,
        })

    def _signed_core_has_lite(self, entry):
        return str((entry.get("signed_optiscaler") or {}).get("version", "")).startswith("0.9.5")

    # ── Two OptiScaler cores per game ─────────────────────────────────────────
    # "fg": ANR FG / XeFG need a core with the custom DLSSG provider (the ANR package,
    # or signed 0.9.4). "ls": Lossless Scaling / no FG only needs upscaling, so the
    # Lite-capable cores (signed 0.9.5, 0.10 Nightly) can be used. Each group keeps
    # its own choice; changing the generator swaps the core automatically.
    CORE_LABELS = {"package": "ANR package", "signed": "OptiScaler 0.9.4 (signed)",
                   "signed095": "OptiScaler 0.9.5-pre5 (signed)", "nightly": "OptiScaler 0.10 Nightly"}
    LS_ONLY_CORES = ("nightly", "signed095")

    @staticmethod
    def _core_group(generator):
        return "fg" if generator in ("anr", "xefg") else "ls"

    def _active_core(self, entry):
        if entry.get("signed_optiscaler"):
            return "signed095" if self._signed_core_has_lite(entry) else "signed"
        return "nightly" if entry.get("nightly_optiscaler") else "package"

    @staticmethod
    def _requires_signed_core(game):
        # Diablo IV rejects unsigned OptiScaler builds (dxgi.dll error / c00000e5 crash).
        return (game or {}).get("name", "").strip().casefold() in ("diablo iv", "diablo 4")

    def _preferred_core(self, entry, group):
        saved = (entry.get("optiscaler_cores") or {}).get(group)
        if group == "fg":
            return saved if saved in ("package", "signed") else "package"
        return saved or self._active_core(entry)

    def _fg_available(self, game, entry):
        return not (self._requires_signed_core(game) and self._preferred_core(entry, "fg") == "package")

    def _remember_core(self, appid, core):
        state = self._load_state()
        entry = state["games"].get(str(appid))
        if entry is None:
            return
        group = self._core_group(entry.get("generator", "anr"))
        if group == "fg" and core in self.LS_ONLY_CORES:
            return
        entry.setdefault("optiscaler_cores", {})[group] = core
        self._save_state(state)

    def _switch_core_for_generator(self, appid, generator):
        """Install the core remembered for the generator's group. Returns a note or ""."""
        game = self._game(str(appid))
        entry = self._load_state()["games"].get(str(appid), {})
        if entry.get("mode") != "full" or not entry.get("proxy"):
            return ""
        group = self._core_group(generator)
        wanted, active = self._preferred_core(entry, group), self._active_core(entry)
        if group == "fg" and self._requires_signed_core(game) and wanted == "package":
            raise ValueError("This game rejects unsigned OptiScaler (dxgi.dll error), so ANR FG and XeFG cannot run "
                             "here: they need the ANR package core. Use Lossless Scaling.")
        if wanted == active:
            return ""
        self._set_optiscaler_core(str(appid), wanted)
        return f" OptiScaler switched to {self.CORE_LABELS[wanted]} for this generator."

    def _apply_signed_upscaler(self, appid, ini, choice, watermark):
        """The signed upstream core uses the SDK backend, not ANR's ffx/model keys.

        Keep SDK files separate from the ANR package and user-imported driver DLLs.
        Upstream 0.9.4 requires ForceEnableInt8 for RDNA 3/3.5 integrated GPUs.
        """
        ini = ini.resolve()
        # The signed 0.9.4 core has no Fsr4Model/Fsr4GpuSupport and never loads amdvkffx64:
        # it cannot select INT8 Lite. Keep the game on FSR 4 INT8 and record that honestly.
        requested = choice  # kept in the profile: turning the signed fix off restores Lite
        lite_requested = choice == "fsr4lite"
        if lite_requested:
            choice = "fsr4"
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
            ("Upscalers", "VulkanUpscaler"): "auto",
            ("FSR", "UpscalerIndex"): "0" if fsr4 else "1",
            ("FSR", "Fsr4Update"): "false",
            # ANR-build keys (Lite model selection); the signed 0.9.4 core ignores them,
            # so leftovers from a previous Lite setup would only misreport the active mode.
            ("FSR", "Fsr4GpuSupport"): "auto", ("FSR", "Fsr4Model"): "auto",
            ("FSR", "Fsr4ForceEnableInt8"): ("1" if self._signed_core_has_lite(entry) else "true") if fsr4 and not self._gpu_is_rdna4() else "false",
            # SDK checks MLSR-WATERMARK's existence, even when its value is "0".
            # Upstream false sets "0"; auto leaves the absent variable untouched.
            ("FSR", "Fsr4EnableWatermark"): "true" if fsr4 and watermark else "auto",
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
            entry.update(upscaler=requested, upscaler_watermark=bool(watermark))
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
                " Restart the game; confirm the active backend in the OptiScaler overlay/log." +
                (" FSR 4 Lite is not available with the signed core; FSR 4 INT8 is used instead." if lite_requested else "")}

    def _set_signed_optiscaler(self, appid, enabled, reapply=False):
        return self._set_optiscaler_core(appid, "signed" if enabled else "package", reapply)

    def _set_optiscaler_core(self, appid, core, reapply=False, nightly_release=None):
        if core not in ("package", "signed", "signed095", "nightly"):
            raise ValueError("Unknown OptiScaler core")
        enabled = core != "package"
        appid = str(appid)
        game = self._game(appid)
        if not game or self._is_running(game): raise ValueError("Close the game first.")
        entry = self._load_state()["games"].get(appid, {})
        if core in self.LS_ONLY_CORES and entry.get("generator", "anr") not in ("lsfg", "off"):
            raise ValueError("OptiScaler Nightly requires Lossless Scaling or frame generation off. ANR FG and XeFG require the package core.")
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
        record = entry.get("signed_optiscaler") or entry.get("nightly_optiscaler") or {}
        active_core = ("signed095" if self._signed_core_has_lite(entry) else "signed") if entry.get("signed_optiscaler") else "nightly" if entry.get("nightly_optiscaler") else "package"
        backup = self._runtime_dir() / "optiscaler-compat-backups" / appid / "original.dll"
        if enabled:
            if record and active_core == core and digest == record.get("installed_sha256") and not nightly_release:
                return {"status": "success", "message": "OptiScaler 0.10 Nightly is already active for this game." if core == "nightly" else "Official signed OptiScaler is already active for this game."}
            package = self._package_dir(entry.get("version") or self._active_version(), "full")
            originals = [p for p in package.rglob("*.dll") if p.name.lower() in ("optiscaler.dll", "dxgi.dll")]
            switching = record and not reapply
            if switching and (digest != record.get("installed_sha256") or not backup.is_file()
                              or self._file_sha256(backup) != record.get("original_sha256")):
                raise ValueError("The OptiScaler proxy or backup changed; no files were overwritten.")
            if not switching and not any(self._file_sha256(p) == digest for p in originals):
                raise ValueError("The OptiScaler proxy was modified outside this plugin; it was not overwritten.")
            release = nightly_release or (record if core == "nightly" and active_core == "nightly" and record.get("url") else None)
            if core == "signed095":
                source = self._signed_lite_opti_source()
            elif core == "nightly" and record.get("local_test_signer") and not nightly_release:
                source = self._nightly_opti_source()
            elif core == "nightly" and release:
                source = self._official_opti_asset("OptiScaler.dll", nightly=True, release=release)
            else:
                source = self._nightly_opti_source() if core == "nightly" else self._signed_opti_source()
            replacement = source.read_bytes()
            if core in ("signed", "signed095") and not has_certificate(replacement): raise ValueError("Official OptiScaler asset has no certificate table")
            if core == "nightly" and self._requires_signed_core(game) and not has_certificate(replacement):
                raise ValueError("Diablo IV requires a signed OptiScaler build. This Nightly is unsigned. Use signed 0.9.4 with standard FSR 4 INT8; Lite needs a signed Nightly build.")
            if core == "nightly" and not replacement.startswith(b"MZ"):
                raise ValueError("Nightly OptiScaler asset is not a Windows DLL")
            if self._is_running(game): raise ValueError("Close the game first.")
            backup_before = backup.read_bytes() if backup.exists() else None
            if not switching:
                backup.parent.mkdir(parents=True, exist_ok=True); backup.write_bytes(current)
            new_record = {"version": NIGHTLY_VERSION if core == "nightly" else VERSION, "installed_sha256": hashlib.sha256(replacement).hexdigest(),
                          "original_sha256": record["original_sha256"] if switching else digest,
                          "archive_sha256": NIGHTLY_SHA256 if core == "nightly" else SHA256}
            if core == "signed095":
                new_record.update(version=SIGNED_LITE_VERSION, archive_sha256=SIGNED_LITE_SHA256)
            if core == "nightly":
                new_record.update({k: release[k] for k in ("version", "url", "archive_sha256")} if release else
                                  {"version": NIGHTLY_VERSION, "url": NIGHTLY_URL, "archive_sha256": NIGHTLY_SHA256})
            if core == "nightly" and source.parent == self._runtime_dir() / "local-signed-optiscaler" / NIGHTLY_VERSION:
                new_record["local_test_signer"] = "Davnozdu Local OptiScaler Test"
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
                latest.pop("signed_optiscaler", None); latest.pop("nightly_optiscaler", None)
                latest["nightly_optiscaler" if core == "nightly" else "signed_optiscaler"] = new_record
                latest["dxgi_fix"] = False
            else:
                latest.pop("signed_optiscaler", None); latest.pop("nightly_optiscaler", None)
            self._save_state(state)
            choice = latest.get("upscaler")
            if core in ("nightly", "signed095") and ini:
                self._set_ini_sections(ini, {("FrameGen", "FGInput"): "nofg"})
            if choice and ini:
                if core != "signed":
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
            if enabled:
                if backup_before is None: backup.unlink(missing_ok=True)
                else: backup.write_bytes(backup_before)
            raise
        if core == "nightly":
            return {"status": "success", "message": "OptiScaler 0.10 Nightly enabled for this game. Select FSR 4 Lite and restart the game."}
        return {"status": "success", "message": "Official signed OptiScaler enabled for this game. Upscaler and generator settings are preserved." if enabled
                else "Original OptiScaler restored for this game."}

    async def set_signed_optiscaler(self, appid: str, enabled: bool, current: str):
        return await self.set_optiscaler_core(appid, "signed" if enabled else "package", current)

    async def set_optiscaler_core(self, appid: str, core: str, current: str = ""):

        try:
            async with self._generator_lock():
                result = await asyncio.to_thread(self._set_optiscaler_core, str(appid), core)
                await asyncio.to_thread(self._remember_core, str(appid), core)
                launch = await self.recommended_launch_options(str(appid), current)
                if launch.get("status") == "success": result["launch_options"] = launch["launch_options"]
                return result
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def _update_nightly_optiscaler(self, appid):
        entry = self._load_state()["games"].get(str(appid), {})
        if not entry.get("nightly_optiscaler"):
            raise ValueError("Select OptiScaler 0.10 Nightly for this game first.")
        releases = json.loads(self._http_get("https://api.github.com/repos/optiscaler/OptiScaler-nightly/releases?per_page=10"))
        for release in releases:
            if release.get("draft"):
                continue
            for asset in release.get("assets", []):
                if not re.fullmatch(r"OptiScaler_v10[\w.\-]*\.7z", asset.get("name", ""), re.IGNORECASE):
                    continue
                digest = asset.get("digest", "")
                url = asset.get("browser_download_url", "")
                tag = release.get("tag_name", "")
                if not re.fullmatch(r"nightly-[\w.\-]+", tag):
                    raise ValueError("Invalid OptiScaler nightly release tag")
                if not re.fullmatch(r"sha256:[a-fA-F0-9]{64}", digest) or not url.startswith(
                    "https://github.com/optiscaler/OptiScaler-nightly/releases/download/" + tag + "/"
                ):
                    raise ValueError("Nightly release has no valid publisher SHA-256 or download URL")
                result = self._set_optiscaler_core(str(appid), "nightly", nightly_release={
                    "version": tag, "url": url, "archive_sha256": digest[7:].lower(),
                })
                result["message"] = "OptiScaler Nightly updated for this game. Restart the game."
                return result
        raise ValueError("No OptiScaler 0.10 nightly archive found")

    async def update_nightly_optiscaler(self, appid: str):
        try:
            async with self._generator_lock():
                return await asyncio.to_thread(self._update_nightly_optiscaler, str(appid))
        except Exception as exc:
            return {"status": "error", "message": str(exc)}
