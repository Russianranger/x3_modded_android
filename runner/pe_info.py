"""Read-only facts about a Windows executable: machine, Large Address Aware, imported DLLs.

Used to warn before launch: a Steam-DRM X3AP.exe imports steam_api.dll and cannot start without
Steam; a 64-bit build needs the 64-bit DXVK; LAA tells whether a 32-bit build can use 4 GB.
All offsets are bounds-checked; nothing is executed or modified.
"""
import struct

MACHINES = {0x14C: "i386", 0x8664: "x86_64", 0xAA64: "arm64"}
MAX_HEADER = 16 * 1024 * 1024


class PEError(ValueError):
    pass


def _u16(data, offset):
    if offset < 0 or offset + 2 > len(data):
        raise PEError("truncated header")
    return struct.unpack_from("<H", data, offset)[0]


def _u32(data, offset):
    if offset < 0 or offset + 4 > len(data):
        raise PEError("truncated header")
    return struct.unpack_from("<I", data, offset)[0]


def inspect(path, max_imports=256):
    with open(path, "rb") as stream:
        data = stream.read(MAX_HEADER)
    if data[:2] != b"MZ":
        raise PEError("not a Windows executable")
    pe = _u32(data, 0x3C)
    if data[pe:pe + 4] != b"PE\0\0":
        raise PEError("invalid PE signature")
    machine = _u16(data, pe + 4)
    sections = _u16(data, pe + 6)
    optional_size = _u16(data, pe + 20)
    characteristics = _u16(data, pe + 22)
    optional = pe + 24
    magic = _u16(data, optional)
    if magic == 0x10B:
        directories = optional + 96
    elif magic == 0x20B:
        directories = optional + 112
    else:
        raise PEError("unknown optional header")
    subsystem = _u16(data, optional + 68)
    table = optional + optional_size
    spans = []
    for i in range(min(sections, 96)):
        base = table + 40 * i
        spans.append((_u32(data, base + 12), max(_u32(data, base + 8), _u32(data, base + 16)), _u32(data, base + 20)))

    def offset_of(rva):
        for virtual, size, raw in spans:
            if virtual <= rva < virtual + size:
                return raw + rva - virtual
        raise PEError("address outside sections")

    def c_string(offset):
        end = data.find(b"\0", offset, offset + 256)
        if offset < 0 or end < 0:
            raise PEError("bad import name")
        return data[offset:end].decode("ascii", "replace")

    imports = []
    import_rva = _u32(data, directories + 8)
    if import_rva:
        cursor = offset_of(import_rva)
        while len(imports) < max_imports:
            if cursor + 20 > len(data):
                break
            descriptor = data[cursor:cursor + 20]
            if descriptor == b"\0" * 20:
                break
            imports.append(c_string(offset_of(_u32(data, cursor + 12))))
            cursor += 20
    return {
        "machine": MACHINES.get(machine, hex(machine)),
        "large_address_aware": bool(characteristics & 0x20),
        "gui": subsystem == 2,
        "imports": imports,
        "steam_api": any(name.lower() in ("steam_api.dll", "steam_api64.dll") for name in imports),
    }
