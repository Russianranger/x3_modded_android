#!/usr/bin/env bash
# x3pin.exe under real Wine (CI, x86-64, inside xvfb-run): the control run must show the crypto
# DLLs unloading, the pinned run must show them staying, with arguments and exit code intact.
set -euo pipefail
out=$(cd "${1:?usage: run_pin_test.sh OUTDIR}" && pwd)
export WINEPREFIX=$(mktemp -d)/prefix WINEDEBUG=-all WINEDLLOVERRIDES="mscoree,mshtml=" WINEARCH=win64
timeout 300 wineboot -i >/dev/null 2>&1 || true
wineserver -w
target=$(winepath -w "$out/pin_target.exe")
echo "control (no x3pin):"; timeout 90 wine "$out/pin_target.exe" --expect-unpinned
log=$(mktemp -d)/x3pin.log
echo "with x3pin:"; X3PIN_LOG=$(winepath -w "$log") timeout 120 wine "$out/x3pin.exe" "$target" --expect-pinned "two words"
grep -q "^x3pin: 3 of 3 DLLs pinned" "$log" || { echo "x3pin did not write its X3PIN_LOG report" >&2; cat "$log" >&2 || true; exit 1; }
echo "X3PIN_LOG report: $(tail -1 "$log")"
set +e; timeout 90 wine "$out/x3pin.exe" "$target" --exit7; code=$?; set -e
test "$code" = 7 || { echo "x3pin did not pass the exit code through (got $code)" >&2; exit 1; }
echo "x3pin: all checks passed"
