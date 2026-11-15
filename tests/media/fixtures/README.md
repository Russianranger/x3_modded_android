# Media test fixtures

All made here with ffmpeg from its own test sources (no game or third-party content).

| File | What it stands in for | Made with |
|---|---|---|
| `comms.m1v` | MPEG-1 video elementary stream | `ffmpeg -f lavfi -i testsrc=size=160x120:rate=25 -t 1 -c:v mpeg1video -b:v 200k -g 12 -bf 0 -f mpeg1video comms.m1v` |
| `comms.mpg` | the same in an MPEG-1 program stream (`mov/*.dat` faces) | `ffmpeg -i comms.m1v -c copy -f mpeg comms.mpg` |
| `faces-clips.mpg` | `mov/00001.dat`: many faces in one MPEG-1 movie that X3 seeks around in | eight one-second solid-colour clips (red, green, blue, yellow, cyan, magenta, white, black), 128×96, 25 fps, concatenated, `-c:v mpeg1video -b:v 400k -g 12 -bf 2 -f mpeg` |
| `music-44k.mp3` | sector music, at the rate X3 mixes at | `sine=frequency=440:sample_rate=44100:duration=3`, stereo, `-c:a libmp3lame -b:a 96k` |
| `music-48k.mp3` | the main menu track (`soundtrack/08404.mp3` is 48 kHz) | the same at `sample_rate=48000` |
| `speech-22k-mono-unpositioned.wav` | what libav's WMA decoder makes of mono speech: mono with no channel position | two seconds of a 330 Hz sine, 22050 Hz, 16-bit, `WAVE_FORMAT_EXTENSIBLE` with channel mask 0 (written by a few lines of Python) |
| `speech-wma2.dat` | `addon/mov/00144.dat`, `00244.dat`: speech, WMA 2 in ASF | `sine=frequency=330:sample_rate=22050:duration=3`, mono, `-c:a wmav2 -b:a 32k -f asf` |

`scripts/build_media_addon.sh` decodes `comms.*` natively and through Box64.
`tests/wine/x3media.c` plays the others through Wine's DirectShow media streams the way X3 does
(`tests/wine/run_dll_tests.py`).
