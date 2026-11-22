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

- **Payload:** PRoot, the patched wineserver, Turnip 24.3.4 and 26.0.0, DXVK d3d9 2.5.3 (3.1.1 comes from upstream), the `pcm_trasc`
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
   - The defaults are Turnip 26.0.0, DXVK 2.5.3, the native surface display path, the **fast**
     CPU profile, `-skipintro` and a 1280×720 Wine desktop (since 0.1.14; a choice you saved
     before is kept).
   - Set the Thor to **High Performance** (pull the quick settings down twice). In Standard mode
     the fastest core was held at 2477 of its 3187 MHz, and X3 is limited by that one core. The
     status line says so when the core runs capped.
   - The first launch creates the Wine prefix, so it takes longer than later ones.
   - **CPU emulation** sets Box64's code translator for X3AP.exe only:
     - **fast** (default since 0.1.11): bigger translated blocks that also cover Windows code,
       and direct call/return. Flag handling and code-change detection stay as in balanced. On
       the Thor, loads took 146 s against balanced's 183 s, and flight ran at 32 fps against 24.
     - **fastest** (experiment): fast without the x86 memory-ordering barriers.
     - **balanced**: the settings the Thor runs up to 0.1.9 used.
     - **accurate**: balanced plus exact x87 and rounding.

     If X3 hangs on fastest, go back to fast; on fast, to balanced. The runner warns when X3's main thread
     has used a full core for a minute without any system call or page fault, which is what the
     0.1.7 hang looked like.
   - The in-game status line shows **last load N s**: the last stretch without a frame, taken from
     Wine's present trace. It's the number to compare between profiles.
   - **DXVK** (0.1.13): **2.5.3** (default again since 0.1.14) or **3.1.1** (experiment). DXVK 3
     spends less CPU per Direct3D 9 call, and on the Thor that CPU time is X3's main thread. But
     in 0.1.13, 3.1.1 crashed X3 inside `vkCreateGraphicsPipelines` soon after the menu
     appeared. With 3.1.1 chosen, Box64 now logs any fault in X3 with native and emulated
     backtraces, and the launch stops with a message naming the Vulkan call. Each version keeps
     its own shader cache.
   - **Display path:** **Native surface** (default since 0.1.13; experimental in 0.1.12) has TRASC's `x11-frame-bridge` copy
     frames from the X server through shared memory straight to an Android surface. The RFB
     connection then carries keys and pointer only, and the app falls back to RFB frames if the
     surface stops. TRASC measured 59.7 frames/s delivered on the Thor this way against 40.7 for
     RFB at 60. **RFB** has the X server encode every frame for the app over its socket. The
     status line shows which path is active.
   - **CPU placement** (automatic since 0.1.12): X3's main thread runs on the fastest core (the
     Thor's Cortex-X3, CPU 7), and every other thread of the launch runs on the other cores.
     Android still decides: when it leaves CPU 7 out, the main thread goes to the other big cores
     (CPUs 3-6, since 0.1.14), not the 2 GHz little ones.
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

## Media add-on (music, voices, movies)

X3 plays sound effects through DirectSound, which works without the add-on. Music, comms voices
and the comms faces go through DirectShow instead. In Wine 10, DirectShow's WAV, MPEG audio and
AVI splitters, its MP3 decoder and its GStreamer splitter (which handles the MPEG-1 video and ASF
files) live in `winegstreamer`, which needs GStreamer.

- **What X3 plays** (survey of the Thor install, LxXRM):
  - `soundtrack/`: MP3.
  - `mov/` and `addon/mov/`: `.dat` files that are either MPEG-1 video (the comms faces) or ASF
    with WMA 2 audio (Betty and NPC speech).
- **Install:** on the **Runtime** card, tap **Download media add-on**. It unpacks native arm64
  GStreamer 1.22 from Debian Bookworm into the runtime: base, good, ugly and libav (FFmpeg's
  decoders, which bring WMA 2), plus `mpegpsdemux` and the MPEG video parser from bad.
  Version 2 adds libav. If the card shows an older add-on, tap the button again.
- **Effect:** the runner sees `/etc/x3-media-addon.json` and stops disabling `winegstreamer`.
  Box64 maps `winegstreamer.so` onto the native libraries. All 206 GStreamer and GLib functions it
  imports are among those Box64 `2f130fab` wraps, which was checked against the binary.
