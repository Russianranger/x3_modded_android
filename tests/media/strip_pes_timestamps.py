#!/usr/bin/env python3
"""Copy an MPEG-1 program stream with the time stamps taken out of its video packets.

X3's comms face movie (mov/00001.dat) has none, so GStreamer hands its frames over untimed
(fourteenth Thor run). Each video PES header's PTS or PTS+DTS field becomes stuffing plus the
"no time stamp" marker, so every packet keeps its size and the pack structure is unchanged.

Usage: python3 -I tests/media/strip_pes_timestamps.py IN.mpg OUT.mpg
"""
import sys


def strip(data):
    data = bytearray(data)
    i = stripped = 0
    while i + 6 <= len(data):
        if data[i:i + 3] != b'\0\0\1':
            i += 1
            continue
        sid = data[i + 3]
        if sid == 0xBA:            # MPEG-1 pack header
            i += 12
            continue
        if sid == 0xB9:            # end code
            break
        if sid < 0xBB:
            i += 1
            continue
        length = int.from_bytes(data[i + 4:i + 6], 'big')
        if 0xE0 <= sid <= 0xEF:
            j = i + 6
            while data[j] == 0xFF:
                j += 1
            std = None
            if data[j] & 0xC0 == 0x40:
                std, j = j, j + 2
            size = {2: 5, 3: 10}.get(data[j] >> 4)
            if size:
                stuffing = data[i + 6:std if std is not None else j]
                field = data[std:std + 2] if std is not None else b''
                new = stuffing + b'\xff' * (size - 1) + field + b'\x0f'
                if len(stuffing) + size - 1 > 16:
                    raise SystemExit('too much stuffing at offset %d' % i)
                data[i + 6:j + size] = new
                stripped += 1
        i += 6 + length
    return bytes(data), stripped


if __name__ == '__main__':
    with open(sys.argv[1], 'rb') as source:
        out, count = strip(source.read())
    with open(sys.argv[2], 'wb') as target:
        target.write(out)
    print('%d video packets lost their time stamps' % count)
