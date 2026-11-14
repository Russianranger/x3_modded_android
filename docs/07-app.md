# The X3 Modded app (Route B)

This is the first app build. It runs the Windows `X3AP.exe` from your own install, with LxXRM
already applied or applied in the app. The stack is Wine 10 WoW64, Box64 and DXVK on Turnip. It is
TRASC's proven RoF2 stack, trimmed to one game.

## How it fits together

```text
Android app (Java, io.github.russianranger.x3)
 ├─ MainActivity        Runtime / Game files / Launch / Tools cards
 ├─ GameImporter        SAF folder -> files/game/current (fresh copy or changed-files sync)
 ├─ RuntimeInstaller    TRASC client-runtime-v1 (Debian arm64 + Box64 + Wine), sha256-pinned
 ├─ GameRuntime         PRoot: binds game->/game, prefix->/prefix, runner->/opt/x3, sockets->/session
 ├─ AudioBridge         pcm_trasc socket -> AudioTrack (USAGE_GAME, 48 kHz S16 stereo)
 ├─ GameActivity        RFB view, gear menu, layer banner, help overlay
 ├─ ControllerInput     TRASC's layer engine + numpad/Pause keys + HelpOverlayToggle/TextInput
 └─ HelpOverlayView     draws the overlay cards from controls/generated/overlay-data.json
PRoot rootfs (TRASC client runtime)
 └─ /opt/x3/x3_runner.py
     Xtigervnc :7 -> x11-frame-bridge --input -> wineboot -> DXVK d3d9 (x86 + x64)
     -> D: = /game -> box64 wine explorer /desktop=X3,WxH D:\X3AP.exe [args]
```

**Copied from TRASC:**

- **Payload:** PRoot, the patched wineserver, Turnip 24.3.4 and 26.0.0, DXVK d3d9, the `pcm_trasc`
  ALSA plugin and the frame/input bridge. Each file is pinned by hash in
  `payload/trasc-payload.lock.json`.
- **Java:** the RFB client, controller engine and audio bridge.
- **Python runner helpers:** the presentation, metrics, Vulkan and audio modules.

**New in this repository:**

- the importer
- the X3 runner, with PE checks: architecture, Large Address Aware flag and Steam API import
- the 64-bit DXVK install
- Egosoft's `dsp0` ALSA alias
- the help overlay renderer
- the X3 controller profile

## Using it on the Thor