- **Testing:** CI builds the add-on inside the pinned runtime image and tests:
  - that the required elements exist;
  - native decodes of WAV, MP3, WMA 2 in ASF, and MPEG-1 video as an elementary stream and as a
    program stream (`tests/media/fixtures`, made from ffmpeg's test pattern);
  - the same decodes from an x86-64 program under the runtime's Box64, through the wrapped
    libraries, with a callback into emulated code.

  The archive is published once per version as a `media-addon-vN` release, and the APK pins its
  hash.
- **Reinstalling the runtime** removes the add-on. Download it again afterwards.

### Patched Wine DLLs

X3 plays its media through Wine's DirectShow media streams (`amstream.dll`) and Wine's GStreamer
filters (`winegstreamer.dll`). `patches/wine/` holds fixes for both, found on the Thor:

- **0001, amstream:** X3 creates its comms face samples on its own surfaces after the video
  graph is already running, which changes the stream's pixel format. Wine 10.0 then tried to
  reconnect the running graph, which the decoder refuses, and read a format it had already freed.
  That was the crash when hailing an NPC in the sixth Thor run. Now, when the reconnect is
  refused, both sides stay connected, the call fails cleanly, and no frame is read without a
  format.
- **0002, amstream:** when both formats are 16, 24 or 32-bit RGB of the same size, accept the
  change instead and convert each frame's pixels while copying it into X3's surface.
- **0003, amstream:** X3 sets its mixer format on the audio stream before opening a file, and
  then the stream accepted nothing else. But it offered upstream filters a fixed 11025 Hz mono
  type with no subtype. Now it offers the format X3 set, then the same in mono (or stereo). It
  also accepts any 16-bit mono or stereo PCM and converts it on the way in: it remixes, and
  resamples linearly. That covers the 48 kHz menu track and the speech. It also asks upstream
  filters for buffers of a tenth of a second: the MP3 decoder sizes its buffers from the
  connected type, and sent X3's music 16 bytes at a time.
- **0005, winegstreamer:** the GStreamer splitter's audio output can change sample format but
  cannot resample. It also can't remix mono that has no channel position, which is how
  GStreamer's WMA decoder reports X3's speech. It still accepted any audio format, so the speech
  connected at X3's rate and channel count and then never played (the stream failed to
  negotiate). Now it refuses formats it cannot produce, and amstream gets the native format and
  converts it (0003).
- **0004, winegstreamer:** X3 keeps all comms faces in one MPEG-1 movie and seeks between pilots.
  Wine's DirectShow decoders ignored flushes, so after a seek two things went wrong:
  - GStreamer kept the old position's queued frames and reference pictures.
  - The decoder kept its pre-seek quality-of-service deadline and dropped every frame up to it.

  Now the decoders flush on a seek, reset that deadline, and (for video) wait for the next key
  frame.
- **0006, winegstreamer:** frames from before a seek target carry negative times, and the
  decoders handed those to GStreamer, whose timestamps are unsigned. They came back as times
  days in the future, and amstream waited for them forever: the face froze after a backward
  seek, and the window kept showing another pilot. Times now reach GStreamer on a base of
  10000 seconds. Also, GStreamer's video decoder dropped the next frame whenever amstream
  reported the last one even slightly late, so faces played at about a third of their frames;
  lateness under a frame now counts as on time.
- **0007, winegstreamer:** GStreamer's MPEG-PS demuxer seeks by system clock reference and lands
  up to a second either side of the target: the end of the previous face showed, or the start
  of the new one was skipped. When the MPEG-1 splitter plays video only, it now seeks
  1.5 seconds early, and the MPEG video decoder drops the frames before the target by their
  (now intact) negative times. Seeks land on the exact frame. That covers a seek on a running
  or paused movie and, since 0.1.11, the one that matters for X3: it stops the face movie,
  seeks, and runs it again, and the seek to the start position then happened without the
  preroll, landing on another pilot.
- **0008, amstream and winegstreamer (not for upstream):** an `x3media` debug channel, always on
  in the runner. It logs files opened, state changes and seeks (target, flags, state), the
  splitter's segments and video preroll, and the decoder's drops. It also logs the formats and
  samples X3 sets up, and the first frames and updates after each segment, flush or state
  change, then counts: a few lines per comms call. The comms face problems never showed up in a
  run with media traces, and those traces are far too heavy to leave on.
