"""Read installed products from Battle.net Agent's protobuf product.db.

Field layout reference (not generated protobuf code):
https://github.com/bartok765/galaxy_blizzard_plugin/blob/master/src/product_db.proto
Only installation metadata is read; account/session records are ignored.
"""
from pathlib import Path
import re

MAX_DB_SIZE = 32 * 1024 * 1024

def _varint(data, offset):
    value = 0
    for shift in range(0, 70, 7):
        if offset >= len(data):
            raise ValueError("Truncated protobuf varint")
        byte = data[offset]
        offset += 1
        value |= (byte & 127) << shift
        if byte < 128:
            return value, offset
    raise ValueError("Invalid protobuf varint")

def _fields(data):
    offset = 0
    while offset < len(data):
        tag, offset = _varint(data, offset)
        number, wire = tag >> 3, tag & 7
        if not number:
            raise ValueError("Invalid protobuf field")
        if wire == 0:
            value, offset = _varint(data, offset)
        elif wire in (1, 2, 5):
            if wire == 2:
                size, offset = _varint(data, offset)
            else:
                size = 8 if wire == 1 else 4
            end = offset + size
            if end > len(data):
                raise ValueError("Truncated protobuf field")
            value, offset = data[offset:end], end
        else:
            raise ValueError("Unsupported protobuf wire type")
        yield number, wire, value

def decode_products(data):
    if len(data) > MAX_DB_SIZE:
        raise ValueError("Battle.net product.db is too large")
    products = []
    for number, wire, value in _fields(data):
        if number != 1 or wire != 2:
            continue
        product = {n: v for n, w, v in _fields(value) if w == 2}
        settings = {n: v for n, w, v in _fields(product.get(3, b"")) if w == 2}
        cached = {n: v for n, w, v in _fields(product.get(4, b"")) if w == 2}
        state = {n: v for n, w, v in _fields(cached.get(1, b"")) if w == 0}
        if not (state.get(1) or state.get(2)):
            continue
        path = settings.get(1, b"").decode("utf-8")
        code = product.get(2, product.get(1, b"")).decode("utf-8")
        uid = product.get(1, b"").decode("utf-8")
        if path and code:
            products.append({"code": code, "uid": uid, "windows_path": path})
    return products

def wine_path(value, prefix):
    value = str(value).replace("\\", "/")
    prefix = Path(prefix)
    if prefix.name == "pfx":
        prefix = prefix.parent
    if value.lower().startswith("z:/"):
        return Path(value[2:])
    if re.match(r"^[a-zA-Z]:/", value):
        drive = value[0].lower()
        root = prefix / "pfx/dosdevices" / (drive + ":")
        if drive == "c" and not root.exists():
            root = prefix / "pfx/drive_c"
        return root / value[3:]
    return Path(value)

def installed_products(prefix):
    prefix = Path(prefix)
    db = prefix / "pfx/drive_c/ProgramData/Battle.net/Agent/product.db"
    if not db.is_file():
        return []
    if db.stat().st_size > MAX_DB_SIZE:
        raise ValueError("Battle.net product.db is too large")
    result = []
    for product in decode_products(db.read_bytes()):
        path = wine_path(product["windows_path"], prefix)
        if path.is_dir():
            result.append({**product, "install_path": str(path.resolve())})
    return result
