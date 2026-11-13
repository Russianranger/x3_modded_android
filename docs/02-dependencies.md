# 2. Dependencies

Everything below runs on **arm64 Android**. Versions are what TRASC pins today where it already
ships a component. "New" marks things TRASC does not have yet.

## Game and mod inputs (you supply these)

| Item | Notes |
| --- | --- |
| X3: Terran Conflict + X3: Albion Prelude (Terran War Pack) | AP needs TC installed underneath it: AP loads TC's cat/dat files first, then its own `addon/`. Egosoft's latest AP is 3.3 (2017). |
| Windows build | Route B. LxXRM's installer is written for it. |
| Linux build (GOG Linux installer or Steam Linux depot) | Route A only. Egosoft updated it in July 2021 (GOG Linux to TC 3.4 / AP 3.3, plus "lib compatibility" fixes). `X3AP_main` is a 32-bit, non-PIE i386 ELF that uses SDL2 and OpenGL. |
| LxXRM 3.1 (`LxXRM31.zip`) + every archive its `SETUP.bat` expects in `_DOWNLOADS` | XRM, all of Lucike's scripts, X3 Customizer tweaks, CPP, Resurrection 3.0 + XRM compatibility pack + patch 3.2 (optional pieces: TCAP for AP, Lost Colony). Steam copies also need Egosoft's NoSteam `X3AP.exe`. |

## Android app (same toolchain as TRASC)

| Component | Version / note |
| --- | --- |
| Android | API 26+ (Android 8), `arm64-v8a`; primary target Android 13 on the Thor |
| Build | JDK 17, Gradle 8.11.1, Android SDK 35 / build-tools 35.0.0, NDK 27.2.12479018 |
| PRoot | TRASC's pinned build with the seccomp-acceleration and SysV IPC patches |
| Presentation | Xvnc (TigerVNC) + RFB, or TRASC's Native Surface helper (X11 -> ANativeWindow) |
| Audio | `AudioBridge.java` (AudioTrack, `USAGE_GAME`) + `libasound_module_pcm_trasc.so` |
| Input | `ControllerInput.java` / `ControllerManager.java`, plus the extended X3 vocabulary (docs/04) |

## Rootfs: common to both routes

Debian Bookworm arm64, app-owned, as in TRASC:

- `libasound2` + the `pcm_trasc` plugin (built by TRASC's `native/audio.Dockerfile`), and
  `alsa-utils` for `speaker-test` diagnostics
- X11 client libraries, `tigervnc-standalone-server`, `xauth`, fonts
- Mesa **Turnip** for Adreno via KGSL, built from the pinned Mesa release TRASC uses (24.3.4 at the
  time of TRASC 0.4.x)

## Route B: Windows build through Wine

| Component | Version / note |
| --- | --- |
| Box64 | TRASC pins commit `2f130fab...` ("0.4.4"), built with `-DARM_DYNAREC=ON`. **New:** add `-DSD8G2=ON`; Box64 has a Snapdragon 8 Gen 2 target. |
| Wine | Kron4ek `wine-10.0-amd64-wow64` (checksum-pinned in TRASC). New WoW64 runs the 32-bit `X3AP.exe` inside 64-bit Wine, so no Box86 or armhf userspace is needed. |
| amd64 multiarch runtime | `libgcc-s1:amd64`, `libstdc++6:amd64`, `libunwind8:amd64` (as in TRASC's client-runtime image) |
| DXVK | 2.5.3, the 32-bit `d3d9.dll` in the prefix's `syswow64`, with `d3d9=n,b` |
| Audio | builtin `dsound` -> `winealsa.drv` (with `winepulse.drv=d`) -> ALSA default -> `pcm_trasc` |
| Media codecs (**verify**) | A community Wine guide for the Terran War Pack installs GStreamer (base/good/ugly/libav) plus winetricks `amstream devenum quartz wsh57 wmp10`. That suggests some media goes through DirectShow. Add GStreamer only if movies or music stay silent once SFX work. |

### Variant B′ (optional): ARM64EC Wine + FEX

FEX publishes WoW64 and ARM64EC emulator DLLs (a `fex-emu-wine` package) that plug into an AArch64
build of Wine. That way only the x86 game is emulated and Wine itself is native. FEX's wiki notes that
upstream Wine still lacks some ARM64EC pieces and recommends its fork. Winlator forks such as
Ludashi already ship "Arm64EC containers" using FEXCore. Consider it if Route B profiles show Wine's
own code (file lookups, audio mixing) dominating.

## Route A: native Linux build through Box64 BOX32

| Component | Version / note |
| --- | --- |
| Box64 | built with `-DARM_DYNAREC=ON -DBOX32=ON -DSD8G2=ON`. Box32 is documented as experimental; v0.4.2 (April 2026) still carried BOX32 fixes. Track upstream. |
| Libraries Box32 wraps to native arm64 | From `box64/src/wrapped32` (checked today): `libc`, `libm`, `libdl`, `libpthread`, `librt`, **`sdl2`**, `sdl1`, **`libgl`**, `libglx`, `libegl`, `libglu`, **`libasound`**, **`openal`**, `libvorbis`, `libogg`, `libx11` + xcb/xext/xrandr/xi/xcursor/xxf86vm/xinerama/xfixes/xrender, `freetype`, `fontconfig`, `udev0/1`, `pulsesimple`, `libdrm`, `gbm`. Install the arm64 Debian packages for whichever of these `X3AP_main` NEEDs (the probe lists them). |
| OpenGL | **New:** Mesa built with the `zink` gallium driver and Turnip (`freedreno` Vulkan, KGSL). Run with `MESA_LOADER_DRIVER_OVERRIDE=zink`, and presentation via `MESA_VK_WSI_DEBUG=sw` as TRASC does for DXVK. |
| Game-bundled libs | The Linux depot ships some i386 libraries in `lib/` (Steam threads mention its own zlib/libpng). Box32 emulates anything it does not wrap; point `BOX64_LD_LIBRARY_PATH` at `lib/`. |
| Launcher | `X3AP_config` is a separate GTK tool. Bypass it: run `X3AP_main` directly and keep its config files under `~/.config/EgoSoft/X3AP/`. |
| Not used | Box86. It needs a 32-bit (armhf) host userspace, which an Android app rootfs cannot reasonably provide; Box32 replaces it. |

## Preparation tools (desktop)

| Tool | Use |
| --- | --- |
| Windows PC (or Wine on a desktop) | Run LxXRM's `SETUP.bat` once. It colours its output on Windows 10+. |
| X3 Customizer (Python 3.7+; Windows exe on GitHub releases) | LxXRM already applies its transforms. Its transforms edit game *data* (`L/x3story.obj`, scripts, director XML) and write into catalogs, so the results are platform-independent. Re-run only if you change the transform file. |
| X Plugin Manager (optional) | Only if you add more mods later |

## Hardware and storage

- Target: Snapdragon 8 Gen 2 / Adreno 740 (AYN Thor), 8 GB RAM minimum (TRASC's own guidance).
- Storage: Steam lists 10 GB for AP. LxXRM's `addon/` grew to about 2.55 GB in one forum report,
  plus about 0.7 GB of installer backup. Add the Wine prefix, DXVK/Box64 caches and save backups.
  Plan on **20 GB free** in app-private internal storage.