- **0009, winegstreamer:** X3's face movie has no time stamps in its video packets, so on the
  Thor every face frame came out of GStreamer untimed (0.1.13's logs). 0007's early seek then
  backfired: the decoder could not tell the 1.5 s before the target from the target, and showed
  it, so most of every call showed the end of the previous face or another one. MPEG-1 video
  has its own clock: the time code in each GOP header and each picture's place in display
  order. The splitter now times untimed MPEG-1 video from those, relative to the movie's first
  time code, while they check out: the first after a seek must lie within 2 s of where the seek
  went, and each later one must follow from the pictures of the GOP before it. If they do not,
  the stream stays untimed and is sought straight to the target from then on.

**Building and testing:** CI builds both DLLs (PE side only; `winegstreamer.dll` keeps using the
runtime's own `winegstreamer.so` from the same source) from the `wine-10.0` tag. It then runs, on
the runtime's exact Wine build (Kron4ek 10.0 WoW64) with GStreamer, stock DLLs against patched:

- Wine's amstream conformance suite. The patched DLL must pass a test the stock one fails, and
  must not fail one it passes.
- Wine's suites for the MPEG decoders and splitter (`quartz_test.exe mpegvideo`, `mpegsplit`,
  `mpegaudio`, `mpeglayer3`). No new failures allowed. 0004 makes one `mpegaudio` todo pass
  (timestamps after a flush), so the patch removes that todo.
- `tests/wine/x3media.c`, which plays media through amstream the way X3 does, in a prefix set up
  like the device's (made with winegstreamer disabled, then registered as the runner does it):
  - a 44.1 kHz MP3 (sector music);
  - a 48 kHz MP3 into a 44.1 kHz stream (the menu track);
  - WMA 2 in ASF (speech);
  - unpositioned mono at 22 kHz into a 44.1 kHz stereo stream (what GStreamer's WMA decoder
    makes of speech; a WAV file, so it runs without the ASF plugin too);
  - seeking back and forth in one MPEG-1 movie (the comms faces): eight one-second clips, each
    one colour under noise, at a constant 640 kbit/s so that frames span several packs, as in
    `mov/00001.dat`. The test first plays the movie to learn where each clip starts, and no
    frame may be lost doing so. Then it seeks in turn while the movie runs, after pausing it,
    and after stopping it (X3's way), backwards too. After each seek, every frame must show that
    clip, the first one at the target time, and no update may stall. Stock Wine loses two frames
    in three, then stalls after the first seek; 0.1.10's DLLs showed the wrong clip after every
    stopped seek.
  - the same movie with the time stamps taken out of its video packets
    (`tests/media/strip_pes_timestamps.py`), as X3's is. 0.1.13's DLLs showed another clip in
    110 of 120 frames, stock Wine in 39; with 0009, none.

  All six must pass with the patched DLLs.

The app binds both DLLs over the runtime's copies, and the runner checks their hashes
(`wine_patches` in `x3-state.json`).

### Media filters in older prefixes

A Wine prefix made before the media add-on was installed has winegstreamer's COM classes, but
not its DirectShow filter entries. Those are written by `DllRegisterServer()`, which never ran
while winegstreamer was disabled. Without them DirectShow has no GStreamer splitter, so speech
and the menu track can't be rendered, while MPEG files still play through the MPEG-1 splitter.
With the add-on installed, the runner looks for the splitter's entry in `system.reg` before each
launch and runs `regsvr32 winegstreamer.dll` (32- and 64-bit) if it's missing. The
`gstreamer_filters` field in `x3-state.json` shows the result.

## Controls

The profile is the six-layer scheme in [04-controls.md](04-controls.md), loaded from
`controls/generated/x3app-controller.json`. The editor is under **Controller mappings**, and
**Reset controls to X3 default** restores the profile. The app adds three actions that TRASC lacks:

| Action | Default binding | What it does |
| --- | --- | --- |
| `HelpOverlayToggle` | Select + Start | Pins or unpins the help overlay. Holding Select alone shows it while held. |
| `TextInput` | Select + Y | Opens the Android keyboard dialog, for ship names and console text. |
| `ClientMenu` | Select + B | Opens the gear menu. |

By default, Wine's gamepad driver (`winebus.sys`) is switched off, so X3 sees only the
keyboard and mouse input the layered profile produces. Wine can see the Thor's built-in pad (SDL2
and udev), and X3 AP reads it through XInput with its own bindings. In the fourth device run, that
doubled actions and made the ship turn and accelerate on its own.

The launcher option **Let X3 also read the gamepad itself** turns Wine's gamepad driver back on.
Use it only with the app's controller profile cleared.

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
- **Music, comms voices and the comms faces** need the media add-on (see below). Without it, only
  sound effects play.
- **Loading** from the menu into a game took 180 s in the sixth Thor run. It is bound by
  emulating X3's own code, so settings alone are unlikely to reach 30 s.
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

### 14 November 2026, AYN Thor, build 0.1.3

**What worked:**

- The patched Box64 passed the `smsw` check.
- X3's launcher opened.
- After **Start**, DXVK built the 1280×720 fullscreen device.

**Result:** a black screen. After the first frame, every X3 and DXVK thread was asleep, using no
CPU, until the session was stopped.

**Cause:**

- The game asks for vsync, so DXVK 2.5.3 switched the swapchain to `VK_PRESENT_MODE_FIFO_KHR`.
- In FIFO mode, DXVK's `dxvk-frame` thread waits for each frame with
  `vkWaitForPresentKHR(..., UINT64_MAX)`. On this display path (Wine X11 surface, Mesa software
  WSI, Xtigervnc) that wait never returns.
- The frame-latency limit then blocked the game thread.
- In IMMEDIATE mode DXVK skips that wait. TRASC's `vulkan-probe` never waits for a present, so
  it could not catch this.

**Fixes in 0.1.4:**

- `DXVK_CONFIG` sets `d3d9.presentInterval = 0`, which keeps DXVK in IMMEDIATE mode, and
  `d3d9.maxFrameRate` set to the display rate (30 or 60), which replaces vsync's pacing.
- `x3-state.json` records the configuration as `dxvk_configuration` and the chosen present mode as
  `dxvk_present_mode`.
- Thread samples now record each sleeping thread's kernel wait channel and syscall, when Android
  allows reading them. A future hang will show what the threads are waiting on.

### 14 November 2026, AYN Thor, build 0.1.4

**What worked:** X3 booted and reached gameplay at about 31 fps (median of Wine's present
counter). The present mode was IMMEDIATE, the frame cap 60, and audio ran through AudioTrack at
48 kHz.

**Problems:**

- **Only sound effects played.** DirectShow could not build a graph without `winegstreamer`. The
  media add-on fixes this.
- **Doubled inputs, and the ship turning and accelerating by itself.** `winexinput.sys` was
  loaded, so Wine had found the built-in pad. X3 read it through XInput on top of the app's
  mappings. Fixed in 0.1.5 by switching off `winebus.sys`, with an opt-in option to turn it back
  on.
- **The new game took about 3 minutes to load.** Most of that was crypto DLL churn: X3 opened and
  closed a CryptoAPI context 1,473 times while loading, apparently once per script it checks.
  Each cycle loaded and unloaded `rsaenh`, `crypt32` and `bcrypt`, together with their emulated
  Unix libraries and wrapped GnuTLS, at about 100–130 ms per cycle. Keeping those DLLs loaded for
  the life of the process would remove most of the delay. That fix is planned next.

### 14 November 2026, AYN Thor, build 0.1.5 (media add-on installed)

**What worked:**

- **Controls:** better, because Wine's gamepad driver was off.
- **GStreamer:** `winegstreamer` loaded with native GStreamer under Box64. The "Wave Parser",
  "MPEG-I Stream Splitter" and "AVI Splitter" failures were gone. Wine built an MP3 decode
  chain: `l3codecx.ax` and `mp3dmod`.
- **Frame rate:** 47 fps.

**Problems:**

- **Loading was still slow.** 1,467 crypto cycles took 208 s.
- **Music and voices were still silent.** About 14 s of audio after the MP3 decoder appeared,
  then silence.
- **Unregistered decoder class.** X3 asked COM 38 times for class
  `{874131cb-4ecc-443b-8948-746b89595d20}`, which Wine does not register. The only other trace
  of that GUID is Wine bug 48763, where X2 and X3 ask for `CLSID_CWMSPDecMediaObject`, the
  Windows Media Audio **Voice** decoder (format tag 0x000A). That suggests some speech is
  WMA Voice, which Wine has no decoder for.

**Changes in 0.1.6:**

- **`x3pin.exe`** (`native/x3pin`) now starts X3AP.exe. Once the launcher dialog is idle, it
  loads `bcrypt`, `crypt32` and `rsaenh` into the game with `CreateRemoteThread(LoadLibraryW)`.
  The extra reference stops them unloading, so the crypto cycles no longer reload them. CI
  builds it with MinGW and tests it under real Wine:
  - a control run shows the DLLs unloading;
  - with `x3pin`, they stay loaded;
  - arguments and the exit code pass through.

  `x3-state.json` records the result as `crypto_pin`.
- **Media diagnostics, for one run:**
  - A survey of `soundtrack/` and `mov/` records extensions and container/codec, including the
    codec tags of ASF audio streams, as `media_files`.
  - Media Wine channels are on: warn and fixme for amstream, quartz, strmbase, winegstreamer,
    qasf, wmvcore, dmo, msacm, mpeg3, mp3dmod and mfplat, plus trace for amstream, which names
    each file X3 opens.
  - The first 8 MB of the Wine log is kept as `x3-wine.start.log` when the log rotates.

### 14 November 2026, AYN Thor, build 0.1.6

**What worked:**

- **Crypto pinning:** the CryptoAPI reload churn was gone, one load instead of about 2,190.
  Menu to game went from 454 s in the run before (no pinning) to 180 s, measured as the pause
  in Wine's present trace.
  The `crypto_pin` field stayed empty only because `x3pin`'s report went to a console nobody
  read.
- **Media survey:** see the media add-on section for what X3's folders hold.

**Problems:**

- **Still too slow.** During the 180 s, X3's main thread ran at 80–100 % of one core, mostly
  the Cortex-X3. Nothing else was busy. That is emulated game code, not Wine or I/O.
- **No music.** The menu produced about 22 s of non-silent output through X3's single DirectSound
  stream, then silence. The MP3 chain (`l3codecx.ax`, `mp3dmod`) was built. Not explained yet.
- **No Betty or NPC voices.** They are WMA 2 in ASF, and add-on v1 had no WMA decoder.
- **Crash on hailing an NPC.** The game died with an unhandled page fault while the comms
  face video started:
  - X3 changes the DirectDraw stream's format while its graph is running, which needs a
    reconnect.
  - The upstream pin refuses to disconnect while running (`VFW_E_NOT_STOPPED`), but Wine's
    `ddraw_IDirectDrawMediaStream_SetFormat` went on and disconnected its own side, which frees
    the connection's media type.
  - The upstream filter kept delivering frames, and `ddraw_meminput_Receive` read the
    bit depth through the freed, NULL format block.

**Changes in 0.1.7:**

- **Media add-on v2** with libav, for WMA 2 voices. Tap **Download media add-on** again.
- **Patched `amstream.dll`** (`patches/wine/0001`, `0002`): a format change on the running comms
  video is now converted per frame instead of reconnecting. Where it can't be converted, it fails
  cleanly with both sides still connected. See "Patched Wine DLLs".
- **Load time:**
  - CPU profiles **fast** (default) and **fastest**, written into X3AP.exe's Box64 section.
  - A request to Android to keep the main thread on the biggest core (`uclamp.min`).
  - **last load N s** in the status line and `present_pauses_seconds` in `x3-state.json`.
  - `x3-threads.log` now records the main thread's user and system time, page faults and time
    spent waiting for a CPU.
- **Diagnostics:**
  - `x3pin` writes its report to a file the runner reads (`X3PIN_LOG`).
  - The media channels were traced on the wrong name in 0.1.6: amstream logs on Wine's
    `quartz` channel. **Sound diagnostics** now traces `quartz`, `dsound` and `msacm`.
  - `x3-audio.log` reports peak and RMS levels per interval, so silence and quiet music can be
    told apart.
  - The survey tells MPEG program streams from elementary video streams.

### 14 November 2026, AYN Thor, build 0.1.7

**What happened:** X3's launcher came up, but after it the screen stayed black until the run was
stopped 155 s later.

- X3 created its D3D9 device and presented one frame. Then its main thread ran at 100 % of a core
  for two minutes. Its system time and page-fault count didn't move once in that time, and its
  other threads and wineserver slept.
- In the 0.1.6 run, X3 set up DirectSound half a second after that same first frame. This time
  Wine logged nothing more at all, and amstream and the media add-on were not loaded yet. So the
  stall came before any of 0.1.7's media changes ran.
- What did change at that point was the CPU profile. 0.1.7's default **fast** was Box64's own
  "fast" profile: on top of bigger blocks and direct call/return, it treats CALL/RET as never
  needing flags (`SAFEFLAGS=0`) and keeps running translated code whose page was written to
  (`DIRTY=1`). Either can leave a loop that never ends.
- **Other results:**
  - The `uclamp.min` request was refused (`EPERM`): Android doesn't let an app raise its own
    threads' clamp.
  - `x3pin` reported through its log file this time (`crypto_pin` 3/3).
  - Add-on v2 and both amstream patches were installed and verified.
  - The survey showed the comms faces are MPEG-1 program streams (15 in `mov`, 2 in
    `addon/mov`), plus 2 elementary streams.

**Changes in 0.1.8:**

- **balanced** is the default again. The saved profile choice starts over, so the 0.1.7 **fast**
  pick doesn't carry over.
- **fast** no longer includes `SAFEFLAGS=0` and `DIRTY=1`. It only builds bigger blocks with direct
  call/return. Both fast profiles are marked as experiments.
- The runner warns about a main thread that spins without kernel work (`main_thread_spinning`).
- The `uclamp.min` request and its launcher option are gone.

### 15 November 2026, AYN Thor, build 0.1.8

Sound diagnostics were on for this run.

**What worked:**

- The game started and loaded, and sector music played.
- The comms face showed instead of crashing (patches 0001 and 0002).
- The load pauses were 10.7 s and 17.1 s at startup and 117 s into the game, with a longer
  302 s pause later.

**Problems:**

- **No main menu music, no Betty, no NPC voices.** X3 sets its mixer format on an amstream audio
  stream, then opens the file:
  - The menu track `soundtrack/08404.mp3` is 48 kHz. The MPEG-1 splitter and MP3 decoder offered
    only 48 kHz, and the stream refused anything but X3's format (`E_INVALIDARG`, then
    `VFW_E_CANNOT_CONNECT`).
  - Speech (`addon/mov/00144.dat`, `00244.dat`, WMA 2 in ASF) found no filter at all
    (`VFW_E_CANNOT_RENDER`). The GStreamer splitter wasn't among the registered DirectShow
    filters (see "Media filters in older prefixes").
  - Sector tracks are 44.1 kHz, which is why they played.
