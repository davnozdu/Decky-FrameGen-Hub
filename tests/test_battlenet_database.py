import sys
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "py_modules/lib" if (ROOT / "py_modules/lib").exists() else ROOT / "py_modules"))
from battlenet_db import decode_products, installed_products, wine_path

def varint(number):
    result = bytearray()
    while number > 127:
        result.append((number & 127) | 128)
        number >>= 7
    result.append(number)
    return bytes(result)

def field(number, value):
    if isinstance(value, str): value = value.encode()
    if isinstance(value, int): return varint(number << 3) + varint(value)
    return varint((number << 3) | 2) + varint(len(value)) + value

def product(code="fenris", path="C:/Program Files (x86)/Diablo IV", installed=1):
    settings = field(1, path)
    state = field(1, installed) + field(2, installed)
    return field(1, field(1, code) + field(2, code) + field(3, settings) + field(4, field(1, state)))

class BattleNetDatabase(unittest.TestCase):
    def test_installed_state_and_unknown_fields(self):
        data = product() + product("uninstalled", installed=0) + field(99, b"unknown")
        parsed = decode_products(data)
        self.assertEqual([p["code"] for p in parsed], ["fenris"])
        self.assertEqual(parsed[0]["windows_path"], "C:/Program Files (x86)/Diablo IV")

    def test_missing_folder_is_not_installed_and_external_drive_is_resolved(self):
        with tempfile.TemporaryDirectory() as temp:
            prefix = Path(temp)/"prefix"
            target = Path(temp)/"External/Diablo IV"; target.mkdir(parents=True)
            devices = prefix/"pfx/dosdevices"; devices.mkdir(parents=True)
            (devices/"d:").symlink_to(target.parent, target_is_directory=True)
            db = prefix/"pfx/drive_c/ProgramData/Battle.net/Agent/product.db"
            db.parent.mkdir(parents=True)
            db.write_bytes(product(path="D:/Diablo IV") + product("missing", path="D:/Missing"))
            parsed = installed_products(prefix)
            self.assertEqual(len(parsed), 1)
            self.assertEqual(parsed[0]["install_path"], str(target.resolve()))
            self.assertEqual(wine_path("Z:"+str(target), prefix), target)

    def test_damaged_product_record_does_not_hide_other_games(self):
        bad = field(1, field(1, "x") + field(3, b"\xff\xfe") + field(4, field(1, field(1, 1))))
        bad_utf8 = field(1, field(1, "y") + field(2, "y") + field(3, field(1, b"\xff")) + field(4, field(1, field(1, 1))))
        parsed = decode_products(bad + bad_utf8 + product())
        self.assertEqual([p["code"] for p in parsed], ["fenris"])

    def test_truncated_database_fails_without_guessing_paths(self):
        for data in (b"\x0a\x80", b"\x0a\x05abc", b"\x00"):
            with self.assertRaises(ValueError): decode_products(data)

if __name__ == "__main__": unittest.main()
