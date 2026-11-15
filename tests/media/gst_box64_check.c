/*
 * x86-64 program run under Box64 inside the runtime: decodes a file through the *native* arm64
 * GStreamer that Box64 wraps, the way Wine's winegstreamer.so does for X3's music and voices.
 * The fakesink "handoff" signal calls back from GStreamer's streaming thread into emulated code,
 * as winegstreamer's pad callbacks do. dlopen keeps the build free of x86-64 GStreamer headers.
 *
 * Usage: box64 gst_box64_check FILE   -> exit 0 when the file decodes to PCM and reaches EOS.
 */
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

static unsigned long long total_bytes;
static unsigned buffers;
static size_t (*buffer_get_size)(void *buffer);

static void handoff(void *sink, void *buffer, void *pad, void *data)
{
    (void)sink; (void)pad; (void)data;
    total_bytes += buffer_get_size(buffer);
    buffers++;
}

#define LOAD(lib, name) do { if (!(name = dlsym(lib, #name))) { fprintf(stderr, "missing %s\n", #name); return 2; } } while (0)

int main(int argc, char **argv)
{
    void (*gst_init)(int *, char ***);
    void *(*gst_parse_launch)(const char *, void **);
    void *(*gst_bin_get_by_name)(void *, const char *);
    int (*gst_element_set_state)(void *, int);
    void *(*gst_element_get_bus)(void *);
    void *(*gst_bus_timed_pop_filtered)(void *, uint64_t, int);
    unsigned long (*g_signal_connect_data)(void *, const char *, void *, void *, void *, int);
    void *gst, *gobject, *error = NULL, *pipeline, *sink, *eos;
    char description[1024];
    int video;

    if (argc < 2) { fprintf(stderr, "usage: %s FILE [video]\n", argv[0]); return 2; }
    gst = dlopen("libgstreamer-1.0.so.0", RTLD_NOW);
    gobject = dlopen("libgobject-2.0.so.0", RTLD_NOW);
    if (!gst || !gobject) { fprintf(stderr, "dlopen: %s\n", dlerror()); return 2; }
    LOAD(gst, gst_init); LOAD(gst, gst_parse_launch); LOAD(gst, gst_bin_get_by_name);
    LOAD(gst, gst_element_set_state); LOAD(gst, gst_element_get_bus); LOAD(gst, gst_bus_timed_pop_filtered);
    if (!(buffer_get_size = dlsym(gst, "gst_buffer_get_size"))) { fprintf(stderr, "missing gst_buffer_get_size\n"); return 2; }
    LOAD(gobject, g_signal_connect_data);

    gst_init(NULL, NULL);
    /* "video" as a second argument: decode to the 32-bit RGB that winegstreamer hands amstream. */
    video = argc > 2 && !strcmp(argv[2], "video");
    snprintf(description, sizeof description,
             video ? "filesrc location=\"%s\" ! decodebin ! videoconvert ! video/x-raw,format=BGRx "
                     "! fakesink name=sink signal-handoffs=true sync=false"
                   : "filesrc location=\"%s\" ! decodebin ! audioconvert ! audio/x-raw,format=S16LE "
                     "! fakesink name=sink signal-handoffs=true sync=false", argv[1]);
    if (!(pipeline = gst_parse_launch(description, &error)) || error) { fprintf(stderr, "pipeline failed\n"); return 1; }
    sink = gst_bin_get_by_name(pipeline, "sink");
    g_signal_connect_data(sink, "handoff", (void *)handoff, NULL, NULL, 0);
    gst_element_set_state(pipeline, 4 /* GST_STATE_PLAYING */);
    eos = gst_bus_timed_pop_filtered(gst_element_get_bus(pipeline), 30ull * 1000000000ull, 1 /* GST_MESSAGE_EOS */);
    gst_element_set_state(pipeline, 1 /* GST_STATE_NULL */);
    printf("%s: %s, %u buffers, %llu %s bytes\n", argv[1], eos ? "EOS" : "no EOS", buffers, total_bytes, video ? "BGRx" : "PCM");
    return eos && total_bytes > 0 ? 0 : 1;
}
