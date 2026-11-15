/*
 * x3media: drive Wine's DirectShow media streams (amstream) the way X3: Albion Prelude does.
 *
 *   x3media.exe audio FILE RATE CHANNELS   IAudioMediaStream with a fixed PCM format set before
 *                                          OpenFile (X3: music and speech); prints what arrived.
 *   x3media.exe seek FILE CLIPS            IDirectDrawMediaStream on a 25 fps movie made of CLIPS
 *                                          one-second clips, each one colour (palette below) under
 *                                          noise. Plays it once to learn where each clip starts (no
 *                                          frame may be lost there), then seeks between clips while
 *                                          running, backwards too (X3: comms faces in mov\00001.dat).
 *                                          Every frame after a seek must show the clip sought, the
 *                                          first one at the target time, and no update may stall.
 *
 * Exit code 0 when the check passed. One line per result, prefixed "x3media:".
 * Build: i686-w64-mingw32-gcc -municode -O2 -o x3media.exe x3media.c -lole32 -luuid -lstrmiids -lddraw
 */
#define COBJMACROS
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <wchar.h>
#include <mmsystem.h>
#include <ddraw.h>
#include <mmstream.h>
#include <amstream.h>
#include <austream.h>
#include <ddstream.h>
#include <strmif.h>
#include <limits.h>

#ifndef ARRAY_SIZE
#define ARRAY_SIZE(a) (sizeof(a) / sizeof((a)[0]))
#endif

static const GUID mspid_primary_video = {0xa35ff56a, 0x9fda, 0x11d0, {0x8f, 0xdf, 0x00, 0xc0, 0x4f, 0xd9, 0x18, 0x9d}};
static const GUID mspid_primary_audio = {0xa35ff56b, 0x9fda, 0x11d0, {0x8f, 0xdf, 0x00, 0xc0, 0x4f, 0xd9, 0x18, 0x9d}};
static const GUID clsid_am_multimedia_stream = {0x49c47ce5, 0x9ba4, 0x11d0, {0x82, 0x12, 0x00, 0xc0, 0x4f, 0xc3, 0x2c, 0x45}};
static const GUID clsid_am_audio_data = {0xf2468580, 0xaf8a, 0x11d0, {0x82, 0x12, 0x00, 0xc0, 0x4f, 0xc3, 0x2c, 0x45}};
static const GUID iid_am_multimedia_stream = {0xbebe595c, 0x9a6f, 0x11d0, {0x8f, 0xde, 0x00, 0xc0, 0x4f, 0xd9, 0x18, 0x9d}};
static const GUID iid_audio_media_stream = {0xf7537560, 0xa3be, 0x11d0, {0x82, 0x12, 0x00, 0xc0, 0x4f, 0xc3, 0x2c, 0x45}};
static const GUID iid_audio_data = {0x54c719c0, 0xaf60, 0x11d0, {0x82, 0x12, 0x00, 0xc0, 0x4f, 0xc3, 0x2c, 0x45}};
static const GUID iid_ddraw_media_stream = {0xf4104fce, 0x9a70, 0x11d0, {0x8f, 0xde, 0x00, 0xc0, 0x4f, 0xd9, 0x18, 0x9d}};
static const GUID iid_media_seeking = {0x36b73880, 0xc2c8, 0x11cf, {0x8b, 0x46, 0x00, 0x80, 0x5f, 0x6c, 0xef, 0x60}};

/* ffmpeg's colour names, in clip order (tests/media/fixtures/README.md). */
static const struct { const char *name; int r, g, b; } palette[] =
{
    {"red", 255, 0, 0}, {"green", 0, 128, 0}, {"blue", 0, 0, 255}, {"yellow", 255, 255, 0},
    {"cyan", 0, 255, 255}, {"magenta", 255, 0, 255}, {"white", 255, 255, 255}, {"black", 0, 0, 0},
};

