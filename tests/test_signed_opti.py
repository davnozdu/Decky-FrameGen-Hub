import copy
from pathlib import Path
import struct
import unittest
import test_generators as fixtures
from signed_opti import has_certificate


def signed_dll():
    data=bytearray(1024);data[:2]=b'MZ';struct.pack_into('<I',data,0x3c,128)
    data[128:132]=b'PE\0\0';struct.pack_into('<H',data,152,0x20b)
    struct.pack_into('<II',data,152+112+32,768,16)
    return bytes(data)


class SignedOpti(unittest.TestCase):
    def setUp(self):
        fixtures.Generators.setUp(self)
        self.proxy=self.game/'dxgi.dll';self.proxy.write_bytes(b'original ANR loader')
        self.package=self.root/'package';self.package.mkdir();(self.package/'OptiScaler.dll').write_bytes(self.proxy.read_bytes())
        self.signed=self.root/'signed.dll';self.signed.write_bytes(signed_dll())
        (self.root/'amdxcffx64.dll').write_bytes(self.signed.read_bytes())
        self.p._package_dir=lambda *args:self.package
        self.p._signed_opti_source=lambda:self.signed
        self.p._official_opti_asset=lambda filename:self.signed
        self.p._gpu_is_rdna4=lambda:False
        self.p._local_fsr4_source=lambda:{'path':str(self.signed), 'hashes':{'amdxcffx64.dll':self.p._file_sha256(self.signed)}}
        state=self.p._load_state();state['games']['1'].update(proxy='dxgi.dll',mode='full',generator='lsfg',upscaler='fsr4lite',render_quality='quality')
        state['games']['2']={'name':'Working Forza','generator':'lsfg','upscaler':'fsr4lite'}
        state['lsfg_profiles']={'1':{'active_in':['Diablo IV.exe'],'multiplier':2},'2':{'active_in':['forza.exe'],'multiplier':2}}
        self.p._save_state(state)

    def test_enable_restore_preserves_fsr_lsfg_and_other_games(self):
        before=copy.deepcopy(self.p._load_state())
        result=self.p._set_signed_optiscaler('1',True)
        self.assertEqual(result['status'],'success');self.assertEqual(self.proxy.read_bytes(),self.signed.read_bytes())
        state=self.p._load_state();self.assertTrue(state['games']['1']['signed_optiscaler'])
        for key in ('upscaler','generator','render_quality'):self.assertEqual(state['games']['1'][key],before['games']['1'][key])
        self.assertEqual(state['games']['2'],before['games']['2']);self.assertEqual(state['lsfg_profiles'],before['lsfg_profiles'])
        self.p._set_signed_optiscaler('1',False)
        self.assertEqual(self.proxy.read_bytes(),b'original ANR loader')
        self.assertNotIn('signed_optiscaler',self.p._load_state()['games']['1'])

    def test_foreign_proxy_and_changed_fix_are_not_overwritten(self):
        self.proxy.write_bytes(b'user mod')
        with self.assertRaisesRegex(ValueError,'modified'):self.p._set_signed_optiscaler('1',True)
        self.assertEqual(self.proxy.read_bytes(),b'user mod')
        self.proxy.write_bytes(b'original ANR loader');self.p._set_signed_optiscaler('1',True)
        self.proxy.write_bytes(b'user changed installed proxy')
        with self.assertRaisesRegex(ValueError,'changed'):self.p._set_signed_optiscaler('1',False)
        self.assertEqual(self.proxy.read_bytes(),b'user changed installed proxy')

    def test_running_game_and_unsigned_replacement_are_rejected(self):
        self.running=True
        with self.assertRaisesRegex(ValueError,'Close'):self.p._set_signed_optiscaler('1',True)
        self.running=False;self.signed.write_bytes(b'unsigned')
        with self.assertRaisesRegex(ValueError,'certificate'):self.p._set_signed_optiscaler('1',True)
        self.assertEqual(self.proxy.read_bytes(),b'original ANR loader')

    def test_reinstall_uses_new_package_as_restore_point(self):
        self.p._set_signed_optiscaler('1',True)
        self.proxy.write_bytes(b'new ANR loader');(self.package/'OptiScaler.dll').write_bytes(b'new ANR loader')
        self.p._set_signed_optiscaler('1',True,reapply=True)
        self.assertEqual(self.proxy.read_bytes(),self.signed.read_bytes())
        self.p._set_signed_optiscaler('1',False);self.assertEqual(self.proxy.read_bytes(),b'new ANR loader')

    def test_certificate_parser_rejects_truncated_data(self):
        self.assertTrue(has_certificate(signed_dll()))
        self.assertFalse(has_certificate(signed_dll()[:700]));self.assertFalse(has_certificate(b'MZ'))

    def test_signed_fsr4_uses_sdk_and_force_int8_without_touching_forza(self):
        self.p._set_signed_optiscaler('1', True)
        before=copy.deepcopy(self.p._load_state())
        result=self.p._apply_upscaler('1',self.game,'fsr4',True)
        self.assertEqual(result['status'],'success')
        content=self.ini.read_text()
        for value in ('Dx12Upscaler=fsr31','UpscalerIndex=0','Fsr4ForceEnableInt8=true',
                      'Fsr4Update=false','Fsr4EnableWatermark=true','FfxDx12SRPath=Z:'):
            self.assertIn(value,content)
        self.assertNotIn('Fsr4GpuSupport=4',content)
        self.assertTrue((self.game/'OptiScaler/OfficialFSR4/amd_fidelityfx_upscaler_dx12.dll').exists())
        state=self.p._load_state()
        self.assertEqual(state['games']['2'],before['games']['2'])
        self.assertEqual(state['lsfg_profiles'],before['lsfg_profiles'])
        self.p._apply_upscaler('1',self.game,'fsr31',False)
        self.assertIn('UpscalerIndex=1',self.ini.read_text())
        self.assertIn('Fsr4ForceEnableInt8=false',self.ini.read_text())

    def test_sdk_foreign_file_is_preserved(self):
        folder=self.game/'OptiScaler/OfficialFSR4';folder.mkdir()
        foreign=folder/'amd_fidelityfx_upscaler_dx12.dll';foreign.write_bytes(b'user SDK')
        original_ini=self.ini.read_bytes()
        with self.assertRaisesRegex(ValueError,'not managed'):
            self.p._set_signed_optiscaler('1',True)
        self.assertEqual(foreign.read_bytes(),b'user SDK')
        self.assertEqual(self.proxy.read_bytes(),b'original ANR loader')
        self.assertEqual(self.ini.read_bytes(),original_ini)
        self.assertNotIn('signed_optiscaler',self.p._load_state()['games']['1'])

    def test_failed_sdk_save_restores_files_ini_and_profile(self):
        self.p._set_signed_optiscaler('1',True)
        before=copy.deepcopy(self.p._load_state());ini=self.ini.read_bytes()
        folder=self.game/'OptiScaler/OfficialFSR4'
        files={p.name:p.read_bytes() for p in folder.glob('*.dll')}
        real_save=self.p._save_state
        def fail_once(state):
            self.p._save_state=real_save
            raise OSError('disk full')
        self.p._save_state=fail_once
        with self.assertRaisesRegex(OSError,'disk full'):
            self.p._apply_upscaler('1',self.game,'fsr4',True)
        self.assertEqual(self.p._load_state(),before)
        self.assertEqual(self.ini.read_bytes(),ini)
        self.assertEqual({p.name:p.read_bytes() for p in folder.glob('*.dll')},files)
