import asyncio
import copy
import unittest
import test_generators as fixtures

class DxgiPolicy(unittest.TestCase):
    def setUp(self):
        fixtures.Generators.setUp(self)
        state=self.p._load_state()
        state['games']['1'].update(generator='lsfg',upscaler=None,render_quality=None,opti={},proxy='dxgi.dll',mode='full')
        state['games']['2']={'name':'Working Forza','generator':'lsfg','upscaler':'fsr4lite','proxy':'dxgi.dll','mode':'full','render_quality':'quality'}
        state['lsfg_profiles']={'1':{'active_in':['Diablo IV.exe'],'multiplier':2},'2':{'active_in':['forza.exe'],'multiplier':2}}
        self.p._save_state(state)
        self.line='WINEDLLOVERRIDES="dxgi=n,b;winhttp=n,b" STEAM_COMPAT_DATA_PATH="/prefix" %command% --exec="launch Fen"'

    def test_default_is_unchanged_and_opt_in_is_per_game(self):
        before=copy.deepcopy(self.p._load_state())
        self.assertTrue(self.p._optiscaler_required('1'))
        result=asyncio.run(self.p.set_dxgi_fix('1',True,self.line))
        self.assertEqual(result['status'],'success')
        self.assertIn('dxgi=b;winhttp=n,b',result['launch_options'])
        self.assertIn('--exec="launch Fen"',result['launch_options'])
        after=self.p._load_state()
        self.assertEqual(after['games']['2'],before['games']['2'])
        self.assertEqual(after['lsfg_profiles'],before['lsfg_profiles'])
        self.assertTrue(self.p._optiscaler_required('2'))
        disabled=asyncio.run(self.p.set_dxgi_fix('1',False,result['launch_options']))
        self.assertIn('dxgi=n,b',disabled['launch_options'])

    def test_all_upscalers_and_native_generators_keep_optiscaler(self):
        for upscaler in ('package','fsr31','fsr4','fsr4lite','xess'):
            state=self.p._load_state();state['games']['1'].update(upscaler=upscaler,dxgi_fix=True);self.p._save_state(state)
            before=self.p._load_state()
            self.assertTrue(self.p._optiscaler_required('1'),upscaler)
            result=asyncio.run(self.p.set_dxgi_fix('1',True,self.line))
            self.assertEqual(result['status'],'error',upscaler)
            self.assertEqual(self.p._load_state(),before)
        for generator in ('anr','xefg'):
            state=self.p._load_state();state['games']['1'].update(generator=generator,upscaler=None,dxgi_fix=True);self.p._save_state(state)
            self.assertTrue(self.p._optiscaler_required('1'),generator)
            result=asyncio.run(self.p.recommended_launch_options('1',self.line.replace('dxgi=n,b','dxgi=b')))
            self.assertIn('dxgi=n,b',result['launch_options'])

    def test_running_game_cannot_change_fix_or_launch_options(self):
        before=self.p._load_state();self.running=True
        result=asyncio.run(self.p.set_dxgi_fix('1',True,self.line))
        self.assertEqual(result['status'],'error');self.assertEqual(self.p._load_state(),before)

    def test_only_plugin_owned_builtin_override_is_removed(self):
        self.assertEqual(self.p._launch_without_override('WINEDLLOVERRIDES="dxgi=b;foo=b" %command%','dxgi.dll',True),'WINEDLLOVERRIDES="foo=b" %command%')
        self.assertEqual(self.p._launch_without_override('WINEDLLOVERRIDES="dxgi=b;foo=b" %command%','dxgi.dll'),'WINEDLLOVERRIDES="dxgi=b;foo=b" %command%')
