#!/usr/bin/env bash
# Build the small Windows (i686) helpers the app runs inside Wine, and their tests.
# Needs i686-w64-mingw32-gcc. Usage: scripts/build_wintools.sh OUTDIR
set -euo pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
out=${1:?usage: build_wintools.sh OUTDIR}
mkdir -p "$out"
cc=i686-w64-mingw32-gcc
"$cc" -municode -O2 -s -Wall -Wextra -o "$out/x3pin.exe" "$repo/native/x3pin/x3pin.c" -lpsapi
"$cc" -mwindows -O2 -s -Wall -Wextra -o "$out/pin_target.exe" "$repo/tests/wine/pin_target.c" -ladvapi32
python3 -I - "$out" <<'PY'
import hashlib, json, pathlib, sys
out = pathlib.Path(sys.argv[1]); exe = out / "x3pin.exe"
record = {"x3pin.exe": {"sha256": hashlib.sha256(exe.read_bytes()).hexdigest(), "bytes": exe.stat().st_size,
                        "source": "native/x3pin/x3pin.c", "tests": ["tests/wine/run_pin_test.sh"]}}
(out / "wintools-build.json").write_text(json.dumps(record, indent=1) + "\n")
print(json.dumps(record))
PY
