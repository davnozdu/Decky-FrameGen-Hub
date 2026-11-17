"""DXGI hook workaround preserves the active core, Lite and generator profiles."""
import asyncio
import copy
import unittest
import test_generators as fixtures


class DxgiSpoofingFix(unittest.TestCase):
    def setUp(self):
        fixtures.Generators.setUp(self)
        state = self.p._load_state()
        state['games']['1'].update(generator='lsfg', upscaler='fsr4lite', nightly_optiscaler={'version': '10-test'})
        state['games']['2'] = {'name': 'Forza', 'upscaler': 'fsr4lite'}
        state['lsfg_profiles'] = {'1': {'multiplier': 2}, '2': {'multiplier': 2}}
        self.p._save_state(state)

    def test_toggle_preserves_lite_core_other_games_and_lsfg(self):
        before = copy.deepcopy(self.p._load_state())
        for value in ('false', 'auto'):
            result = asyncio.run(self.p.set_opti_setting('1', 'dxgi_spoofing', value))
            self.assertEqual(result['status'], 'success', result)
            self.assertEqual(self.p._read_ini_sections(self.ini)[('Spoofing', 'Dxgi')], value)
            state = self.p._load_state()
            for key in ('upscaler', 'generator', 'nightly_optiscaler'):
                self.assertEqual(state['games']['1'][key], before['games']['1'][key])
            self.assertEqual(state['games']['2'], before['games']['2'])
            self.assertEqual(state['lsfg_profiles'], before['lsfg_profiles'])

    def test_running_game_blocks_hook_change(self):
        self.running = True
        before = self.p._load_state()
        ini = self.ini.read_bytes()
        result = asyncio.run(self.p.set_opti_setting('1', 'dxgi_spoofing', 'false'))
        self.assertEqual(result['status'], 'error')
        self.assertEqual(self.p._load_state(), before)
        self.assertEqual(self.ini.read_bytes(), ini)