static DWORD WINAPI watchdog(void *arg)
{
    Sleep(90000);
    printf("x3media: timed out\n");
    fflush(stdout);
    ExitProcess(3);
    return 0;
}

static IAMMultiMediaStream *create_stream(const GUID *purpose, IMediaStream **stream)
{
    IAMMultiMediaStream *mms;
    HRESULT hr;

    if (FAILED(hr = CoCreateInstance(&clsid_am_multimedia_stream, NULL, CLSCTX_INPROC_SERVER,
            &iid_am_multimedia_stream, (void **)&mms)))
    {
        printf("x3media: no multimedia stream, hr %#lx\n", hr);
        exit(2);
    }
    if (FAILED(hr = IAMMultiMediaStream_Initialize(mms, STREAMTYPE_READ, 0, NULL))
            || FAILED(hr = IAMMultiMediaStream_AddMediaStream(mms, NULL, purpose, 0, stream)))
    {
        printf("x3media: stream setup failed, hr %#lx\n", hr);
        exit(2);
    }
    return mms;
}

static int test_audio(const WCHAR *file, DWORD rate, WORD channels)
{
    WAVEFORMATEX format = {WAVE_FORMAT_PCM, channels, rate, rate * channels * 2, channels * 2, 16, 0};
    IAudioStreamSample *sample;
    IAudioMediaStream *audio;
    unsigned int updates = 0;
    DWORD total = 0, size, actual;
    IMediaStream *stream;
    IAMMultiMediaStream *mms;
    IAudioData *data;
    int peak = 0;
    BYTE *pointer;
    HRESULT hr;

    mms = create_stream(&mspid_primary_audio, &stream);
    IMediaStream_QueryInterface(stream, &iid_audio_media_stream, (void **)&audio);
    if (FAILED(hr = IAudioMediaStream_SetFormat(audio, &format)))
        printf("x3media: SetFormat %lu Hz x%u: hr %#lx\n", rate, channels, hr);
    hr = IAMMultiMediaStream_OpenFile(mms, file, 0);
    printf("x3media: audio open %ls as %lu Hz x%u: hr %#lx\n", file, rate, channels, hr);
    if (FAILED(hr))
        return 1;

    CoCreateInstance(&clsid_am_audio_data, NULL, CLSCTX_INPROC_SERVER, &iid_audio_data, (void **)&data);
    IAudioData_SetBuffer(data, 8192, NULL, 0);
    IAudioData_SetFormat(data, &format);
    if (FAILED(hr = IAudioMediaStream_CreateSample(audio, data, 0, &sample)))
    {
        printf("x3media: CreateSample hr %#lx\n", hr);
        return 1;
    }
    IAMMultiMediaStream_SetState(mms, STREAMSTATE_RUN);
    while (updates < 64 && (hr = IAudioStreamSample_Update(sample, 0, NULL, NULL, 0)) == S_OK)
    {
        const short *pcm;
        DWORD i;

        IAudioData_GetInfo(data, &size, &pointer, &actual);
        pcm = (const short *)pointer;
        for (i = 0; i < actual / 2; ++i)
            if (abs(pcm[i]) > peak) peak = abs(pcm[i]);
        total += actual;
        ++updates;
    }
    printf("x3media: audio %ls: %lu bytes in %u updates (last hr %#lx), peak %d\n", file, total, updates, hr, peak);
    IAMMultiMediaStream_SetState(mms, STREAMSTATE_STOP);
    return total >= rate && peak > 1000 ? 0 : 1;
}

static int nearest_colour(int r, int g, int b)
{
    int best = 0, best_distance = INT_MAX;
    unsigned int i;

    for (i = 0; i < ARRAY_SIZE(palette); ++i)
    {
        int distance = (r - palette[i].r) * (r - palette[i].r) + (g - palette[i].g) * (g - palette[i].g)
                + (b - palette[i].b) * (b - palette[i].b);
        if (distance < best_distance)
        {
            best_distance = distance;
            best = i;
        }
    }
    return best;
}

