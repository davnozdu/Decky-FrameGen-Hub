"""NPU upscaling toggle: only edits the per-AppId list and starts the user service; never touches game files."""
import asyncio
import json
import os
import socket
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import test_generators as fixtures
import npusr
from npusr_runtime import REQUIRED_FILES, install_runtime


class NpuSr(unittest.TestCase):
    def setUp(self):
        fixtures.Generators.setUp(self)
        self.home = self.root / "home"
        self.p._home = lambda: self.home
        self.calls = []
        self.p._npusr_systemctl = lambda *a: (self.calls.append(a), (0, "active"))[1]
        self.manifest = self.root / "VkLayer_zz_npu_sr.json"
        patcher = patch.object(npusr, "NPUSR_MANIFESTS", (self.manifest,))
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("XDG_CONFIG_HOME", None)

    def install(self):
        root = self.home / "AsusNPU"
        dest = root / "npu-sr"
        (dest / "models").mkdir(parents=True)
        for path in npusr.NPUSR_PACKAGE_FILES:
            (dest / path).touch()
        (dest / "models" / "npu_flow_test.onnx").touch()  # package marker, ignored by selectable SR models
        self.manifest.write_text(json.dumps({"layer": {"library_path": str(dest / "libVkLayer_npu_sr.so")}}))
        for part, files in REQUIRED_FILES.items():
            for name in files:
                marker = root / part / name
                marker.parent.mkdir(parents=True, exist_ok=True)
                marker.touch()
        patcher = patch.object(npusr, "_ryzen_npu_state", return_value="ready")
        patcher.start()
        self.addCleanup(patcher.stop)
        unit = self.home / ".config/systemd/user/npu-sr.service"
        unit.parent.mkdir(parents=True)
        unit.write_text("[Service]\n")

    def apps(self):
        return (self.home / ".config/npu-sr/enabled-apps").read_text().split()

    def test_missing_components_refuse_enable_and_list_what_is_missing(self):
        st = asyncio.run(self.p.get_npu_sr("1"))
        self.assertFalse(st["available"])
        self.assertEqual(st["missing"], ["Vulkan layer", "layer manifest", "NPU service"])
        r = asyncio.run(self.p.set_npu_sr("1", True))
        self.assertEqual(r["status"], "error")
        self.assertFalse((self.home / ".config/npu-sr/enabled-apps").exists())

    def test_enable_disable_keeps_other_games_and_game_files(self):
        self.install()
        lst = self.home / ".config/npu-sr/enabled-apps"
        lst.parent.mkdir(parents=True)
        lst.write_text("1174180  # rdr2\n")
        before = {p: p.read_bytes() for p in self.game.rglob("*") if p.is_file()}
        r = asyncio.run(self.p.set_npu_sr("1", True))
        self.assertEqual(r["status"], "success")
        self.assertEqual(self.apps(), ["1174180", "1"])
        self.assertIn(("enable", "--now", "npu-sr.service"), self.calls)
        self.assertTrue(asyncio.run(self.p.get_npu_sr("1"))["enabled"])
        asyncio.run(self.p.set_npu_sr("1", True))  # idempotent
        self.assertEqual(self.apps(), ["1174180", "1"])
        asyncio.run(self.p.set_npu_sr("1", False))
        self.assertEqual(self.apps(), ["1174180"])
        self.assertEqual({p: p.read_bytes() for p in self.game.rglob("*") if p.is_file()}, before)

    def test_live_stats_only_for_a_running_process(self):
        self.install()
        stats = self.home / ".cache/npu-sr/stats.json"
        stats.parent.mkdir(parents=True)
        stats.write_text(json.dumps({"pid": os.getpid(), "in": "1280x720", "out": "1920x1080", "npu_ms": 6.7, "connected": True}))
        self.assertEqual(asyncio.run(self.p.get_npu_sr("1"))["live"]["npu_ms"], 6.7)
        stats.write_text(json.dumps({"pid": 2 ** 22 + 12345, "npu_ms": 6.7}))
        self.assertIsNone(asyncio.run(self.p.get_npu_sr("1"))["live"])

    def test_launch_options_added_and_removed_without_touching_the_rest(self):
        L = self.p._npusr_launch
        env = npusr.NPUSR_LAUNCH_ENV
        self.assertEqual(L("", True), f"{env} %command%")
        self.assertEqual(L("", False), "")
        line = 'WINEDLLOVERRIDES="dxgi=n,b" PROTON_LOG=1 %command% -skip'
        on = L(line, True)
        self.assertEqual(on, f'{env} WINEDLLOVERRIDES="dxgi=n,b" PROTON_LOG=1 %command% -skip')
        self.assertEqual(L(on, True), on)  # idempotent
        self.assertEqual(L(on, False), line)
        self.assertEqual(L(f"{env} %command%", False), "")
        self.assertEqual(L("-windowed", True), f"{env} %command% -windowed")
        # Wrapper before %command% (Battle.net via Grip Deck): the env must not become the wrapper's argument.
        wrapped = 'WINEDLLOVERRIDES="dxgi=n,b" bash "/x/grip-deck-launch" %command% --exec="launch Fen"'
        self.assertEqual(L(wrapped, True), f"{env} {wrapped}")
        broken = f'WINEDLLOVERRIDES="dxgi=n,b" bash "/x/grip-deck-launch" {env} %command% --exec="launch Fen"'
        self.assertEqual(L(broken, True), f"{env} {wrapped}")  # repairs the old placement

    def test_enable_returns_launch_options(self):
        self.install()
        r = asyncio.run(self.p.set_npu_sr("1", True, "%command% -dx12"))
        self.assertEqual(r["launch_options"], f"{npusr.NPUSR_LAUNCH_ENV} %command% -dx12")
        r = asyncio.run(self.p.set_npu_sr("1", False, r["launch_options"]))
        self.assertEqual(r["launch_options"], "%command% -dx12")

    def test_models_catalog_and_switch(self):
        self.install()
        models = self.home / "AsusNPU/npu-sr/models"
        models.mkdir(exist_ok=True)
        for name in ("a_u8.onnx", "b_u8.onnx", "junk_u8.onnx"):
            (models / name).write_bytes(b"onnx")
        (models / "archive").mkdir()
        (models / "archive/old_u8.onnx").write_bytes(b"onnx")
        (models / "catalog.json").write_text(json.dumps({"b_u8.onnx": {"label": "Fast", "order": 1},
                                                         "junk_u8.onnx": {"hidden": True}}))
        st = asyncio.run(self.p.get_npu_sr("1"))
        self.assertEqual([m["file"] for m in st["models"]], ["b_u8.onnx", "a_u8.onnx"])
        self.assertEqual(st["models"][0]["label"], "Fast")
        self.assertEqual(asyncio.run(self.p.set_npu_sr_model("archive/old_u8.onnx"))["status"], "error")
        self.assertEqual(asyncio.run(self.p.set_npu_sr_model("a_u8.onnx"))["status"], "success")
        self.assertEqual(asyncio.run(self.p.get_npu_sr("1"))["model"], "a_u8.onnx")
        self.assertIn(("restart", "npu-sr.service"), self.calls)

    def test_native_aa_render_quality_writes_ratio_one(self):
        self.assertEqual(self.p.RENDER_QUALITY["native"][1], 1.0)
        ini = self.ini
        r = self.p._apply_render_quality("1", self.game, "native")
        self.assertEqual(r["status"], "success")
        text = ini.read_text()
        self.assertIn("UpscaleRatioOverrideEnabled=true", text)
        self.assertIn("UpscaleRatioOverrideValue=1.0", text)


