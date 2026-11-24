"""Install the pinned AMD userspace runtime under the player's home directory."""

from __future__ import annotations

import hashlib
import os
import platform
import shutil
import subprocess
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class Download:
    url: str
    size: int
    sha256: str

    @property
    def name(self) -> str:
        return self.url.rsplit("/", 1)[-1]


AMD = "https://download.amd.com/opendownload/RyzenAI/1.9.0/"
UBUNTU = "https://archive.ubuntu.com/ubuntu/pool/main/"
RYZEN_AI = Download(AMD + "ryzen-ai-runtime_1.9.0-1_amd64.deb", 2380940568,
                    "7928fef49241f301d04287b06872d6ee051afad45125206e9a9240c27b1e4622")
XRT = Download(AMD + "RAI_1.9_Linux_NPU_XRT.zip", 90496600,
               "074c981fad839ea4b7623337f63ed772e3469f5212d16c220b0f6f8b002b7877")
XRT_DEBS = (
    "xrt_202620.2.26.89_24.04-amd64-base.deb",
    "xrt_202620.2.26.89_24.04-amd64-npu.deb",
    "xrt_plugin.2.26.260102.59.release_24.04-amd64-amdxdna.deb",
)
COMPAT = (
    Download(UBUNTU + "n/ncurses/libncurses6_6.4+20240113-1ubuntu2.2_amd64.deb", 111902,
             "59e8527dfd14473393960bfb7c69566f1ad9d576423421dcb8b8dcdbb3e7fca1"),
    Download(UBUNTU + "n/ncurses/libtinfo6_6.4+20240113-1ubuntu2.2_amd64.deb", 108086,
             "b67a6df2bdab61d273eabebd208bb6a3fb12618a390a067e1ee305a409ff03d9"),
    Download(UBUNTU + "b/boost1.83/libboost-filesystem1.83.0_1.83.0-2.1ubuntu3.2_amd64.deb", 283562,
             "154b74fe60f7fc6223b0ff86063b8eb9429bfd1f532085fce66b555ebf2bf96c"),
    Download(UBUNTU + "b/boost1.83/libboost-program-options1.83.0_1.83.0-2.1ubuntu3.2_amd64.deb", 320510,
             "9e7c21160a9cf2e8847b0789bba7a2b3301a4846f0f999270b41b424afb37559"),
)
UV = Download("https://github.com/astral-sh/uv/releases/download/0.13.9/uv-x86_64-unknown-linux-gnu.tar.gz",
              17068176, "a7fbaff2b9a271d85c1bdb540941090fd1ce011797b4abeb48e4dcd39c2471d5")

_RYZEN_LIB = "opt/amd/ryzenai/1.9.0/deployment/lib/"
_XRT_LIB = "opt/xilinx/xrt/lib/"
_COMPAT_LIB = "usr/lib/x86_64-linux-gnu/"
REQUIRED_FILES = {
    "runtime-1.9": (_RYZEN_LIB + "libonnxruntime.so.1", _RYZEN_LIB + "libonnxruntime_providers_vitisai.so"),
    "xrt-1.9": (_XRT_LIB + "libxrt_core.so.2.26.89", _XRT_LIB + "libxrt_driver_xdna.so.2.26.260102.59.release"),
    "sesr-env": ("bin/python", "lib/python3.12/site-packages/numpy/__init__.py",
                 "lib/python3.12/site-packages/onnx/__init__.py"),
    "ubuntu-compat": tuple(_COMPAT_LIB + name for name in (
        "libncurses.so.6", "libtinfo.so.6", "libboost_filesystem.so.1.83.0", "libboost_program_options.so.1.83.0",
    )),
}


def missing_components(root: Path) -> list[str]:
    missing = []
    for part, files in REQUIRED_FILES.items():
        try:
            if all((root / part / name).is_file() for name in files):
                continue
        except PermissionError:
            pass
        missing.append(part)
    return missing