- **The comms face flickered between pilots.** All faces are in `mov/00001.dat`: a 640 MB,
  51-minute MPEG-1 movie at 256×256 and 30 fps. X3 seeks to a pilot's clip with
  `IMediaSeeking::SetPositions`. The decoder kept the old position's frames and reference pictures
  across the seek.
- **The log lost the middle of the session.** Tracing dsound and dsound3d produced three
  quarters of the output and filled each 8 MB segment in seconds.

**Reproduced off the device:** `x3media.exe`, built locally with clang and Wine's headers, showed
all three problems on stock Kron4ek Wine 10.0 with the host's GStreamer. The patched PE DLLs
can be built the same way (clang, lld, Wine's headers via `widl`, Kron4ek's import libraries,
`winebuild --builtin`), which is how 0004's quality-of-service fix was found:

- `0x80040217` for the 48 kHz MP3 and for ASF;
- after seeks, 47 of 60 frames came from the wrong clip.

**Changes in 0.1.9:**

- The runner registers winegstreamer's filters when they are missing.
- Patches 0003 (amstream) and 0004 (winegstreamer), with the CI scenarios above.
- **Sound diagnostics** trace DirectShow only (`quartz`, `strmbase`, `msacm`). They leave out
  per-sample and reference-counting lines, and count what they leave out
  (`wine_log_dropped_lines`).