1. Install the APK from the
   [preview release](https://github.com/Russianranger/x3_modded_android/releases/tag/preview).
2. On the **Runtime** card, tap **Download runtime (338 MB)**. Or use **Install from file…** if you
   already have `client-runtime-arm64.tar.gz`. The runtime is the same one TRASC uses, checked
   against the same SHA-256.
3. On the **Game files** card, tap **Import X3 folder…** and pick the folder that holds `X3AP.exe`.
   That is normally `X3 Terran Conflict`, with `addon/` inside it. You can also pick its parent
   folder if it holds nothing else.
   - The files are copied into app-private storage, so Wine never reads them through Android's
     slow FUSE layer. Expect 10–15 GB with LxXRM.
   - After you change files on shared storage, tap **Sync changed files**. It copies only the files
     whose size or date changed.
   - **Leave out LxXRM installer archives** is on by default. It skips any `_DOWNLOADS` folder:
     `SETUP.bat` unpacks from those archives, and the game never reads them once the mod is applied.
     That saves several GB and a lot of copy time. Turn it off only if you want to re-run `SETUP.bat`
     in the app.
   - After the import, the card reads `X3AP.exe` itself. It shows whether the exe is the NoSteam
     build, which it judges from the exe's imports. A Steam install keeps `steam_api.dll` in the
     folder even next to the NoSteam exe, so the folder alone doesn't tell. The card also shows
     whether the exe is Large Address Aware.
4. Launch the game:
   - Pick `X3AP.exe` and a resolution, then tap **Launch**.
   - The defaults are Turnip 24.3.4, the balanced CPU profile, `-skipintro` and a 1280×720 Wine
     desktop.
   - The first launch creates the Wine prefix, so it takes longer than later ones.
5. In X3's own settings, turn **EAX off**. Pick a resolution that matches the Wine desktop.

### Saves and settings

X3 keeps its saves and settings in `Documents\Egosoft\X3AP`. Before each launch, the runner
links `Documents\Egosoft` inside the Wine prefix to the app folder `files/game/saves/Egosoft`,
which the runtime sees as `/saves`. Saves therefore survive **Reset Wine prefix**, runtime updates
and APK updates. Uninstalling the app deletes them.

If the prefix already holds a real `Egosoft` folder, the runner moves it, never deletes it. It goes
into `/saves/Egosoft` when that folder is empty. Otherwise it goes beside it as
`Egosoft-from-<user>-<time>`. `x3-state.json` records what was linked or moved under `saves`.

### Applying LxXRM inside the app

You can run LxXRM's installer in the app if your folder doesn't already have the mod. If it
already has the mod, skip this section.

1. Copy `LxXRM/` (with `_DOWNLOADS/`) into the game folder on the Thor.
2. Untick **Leave out LxXRM installer archives**, then tap **Sync changed files**.
3. In the program list, pick `LxXRM/SETUP.bat`. It runs in a `cmd` window inside the Wine desktop.

The program list shows `.exe`, `.bat` and `.cmd` files in the game folder and one level down.
`X3AP.exe` is always first.

Steam's `X3AP.exe` imports `steam_api.dll`, and there is no Steam client inside the app. Use the
NoSteam `X3AP.exe`, either the one LxXRM's setup installs or Egosoft's own. The **Game files**
card and the runner both warn when they detect the Steam executable.

## Controls

The profile is the six-layer scheme in [04-controls.md](04-controls.md), loaded from
`controls/generated/x3app-controller.json`. The editor is under **Controller mappings**, and
**Reset controls to X3 default** restores the profile. The app adds three actions that TRASC lacks:

| Action | Default binding | What it does |
| --- | --- | --- |
| `HelpOverlayToggle` | Select + Start | Pins or unpins the help overlay. Holding Select alone shows it while held. |
| `TextInput` | Select + Y | Opens the Android keyboard dialog, for ship names and console text. |
| `ClientMenu` | Select + B | Opens the gear menu. |

The keyboard can also send numpad and Pause keys (`NumpadEnter`, `Numpad0`–`9`, `NumpadAdd` and so
on), because X3 binds several actions to them.

When you rebind a control, the overlay shows "(custom)" for it instead of the default label.

## Logs

**Tools → Export logs…** writes a zip that contains:

- `x3-wine.log`: Wine and game output
- `x3-proot.log`: runner output; `x3-state.json`: the runner's last state
- `x3-prefix.log`, `x3-vulkan.log`, `x3-graphics.log`: prefix setup and the Turnip/DXVK preflight
- `x3-audio.log`
- `client-input.log`, `client-frame-bridge.log`
- `android-crash.log`
- the import record and launch status, in `metadata.json`

Attach the zip to an issue in this repository when something fails.

## Building

CI builds every push. See `.github/workflows/ci.yml`:

1. Run the runner unit tests, the controller generator check and the controller engine checks: the
   X3 app's engine, and TRASC's own engine through `tools/trasc_check`.
2. Fetch and verify the TRASC payload with `python3 -I scripts/fetch_trasc_payload.py`.
3. Build with `gradle :app:assembleDebug` (AGP 8.9.1, SDK 35, arm64-v8a only).
4. Check the APK against the pinned preview certificate.
5. On `main`, publish the APK, `build-info.json` and `launcher-sources.tar.gz` to the `preview`
   release.

To build locally, you need JDK 17, Android SDK platform 35 with build-tools 35.0.0, and Gradle
8.11:

```sh
python3 -I scripts/fetch_trasc_payload.py
gradle :app:assembleDebug
python3 -I -m unittest discover -s tests -v
```

## Known gaps

- **Display:** frames come over RFB only. TRASC's native presentation library is tied to TRASC's
  package name, so its zero-copy path is not available yet.
- **Music, comms voices and movies:** X3 plays these through DirectShow, and in Wine 10 DirectShow
  decodes through `winegstreamer`. The TRASC runtime has no GStreamer, so `winegstreamer` is off.
  Until a GStreamer add-on for the runtime exists, expect sound effects (DirectSound) but possibly
  no music, voices or movies. A Wine report on X3: Reunion found that the videos and the radio
  chatter need GStreamer plugins
  ([bug 55738](https://bugs.winehq.org/show_bug.cgi?id=55738)).
- **Route A** (native Linux `X3AP_main` via BOX32) is not wired into the app.

## Device runs

### 13 November 2026, AYN Thor (Android 13, Adreno 740), build 0.1.1

**What worked:**

- **Import:** 5,952 files, 11.0 GB. The NoSteam `X3AP.exe` was detected, and it is Large Address
  Aware.
- **Startup:** the runtime probe passed, and seccomp acceleration was active. Building the Wine
  prefix took 68.5 s. DXVK 2.5.3 started on Turnip 24.3.4 (Adreno 740), and the ALSA to AudioTrack
  bridge opened at 48 kHz.

**Result:** a black screen.

**Cause:** `X3AP.exe` aborted about 8 s after start:

- It sets up DirectShow at start-up.
- DirectShow's `devenum` opens every installed video codec to list it.
- Wine's Indeo 5 codec (`ir50_32`) delay-loads `winegstreamer`, which is disabled.
- Wine aborts the whole process when a delay load fails.

**Fixes in 0.1.2:**

- `ir50_32` is disabled.
- The runner now reports this kind of abort as an error instead of sitting on an empty Wine
  desktop.
- The game-process marker matches the runner. 0.1.1 never found the game process, so it could not
  tell the game had gone.
- The session ends by itself when X3 exits.
- The right-stick mouse channel retries its connection. It had lost a start-up race and stayed off
  for the whole session.

### 13 November 2026, AYN Thor, build 0.1.2

**What worked:** the codec crash was gone. X3 got further, past DXVK device setup, DirectSound
and DirectShow, and the right-stick input channel connected.

**Result:** still a black screen.

**Cause:** X3AP.exe stopped about 7 s in, at `0x4F9975`. Box64 reported:

```text
Unimplemented 32bits Opcode ... 66 0F 01 E0
```

That instruction is `smsw ax`, part of the game's CPU and FPU check at start-up. Box64 knew
`smsw` but not this prefixed form. Wine then reported an "illegal instruction", which 0.1.2 did
not recognise as an error, and every Wine process exited 10 s later.

**Fixes in 0.1.3:**

- The app ships a patched build of the runtime's own Box64 commit
  ([patches/box64](../patches/box64/README.md)). It is tested in CI with the exact instruction
  bytes from the game.
- The runner names any "Unhandled …" crash, including the x86 instruction Box64 could not run.
- The runner ends the session with an error when Wine shuts down before the game window appears.
