Native arm64 GStreamer for the X3 Modded app. With it, Wine's `winegstreamer` can decode what X3
plays through DirectShow: music, comms voices and movies. Sound effects use DirectSound and work
without it.

The app downloads `media-addon-arm64.tar.gz` and checks its SHA-256 against the value built into
the APK. It then unpacks the archive over the app's runtime (TRASC `client-runtime-v1`).
`media-addon.json` lists:

- the archive's hash and size
- the Debian Bookworm packages it adds
- the tests CI ran on it before publishing: element checks, native WAV and MP3 decodes, and the
  same decodes from x86-64 code through Box64's wrapped GStreamer

Contents:

- GStreamer 1.22 core, plus plugins-base, -good and -ugly from Debian Bookworm (arm64)
- from -bad, only `mpegpsdemux` and `videoparsersbad` (MPEG program streams)

All of it is Debian packages under their own licences (mostly LGPL-2.1+). Sources are on
[sources.debian.org](https://sources.debian.org) for the versions listed in `media-addon.json`.
The recipe is `scripts/build_media_addon.sh` in this repository.
