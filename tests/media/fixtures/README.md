# Media test fixtures

Made here with ffmpeg's own test pattern (no game or third-party content), one second at 25 fps:

    ffmpeg -f lavfi -i testsrc=size=160x120:rate=25 -t 1 -c:v mpeg1video -b:v 200k -g 12 -bf 0 -f mpeg1video comms.m1v
    ffmpeg -i comms.m1v -c copy -f mpeg comms.mpg

`comms.m1v` is an MPEG-1 video elementary stream (starts `00 00 01 B3`), `comms.mpg` the same
video in an MPEG-1 program stream (starts `00 00 01 BA`). X3's comm faces in `mov/*.dat` are
MPEG-1 video; `scripts/build_media_addon.sh` decodes both natively and through Box64.
