/*
 * x3media: drive Wine's DirectShow media streams (amstream) the way X3: Albion Prelude does.
 *
 *   x3media.exe audio FILE RATE CHANNELS   IAudioMediaStream with a fixed PCM format set before
 *                                          OpenFile (X3: music and speech); prints what arrived.
 *   x3media.exe seek FILE CLIPS            IDirectDrawMediaStream on a movie made of CLIPS one-second
 *                                          solid-colour clips (palette below); seeks between clips
 *                                          while running (X3: comms faces in mov\00001.dat) and
 *                                          checks every frame it gets against the clip's colour.
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

static int surface_colour(IDirectDrawSurface *surface, const RECT *rect)
{
    DDSURFACEDESC desc = {sizeof(desc)};
    const BYTE *row;
    DWORD pixel = 0, bpp;
    int colour;

    if (FAILED(IDirectDrawSurface_Lock(surface, NULL, &desc, DDLOCK_WAIT, NULL)))
        return -1;
    bpp = desc.ddpfPixelFormat.dwRGBBitCount;
    row = (const BYTE *)desc.lpSurface + ((rect->top + rect->bottom) / 2) * desc.lPitch;
    row += ((rect->left + rect->right) / 2) * (bpp / 8);
    if (bpp == 16) pixel = *(const WORD *)row;
    else if (bpp == 24) pixel = row[0] | (row[1] << 8) | (row[2] << 16);
    else if (bpp == 32) pixel = *(const DWORD *)row;
    colour = nearest_colour(channel(pixel, desc.ddpfPixelFormat.dwRBitMask),
            channel(pixel, desc.ddpfPixelFormat.dwGBitMask), channel(pixel, desc.ddpfPixelFormat.dwBBitMask));
    IDirectDrawSurface_Unlock(surface, NULL);
    return colour;
}

static int test_seek(const WCHAR *file, int clips)
{
    static const int order[] = {3, 1, 6, 2, 5, 0, 7, 4, 4, 2};
    unsigned int i, frames = 0, wrong = 0, failures = 0;
    IDirectDrawStreamSample *sample;
    IDirectDrawMediaStream *ddraw;
    IDirectDrawSurface *surface;
    IMediaSeeking *seeking;
    IGraphBuilder *graph;
    IMediaStream *stream;
    IAMMultiMediaStream *mms;
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

    for (i = 0; i < ARRAY_SIZE(order); ++i)
    {
        int clip = order[i] % clips, frame, seen[8] = {0};
        LONGLONG position = clip * (LONGLONG)10000000 + 400000;   /* 40 ms into the clip */
        char line[256];
        int length;

        hr = IMediaSeeking_SetPositions(seeking, &position, AM_SEEKING_AbsolutePositioning, NULL, AM_SEEKING_NoPositioning);
        length = sprintf(line, "x3media: seek to clip %d (%s), hr %#lx, frames:", clip, palette[clip].name, hr);
        for (frame = 0; frame < 6; ++frame)
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
            if (colour != clip) ++wrong;
            if (colour >= 0) ++seen[colour];
            length += sprintf(line + length, " %s@%.2f", colour >= 0 ? palette[colour].name : "?", start / 1e7);
        }
        printf("%s\n", line);
    }
    printf("x3media: seek %ls: %u frames, %u from the wrong clip, %u failed updates\n", file, frames, wrong, failures);
    IAMMultiMediaStream_SetState(mms, STREAMSTATE_STOP);
    return !frames || wrong || failures;
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