### 15 November 2026, AYN Thor, build 0.1.9

Media diagnostics were on for this run.

**What worked:** the main menu music, sector music, Betty and NPC voices. The filters were
registered on the first launch (13.5 s, once).

**Problems:**

- **The menu music restarted a couple of times.** X3 reads music two seconds at a time. Each of
  those reads took seven to nine seconds to fill: the MP3 decoder connected with amstream's PCM
  type, sized its buffers from it, and sent 16 bytes per sample. That made about 22,000 samples
  per read. Fixed by 0003's allocator requirements: about 20 samples per read.
- **The comms face still cycled between pilots.** The log lost the comms part of the session
  (see below), but a movie built like `mov/00001.dat` showed what happens:
  - the demuxer landed up to 0.8 s after the target (0007);
  - after a backward seek, frames with negative times froze the stream (0006);
  - GStreamer dropped two frames in three for QoS (0006).
- **Slow loading and play.** X3's main thread ran at 91% of a core for the whole session: X3's
  own code and DXVK's 32-bit d3d9, both under emulation. The other main costs, each on its own
  core, were DirectSound's mixer (16%: it resamples X3's 44.1 kHz buffers to the 48 kHz output),
  the X server and the swapchain thread (16% each), and wineserver (15%). The diagnostics
  themselves wrote 4.4 GB of trace, almost all of it the 16-byte music samples, so this run's
  load times (a 179 s pause) are not representative.

