"""Test the patched Wine DLLs on the runtime's exact Wine build, stock against patched.

Usage (x86-64 Linux with GStreamer, under xvfb-run):
    python3 -I tests/wine/run_dll_tests.py WINE_ROOT DLLDIR FIXTURES
WINE_ROOT is the unpacked Kron4ek wine-10.0-amd64-wow64; DLLDIR holds the patched DLLs, the test
programs and wine-dlls.json from scripts/build_wine_dlls.sh; FIXTURES is tests/media/fixtures.

1. Wine's own conformance suites for each patched DLL run with the stock DLL and with ours. The
   patched run must not fail a test line the stock run passed. Where the patches carry their own
   regression test (amstream), at least one line failing with the stock DLL must pass with ours.
2. x3media.exe plays X3-like media through DirectShow media streams, in a prefix set up the way the
   device has it: created with winegstreamer disabled, then its filters registered as the runner
   does. With every patched DLL in place, all scenarios must pass. The stock results are printed
   for comparison and must show the problems the patches are for.
"""
import json, os, pathlib, re, shutil, subprocess, sys, tempfile

root, dlls, fixtures = (pathlib.Path(p).resolve() for p in sys.argv[1:4])
wine = root / "bin" / "wine"
target = root / "lib" / "wine" / "i386-windows"
manifest = json.loads((dlls / "wine-dlls.json").read_text())

# DLL -> (test program, [test names] or None for the whole program, needs a fixed line)
SUITES = {
    "amstream": ("amstream_test.exe", ["amstream"], True),
    "winegstreamer": ("quartz_test.exe", ["mpegvideo", "mpegsplit", "mpegaudio", "mpeglayer3"], False),
}
# name, arguments, what the stock DLLs are expected to do
SCENARIOS = [
    ("sector music (44.1 kHz MP3)", ["audio", "music-44k.mp3", "44100", "2"], "pass"),
    ("menu music (48 kHz MP3 into a 44.1 kHz stream)", ["audio", "music-48k.mp3", "44100", "2"], "fail"),
    ("speech (WMA 2 in ASF)", ["audio", "speech-wma2.dat", "44100", "2"], "fail"),
    ("unpositioned mono at 22 kHz into a 44.1 kHz stereo stream", ["audio", "speech-22k-mono-unpositioned.wav", "44100", "2"], "fail"),
    ("comms faces (seeking in one MPEG-1 movie)", ["seek", "faces-clips.mpg", "8"], "fail"),
]


def wine_env(prefix, debug="-all"):
    return dict(os.environ, WINEPREFIX=str(prefix), WINEDEBUG=debug, WINEDLLOVERRIDES="mscoree,mshtml=")


