"""Signed stable-branch Lite uses its own model-selection key."""
import copy
import unittest
import test_nightly_opti as fixtures


class Signed095(unittest.TestCase):
    def setUp(self):
        fixtures.NightlyOpti.setUp(self)
        self.p._signed_lite_opti_source = lambda: self.signed

    def test_signed095_lite_uses_driver_and_numeric_legacy_model(self):
        before = copy.deepcopy(self.p._load_state())
        result = self.p._set_optiscaler_core('1', 'signed095')
        self.assertEqual(result['status'], 'success')
        values = self.p._read_ini_sections(self.ini)
        for key, val in {'Fsr4ForceEnableInt8': '3', 'Fsr4Update': 'true', 'Fsr4Model': 'auto', 'Fsr4GpuSupport': 'auto'}.items():
            self.assertEqual(values[('FSR', key)], val)
        self.assertEqual(values[('Upscalers', 'Dx12Upscaler')], 'fsr31')
        self.assertEqual(values[('FrameGen', 'FGInput')], 'nofg')
        self.assertTrue(values[('Libraries', 'OptiDllPath')].startswith('Z:'))
        self.assertEqual(self.p._optiscaler_main_dir(self.ini).resolve(), (self.game / 'OptiScaler').resolve())
        state = self.p._load_state()
        self.assertTrue(state['games']['1']['signed_optiscaler']['version'].startswith('0.9.5'))
        self.assertEqual(state['games']['2'], before['games']['2'])
        self.assertEqual(state['lsfg_profiles'], before['lsfg_profiles'])
        self.assertEqual(self.p._apply_upscaler('1', self.game, 'fsr4lite', True)['status'], 'success')
        self.assertEqual(self.p._read_ini_sections(self.ini)[('FSR', 'Fsr4EnableWatermark')], 'true')
        with self.assertRaisesRegex(ValueError, 'require the package core'):
            self.p._apply_generator('1', 'anr')

    def test_signed095_preserves_original_restore_point(self):
        self.p._set_optiscaler_core('1', 'nightly')
        self.p._set_optiscaler_core('1', 'signed095')
        self.p._set_optiscaler_core('1', 'signed')
        self.p._set_optiscaler_core('1', 'package')
        self.assertEqual(self.proxy.read_bytes(), b'original ANR loader')