**Changes in 0.1.10:**

- Patches 0003 (allocator requirements), 0006 and 0007; the face-seek scenario uses a realistic
  movie and checks every frame.
- Verbose logging and media diagnostics now apply to the next launch only.


### 15 November 2026, AYN Thor, build 0.1.10 (CPU profile fast)

**What worked:** audio throughout. Loading felt faster: the two game loads took 146 s each,
against 183 s and 180 s in the two earlier runs on the balanced profile. In flight the median
was 32 frames per second, against 24 and 29.

**Problems:**

- **The comms window was still wrong.** The run had no media traces, but the previous run's
  showed X3's pattern: it stops a movie (or pauses it), seeks, then runs it. 0007 only moved
  seeks on a running or paused movie. On a stopped one, the splitter seeks when streaming
  starts, and that seek went to the plain target. `x3media.exe`, extended to seek all three
  ways, showed 0.1.10's DLLs landing on the wrong clip after every stopped seek (white sought,
  black shown).
- **Performance.** X3's main thread ran at 95% of a core in flight and about 86% while
  loading, of which 10–23% was kernel time. In 3 of 32 samples taken during loads, it was
  stopped by PRoot. Nothing else was near a full core: the swapchain thread 28%, the X server
  23%, DirectSound's mixer 17%.

