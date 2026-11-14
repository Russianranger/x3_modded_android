"""Write synthetic PE files plus runner/pe_info.py's verdicts, for tests/java/PeInfoCheck.java.

Usage: python3 -I tests/pe_fixtures.py OUTDIR [EXTRA.exe|dll ...]
Writes OUTDIR/*.bin and OUTDIR/expected.tsv (file, machine, laa, gui, steam_api, imports or ERROR).
Extra real files (for example the DXVK DLLs in payload/out) are added to the comparison as-is.
"""
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "runner"))
sys.path.insert(0, str(HERE))

import pe_info  # noqa: E402
from test_runner import make_pe  # noqa: E402

CASES = {
    "nosteam_i386_laa": make_pe(laa=True, imports=("KERNEL32.dll", "d3d9.dll", "DSOUND.dll", "WINMM.dll")),
    "steam_i386": make_pe(imports=("KERNEL32.dll", "steam_api.dll")),
    "steam64_x86_64": make_pe(machine=0x8664, plus=True, imports=("steam_api64.dll",)),
    "console_no_imports": make_pe(imports=(), gui=False),
    "arm64": make_pe(machine=0xAA64, plus=True),
    "high_byte_name": make_pe(imports=("KERNEL32.dll",)).replace(b"KERNEL32.dll", b"KERN\xc932.dll"),
    "truncated": make_pe()[:0x90],
    "not_pe": b"@echo off\r\n",
}


def row(name, path):
    try:
        info = pe_info.inspect(path)
    except (OSError, ValueError):
        return f"{name}\tERROR"
    return "\t".join([name, info["machine"], str(info["large_address_aware"]).lower(), str(info["gui"]).lower(),
                      str(info["steam_api"]).lower(), ",".join(info["imports"])])


def main():
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for name, data in CASES.items():
        path = out / (name + ".bin")
        path.write_bytes(data)
        rows.append(row(path.name, path))
    for extra in sys.argv[2:]:
        source = Path(extra)
        path = out / ("real-" + source.name)
        shutil.copyfile(source, path)
        rows.append(row(path.name, path))
    (out / "expected.tsv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    print(f"{len(rows)} PE fixtures in {out}")


if __name__ == "__main__":
    main()