static int channel(DWORD pixel, DWORD mask)
{
    DWORD shift = 0, max;

    if (!mask) return 0;
    while (!(mask & (1u << shift))) ++shift;
    max = mask >> shift;
    return ((pixel & mask) >> shift) * 255 / max;
}

/* Mean colour of a 16x16 block in the middle of the picture: the clips carry noise, so that the
 * movie has the near-constant bitrate of a real one (GStreamer's MPEG-PS demuxer seeks by it). */
static int surface_colour(IDirectDrawSurface *surface, const RECT *rect)
{
    DDSURFACEDESC desc = {sizeof(desc)};
    int x, y, r = 0, g = 0, b = 0, colour;
    DWORD bpp;

    if (FAILED(IDirectDrawSurface_Lock(surface, NULL, &desc, DDLOCK_WAIT, NULL)))
        return -1;
    bpp = desc.ddpfPixelFormat.dwRGBBitCount;
    for (y = -8; y < 8; ++y)
        for (x = -8; x < 8; ++x)
        {
            const BYTE *p = (const BYTE *)desc.lpSurface + ((rect->top + rect->bottom) / 2 + y) * desc.lPitch
                    + ((rect->left + rect->right) / 2 + x) * (bpp / 8);
            DWORD pixel = 0;

            if (bpp == 16) pixel = *(const WORD *)p;
            else if (bpp == 24) pixel = p[0] | (p[1] << 8) | (p[2] << 16);
            else if (bpp == 32) pixel = *(const DWORD *)p;
            r += channel(pixel, desc.ddpfPixelFormat.dwRBitMask);
            g += channel(pixel, desc.ddpfPixelFormat.dwGBitMask);
            b += channel(pixel, desc.ddpfPixelFormat.dwBBitMask);
        }
    colour = nearest_colour(r / 256, g / 256, b / 256);
    IDirectDrawSurface_Unlock(surface, NULL);
    return colour;
}

