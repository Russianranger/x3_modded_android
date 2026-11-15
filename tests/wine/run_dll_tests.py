"""Run Wine's own conformance tests for each patched DLL on the runtime's exact Wine build.

Usage (x86-64 Linux, under xvfb-run): python3 -I tests/wine/run_dll_tests.py WINE_ROOT DLLDIR
WINE_ROOT is the unpacked Kron4ek wine-10.0-amd64-wow64; DLLDIR holds <dll>.dll, <dll>_test.exe
and wine-dlls.json from scripts/build_wine_dlls.sh. Each suite runs twice, with the stock DLL and
with the patched one. Pass: the patched run fails no test line the stock run passed, and at least
one line that fails with the stock DLL (the patch's own regression test) passes with ours.
"""
import json, os, pathlib, re, shutil, subprocess, sys, tempfile

root, dlls = pathlib.Path(sys.argv[1]).resolve(), pathlib.Path(sys.argv[2]).resolve()
wine = root / "bin" / "wine"
target = root / "lib" / "wine" / "i386-windows"
manifest = json.loads((dlls / "wine-dlls.json").read_text())


def run(test, dll_name):
    prefix = tempfile.mkdtemp(prefix="prefix-")
    env = dict(os.environ, WINEPREFIX=prefix, WINEDEBUG="-all", WINEDLLOVERRIDES="mscoree,mshtml=")
    subprocess.run([str(wine), "wineboot", "-i"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300)
    result = subprocess.run([str(wine), str(test), dll_name], env=env, capture_output=True, text=True, errors="replace", timeout=900)
    subprocess.run([str(root / "bin" / "wineserver"), "-k"], env=env, timeout=60)
    shutil.rmtree(prefix, ignore_errors=True)
    output = result.stdout + result.stderr
    failed = {m[1] for m in re.finditer(r"^\s*([\w.]+:\d+): Test failed", output, re.M)}
    summary = re.findall(r"^.*\d+ tests executed.*$", output, re.M)
    return failed, (summary[-1] if summary else f"no summary (exit {result.returncode})"), output


ok = True
for name in manifest["dlls"]:
    dll = name[:-4]
    installed = target / name
    stock = installed.with_suffix(".dll.stock")
    shutil.copy2(installed, stock)
    try:
        stock_failed, stock_summary, _ = run(dlls / f"{dll}_test.exe", dll)
        shutil.copy2(dlls / name, installed)
        patched_failed, patched_summary, output = run(dlls / f"{dll}_test.exe", dll)
    finally:
        shutil.copy2(stock, installed)
    new = sorted(patched_failed - stock_failed)
    fixed = sorted(stock_failed - patched_failed)
    print(f"{name}: stock   {stock_summary}\n{name}: patched {patched_summary}")
    print(f"{name}: fixed by the patch: {', '.join(fixed) or 'none'}")
    if new:
        ok = False
        print(f"{name}: NEW failures with the patch: {', '.join(new)}")
        print("\n".join(line for line in output.splitlines() if "Test failed" in line)[:4000])
    if not fixed:
        ok = False
        print(f"{name}: the patch's regression test did not fail with the stock DLL")
sys.exit(0 if ok else 1)