class Fsr4LiteCore(unittest.TestCase):
    """FSR 4 Lite needs a Lite-capable OptiScaler core (signed 0.9.5 or Nightly)."""
    def setUp(self):
        fixtures.Generators.setUp(self)
        self.switched = []
        self.p._set_optiscaler_core = lambda appid, core, **k: self.switched.append(core)
        self.p._apply_upscaler = lambda appid, target, choice, wm: {"status": "success", "message": f"Upscaler: {choice}."}
        self.p._resolve_target = lambda game, entry: self.game

    def entry(self, **kw):
        state = self.p._load_state(); state["games"]["1"].update(proxy="dxgi.dll", mode="full", **kw); self.p._save_state(state)

    def test_lite_with_anr_fg_is_refused(self):
        self.entry(generator="anr")
        r = asyncio.run(self.p.set_upscaler("1", "fsr4lite"))
        self.assertEqual(r["status"], "error")
        self.assertIn("0.9.5", r["message"])
        self.assertEqual(self.switched, [])

    def test_lite_without_fg_switches_to_signed_095(self):
        self.entry(generator="off")
        r = asyncio.run(self.p.set_upscaler("1", "fsr4lite"))
        self.assertEqual(r["status"], "success")
        self.assertEqual(self.switched, ["signed095"])
        self.assertIn("0.9.5-pre5", r["message"])

    def test_lite_on_lite_core_does_not_switch(self):
        self.entry(generator="lsfg", signed_optiscaler={"version": "0.9.5-pre5-20261111"})
        r = asyncio.run(self.p.set_upscaler("1", "fsr4lite"))
        self.assertEqual(r["status"], "success")
        self.assertEqual(self.switched, [])

    def test_vulkan_upscaler_values(self):
        self.assertEqual(self.p._upscaler_values("fsr4", False)[("Upscalers", "VulkanUpscaler")], "auto")
        self.assertEqual(self.p._upscaler_values("fsr31", False)[("Upscalers", "VulkanUpscaler")], "auto")


