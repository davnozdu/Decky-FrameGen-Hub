import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "py_modules"))
import nsl_vdf
from nsl_games import external_games

class ExternalGames(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.shortcut = self.root / "userdata/1/config/shortcuts.vdf"
        self.shortcut.parent.mkdir(parents=True)
        self.game = self.root / "My Game"
        self.game.mkdir()
        (self.game / "Game.exe").touch()

    def save(self, exe, options="", name="My Game"):
        self.shortcut.write_bytes(nsl_vdf.binary_dumps({"shortcuts": {"0": {
            "appid": -123, "appname": name, "exe": exe, "LaunchOptions": options}}}))

    def test_direct_game_uses_unsigned_id_and_does_not_modify_shortcut(self):
        self.save(f'"{self.game}/Game.exe"', 'WINEDLLOVERRIDES="dxgi=n,b" %command%')
        before = self.shortcut.read_bytes()
        games = external_games([self.root])
        self.assertEqual(games[0]["appid"], str(2**32 - 123))
        self.assertEqual(games[0]["install_path"], str(self.game.resolve()))
        self.assertEqual(self.shortcut.read_bytes(), before)
        self.assertEqual(external_games([self.root], "123"), [])

    def test_epic_launcher_resolves_game_folder_not_launcher(self):
        prefix = self.root / "prefix"
        launcher = prefix / "pfx/drive_c/Epic/EpicGamesLauncher.exe"
        launcher.parent.mkdir(parents=True)
        launcher.touch()
        manifests = prefix / "pfx/drive_c/ProgramData/Epic/EpicGamesLauncher/Data/Manifests"
        manifests.mkdir(parents=True)
        (manifests / "game.item").write_text(json.dumps({"DisplayName":"My Game", "InstallLocation":"Z:"+str(self.game)}))
        self.save(f'"{launcher}"', f'STEAM_COMPAT_DATA_PATH="{prefix}" %command%')
        self.assertEqual(external_games([self.root])[0]["install_path"], str(self.game.resolve()))
        (manifests / "game.item").unlink()
        self.assertEqual(external_games([self.root]), [])

    def test_missing_executable_is_not_offered(self):
        self.save('"/missing/game.exe"')
        self.assertEqual(external_games([self.root]), [])

if __name__ == "__main__":
    unittest.main()