**Changes in 0.1.11:**

- 0007 also moves the seek made when streaming starts, and the MPEG video decoder drops frames
  from before the start position after a start as well as after a flush.
- `fast` is the default CPU profile.
- `main_thread_profile` in `x3-state.json`: the game's main thread sampled 20 times a second,
  shares of running, waiting and stopped by PRoot, and the commonest system calls, kept apart
  for loading (no frame presented for 4 s) and playing.


### 15 November 2026, AYN Thor, build 0.1.11 (CPU profile fastest)

**What worked:** loading took 143 s, and play ended at 42 frames per second (fast in the run
before: 146 s, median 32).

**Problems:**

- **The comms face video still glitched.** The run had no media traces, and the previous
  diagnostic run lost the comms part of its log to rotation. So 0008 adds a light media log
  that is always on.
- **The main thread lost the prime core.** The new main-thread profile split time like this:

  | | Running | Asleep | Stopped by PRoot | Disk |
  |---|---:|---:|---:|---:|
  | Loading | 73% | 15% | 7.5% | 4.3% |
  | Playing | 72% | 26% | 1.8% | |

  Asleep while playing was almost all in `futex` (19%): waiting for other threads, mostly the
  presentation chain. The swapchain thread used 31% of a core and the X server 23%.

  The 10 s thread samples explained part of the loading time. The supervisor's own CPU mask
  changed every few seconds (0-5, 0-6, 0-4,6-7, 0-5,7, 0-7). `allow_game_cpus` copied it onto
  every game thread, 12 to 59 threads a time. Whenever it lacked CPU 7, X3's main thread ran on
  the A715/A710 cores (CPUs 3-5) for the next stretch: most of the loads.
- **Box64's DynaCache** (0.4.4 caches translated code in `$HOME/.cache/box64` by default) left
  no trace in the logs. Two balanced runs both loaded in about 180 s, so whether it holds X3's
  32-bit code is unknown.

**Changes in 0.1.12:**

- Patch 0008 and `trace+x3media` in every run.
- CPU placement `prime` (new default, `cpu_affinity`): the main thread goes on the fastest
  core, re-checked every second, and other launch threads go off it. The supervisor's mask is
  no longer copied. `affinity_update`, `android_cpuset`, `prime_cpus` and `main_thread_repins`
  are in the state.
- `dynacache_at_launch` and `dynacache` (each minute): Box64's cache folder, files and bytes.
- Display path option: native surface (TRASC's frame bridge and its pinned
  `libtrasc-presentation.so`).

### 21 November 2026, AYN Thor, build 0.1.12 (native surface; then also Turnip 26.0.0)

**What worked:** both runs were faster than 0.1.11 (143 s, 42 fps):