class UpscalerOff(unittest.TestCase):
    def setUp(self):
        fixtures.Generators.setUp(self)

    def test_off_resets_ratio_and_marks_state(self):
        self.ini.write_text(self.ini.read_text() + "\n[UpscaleRatio]\nUpscaleRatioOverrideEnabled=true\nUpscaleRatioOverrideValue=1.5\n[FSR]\nFsr4Model=3\n")
        state = self.p._load_state(); state["games"]["1"].update(upscaler="fsr4lite", render_quality="quality", generator="off"); self.p._save_state(state)
        r = self.p._apply_upscaler_off("1", self.ini)
        self.assertEqual(r["status"], "success")
        self.assertIn("OptiScaler is not needed", r["message"])
        text = self.ini.read_text()
        self.assertIn("UpscaleRatioOverrideEnabled=auto", text)
        self.assertIn("Fsr4Model=auto", text)
        e = self.p._load_state()["games"]["1"]
        self.assertEqual((e["upscaler"], e["render_quality"]), ("off", None))
        self.assertIn("off", self.p.UPSCALERS)


if __name__ == "__main__":
    unittest.main()


class NpuPackage(unittest.TestCase):
    """Private NPU package ZIP: verified by SHA-256, only listed files, installed under ~/AsusNPU/npu-sr."""

    def setUp(self):
        NpuSr.setUp(self)

    def make_zip(self, extra=None, corrupt=False):
        import hashlib
        import zipfile
        files = {n: f"#{n}\n".encode() for n in npusr.NPUSR_PACKAGE_FILES}
        files["VkLayer_zz_npu_sr.json"] = json.dumps({"layer": {"library_path": "/home/other/x.so"}}).encode()
        files["models/m1.onnx"] = b"onnx"
        files["models/catalog.json"] = json.dumps({"m1.onnx": {"order": 1, "label": "Fast"}}).encode()
        manifest = {"name": "npu-sr", "version": "1.0", "files": {n: {"sha256": hashlib.sha256(d).hexdigest()} for n, d in files.items()}}
        if corrupt:
            files["npu-sr-service"] = b"tampered"
        path = self.root / "pkg.zip"
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("manifest.json", json.dumps(manifest))
            for n, d in {**files, **(extra or {})}.items():
                z.writestr(n, d)
        return path

    def test_import_installs_files_rewrites_layer_path_and_selects_first_model(self):
        r = asyncio.run(self.p.import_npu_package(str(self.make_zip())))
        self.assertEqual(r["status"], "success", r)
        d = self.home / "AsusNPU/npu-sr"
        self.assertTrue(os.access(d / "npu-sr-service", os.X_OK))
        self.assertEqual(json.loads((d / "VkLayer_zz_npu_sr.json").read_text())["layer"]["library_path"],
                         str(d / "libVkLayer_npu_sr.so"))
        self.assertTrue((self.home / ".config/systemd/user/npu-sr.service").is_file())
        self.assertIn("m1.onnx", (self.home / ".config/environment.d/npu-sr.conf").read_text())
        self.assertIn(("daemon-reload",), self.calls)

    def test_tampered_or_unlisted_files_are_rejected(self):
        r = asyncio.run(self.p.import_npu_package(str(self.make_zip(corrupt=True))))
        self.assertEqual(r["status"], "error")
        self.assertIn("Checksum", r["message"])
        r = asyncio.run(self.p.import_npu_package(str(self.make_zip(extra={"../evil.sh": b"x"}))))
        self.assertEqual(r["status"], "error")
        self.assertFalse((self.home / "AsusNPU/npu-sr").exists())

    def test_not_a_zip(self):
        bad = self.root / "x.zip"
        bad.write_text("nope")
        self.assertEqual(asyncio.run(self.p.import_npu_package(str(bad)))["message"], "Not a valid NPU package ZIP.")


