#!/usr/bin/env bash
# x3pin.exe under real Wine (CI, x86-64, inside xvfb-run): the control run must show the crypto
# DLLs unloading, the pinned run must show them staying, with arguments and exit code intact.
set -euo pipefail
out=$(cd "${1:?usage: run_pin_test.sh OUTDIR}" && pwd)
export WINEPREFIX=$(mktemp -d)/prefix WINEDEBUG=-all WINEDLLOVERRIDES="mscoree,mshtml=" WINEARCH=win64
wineboot -i >/dev/null 2>&1 || true
wineserver -w
target=$(winepath -w "$out/pin_target.exe")
echo "control (no x3pin):"; wine "$out/pin_target.exe" --expect-unpinned
echo "with x3pin:"; wine "$out/x3pin.exe" "$target" --expect-pinned "two words"
set +e; wine "$out/x3pin.exe" "$target" --exit7; code=$?; set -e
test "$code" = 7 || { echo "x3pin did not pass the exit code through (got $code)" >&2; exit 1; }
echo "x3pin: all checks passed"