| | Load | Median fps | 75th / 90th percentile |
|---|---:|---:|---:|
| Native surface, Turnip 24.3.4 | 98.5 s | 44 | |
| Native surface, Turnip 26.0.0 | 94.8 s | 50 | 59 / 60 |

- Prime placement held: the main thread stayed on CPU 7 (5 re-pins in the run).
- Box64's DynaCache works: 240 files, 69 MB, `X3AP.exe` and `d3d9.dll` among them.

**Where the time goes now:**

- X3's main thread was busy 83% of the playing time, and 85-94% in the 42-48 fps stretches.
  Most of its sleep was in `futex` (9%), which includes waiting at the 60 fps cap.
- Other threads: DXVK's command thread 8-16% of a core, the swapchain thread 3% (31% on
  RFB), the X server 12-16%, the frame bridge 8%. DirectSound's mixer used 15-48%: it
  resamples every voice to 48 kHz with a 66-tap filter, in emulated x86 code. These all run on
  other cores.
- The game rendered at 1280×720, so the GPU is unlikely to be the limit. The run could not
  show it either way.
- So 60 fps in busy scenes needs about a quarter less work on the main thread per frame. That
  work is X3's own code plus DXVK's Direct3D 9 front end, both translated by Box64.
- **Comms faces:** neither run played a face clip. The face stream opened, paused and
  stopped with 0 frames and 0 updates, so there is nothing to compare yet.

**Changes in 0.1.13:**

- DXVK 3.1.1 option (default), pinned by SHA-256 from the upstream release. 2.5.3 stays
  available. The frame cap goes in `dxvk.maxFrameRate` for 3.x. The state gains
  `dxvk_requested`, `dxvk_loaded` and `dxvk_binding_model`.
- New defaults: Turnip 26.0.0 and the native surface.
- `main_thread_profile.below_cap`: the playing samples taken while Wine reported more than 3 fps
  under the cap.
- `clock_profile`: once a second while playing, at the cap and below it, CPU 7's clock and
  limit and, when Android allows it, kgsl's GPU busy share and clock.

### 21 November 2026, AYN Thor, build 0.1.13 (DXVK 3.1.1, then 2.5.3)

**What happened:**

- **DXVK 3.1.1 crashed X3** about 8 s after the menu appeared. The device came up without
  complaint: Vulkan 1.3 features all present, legacy binding model, IMMEDIATE present. Then
  DXVK's command thread hit `assert(!status && "vkCreateGraphicsPipelines")` in winevulkan.
  That means a fault inside the call: in Wine's 32-to-64-bit conversion, Box64's Vulkan bridge
  or Turnip's shader compiler. The log cannot say which. That run used the **fastest** CPU
  profile, which drops Box64's x86 memory ordering, and DXVK 3's new multithreaded code may
  depend on it.
- **The comms faces were wrong, and now we know why.** This run played faces: 391 frames
  over several calls. Every frame of X3's face movie arrived untimed: its video packets carry no
  time stamps. So after each of X3's seeks the decoder could not drop the 1.5 s that 0007
  seeks early by, and showed them. The same thing happens with the test movie once its time
  stamps are stripped: another clip in 110 of 120 frames.
- **The fastest core was capped.** CPU 7's limit stayed at 2477 MHz for the whole run, against
  its 3187 MHz maximum, and it averaged about 2100 MHz. The GPU ran at its lowest step
  (401 MHz) and was about 40% busy, so it is not the limit.
- **Android left CPU 7 out about a quarter of the time,** and X3's main thread then ran on any
  core, the little ones included.
- **Start-of-game stutter:** after the 153 s load, presenting stopped for 12 s, 5 s and 9 s.
  X3's main thread was busy throughout and its memory was growing, so this is X3 loading
  the sector, slowed by the capped core. 0.1.12's runs had pauses of the same size.

**Changes in 0.1.14:**

- Patch 0009: untimed MPEG-1 video timed from its GOP time codes (see above), and a new
  x3media scenario with a movie without time stamps.
- DXVK 2.5.3 is the default again. With 3.1.1, Box64 reports faults with backtraces
  (`BOX64_SHOWSEGV`, `BOX64_SHOWBT`), and a winevulkan assert stops the launch with a message.
- The main thread falls back to the big cores (`big_cpus`, `main_thread_big_core_fallbacks`).
- `performance_hint` on the status line when the prime core is held below 92% of its top clock.