class NpuBlocksPatch(unittest.TestCase):
    def setUp(self):
        NpuSr.setUp(self)

    def test_install_hub_is_refused_while_npu_mode_is_on(self):
        NpuSr.install(self)
        asyncio.run(self.p.set_npu_sr("1", True, ""))
        r = self.p._patch("1", "", "")
        self.assertEqual(r["status"], "error")
        self.assertIn("NPU mode", r["message"])


class NpuSetup(unittest.TestCase):
    setUp = NpuPackage.setUp
    make_zip = NpuPackage.make_zip
    def test_setup_prepares_runtime_package_and_service_in_order(self):
        sock = self.home / ".cache/npu-sr/npu-sr.sock"
        sock.parent.mkdir(parents=True)
        archive = self.make_zip()
        calls = []
        def prepare(root, progress):
            self.assertEqual(root, self.home / "AsusNPU")
            calls.append("runtime")
        def download(*, start_service):
            self.assertFalse(start_service)
            calls.append("package")
            return self.p._npusr_import_package(str(archive), start_service=False)
        def start():
            calls.append("service")
            ready.bind(str(sock))
        with socket.socket(socket.AF_UNIX) as ready, patch.object(npusr, "_ryzen_npu_state", return_value="ready"), \
             patch.object(npusr, "install_runtime", side_effect=prepare), \
             patch.object(self.p, "_npusr_install_from_github", side_effect=download), \
             patch.object(self.p, "_npusr_start_service", side_effect=start):
            asyncio.run(self.p._npusr_run_setup(False))
        self.assertEqual(calls, ["runtime", "package", "service"])
        self.assertEqual(self.p._npusr_setup_progress["stage"], "ready")
        self.assertTrue(self.p._npusr_user_manifest().is_file())

    def test_without_driver_setup_gives_help_without_downloading(self):
        with patch.object(npusr, "_ryzen_npu_state", return_value="driver"), patch.object(npusr, "install_runtime") as install:
            result = asyncio.run(self.p.install_npu_from_github())
        self.assertEqual(result["status"], "error")
        self.assertIn("sudo modprobe amdxdna", result["message"])
        install.assert_not_called()

    def test_startup_continues_online_if_offline_bundle_is_unreadable(self):
        bundle = self.root / "offline.zip"
        bundle.write_text("not a zip")
        with patch.object(npusr, "_ryzen_npu_state", return_value="ready"), \
             patch.object(npusr.asyncio, "sleep", new_callable=AsyncMock), \
             patch.object(self.p, "_local_fsr4_source", return_value=None), \
             patch.object(self.p, "_lsfg_dll", return_value=None), \
             patch.object(self.p, "_find_local_bundle", return_value=bundle), \
             patch.object(self.p, "_npusr_request_setup") as setup:
            asyncio.run(self.p._npusr_auto_bootstrap())
        setup.assert_called_once_with()

    def test_existing_runtime_needs_no_download(self):
        NpuSr.install(self)
        with patch("npusr_runtime._download") as download:
            install_runtime(self.home / "AsusNPU", lambda stage: None)
        download.assert_not_called()

    def test_service_permission_error_gives_command_for_konsole(self):
        with patch.object(self.p, "_npusr_systemctl", return_value=(1, "Access denied")):
            with self.assertRaisesRegex(RuntimeError, "systemctl --user daemon-reload in Konsole"):
                self.p._npusr_start_service()

    def test_rootless_layer_follows_system_layers_and_keeps_custom_path(self):
        self.p._npusr_import_package(str(self.make_zip()), start_service=False)
        ordered = self.p._npusr_ordered_layer_env()
        self.assertLess(ordered.index("/usr/share/vulkan/implicit_layer.d"), ordered.index(str(self.p._npusr_user_manifest().parent)))
        enabled = self.p._npusr_launch("FOO=bar %command% -dx12", True)
        self.assertIn(ordered, enabled)
        self.assertEqual(self.p._npusr_launch(enabled, False), "FOO=bar %command% -dx12")
        custom = "VK_IMPLICIT_LAYER_PATH=/custom %command%"
        self.assertNotIn(ordered, self.p._npusr_launch(custom, True))


