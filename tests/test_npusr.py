"""NPU upscaling toggle: only edits the per-AppId list and starts the user service; never touches game files."""
import asyncio
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

import test_generators as fixtures
import npusr


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
        (self.home / "AsusNPU/npu-sr").mkdir(parents=True)
        (self.home / "AsusNPU/npu-sr/libVkLayer_npu_sr.so").write_bytes(b"ELF")
        self.manifest.write_text("{}")
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
        self.assertEqual(on, f'WINEDLLOVERRIDES="dxgi=n,b" PROTON_LOG=1 {env} %command% -skip')
        self.assertEqual(L(on, True), on)  # idempotent
        self.assertEqual(L(on, False), line)
        self.assertEqual(L(f"{env} %command%", False), "")
        self.assertEqual(L("-windowed", True), f"{env} %command% -windowed")

    def test_enable_returns_launch_options(self):
        self.install()
        r = asyncio.run(self.p.set_npu_sr("1", True, "%command% -dx12"))
        self.assertEqual(r["launch_options"], f"{npusr.NPUSR_LAUNCH_ENV} %command% -dx12")
        r = asyncio.run(self.p.set_npu_sr("1", False, r["launch_options"]))
        self.assertEqual(r["launch_options"], "%command% -dx12")

    def test_models_catalog_and_switch(self):
        self.install()
        models = self.home / "AsusNPU/npu-sr/models"
        models.mkdir()
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


if __name__ == "__main__":
    unittest.main()
