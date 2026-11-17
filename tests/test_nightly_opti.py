"""Per-game nightly selection, cross-core rollback and Lite configuration."""
import copy
import unittest
from unittest.mock import patch
import test_signed_opti as fixtures


class NightlyOpti(unittest.TestCase):
    def setUp(self):
        fixtures.SignedOpti.setUp(self)
        self.nightly = self.root / 'nightly.dll'
        self.nightly.write_bytes(b'MZ nightly with Fsr4Model')
        self.p._nightly_opti_source = lambda: self.nightly
        # Supply a complete driver pair without changing signed-core fixture state.
        sources = self.root / 'drivers'
        sources.mkdir()
        hashes = {}
        for name in self.p.FSR4_DLL_NAMES:
            path = sources / name
            path.write_bytes(('MZ-' + name).encode())
            hashes[name] = self.p._file_sha256(path)
        self.p._local_fsr4_source = lambda: {'path': str(sources / 'amdxcffx64.dll'), 'hashes': hashes}
        self.nightly = self.root / 'nightly.dll'
        self.nightly.write_bytes(b'MZ nightly with Fsr4Model')
        self.p._nightly_opti_source = lambda: self.nightly
        official = self.p._official_opti_asset
        self.p._official_opti_asset = lambda filename, **kwargs: self.nightly if kwargs.get('nightly') else official(filename)

    def test_nightly_selects_lite_and_preserves_generator_and_other_games(self):
        before = copy.deepcopy(self.p._load_state())
        self.p._set_optiscaler_core('1', 'nightly')
        state = self.p._load_state()
        self.assertEqual(self.proxy.read_bytes(), self.nightly.read_bytes())
        self.assertIn('nightly_optiscaler', state['games']['1'])
        self.assertNotIn('signed_optiscaler', state['games']['1'])
        for key in ('generator', 'render_quality', 'upscaler'):
            self.assertEqual(state['games']['1'][key], before['games']['1'][key])
        self.assertEqual(state['games']['2'], before['games']['2'])
        self.assertEqual(state['lsfg_profiles'], before['lsfg_profiles'])
        text = self.ini.read_text()
        for setting in ('Dx12Upscaler=ffx', 'Fsr4Model=3', 'Fsr4GpuSupport=4', 'FGInput=nofg'):
            self.assertIn(setting, text)
        self.p._apply_upscaler('1', self.game, 'fsr4lite', True)
        self.assertIn('Fsr4EnableWatermark=true', self.ini.read_text())

    def test_switching_cores_keeps_original_backup(self):
        for core in ('signed', 'nightly', 'signed', 'nightly', 'package'):
            self.assertEqual(self.p._set_optiscaler_core('1', core)['status'], 'success')
        self.assertEqual(self.proxy.read_bytes(), b'original ANR loader')
        entry = self.p._load_state()['games']['1']
        self.assertNotIn('signed_optiscaler', entry)
        self.assertNotIn('nightly_optiscaler', entry)

    def test_failed_lite_apply_restores_core_profile_ini_and_backup(self):
        self.p._set_optiscaler_core('1', 'signed')
        before = copy.deepcopy(self.p._load_state())
        ini = self.ini.read_bytes()
        proxy = self.proxy.read_bytes()
        with patch.object(self.p, '_set_ini_sections', side_effect=OSError('disk full')):
            with self.assertRaisesRegex(OSError, 'disk full'):
                self.p._set_optiscaler_core('1', 'nightly')
        self.assertEqual(self.p._load_state(), before)
        self.assertEqual(self.ini.read_bytes(), ini)
        self.assertEqual(self.proxy.read_bytes(), proxy)
        self.assertFalse((self.game / 'OptiScaler/amdxcffx64.dll').exists())
        self.p._set_optiscaler_core('1', 'package')
        self.assertEqual(self.proxy.read_bytes(), b'original ANR loader')

    def test_modified_nightly_cannot_be_switched_or_restored(self):
        self.p._set_optiscaler_core('1', 'nightly')
        self.proxy.write_bytes(b'foreign DLL')
        for core in ('package', 'signed'):
            with self.assertRaisesRegex(ValueError, 'changed'):
                self.p._set_optiscaler_core('1', core)
            self.assertEqual(self.proxy.read_bytes(), b'foreign DLL')

    def test_reinstall_uses_new_package_as_restore_point(self):
        self.p._set_optiscaler_core('1', 'nightly')
        self.proxy.write_bytes(b'updated ANR core')
        (self.package / 'OptiScaler.dll').write_bytes(self.proxy.read_bytes())
        self.p._set_optiscaler_core('1', 'nightly', reapply=True)
        self.p._set_optiscaler_core('1', 'package')
        self.assertEqual(self.proxy.read_bytes(), b'updated ANR core')

    def test_failed_download_keeps_existing_install(self):
        before = copy.deepcopy(self.p._load_state())
        with patch.object(self.p, '_nightly_opti_source', side_effect=OSError('network down')):
            with self.assertRaisesRegex(OSError, 'network down'):
                self.p._set_optiscaler_core('1', 'nightly')
        self.assertEqual(self.proxy.read_bytes(), b'original ANR loader')
        self.assertEqual(self.p._load_state(), before)

    def test_nightly_and_anr_xefg_are_mutually_exclusive(self):
        import asyncio
        for generator in ('anr', 'xefg'):
            state = self.p._load_state()
            state['games']['1']['generator'] = generator
            self.p._save_state(state)
            with self.assertRaisesRegex(ValueError, 'requires Lossless'):
                self.p._set_optiscaler_core('1', 'nightly')
            self.assertEqual(self.proxy.read_bytes(), b'original ANR loader')
        state['games']['1']['generator'] = 'lsfg'
        self.p._save_state(state)
        self.p._set_optiscaler_core('1', 'nightly')
        before = copy.deepcopy(self.p._load_state())
        for generator in ('anr', 'xefg'):
            # The low-level call still refuses; set_generator_mode swaps the core first (test_two_cores).
            with self.assertRaisesRegex(ValueError, 'require the package core'):
                self.p._apply_generator('1', generator)
        self.assertEqual(self.p._load_state(), before)

    def test_update_only_replaces_selected_core_and_can_restore_original(self):
        import json
        self.p._set_optiscaler_core('1', 'nightly')
        before = copy.deepcopy(self.p._load_state())
        self.nightly.write_bytes(b'MZ updated nightly')
        release = {'tag_name': 'nightly-20261116', 'assets': [{
            'name': 'OptiScaler_v10.0.0-pre1_20261116.7z',
            'digest': 'sha256:' + 'a' * 64,
            'browser_download_url': 'https://github.com/optiscaler/OptiScaler-nightly/releases/download/nightly-20261116/core.7z',
        }]}
        self.p._http_get = lambda url: json.dumps([release]).encode()
        self.p._update_nightly_optiscaler('1')
        after = self.p._load_state()
        self.assertEqual(after['games']['2'], before['games']['2'])
        self.assertEqual(after['lsfg_profiles'], before['lsfg_profiles'])
        self.assertEqual(after['games']['1']['nightly_optiscaler']['version'], 'nightly-20261116')
        self.assertEqual(self.proxy.read_bytes(), b'MZ updated nightly')
        self.p._set_optiscaler_core('1', 'package')
        self.assertEqual(self.proxy.read_bytes(), b'original ANR loader')

    def test_update_rejects_missing_digest_without_writing(self):
        import json
        self.p._set_optiscaler_core('1', 'nightly')
        before = copy.deepcopy(self.p._load_state())
        self.p._http_get = lambda url: json.dumps([{'tag_name': 'nightly-20261116', 'assets': [{
            'name': 'OptiScaler_v10.0.0-pre1_20261116.7z', 'browser_download_url': 'https://example.com/core.7z',
        }]}]).encode()
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            self.p._update_nightly_optiscaler('1')
        self.assertEqual(self.p._load_state(), before)
        self.assertEqual(self.proxy.read_bytes(), self.nightly.read_bytes())

    def test_diablo_rejects_unsigned_nightly_before_replacing_files(self):
        self.info['name'] = 'Diablo IV'
        before = copy.deepcopy(self.p._load_state())
        ini = self.ini.read_bytes()
        with self.assertRaisesRegex(ValueError, 'requires a signed'):
            self.p._set_optiscaler_core('1', 'nightly')
        self.assertEqual(self.proxy.read_bytes(), b'original ANR loader')
        self.assertEqual(self.ini.read_bytes(), ini)
        self.assertEqual(self.p._load_state(), before)

    def test_diablo_accepts_future_signed_nightly(self):
        self.info['name'] = 'Diablo IV'
        self.nightly.write_bytes(fixtures.signed_dll())
        self.assertEqual(self.p._set_optiscaler_core('1', 'nightly')['status'], 'success')

    def test_cached_local_signature_is_verified_before_reuse(self):
        import json
        from signed_opti import NIGHTLY_VERSION, NIGHTLY_SHA256
        folder = self.p._runtime_dir() / 'local-signed-optiscaler' / NIGHTLY_VERSION
        folder.mkdir(parents=True)
        source = folder / 'OptiScaler.dll'
        source.write_bytes(fixtures.signed_dll())
        (folder / 'signature.json').write_text(json.dumps({
            'archive_sha256': NIGHTLY_SHA256, 'sha256': self.p._file_sha256(source),
        }))
        self.assertEqual(type(self.p)._nightly_opti_source(self.p), source)
        source.write_bytes(b'changed file')
        with self.assertRaisesRegex(ValueError, 'changed'):
            type(self.p)._nightly_opti_source(self.p)