class NpuX2Models(unittest.TestCase):
    def setUp(self):
        NpuSr.setUp(self)
        NpuSr.install(self)
        m = self.home / "AsusNPU/npu-sr/models"
        m.mkdir(parents=True, exist_ok=True)
        for n in ("c16l4g3_qat_s2d_360x640x4_u8.onnx", "c32l6x2_qat_s2d_288x512x4_u8.onnx"):
            (m / n).write_bytes(b"x")

    def test_lists_are_separate_and_switching_keeps_the_other_mode(self):
        st = asyncio.run(self.p.get_npu_sr("1"))
        self.assertEqual([x["file"] for x in st["models"]], ["c16l4g3_qat_s2d_360x640x4_u8.onnx"])
        self.assertEqual([x["file"] for x in st["models_x2"]], ["c32l6x2_qat_s2d_288x512x4_u8.onnx"])
        self.assertEqual(asyncio.run(self.p.set_npu_sr_model("c16l4g3_qat_s2d_360x640x4_u8.onnx"))["status"], "success")
        self.assertEqual(asyncio.run(self.p.set_npu_sr_model("c32l6x2_qat_s2d_288x512x4_u8.onnx"))["status"], "success")
        conf = (self.home / ".config/environment.d/npu-sr.conf").read_text()
        self.assertIn("NPU_SR_MODEL=", conf)
        self.assertIn("NPU_SR_MODEL_X2=", conf)
        st = asyncio.run(self.p.get_npu_sr("1"))
        self.assertEqual(st["model_x2"], "c32l6x2_qat_s2d_288x512x4_u8.onnx")
        self.assertEqual(st["model"], "c16l4g3_qat_s2d_360x640x4_u8.onnx")