static int test_seek(const WCHAR *file, int clips)
{
    static const int order[] = {3, 1, 6, 2, 5, 0, 7, 4, 4, 2};
    unsigned int i, played, frames = 0, wrong = 0, off_target = 0, failures = 0;
    LONGLONG clip_start[ARRAY_SIZE(palette)];
    IDirectDrawStreamSample *sample;
    IDirectDrawMediaStream *ddraw;
    IDirectDrawSurface *surface;
    IMediaSeeking *seeking;
    IGraphBuilder *graph;
    IMediaStream *stream;
    IAMMultiMediaStream *mms;
    int previous = -1;
    RECT rect;
    HRESULT hr;

    mms = create_stream(&mspid_primary_video, &stream);
    hr = IAMMultiMediaStream_OpenFile(mms, file, 0);
    printf("x3media: video open %ls: hr %#lx\n", file, hr);
    if (FAILED(hr))
        return 1;
    IMediaStream_QueryInterface(stream, &iid_ddraw_media_stream, (void **)&ddraw);
    if (FAILED(hr = IDirectDrawMediaStream_CreateSample(ddraw, NULL, NULL, 0, &sample)))
    {
        printf("x3media: CreateSample hr %#lx\n", hr);
        return 1;
    }
    IDirectDrawStreamSample_GetSurface(sample, &surface, &rect);
    IAMMultiMediaStream_GetFilterGraph(mms, &graph);
    IGraphBuilder_QueryInterface(graph, &iid_media_seeking, (void **)&seeking);
    IAMMultiMediaStream_SetState(mms, STREAMSTATE_RUN);

    /* Where each clip starts when the movie simply plays: seeking there must show the same. */
    for (i = 0; i < ARRAY_SIZE(clip_start); ++i) clip_start[i] = -1;
    for (i = 0; i < 400 && IDirectDrawStreamSample_Update(sample, 0, NULL, NULL, 0) == S_OK; ++i)
    {
        STREAM_TIME start = 0, end = 0;
        int colour = surface_colour(surface, &rect);

        IDirectDrawStreamSample_GetSampleTimes(sample, &start, &end, NULL);
        if (colour >= 0 && colour != previous && clip_start[colour] < 0)
            clip_start[colour] = start;
        previous = colour;
    }
    played = i;
    printf("x3media: played %u frames; clips start at", played);
    for (i = 0; i < (unsigned int)clips; ++i)
        printf(" %s %.2f", palette[i].name, clip_start[i] / 1e7);
    printf("\n");
    for (i = 0; i < (unsigned int)clips; ++i)
        if (clip_start[i] < 0)
        {
            printf("x3media: clip %d (%s) never appeared in plain playback\n", i, palette[i].name);
            return 1;
        }
    /* An application that takes frames as they come must get them all: GStreamer's decoder used to
     * drop the next frame whenever amstream reported the last one even slightly late. */
    if (played < (unsigned int)clips * 25 - 3)
    {
        printf("x3media: plain playback lost frames: %u of %d\n", played, clips * 25);
        ++failures;
    }

    for (i = 0; i < ARRAY_SIZE(order); ++i)
    {
        int clip = order[i] % clips, frame;
        LONGLONG target = clip_start[clip] + 3000000;   /* 0.3 s into the clip, as X3 seeks to a face */
        char line[1024];
        int length;

        hr = IMediaSeeking_SetPositions(seeking, &target, AM_SEEKING_AbsolutePositioning, NULL, AM_SEEKING_NoPositioning);
        length = sprintf(line, "x3media: seek to %.2f in clip %d (%s), hr %#lx, frames:", target / 1e7, clip, palette[clip].name, hr);
        for (frame = 0; frame < 10; ++frame)    /* 0.4 s: all inside the clip */
        {
            STREAM_TIME start = 0, end = 0;
            int colour;

            if ((hr = IDirectDrawStreamSample_Update(sample, 0, NULL, NULL, 0)) != S_OK)
            {
                length += sprintf(line + length, " update %#lx", hr);
                ++failures;
                break;
            }
            IDirectDrawStreamSample_GetSampleTimes(sample, &start, &end, NULL);
            colour = surface_colour(surface, &rect);
            ++frames;
            /* GStreamer's MPEG-PS demuxer lands up to a second either side of the target: the
             * previous face, or the next one, showed. */
            if (colour != clip) ++wrong;
            /* The first frame must be the one showing at the target (within a frame). */
            if (!frame && (start > target || target - start > 400000)) ++off_target;
            length += sprintf(line + length, " %s@%.2f", colour >= 0 ? palette[colour].name : "?", start / 1e7);
        }
        printf("%s\n", line);
    }
    printf("x3media: seek %ls: %u frames, %u from another clip, %u seeks starting off the target, "
            "%u failed updates\n", file, frames, wrong, off_target, failures);
    IAMMultiMediaStream_SetState(mms, STREAMSTATE_STOP);
    return !frames || wrong || off_target || failures;
}

int wmain(int argc, WCHAR **argv)
{
    int result = 2;

    setvbuf(stdout, NULL, _IONBF, 0);
    CloseHandle(CreateThread(NULL, 0, watchdog, NULL, 0, NULL));
    CoInitializeEx(NULL, COINIT_MULTITHREADED);
    if (argc == 5 && !wcscmp(argv[1], L"audio"))
        result = test_audio(argv[2], wcstoul(argv[3], NULL, 10), wcstoul(argv[4], NULL, 10));
    else if (argc == 4 && !wcscmp(argv[1], L"seek"))
        result = test_seek(argv[2], _wtoi(argv[3]));
    else
        printf("x3media: usage: x3media audio FILE RATE CHANNELS | x3media seek FILE CLIPS\n");
    printf("x3media: %s\n", result ? "FAILED" : "passed");
    return result;
}