def download_percent(root: Path, stage: str) -> int | None:
    asset = {"ryzen": RYZEN_AI, "xrt": XRT}.get(stage)
    if asset is None:
        return None
    cached = root / ".runtime-downloads" / asset.name
    for path in (cached, cached.with_suffix(cached.suffix + ".part")):
        try:
            return min(100, path.stat().st_size * 100 // asset.size)
        except OSError:
            continue
    return None


def _system_env() -> dict[str, str]:
    # Decky runs the plugin with a bundled Python. Host tools need the host's libraries.
    return {k: v for k, v in os.environ.items() if k not in {"LD_LIBRARY_PATH", "PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV"}}


def _run(command: list[str], *, timeout: int, env: dict[str, str] | None = None) -> None:
    result = subprocess.run(command, env=env or _system_env(), stdout=subprocess.DEVNULL,
                            stderr=subprocess.PIPE, text=True, timeout=timeout)
    if result.returncode:
        detail = result.stderr.strip().splitlines()[-1:] or [f"exit status {result.returncode}"]
        raise RuntimeError(f"{Path(command[0]).name}: {detail[0]}")


def _matches(path: Path, asset: Download) -> bool:
    if not path.is_file() or path.stat().st_size != asset.size:
        return False
    with path.open("rb") as source:
        digest = hashlib.sha256()
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
        return digest.hexdigest() == asset.sha256


def _download(root: Path, cache: Path, curl: str | None, asset: Download) -> Path:
    # Reuse original vendor packages from local installations or from an interrupted setup.
    cached = cache / asset.name
    for candidate in (root / asset.name, root.parent / "Downloads" / asset.name, cached):
        if _matches(candidate, asset):
            return candidate
    if curl is None:
        raise RuntimeError(f"curl is unavailable. Download {asset.name} from {asset.url} into ~/Downloads and retry.")
    partial = cached.with_suffix(cached.suffix + ".part")
    args = [curl, "--disable", "--fail", "--silent", "--show-error", "--location", "--proto", "=https",
            "--proto-redir", "=https", "--retry", "3", "--retry-max-time", "180", "--connect-timeout", "15",
            "--max-time", "1800", "--speed-limit", "1024", "--speed-time", "60",
            "--max-filesize", str(asset.size), "--output", str(partial)]
    try:
        if partial.is_file() and 0 < partial.stat().st_size < asset.size:
            try:
                _run([*args, "--continue-at", "-", asset.url], timeout=1900)
            except RuntimeError as exc:
                if "(33)" not in str(exc) and "416" not in str(exc):
                    raise
                _run([*args, asset.url], timeout=1900)
        else:
            _run([*args, asset.url], timeout=1900)
    except (RuntimeError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"Could not download {asset.name}. Download it from {asset.url} into ~/Downloads and retry. {exc}") from exc
    if not _matches(partial, asset):
        partial.unlink(missing_ok=True)
        raise RuntimeError(f"SHA-256 or size mismatch for {asset.name}")
    partial.replace(cached)
    return cached


def _unpack_deb(tar: str, deb: Path, dest: Path) -> None:
    members = subprocess.run([tar, "-tf", str(deb)], check=True, capture_output=True, text=True,
                             timeout=15, env=_system_env()).stdout.splitlines()
    data = [name for name in members if name in {"data.tar", "data.tar.zst", "data.tar.xz", "data.tar.gz"}]
    if len(data) != 1:
        raise RuntimeError(f"Could not locate the payload in {deb.name}")
    with subprocess.Popen([tar, "-xOf", str(deb), data[0]], stdout=subprocess.PIPE, env=_system_env()) as source:
        assert source.stdout is not None
        try:
            result = subprocess.run([tar, "-xf", "-", "--no-same-owner", "-C", str(dest)], stdin=source.stdout,
                                    stderr=subprocess.PIPE, text=True, env=_system_env(), timeout=300)
            source.stdout.close()
            status = source.wait(timeout=15)
        finally:
            if source.poll() is None:
                source.kill()
        if result.returncode or status:
            raise RuntimeError(f"Could not extract {deb.name}: {result.stderr.strip()}")


def _prepare_python(root: Path, stage: Path, asset: Path, dest: Path) -> None:
    uv = stage / "uv"
    with tarfile.open(asset) as archive, uv.open("wb") as target:
        source = archive.extractfile("uv-x86_64-unknown-linux-gnu/uv")
        if source is None:
            raise RuntimeError("uv executable is missing from its archive")
        with source:
            shutil.copyfileobj(source, target)
    uv.chmod(0o700)
    env = _system_env()
    env.update(UV_PYTHON_INSTALL_DIR=str(root / ".python"), UV_CACHE_DIR=str(root / ".uv-cache"))
    _run([str(uv), "--no-config", "venv", "--managed-python", "--python", "3.12.16", str(dest)], timeout=300, env=env)
    _run([str(uv), "--no-config", "pip", "install", "--only-binary", ":all:", "--index-url", "https://pypi.org/simple",
          "--python", str(dest / "bin/python"), "numpy==2.5.5", "onnx==1.23.2"], timeout=300, env=env)


def install_runtime(root: Path, report: Callable[[str], None]) -> None:
    missing = missing_components(root)
    if not missing:
        return
    if platform.machine() != "x86_64":
        raise RuntimeError("AMD Ryzen AI setup requires x86-64 Linux.")
    root.mkdir(parents=True, exist_ok=True)
    tar = shutil.which("bsdtar")
    if tar is None and any(part != "sesr-env" for part in missing):
        raise RuntimeError("bsdtar is unavailable. Install your distribution's libarchive utilities and retry.")
    cache = root / ".runtime-downloads"
    cache.mkdir(mode=0o700, exist_ok=True)
    curl = shutil.which("curl")
    with tempfile.TemporaryDirectory(prefix=".runtime-setup-", dir=root) as workdir:
        stage = Path(workdir)
        for part in missing:
            dest = stage / part
            if part == "sesr-env":
                report("python")
                _prepare_python(root, stage, _download(root, cache, curl, UV), dest)
                continue
            assert tar is not None
            dest.mkdir()
            if part == "runtime-1.9":
                report("ryzen")
                _unpack_deb(tar, _download(root, cache, curl, RYZEN_AI), dest)
            elif part == "xrt-1.9":
                report("xrt")
                with zipfile.ZipFile(_download(root, cache, curl, XRT)) as xrt:
                    for name in XRT_DEBS:
                        deb = stage / name
                        with xrt.open(name) as data, deb.open("wb") as out:
                            shutil.copyfileobj(data, out)
                        _unpack_deb(tar, deb, dest)
                        deb.unlink()
            else:
                report("compat")
                for asset in COMPAT:
                    _unpack_deb(tar, _download(root, cache, curl, asset), dest)
        unprepared = set(missing_components(stage)).intersection(missing)
        if unprepared:
            raise RuntimeError("Missing files after extraction: " + ", ".join(sorted(unprepared)))
        # Keep an existing partial installation available for recovery.
        for part in missing:
            final = root / part
            if final.exists() or final.is_symlink():
                backup = Path(tempfile.mkdtemp(prefix=".runtime-backup-", dir=root)) / part
                final.replace(backup)
                try:
                    (stage / part).replace(final)
                except OSError:
                    backup.replace(final)
                    raise
            else:
                (stage / part).replace(final)
    # The runtime is already installed. Don't retain the multi-gigabyte downloads.
    for asset in (RYZEN_AI, XRT, UV, *COMPAT):
        (cache / asset.name).unlink(missing_ok=True)
