# Third-party components

The X3 Modded APK reuses binaries from
[trasc-server-android](https://github.com/Russianranger/trasc-server-android) at commit
`99e8c86fa2666c8d4da6c52f4b6f45160aa6d795` (release `v0.7.0-beta`). They are not rebuilt here.
`scripts/fetch_trasc_payload.py` downloads them and checks every file against the SHA-256 values in
`payload/trasc-payload.lock.json`. The APK records the result in
`assets/payload/payload-provenance.json`.

Each preview release also carries TRASC's `launcher-sources.tar.gz`, byte for byte, as the
corresponding source for these binaries. It contains the pinned source archives, patches and build
recipes. Its SHA-256 is pinned in the same lock file. Keep these notices and that archive with any
copy of the APK you pass on.

| In the APK | Component | License |
| --- | --- | --- |
| `lib/arm64-v8a/libproot.so`, `libproot-loader.so` | [Termux PRoot](https://github.com/termux/proot/tree/7266fb3e8516535682f5a9c8f3a7e70f6506eddb) with TRASC's seccomp acceleration patch, statically linking [talloc 2.4.3](https://www.samba.org/ftp/talloc/talloc-2.4.3.tar.gz) | GPL-2.0-or-later (PRoot), LGPL-3.0-or-later (talloc) |
| `assets/payload/wineserver` | Wine 10.0 x86-64 wineserver with TRASC's translated-exit grace patch | LGPL-2.1-or-later |
| `assets/payload/turnip.so`, `turnip-26.0.0.so` | Mesa 24.3.4 and 26.0.0 Turnip (Qualcomm KGSL), built from unmodified release source | MIT, plus the component notices in Mesa's source |
| `assets/payload/dxvk-d3d9.dll`, `dxvk-d3d9-x64.dll` | [DXVK 2.5.3](https://github.com/doitsujin/dxvk/releases/tag/v2.5.3) `d3d9.dll`, x86 and x64. The x64 file is taken from the upstream release archive (SHA-256 `d8e6ef7d…ea1eb8`). | zlib |
| `assets/payload/libasound_module_pcm_trasc.so` | TRASC ALSA PCM endpoint (feeds Android AudioTrack) | MIT |
| `assets/payload/box64` | [Box64](https://github.com/ptitSeb/box64/tree/2f130fab1d6e1a4ee8a71dc60cfdfcc839ad192a) 0.4.4, the same commit as the runtime, with [`patches/box64`](patches/box64) applied, built by this repository's CI (`scripts/build_box64.sh`) | MIT |
| `assets/payload/x11-frame-bridge`, `vulkan-probe` | TRASC frame/input helper and Vulkan preflight. The helper statically links libXdamage and libXtst; their notices are in `presentation-notices.txt`. | MIT / X11 |

The app downloads TRASC's **client runtime** (`client-runtime-v1`, SHA-256
`2f130c07…75c76c4`) on first use rather than bundling it. That runtime is a Debian Bookworm arm64
image with [Box64 0.4.4](https://github.com/ptitSeb/box64/tree/2f130fab1d6e1a4ee8a71dc60cfdfcc839ad192a)
(MIT), Wine 10.0 WoW64 from [Kron4ek](https://github.com/Kron4ek/Wine-Builds/releases/tag/10.0)
(LGPL-2.1-or-later), TigerVNC (GPL-2.0-or-later), Python and Debian support libraries. Its
corresponding sources are published with that runtime release as `client-runtime-sources.tar.gz`.
Package licence notices are kept in `/usr/share/doc` inside the image.

The optional **media add-on** (`media-addon-v1` release, downloaded on request) is
GStreamer 1.22 from Debian Bookworm arm64: core, plugins-base, plugins-good and plugins-ugly, plus
`mpegpsdemux` and `videoparsersbad` from plugins-bad, with their Debian dependencies. These are
mostly LGPL-2.1-or-later. Package names and versions are listed in the release's
`media-addon.json`, and the sources are at [sources.debian.org](https://sources.debian.org). The
recipe is `scripts/build_media_addon.sh`.

## Code adapted from TRASC

These parts of the Android app and runner are copied from TRASC, or adapted from it, with the same
author's permission:

- **Android:** the RFB client, controller and layer engine, audio bridge, PRoot acceleration
  preflight and tar extractor.
- **Runner:** the presentation, metrics, Vulkan, audio and log-retention helpers.

Each file names its TRASC origin in a header comment. Everything else is original to this
repository.

## Not included

This project includes none of the following:

- X3 executables, game data, Steam DRM or `steam_api.dll`
- LxXRM files or other mod files
- Microsoft libraries
- Winlator binaries

You import your own legally owned X3: Albion Prelude installation. The app copies it into its
private storage on your own device.
