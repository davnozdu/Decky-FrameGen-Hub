"""Two OptiScaler cores per game: one for ANR FG/XeFG, one for Lossless Scaling/off."""
import asyncio
import copy
import unittest
import test_nightly_opti as fixtures


class TwoCores(unittest.TestCase):
    def setUp(self):
        fixtures.NightlyOpti.setUp(self)
        fixtures.fixtures.fixtures.decky.HOME = str(self.root / 'home')
        self.p._lsfg_installed = lambda: True
        self.p._lsfg_write_config = lambda *a, **k: None
        self.p._lsfg_validate = lambda: (True, '')

    def mode(self, choice):
        return asyncio.run(self.p.set_generator_mode('1', choice))

    def test_generator_switch_swaps_core_and_remembers_each_group(self):
        other = copy.deepcopy(self.p._load_state()['games']['2'])
        asyncio.run(self.p.set_optiscaler_core('1', 'nightly', ''))
        self.assertEqual(self.p._load_state()['games']['1']['optiscaler_cores'], {'ls': 'nightly'})
        r = self.mode('anr')
        self.assertEqual(r['status'], 'success', r)
        self.assertIn('ANR package', r['message'])
        self.assertEqual(self.proxy.read_bytes(), b'original ANR loader')
        entry = self.p._load_state()['games']['1']
        self.assertEqual(entry['generator'], 'anr')
        self.assertNotIn('nightly_optiscaler', entry)
        r = self.mode('lsfg')
        self.assertEqual(r['status'], 'success', r)
        self.assertEqual(self.proxy.read_bytes(), self.nightly.read_bytes())
        entry = self.p._load_state()['games']['1']
        self.assertIn('nightly_optiscaler', entry)
        self.assertEqual(entry['upscaler'], 'fsr4lite')
        self.assertEqual(self.p._load_state()['games']['2'], other)

    def test_fg_core_choice_is_kept_separately(self):
        state = self.p._load_state(); state['games']['1']['generator'] = 'anr'; self.p._save_state(state)
        asyncio.run(self.p.set_optiscaler_core('1', 'signed', ''))
        self.assertEqual(self.p._load_state()['games']['1']['optiscaler_cores'], {'fg': 'signed'})
        self.mode('lsfg')  # no LS choice yet: the current core stays
        self.assertTrue(self.p._load_state()['games']['1'].get('signed_optiscaler'))
        asyncio.run(self.p.set_optiscaler_core('1', 'nightly', ''))
        self.mode('anr')
        entry = self.p._load_state()['games']['1']
        self.assertEqual(entry['optiscaler_cores'], {'fg': 'signed', 'ls': 'nightly'})
        self.assertEqual(self.proxy.read_bytes(), self.signed.read_bytes())

    def test_unchanged_core_is_not_reinstalled(self):
        asyncio.run(self.p.set_optiscaler_core('1', 'nightly', ''))
        self.p._set_optiscaler_core = lambda *a, **k: self.fail('core must not be reinstalled')
        self.assertEqual(self.mode('lsfg')['status'], 'success')
        self.assertEqual(self.mode('off')['status'], 'success')

    def test_signed_only_game_refuses_anr_without_touching_files(self):
        self.info['name'] = 'Diablo IV'
        self.nightly.write_bytes(fixtures.fixtures.signed_dll())
        asyncio.run(self.p.set_optiscaler_core('1', 'nightly', ''))
        before = copy.deepcopy(self.p._load_state()); proxy = self.proxy.read_bytes(); ini = self.ini.read_bytes()
        r = self.mode('anr')
        self.assertEqual(r['status'], 'error')
        self.assertIn('rejects unsigned', r['message'])
        self.assertEqual(self.p._load_state(), before)
        self.assertEqual(self.proxy.read_bytes(), proxy)
        self.assertEqual(self.ini.read_bytes(), ini)
        self.assertFalse(self.p._fg_available(self.info, before['games']['1']))


if __name__ == '__main__':
    unittest.main()
