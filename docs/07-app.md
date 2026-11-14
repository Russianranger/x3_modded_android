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
4. Launch the game:
   - Pick `X3AP.exe` and a resolution, then tap **Launch**.
   - The defaults are Turnip 24.3.4, the balanced CPU profile, `-skipintro` and a 1280×720 Wine
     desktop.
   - The first launch creates the Wine prefix, so it takes longer than later ones.
5. In X3's own settings, turn **EAX off**. Pick a resolution that matches the Wine desktop.

### Applying LxXRM inside the app

You can run LxXRM's installer in the app if your folder doesn't already have the mod:

1. Copy `LxXRM/` (with `_DOWNLOADS/`) into the game folder on the Thor.
2. Tap **Sync changed files**.
3. In the program list, pick `LxXRM/SETUP.bat`. It runs in a `cmd` window inside the Wine desktop.

The program list shows `.exe`, `.bat` and `.cmd` files in the game folder and one level down.
`X3AP.exe` is always first.

Steam's `X3AP.exe` imports `steam_api.dll`, and there is no Steam client inside the app. If the game
exits right away, use the NoSteam `X3AP.exe` that LxXRM's setup installs (or Egosoft's own). The
launcher and the runner both warn when they detect the Steam executable.

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
- **Untested on hardware:** no device has run this build yet. Load times, Turnip compatibility with
  X3's D3D9 renderer and the EAX-off audio path still need testing on the Thor.
- **Route A** (native Linux `X3AP_main` via BOX32) is not wired into the app.