def new_prefix(device_like=False):
    prefix = pathlib.Path(tempfile.mkdtemp(prefix="prefix-"))
    env = wine_env(prefix)
    if device_like:
        # The device's prefix was made before the media add-on existed, with winegstreamer
        # disabled, so its DirectShow filters were never registered (seventh Thor run).
        env["WINEDLLOVERRIDES"] = "winegstreamer=;mscoree,mshtml="
    subprocess.run([str(wine), "wineboot", "-i"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300)
    subprocess.run([str(root / "bin" / "wineserver"), "-w"], env=env, timeout=120)
    return prefix


def finish(prefix):
    subprocess.run([str(root / "bin" / "wineserver"), "-k"], env=wine_env(prefix), timeout=60)
    shutil.rmtree(prefix, ignore_errors=True)


def run_suite(program, test, dll):
    prefix = new_prefix()
    env = wine_env(prefix, "-all,trace+loaddll")   # which DLL the test really loaded
    result = subprocess.run([str(wine), str(dlls / program), test], env=env, capture_output=True, text=True,
                            errors="replace", timeout=900)
    finish(prefix)
    output = result.stdout + result.stderr
    loaded = sorted({line.split("Loaded ", 1)[1] for line in output.splitlines()
                     if "Loaded " in line and dll.lower() in line.lower()})
    print(f"{dll}/{test}: loaded {'; '.join(loaded) or 'nothing matching'}")
    failed = {m[1] for m in re.finditer(r"^\s*([\w.]+:\d+): Test failed", output, re.M)}
    summary = re.findall(r"^.*\d+ tests executed.*$", output, re.M)
    return failed, (summary[-1] if summary else f"no summary (exit {result.returncode})"), output


def install(patched):
    for name in manifest["dlls"]:
        shutil.copy2((dlls if patched else stock_dir) / name, target / name)


def register_filters(prefix):
    """What the runner does on the device once the media add-on is there."""
    env = wine_env(prefix)
    for regsvr32 in (r"C:\windows\syswow64\regsvr32.exe", "regsvr32"):
        subprocess.run([str(wine), regsvr32, "/s", "winegstreamer.dll"], env=env, timeout=300,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run([str(root / "bin" / "wineserver"), "-w"], env=env, timeout=120)
    registry = (prefix / "system.reg").read_text(errors="replace").lower()
    return "instance\\\\{f9d8d64e-a144-47dc-8ee0-f53498372c29}" in registry


def run_scenarios(label):
    prefix = new_prefix(device_like=True)
    registered = register_filters(prefix)
    drive = prefix / "drive_c"
    for fixture in fixtures.iterdir():
        if fixture.is_file(): shutil.copy2(fixture, drive / fixture.name)
    results = {}
    for name, arguments, _ in SCENARIOS:
        result = subprocess.run([str(wine), str(dlls / "x3media.exe"), *arguments], env=wine_env(prefix),
                                cwd=drive, capture_output=True, text=True, errors="replace", timeout=300)
        lines = [line for line in result.stdout.splitlines() if line.startswith("x3media:")]
        results[name] = result.returncode == 0
        print(f"--- {label}: {name}: {'passed' if results[name] else 'FAILED (exit %d)' % result.returncode}")
        print("\n".join(lines[-14:]))
        if not results[name] and label.startswith("patched"):
            # Once more with DirectShow and GStreamer traces, for the reason.
            env = dict(wine_env(prefix, "+quartz,+strmbase,+loaddll"), GST_DEBUG="2,WINE:4")
            traced = subprocess.run([str(wine), str(dlls / "x3media.exe"), *arguments], env=env, cwd=drive,
                                    capture_output=True, text=True, errors="replace", timeout=300)
            noise = re.compile(r"AddRef|Release|StdMediaSample2_|BaseMemAllocator_|enum_pins|pin_Query|FM2_Read"
                               r"|QueryInterface|DllGetClassObject|DSCF_|filter_mapper|AMFilterData|SystemClockImpl")
            text = [line for line in (traced.stdout + traced.stderr).splitlines() if not noise.search(line)]
            print(f"--- {label}: {name}: trace (last 160 of {len(text)} lines)")
            print("\n".join(line[:240] for line in text[-160:]))
    finish(prefix)
    print(f"--- {label}: GStreamer splitter registered by regsvr32: {registered}")
    return results, registered


stock_dir = pathlib.Path(tempfile.mkdtemp(prefix="stock-"))   # outside lib/wine: wineboot registers what it finds there
for name in manifest["dlls"]:
    shutil.copy2(target / name, stock_dir / name)

ok = True
try:
    for name in manifest["dlls"]:
        dll = name[:-4]
        program, tests, needs_fix = SUITES[dll]
        any_fixed = False
        for test in tests:
            install(False)
            stock_failed, stock_summary, stock_output = run_suite(program, test, dll)
            install(True)
            patched_failed, patched_summary, output = run_suite(program, test, dll)
            new = sorted(patched_failed - stock_failed)
            fixed = sorted(stock_failed - patched_failed)
            any_fixed = any_fixed or bool(fixed)
            print(f"{dll}/{test}: stock   {stock_summary}\n{dll}/{test}: patched {patched_summary}")
            print(f"{dll}/{test}: fixed by the patches: {', '.join(fixed) or 'none'}")
            if "no summary" in patched_summary:
                ok = False
                print(f"{dll}/{test}: the patched run did not finish")
            if new:
                ok = False
                print(f"{dll}/{test}: NEW failures with the patches: {', '.join(new)}")
                for label, text in (("stock", stock_output), ("patched", output)):
                    print(f"--- {dll}/{test}: {label} failures")
                    print("\n".join(line for line in text.splitlines() if "Test failed" in line)[:6000])
        if needs_fix and not any_fixed:
            ok = False
            print(f"{dll}: the patches' regression tests did not fail with the stock DLL")

    install(False)
    stock_results, _ = run_scenarios("stock DLLs")
    install(True)
    patched_results, registered = run_scenarios("patched DLLs")
    if not registered:
        ok = False
        print("x3media: regsvr32 did not register the GStreamer splitter")
    for name, _, stock_expected in SCENARIOS:
        if not patched_results[name]:
            ok = False
            print(f"x3media: {name}: fails with the patched DLLs")
        if stock_results[name] != (stock_expected == "pass"):
            print(f"x3media: note: {name}: stock DLLs {'passed' if stock_results[name] else 'failed'}, "
                  f"expected to {stock_expected}")
finally:
    install(False)
sys.exit(0 if ok else 1)
