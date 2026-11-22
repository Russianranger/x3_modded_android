"""Unit tests for the rootfs-side supervisor (no Wine, Box64 or Android needed)."""
import json
import os
import struct
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "runner"))

import client_audio  # noqa: E402
import pe_info  # noqa: E402
import client_metrics  # noqa: E402
import x3_runner  # noqa: E402


def make_pe(machine=0x14C, laa=False, imports=("KERNEL32.dll",), plus=False, gui=True):
    optional_size = 240 if plus else 224
    data = bytearray(0x600)
    data[0:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x80)
    data[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<HHIIIHH", data, 0x84, machine, 1, 0, 0, 0, optional_size, 0x0102 | (0x20 if laa else 0))
    optional = 0x98
    struct.pack_into("<H", data, optional, 0x20B if plus else 0x10B)
    struct.pack_into("<H", data, optional + 68, 2 if gui else 3)
    directories = optional + (112 if plus else 96)
    struct.pack_into("<II", data, directories + 8, 0x1000, 20 * (len(imports) + 1))
    section = optional + optional_size
    data[section:section + 8] = b".idata\0\0"
    struct.pack_into("<IIII", data, section + 8, 0x200, 0x1000, 0x200, 0x400)
    names_rva = 0x1000 + 20 * (len(imports) + 1)
    cursor = 0x400
    for name in imports:
        struct.pack_into("<I", data, cursor + 12, names_rva)
        raw = name.encode() + b"\0"
        data[0x400 + names_rva - 0x1000:0x400 + names_rva - 0x1000 + len(raw)] = raw
        names_rva += len(raw)
        cursor += 20
    return bytes(data)


class PEInfoTests(unittest.TestCase):
    def test_i386_steam_laa(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "X3AP.exe")
            path.write_bytes(make_pe(laa=True, imports=("KERNEL32.dll", "steam_api.dll")))
            info = pe_info.inspect(path)
            self.assertEqual(info["machine"], "i386")
            self.assertTrue(info["large_address_aware"])
            self.assertTrue(info["steam_api"])
            self.assertEqual(info["imports"], ["KERNEL32.dll", "steam_api.dll"])

    def test_x86_64_plain(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "X3AP.exe")
            path.write_bytes(make_pe(machine=0x8664, plus=True))
            info = pe_info.inspect(path)
            self.assertEqual(info["machine"], "x86_64")
            self.assertFalse(info["steam_api"])

    def test_rejects_non_pe(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "SETUP.bat")
            path.write_text("@echo off\n")
            with self.assertRaises(pe_info.PEError):
                pe_info.inspect(path)


class RequestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.game = Path(self.tmp.name, "game")
        (self.game / "LxXRM").mkdir(parents=True)
        (self.game / "X3AP.exe").write_bytes(make_pe(imports=("KERNEL32.dll", "steam_api.dll")))
        (self.game / "LxXRM" / "SETUP.bat").write_text("@echo off\n")
        self.request = {"mode": "game", "program": "X3AP.exe", "resolution": "1280x720", "renderer": "turnip",
                        "turnip_driver": "24.3.4", "display_fps": 60, "presentation_mode": "rfb",
                        "audio": True, "dxvk_hud": True, "arguments": ["-skipintro"]}

    def tearDown(self):
        self.tmp.cleanup()

    def test_game_request(self):
        info = x3_runner.validate_request(self.request, self.game)
        self.assertEqual(info["machine"], "i386")
        self.assertTrue(info["steam_api"])

    def test_paths_cannot_escape(self):
        for bad in ("../X3AP.exe", "/X3AP.exe", "LxXRM\\SETUP.bat", "a/./X3AP.exe", "", "notes.txt", "Missing.exe"):
            with self.assertRaises(ValueError, msg=bad):
                x3_runner.program_path(bad, self.game)

    def test_symlink_rejected(self):
        os.symlink(self.game / "X3AP.exe", self.game / "Link.exe")
        with self.assertRaises(ValueError):
            x3_runner.program_path("Link.exe", self.game)

    def test_cpu_profiles_are_validated(self):
        for profile in ("fast", "fastest", "balanced", "accurate"):
            x3_runner.validate_request(dict(self.request, cpu_profile=profile), self.game)
        for key, value in (("cpu_profile", "turbo"), ("controller_passthrough", "yes")):
            with self.assertRaises(ValueError, msg=key):
                x3_runner.validate_request(dict(self.request, **{key: value}), self.game)

    def test_bad_options(self):
        for key, value in (("resolution", "999x999"), ("renderer", "virgl"), ("display_fps", 45),
                           ("audio", "yes"), ("arguments", "-skipintro"), ("turnip_driver", "1.0")):
            request = dict(self.request, **{key: value})
            with self.assertRaises(ValueError, msg=key):
                x3_runner.validate_request(request, self.game)

    def test_commands(self):
        args, cwd = x3_runner.build_command(self.request, {"kind": "exe"}, pin=False)
        self.assertEqual(args[2:], ["explorer", "/desktop=X3,1280x720", "D:\\X3AP.exe", "-skipintro"])
        args, _ = x3_runner.build_command(self.request, {"kind": "exe"}, pin=True)
        self.assertEqual(args[4:], [x3_runner.X3PIN_WINDOWS, "D:\\X3AP.exe", "-skipintro"])
        self.assertTrue(x3_runner.X3PIN_WINDOWS.startswith("Z:\\") and x3_runner.X3PIN_WINDOWS.endswith("\\x3pin.exe"))
        tool = dict(self.request, mode="program", program="tools/X3Editor.exe")
        self.assertEqual(x3_runner.build_command(tool, {"kind": "exe"}, pin=True)[0][4:], ["D:\\tools\\X3Editor.exe", "-skipintro"])
        self.assertEqual(cwd, x3_runner.GAME)
        batch = dict(self.request, program="LxXRM/SETUP.bat", arguments=[])
        args, cwd = x3_runner.build_command(batch, {"kind": "bat"})
        self.assertEqual(args[4:], ["cmd.exe", "/k", "D:\\LxXRM\\SETUP.bat"])
        self.assertEqual(cwd, x3_runner.GAME / "LxXRM")


class LogTests(unittest.TestCase):
    def test_fatal_errors(self):
        crash = "wine: Unhandled page fault on read access at address 0x1234 starting debugger\n"
        self.assertIn("0x1234", x3_runner.fatal_launch_error(crash, game=True))
        self.assertIsNone(x3_runner.fatal_launch_error(crash, game=False))
        missing = ("err:module:import_dll Library d3dx9_43.dll (which is needed by L\"D:\\\\X3AP.exe\") not found\n"
                   "err:module:LdrInitializeThunk Importing dlls for L\"D:\\\\X3AP.exe\" failed, status c0000135\n")
        self.assertIn("d3dx9_43.dll", x3_runner.fatal_launch_error(missing))

    def test_wine_log_parsing(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = x3_runner.WineLog(Path(tmp, "x3-wine.log"), game=True)
            log.observe(b"info:  DXVK: v2.5.3\n")
            log.observe(b'0024:trace:loaddll:build_module Loaded L"C:\\\\windows\\\\system32\\\\dsound.dll" at 7B000000: builtin\n')
            for _ in range(2):
                log.observe(b"1.0:0020:0024:trace:fps:d3d9_swapchain_Present 0x12 @ approx 58.20fps\n")
            fields, error = log.snapshot()
            self.assertEqual(fields["dxvk_loaded"], "2.5.3")
            self.assertEqual(fields["dsound_loaded"], "builtin")
            self.assertAlmostEqual(fields["wine_present"]["per_second"], 58.2)
            self.assertIsNone(error)


class AudioTests(unittest.TestCase):
    def test_asound_has_default_and_dsp0(self):
        text = client_audio.asound_conf("/opt/x3/libasound_module_pcm_trasc.so")
        self.assertIn('pcm_type.trasc { lib "/opt/x3/libasound_module_pcm_trasc.so" }', text)
        self.assertIn("pcm.!default { type plug", text)
        self.assertIn("pcm.dsp0 { type plug", text)

    def test_environment_disables_pulse(self):
        env = {"WINEDLLOVERRIDES": "mscoree="}
        client_audio.configure_environment(env, Path("/session"))
        self.assertTrue(env["WINEDLLOVERRIDES"].endswith(";winepulse.drv=d"))
        self.assertEqual(env["TRASC_AUDIO_SOCKET"], "/session/audio.sock")


class FirstDeviceRunTests(unittest.TestCase):
    """Regressions from the first launch on the AYN Thor (black screen, Nov 2026)."""

    # Trimmed from that run's x3-wine.log.
    ABORT = (
        "20246.738:0200:0204:trace:loaddll:build_module Loaded L\"C:\\\\windows\\\\system32\\\\ir50_32.dll\" at 79210000: builtin\n"
        "20246.742:0200:0204:err:module:DelayLoadFailureHook failed to delay load winegstreamer.dll.winegstreamer_create_video_decoder\n"
        "wine: Call from 000000007BBEA5FE to unimplemented function winegstreamer.dll.winegstreamer_create_video_decoder, aborting\n"
        "wine: Call from 7BBEA5FE to unimplemented function winegstreamer.dll.winegstreamer_create_video_decoder, aborting\n"
        "wine: Unimplemented function winegstreamer.dll.winegstreamer_create_video_decoder called at address 7BBEA5FE (thread 0204), starting debugger...\n"
    )

    def test_abort_on_missing_function_is_reported(self):
        message = x3_runner.fatal_launch_error(self.ABORT, game=True)
        self.assertIn("winegstreamer.dll winegstreamer_create_video_decoder", message)
        self.assertIn("disabled or could not load", message)
        log = x3_runner.WineLog(Path(tempfile.gettempdir()) / "unused.log", game=True)
        log.observe(self.ABORT.encode())
        self.assertEqual(log.snapshot()[1], message)

    def test_untranslated_instruction_is_named(self):
        # Second Thor run (0.1.2): X3AP.exe's start-up "smsw ax" reached unpatched Box64.
        log = ("[BOX64] 32707|0x4f9975: Unimplemented 32bits Opcode (00 01 74 5D) 66 0F 01 E0 A8 04 75 55 55 8B F4 81 EC 00 02\n"
               "wine: Unhandled illegal instruction at address 004F9975 (thread 0144), starting debugger...\n")
        message = x3_runner.fatal_launch_error(log, game=True)
        self.assertIn("unhandled illegal instruction at 0x004F9975", message)
        self.assertIn("Box64 cannot run the x86 instruction 66 0F 01 E0 A8 04", message)
        page_fault = "wine: Unhandled page fault on read access to 00000000 at address 004F1234 (thread 0144), starting debugger...\n"
        self.assertNotIn("Box64", x3_runner.fatal_launch_error(log.splitlines()[0] + "\n" + page_fault, game=True))

    def test_dxvk_stays_off_fifo_unless_vsync_is_requested(self):
        # Third Thor run (0.1.3): FIFO + vkWaitForPresentKHR never returned -> black screen.
        default = x3_runner.dxvk_configuration({"display_fps": 60})
        self.assertEqual(default, "d3d9.presentInterval = 0; d3d9.maxFrameRate = 60")
        new = x3_runner.dxvk_configuration({"display_fps": 60, "dxvk_version": "3.1.1"})
        self.assertEqual(new, "d3d9.presentInterval = 0; dxvk.maxFrameRate = 60")
        self.assertEqual(x3_runner.dxvk_configuration({"display_fps": 30, "vsync": True}), "d3d9.maxFrameRate = 30")
        request = dict(mode="game", program="X3AP.exe", resolution="1280x720", vsync="yes")
        with self.assertRaisesRegex(ValueError, "vsync"):
            x3_runner.validate_request(request)

    def test_dxvk_version_is_checked_and_reported(self):
        request = dict(mode="game", program="X3AP.exe", resolution="1280x720", dxvk_version="9.9")
        with self.assertRaisesRegex(ValueError, "DXVK version"):
            x3_runner.validate_request(request)
        log = x3_runner.WineLog(Path(tempfile.gettempdir()) / "unused.log", game=True)
        log.observe(b"info:  DXVK: v3.1.1\ninfo:  Binding model: Descriptor buffer\n")
        self.assertEqual(log.snapshot()[0]["dxvk_loaded"], "3.1.1")
        self.assertEqual(log.snapshot()[0]["dxvk_binding_model"], "Descriptor buffer")

    def test_a_driver_dxvk_cannot_use_stops_the_launch_with_advice(self):
        log = "err:   DxvkAdapter: Device does not support required feature 'shaderInt64'\n"
        self.assertIn("lacks shaderInt64", x3_runner.fatal_launch_error(log, game=True))
        self.assertIn("DXVK 2.5.3", x3_runner.fatal_launch_error("warn:  DXVK: No adapters found. Please check\n"))

    def test_a_vulkan_driver_crash_names_the_call_and_the_way_back(self):
        log = ('info:  DXVK: v3.1.1\n'
               '27316.755:0140:0198:err:msvcrt:_wassert (L"!status && \\"vkCreateGraphicsPipelines\\"",'
               'L"/home/runner/build_wine/wine/dlls/winevulkan/loader_thunks.c",3154)\n')
        message = x3_runner.fatal_launch_error(log, game=True)
        self.assertIn("vkCreateGraphicsPipelines (DXVK 3.1.1)", message)
        self.assertIn("DXVK 2.5.3", message)

    def test_box64_reports_faults_while_dxvk_3_is_tried(self):
        rc = x3_runner.box64_rc("X3AP.exe", "fast", {"BOX64_SHOWSEGV": "1", "BOX64_SHOWBT": "1"})
        section = rc.split("[X3AP.exe]\n", 1)[1]
        self.assertIn("BOX64_SHOWSEGV=1\n", section)
        self.assertIn("BOX64_DYNAREC_STRONGMEM=1\n", section)
        self.assertNotIn("SHOWSEGV", x3_runner.box64_rc("X3AP.exe", "fast"))

    def test_dxvk_versions_install_their_own_files_and_caches(self):
        import client_vulkan
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.assertEqual(client_vulkan.cache_paths(root, "24.3.4")[0].name, "dxvk")
            self.assertEqual(client_vulkan.cache_paths(root, "26.0.0", "3.1.1")[0].name, "dxvk-3.1.1-turnip-26.0.0")
            env = {"WINEDLLOVERRIDES": ""}
            client_vulkan.configure_environment(env, root, root, root, "26.0.0", "3.1.1")
            self.assertEqual(env["DXVK_SHADER_CACHE_PATH"], str(root / "x3-cache" / "dxvk-3.1.1-turnip-26.0.0"))
            with self.assertRaisesRegex(ValueError, "DXVK version"):
                client_vulkan.dxvk_files("2.7")

    def test_present_mode_is_recorded(self):
        log = x3_runner.WineLog(Path(tempfile.gettempdir()) / "unused.log", game=True)
        log.observe(b"info:    Present mode: VK_PRESENT_MODE_IMMEDIATE_KHR (dynamic: yes)\n"
                    b"info:    Present mode: VK_PRESENT_MODE_FIFO_KHR (dynamic: yes)\n")
        self.assertEqual(log.snapshot()[0]["dxvk_present_mode"], "VK_PRESENT_MODE_FIFO_KHR")

    def test_sleeping_threads_report_where_they_wait(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = Path(tmp)
            (task / "wchan").write_text("futex_wait_queue")
            (task / "syscall").write_text("98 0x7f00 0x80 0x0 0x0 0x0 0x0 0x7ffd 0x7f12\n")
            self.assertEqual(client_metrics.blocked_in(task), {"wchan": "futex_wait_queue", "syscall": 98})
            (task / "wchan").write_text("0")
            (task / "syscall").unlink()
            self.assertEqual(client_metrics.blocked_in(task), {})

    def overrides(self, value):
        parsed = {}
        for group in value.split(";"):
            names, _, setting = group.partition("=")
            parsed.update({name: setting for name in names.split(",")})
        return parsed

    def test_codec_that_needs_gstreamer_is_disabled(self):
        for addon in (False, True):
            self.assertEqual(self.overrides(x3_runner.dll_overrides(media_addon=addon))["ir50_32"], "")
        self.assertEqual(self.overrides(x3_runner.dll_overrides())["winegstreamer"], "")
        self.assertNotIn("winegstreamer", self.overrides(x3_runner.dll_overrides(media_addon=True)))

    def test_wine_keeps_its_hands_off_the_gamepad_by_default(self):
        # Fourth Thor run: X3 read the pad through XInput as well as the app's mappings.
        self.assertEqual(self.overrides(x3_runner.dll_overrides())["winebus.sys"], "")
        self.assertNotIn("winebus.sys", self.overrides(x3_runner.dll_overrides(controller_passthrough=True)))
        with self.assertRaisesRegex(ValueError, "controller_passthrough"):
            x3_runner.validate_request(dict(mode="game", program="X3AP.exe", resolution="1280x720", controller_passthrough=1))

    def test_media_addon_manifest_and_gstreamer_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "x3-media-addon.json"
            self.assertIsNone(x3_runner.media_addon(marker))
            marker.write_text('{"format": 1, "version": "media-addon-v1", "sha256": "ab"}')
            self.assertEqual(x3_runner.media_addon(marker)["version"], "media-addon-v1")
            marker.write_text("not json")
            self.assertIsNone(x3_runner.media_addon(marker))
        env = x3_runner.gstreamer_environment(Path("/prefix"))
        self.assertEqual(env["GST_PLUGIN_SYSTEM_PATH_1_0"], "/usr/lib/aarch64-linux-gnu/gstreamer-1.0")
        self.assertTrue(env["GST_REGISTRY_1_0"].startswith("/prefix/x3-cache/"))

    def test_game_process_found_by_launch_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = Path(tmp)
            (proc / "self").mkdir()
            token = "0123abcd"
            for pid, name, env in ((4100, "X3AP.exe", f"{x3_runner.LAUNCH_ENV}={token}"),
                                   (4200, "X3AP.exe", "OTHER=1"),
                                   (4300, "explorer.exe", f"{x3_runner.LAUNCH_ENV}={token}")):
                task = proc / str(pid) / "task" / str(pid)
                task.mkdir(parents=True)
                (proc / str(pid) / "environ").write_bytes(f"PATH=/usr/bin\0{env}\0".encode())
                fields = ["S"] + ["0"] * 18 + ["777"] + ["0"] * 30
                (task / "stat").write_text(f"{pid} ({name}) " + " ".join(fields))
                (task / "status").write_text("Cpus_allowed_list:\t0-7\n")
                (task / "schedstat").write_text("5000000000 250000000 123\n")
            sample = x3_runner.process_threads(4300, proc=proc, launch_token=token, game_name="X3AP.exe")
        self.assertTrue(sample["game_running"])
        main = [t for t in sample["threads"] if t["pid"] == 4100][0]
        self.assertEqual((main["on_cpu_ms"], main["run_delay_ms"], main["user_ticks"]), (5000, 250, 0))
        self.assertNotIn("run_delay_ms", [t for t in sample["threads"] if t["pid"] == 4300][0])
        self.assertEqual(sample["processes"], 2)      # the unmarked X3AP.exe is not ours
        self.assertEqual(sorted(t["pid"] for t in sample["threads"]), [4100, 4300])


class MediaSurveyTests(unittest.TestCase):
    @staticmethod
    def asf(tag):
        import struct
        wave = struct.pack("<HHIIHHH", tag, 1, 16000, 2000, 640, 16, 0)
        props = (x3_runner.ASF_AUDIO + bytes(16) + bytes(8) + struct.pack("<IIH", len(wave), 0, 1) + bytes(4) + wave)
        stream = x3_runner.ASF_STREAM_PROPERTIES + struct.pack("<Q", 24 + len(props)) + props
        return x3_runner.ASF_HEADER + struct.pack("<QIBB", 30 + len(stream), 1, 1, 2) + stream

    def test_sniff(self):
        import struct
        self.assertEqual(x3_runner.sniff_media(self.asf(0x000a)), "asf/wma-voice (WMSP)")
        self.assertEqual(x3_runner.sniff_media(self.asf(0x0161)), "asf/wma2")
        self.assertEqual(x3_runner.sniff_media(b"ID3\x03\x00" + bytes(20)), "mpeg-audio")
        self.assertEqual(x3_runner.sniff_media(b"\xff\xfb\x90\x00" + bytes(20)), "mpeg-audio")
        wav = b"RIFF" + bytes(4) + b"WAVEfmt " + struct.pack("<IH", 16, 0x0055) + bytes(14)
        self.assertEqual(x3_runner.sniff_media(wav), "wav/mp3")
        self.assertEqual(x3_runner.sniff_media(b"\x00\x00\x01\xba\x21" + bytes(8)), "mpeg-ps1")
        self.assertEqual(x3_runner.sniff_media(b"\x00\x00\x01\xba\x44" + bytes(8)), "mpeg-ps2")
        self.assertEqual(x3_runner.sniff_media(b"\x00\x00\x01\xb3" + bytes(8)), "mpeg-video-es")
        fixtures = Path(__file__).resolve().parent / "media" / "fixtures"
        self.assertEqual(x3_runner.sniff_media((fixtures / "comms.mpg").read_bytes()[:64]), "mpeg-ps1")
        self.assertEqual(x3_runner.sniff_media((fixtures / "comms.m1v").read_bytes()[:64]), "mpeg-video-es")
        self.assertEqual(x3_runner.sniff_media(b"hello"), "other")

    def test_survey_counts_folders_case_insensitively(self):
        with tempfile.TemporaryDirectory() as tmp:
            game = Path(tmp)
            (game / "Soundtrack").mkdir(); (game / "addon" / "mov").mkdir(parents=True)
            (game / "Soundtrack" / "00001.mp3").write_bytes(b"ID3" + bytes(10))
            (game / "Soundtrack" / "readme.txt").write_text("x")
            (game / "addon" / "mov" / "00144.dat").write_bytes(self.asf(0x000a))
            survey = x3_runner.media_survey(game)
        self.assertEqual(survey["Soundtrack"], {".mp3:mpeg-audio": 1, ".txt": 1})
        self.assertEqual(survey["addon/mov"], {".dat:asf/wma-voice (WMSP)": 1})

    def test_x3pin_result_is_recorded(self):
        log = x3_runner.WineLog(Path(tempfile.gettempdir()) / "unused.log", game=True)
        log.observe(b"x3pin: rsaenh.dll pinned in pid 292\nx3pin: 3 of 3 DLLs pinned (program idle)\n")
        self.assertEqual(log.snapshot()[0]["crypto_pin"], "3/3 (program idle)")


class LoadTimeTests(unittest.TestCase):
    """Sixth Thor run: menu to game took 180 s, CPU-bound in X3's own (emulated) code."""

    def test_game_profiles_go_into_its_rc_section(self):
        rc = x3_runner.box64_rc("X3AP.exe", "fast")
        section = rc.split("[X3AP.exe]\n", 1)[1]
        self.assertIn("BOX64_DYNAREC_BIGBLOCK=3\n", section)
        self.assertIn("BOX64_DYNAREC_CALLRET=1\n", section)
        # Seventh Thor run: SAFEFLAGS=0 + DIRTY=1 (Box64's own "fast") hung X3 at startup.
        self.assertIn("BOX64_DYNAREC_SAFEFLAGS=1\n", section)
        self.assertNotIn("DIRTY", rc)
        self.assertIn("BOX64_DYNAREC_STRONGMEM=1\n", section)
        self.assertIn("BOX64_DYNAREC_STRONGMEM=0\n", x3_runner.box64_rc("X3AP.exe", "fastest"))
        self.assertIn("[wine]\nBOX64_MAXCPU=0\n", rc)
        self.assertIn("BOX64_DYNAREC_BIGBLOCK=2\nBOX64_DYNAREC_SAFEFLAGS=1\nBOX64_DYNAREC_STRONGMEM=1\n",
                      x3_runner.box64_rc("X3AP.exe", "balanced"))
        self.assertTrue(x3_runner.box64_rc("x3 ap;rm.exe", "fast").count("[x3aprm.exe]") == 1)
        # Tenth Thor run: fast loaded in 146 s against balanced's 183 s and played at 32 fps against 24.
        self.assertEqual(x3_runner.DEFAULT_CPU_PROFILE, "fast")

    def test_spinning_main_thread_is_noticed(self):
        # The 0.1.7 hang: +1013 user ticks per 10 s, system ticks and faults frozen.
        watch = x3_runner.SpinWatch()
        results = [watch.observe({"user_ticks": 792 + 1013 * i, "system_ticks": 115, "minor_faults": 68481}, 10.1)
                   for i in range(8)]
        self.assertEqual(results, [False] * 6 + [True, True])
        # A load: busy too, but its page faults move.
        watch = x3_runner.SpinWatch()
        self.assertFalse(any(watch.observe({"user_ticks": 1000 * i, "system_ticks": 100, "minor_faults": 5000 + 40 * i}, 10)
                             for i in range(12)))
        # An idle menu thread is not busy.
        watch = x3_runner.SpinWatch()
        self.assertFalse(any(watch.observe({"user_ticks": 540 * i, "system_ticks": 9, "minor_faults": 7}, 10)
                             for i in range(12)))

    def test_present_pauses_measure_loads(self):
        log = x3_runner.WineLog(Path(tempfile.gettempdir()) / "unused.log", game=True)
        line = "{:.3f}:0140:01c0:trace:fps:win32u_vkQueuePresentKHR 0x38197b08 @ approx 59.90fps, total 59.00fps\n"
        times = [100.0, 101.6, 103.2, 283.2, 284.8, 300.0, 301.5]
        log.observe("".join(line.format(t) for t in times).encode())
        fields = log.snapshot()[0]
        self.assertEqual(fields["present_pauses_seconds"], [180.0, 15.2])
        self.assertEqual(fields["longest_present_pause_seconds"], 180.0)

    def test_x3pin_report_file_format(self):
        match = x3_runner.X3PIN_SUMMARY.search("x3pin: 3 of 3 DLLs pinned (program idle)\n")
        self.assertEqual(match.groups(), ("3", "3", "program idle"))
        self.assertTrue(x3_runner.X3PIN_LOG.name == "x3pin.log")

class PrimePlacementTests(unittest.TestCase):
    def topology(self, root, capacities):
        for cpu, capacity in capacities.items():
            (root / f"cpu{cpu}").mkdir(parents=True)
            (root / f"cpu{cpu}" / "cpu_capacity").write_text(f"{capacity}\n")
        (root / "cpufreq").mkdir()            # not a CPU

    def test_fastest_cpus_are_the_highest_capacity(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            # Snapdragon 8 Gen 2: three A510, two A715, two A710, one X3.
            self.topology(root, {0: 325, 1: 325, 2: 325, 3: 870, 4: 870, 5: 870, 6: 870, 7: 1024})
            self.assertEqual(client_metrics.fastest_cpus(root), {7})
            self.assertEqual(client_metrics.fastest_cpus(root / "missing"), set())

    def launch(self, root, token, threads):
        for pid, tid, name in threads:
            task = root / str(pid) / "task" / str(tid)
            task.mkdir(parents=True, exist_ok=True)
            (task / "stat").write_text(f"{tid} ({name}) R " + " ".join(["0"] * 16) + " 0 0 777 0\n")
            (root / str(pid) / "environ").write_bytes(b"A=1\0" + client_metrics.LAUNCH_ENV.encode() + b"=" + token.encode() + b"\0")
        (root / "self").mkdir(exist_ok=True)
        return {"threads": [{"pid": pid, "tid": tid, "name": name, "start_ticks": 777} for pid, tid, name in threads]}

    def test_main_thread_gets_the_prime_core_and_the_rest_leave_it(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            cpus = root / "sys"
            self.topology(cpus, {i: (1024 if i == 7 else 870) for i in range(8)})
            sample = self.launch(root / "proc", "tok", [(10, 10, "X3AP.exe"), (10, 11, "dxvk-cs"), (20, 20, "Xtigervnc")])
            masks = {10: set(range(8)), 11: {0, 1, 2, 3, 4, 5}, 20: set(range(8))}
            calls = []
            def setaffinity(tid, mask): calls.append((tid, set(mask))); masks[tid] = set(mask)
            with unittest.mock.patch("os.cpu_count", return_value=8):
                result = client_metrics.place_game_threads(sample, "tok", proc=root / "proc", cpus=cpus,
                                                          getaffinity=lambda tid: masks[tid], setaffinity=setaffinity)
            # dxvk-cs was already off CPU 7: left alone.
            self.assertEqual(calls, [(10, {7}), (20, set(range(7)))])
            self.assertEqual(result["main_thread_cpus"], [7])
            self.assertEqual(result["changed_threads"], 2)

    def test_main_thread_falls_back_when_android_forbids_the_prime_core(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            cpus = root / "sys"
            self.topology(cpus, {i: (1024 if i == 7 else 870) for i in range(8)})
            sample = self.launch(root / "proc", "tok", [(10, 10, "X3AP.exe")])
            masks = {10: {0, 1, 2, 3, 4, 5}}
            def setaffinity(tid, mask):
                allowed = set(mask) & {0, 1, 2, 3, 4, 5}      # what the kernel does with a cpuset
                if not allowed: raise OSError(22, "Invalid argument")
                masks[tid] = allowed
            with unittest.mock.patch("os.cpu_count", return_value=8):
                result = client_metrics.place_game_threads(sample, "tok", proc=root / "proc", cpus=cpus,
                                                          getaffinity=lambda tid: masks[tid], setaffinity=setaffinity)
            self.assertEqual(result["main_thread_cpus"], [0, 1, 2, 3, 4, 5])
            self.assertEqual(result["errors"], 0)

    def test_without_the_prime_core_the_main_thread_stays_on_big_cores(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            cpus = root / "sys"
            self.topology(cpus, {0: 325, 1: 325, 2: 325, 3: 870, 4: 870, 5: 870, 6: 870, 7: 1024})
            self.assertEqual(client_metrics.fast_cpus(cpus), {3, 4, 5, 6, 7})
            sample = self.launch(root / "proc", "tok", [(10, 10, "X3AP.exe")])
            masks = {10: set(range(8))}       # a cpuset change resets the mask to everything
            def setaffinity(tid, mask):
                allowed = set(mask) & {0, 1, 2, 3, 4, 5, 6}   # Android left CPU 7 out
                if not allowed: raise OSError(22, "Invalid argument")
                masks[tid] = allowed
            with unittest.mock.patch("os.cpu_count", return_value=8):
                result = client_metrics.place_game_threads(sample, "tok", proc=root / "proc", cpus=cpus,
                                                          getaffinity=lambda tid: masks[tid], setaffinity=setaffinity)
            self.assertEqual(result["main_thread_cpus"], [3, 4, 5, 6])

    def test_big_cores_by_clock_when_there_are_no_capacities(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for cpu, khz in {0: 2016000, 1: 2016000, 2: 2016000, 3: 2803200, 4: 2803200, 5: 2803200, 6: 2803200, 7: 3187200}.items():
                (root / f"cpu{cpu}" / "cpufreq").mkdir(parents=True)
                (root / f"cpu{cpu}" / "cpufreq" / "cpuinfo_max_freq").write_text(f"{khz}\n")
            self.assertEqual(client_metrics.fast_cpus(root), {3, 4, 5, 6, 7})
            self.assertEqual(client_metrics.fast_cpus(root / "missing"), set())

    def test_other_launches_are_not_touched(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            cpus = root / "sys"
            self.topology(cpus, {i: (1024 if i == 7 else 870) for i in range(8)})
            sample = self.launch(root / "proc", "other", [(10, 10, "X3AP.exe")])
            with unittest.mock.patch("os.cpu_count", return_value=8):
                result = client_metrics.place_game_threads(sample, "tok", proc=root / "proc", cpus=cpus,
                                                          getaffinity=lambda tid: set(range(8)),
                                                          setaffinity=lambda tid, mask: self.fail("changed"))
            self.assertEqual(result["changed_threads"], 0)

    def test_dynacache_folder_is_summarised(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.assertTrue(x3_runner.dynacache_summary(root / "box64")["missing"])
            (root / "box64").mkdir()
            (root / "box64" / "X3AP.exe-abc.box64").write_bytes(b"x" * 300)
            (root / "box64" / "ntdll.so-def.box64").write_bytes(b"x" * 100)
            summary = x3_runner.dynacache_summary(root / "box64")
            self.assertEqual((summary["files"], summary["bytes"]), (2, 400))
            self.assertEqual(summary["largest"][0], {"name": "X3AP.exe-abc.box64", "bytes": 300})

    def test_android_cpuset_is_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "proc" / "self").mkdir(parents=True)
            (root / "proc" / "self" / "cgroup").write_text("5:schedtune:/top-app\n4:cpuset:/top-app\n0::/uid_10234/pid_99\n")
            (root / "dev" / "top-app").mkdir(parents=True)
            (root / "dev" / "top-app" / "cpus").write_text("0-7\n")
            self.assertEqual(x3_runner.android_cpuset(root / "proc", root / "dev"), {"group": "/top-app", "cpus": "0-7"})


class MainThreadProfileTests(unittest.TestCase):
    def task(self, root, state, syscall):
        task = root / "4242" / "task" / "4242"
        task.mkdir(parents=True, exist_ok=True)
        (task / "stat").write_text(f"4242 (X3AP.exe) {state} 1 2 3 4 5\n")
        (task / "syscall").write_text(syscall + "\n")

    def test_states_and_syscalls_are_shared_out_by_phase(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            profile = x3_runner.MainThreadProfile(proc=root)
            profile.sample("loading")           # no game thread known yet: nothing counted
            self.assertEqual(profile.report(), {})
            profile.pid = 4242
            for state, call in [("R", "running"), ("R", "running"), ("t", "56 0x1 0x2"), ("S", "63 0x5")]:
                self.task(root, state, call)
                profile.sample("loading")
            self.task(root, "R", "running")
            profile.sample("playing")
            report = profile.report()
            self.assertEqual(report["loading"]["samples"], 4)
            self.assertEqual(report["loading"]["running"], 0.5)
            self.assertEqual(report["loading"]["traced"], 0.25)
            self.assertEqual(report["loading"]["syscalls"], {"traced:openat": 0.25, "sleeping:read": 0.25})
            self.assertEqual(report["playing"], {"samples": 1, "running": 1.0, "syscalls": {}})

    def test_samples_below_the_frame_cap_are_also_counted_apart(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            profile = x3_runner.MainThreadProfile(proc=root)
            profile.pid = 4242
            self.task(root, "S", "98 0x1")
            profile.sample("playing", "below_cap")
            self.task(root, "R", "running")
            profile.sample("playing")
            report = profile.report()
            self.assertEqual(report["playing"]["samples"], 2)
            self.assertEqual(report["below_cap"], {"samples": 1, "sleeping": 1.0, "syscalls": {"sleeping:futex": 1.0}})

    def test_frame_band_follows_wines_fps_reports(self):
        log = x3_runner.WineLog(Path(tempfile.gettempdir()) / "unused.log", game=True)
        self.assertEqual(x3_runner.frame_band(log, 60), "unknown")
        log.fields["wine_present"] = {"per_second": 45.0, "sampled_at": 1000.0}
        self.assertEqual(x3_runner.frame_band(log, 60, now=1001.0), "below_cap")
        log.fields["wine_present"] = {"per_second": 59.5, "sampled_at": 1000.0}
        self.assertEqual(x3_runner.frame_band(log, 60, now=1001.0), "at_cap")
        self.assertEqual(x3_runner.frame_band(log, 60, now=1010.0), "unknown")

    def test_clock_profile_reads_cpu_and_gpu_clocks(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            freq = root / "cpu" / "cpu7" / "cpufreq"; freq.mkdir(parents=True)
            (freq / "cpuinfo_max_freq").write_text("3360000\n")
            (freq / "scaling_max_freq").write_text("3360000\n")
            kgsl = root / "kgsl"; (kgsl / "devfreq").mkdir(parents=True)
            clocks = x3_runner.ClockProfile(7, cpus=root / "cpu", kgsl=kgsl)
            (freq / "scaling_cur_freq").write_text("3360000\n")
            clocks.sample("below_cap")
            self.assertFalse(clocks.report()["gpu_readable"])   # Android hid kgsl: only the CPU is known
            (freq / "scaling_cur_freq").write_text("2400000\n")
            (kgsl / "gpu_busy_percentage").write_text("37 %\n")
            (kgsl / "devfreq" / "cur_freq").write_text("680000000\n")
            clocks.sample("below_cap")
            report = clocks.report()
            self.assertEqual(report["cpu"], "cpu7")
            self.assertEqual(report["cpu_max_mhz"], 3360)
            self.assertTrue(report["gpu_readable"])
            self.assertEqual(report["below_cap"]["samples"], 2)
            self.assertEqual(report["below_cap"]["cpu_mhz"], {"mean": 2880, "min": 2400, "max": 3360})
            self.assertEqual(report["below_cap"]["gpu_busy_percent"], {"mean": 37, "min": 37, "max": 37})
            self.assertEqual(report["below_cap"]["gpu_mhz"], {"mean": 680, "min": 680, "max": 680})

    def test_a_capped_prime_core_gives_a_performance_hint(self):
        capped = {"cpu": "cpu7", "cpu_max_mhz": 3187, "gpu_readable": True,
                  "below_cap": {"samples": 42, "cpu_limit_mhz": {"mean": 2477, "min": 2477, "max": 2477}}}
        self.assertIn("2477 of its 3187 MHz", x3_runner.clock_hint(capped))
        self.assertIn("High Performance", x3_runner.clock_hint(capped))
        free = {"cpu": "cpu7", "cpu_max_mhz": 3187, "at_cap": {"samples": 9, "cpu_limit_mhz": {"mean": 3187, "min": 3187, "max": 3187}}}
        self.assertIsNone(x3_runner.clock_hint(free))
        self.assertIsNone(x3_runner.clock_hint({"cpu": None, "cpu_max_mhz": None}))

    def test_a_thread_that_went_away_is_skipped(self):
        with tempfile.TemporaryDirectory() as folder:
            profile = x3_runner.MainThreadProfile(proc=Path(folder))
            profile.pid = 999
            profile.sample("playing")
            self.assertEqual(profile.report(), {})


class MediaRunEightTests(unittest.TestCase):
    """Eighth Thor run (0.1.8): no speech, no menu music, comms faces from other pilots."""

    def test_gstreamer_filters_detected_in_32_bit_view(self):
        prefix = Path(tempfile.mkdtemp())
        key = ("[Software\\\\Classes\\\\{view}CLSID\\\\{{083863F1-70DE-11D0-BD40-00A0C911CE86}}"
               "\\\\Instance\\\\{{F9D8D64E-A144-47DC-8EE0-F53498372C29}}] 1794763463\n")
        self.assertFalse(x3_runner.gstreamer_filters_registered(prefix))          # no registry yet
        (prefix / "system.reg").write_text("WINE REGISTRY Version 2\n" + key.format(view=""))
        self.assertFalse(x3_runner.gstreamer_filters_registered(prefix))          # 64-bit view only
        (prefix / "system.reg").write_text("WINE REGISTRY Version 2\n" + key.format(view="Wow6432Node\\\\"))
        self.assertTrue(x3_runner.gstreamer_filters_registered(prefix))

    def test_media_events_are_always_logged(self):
        self.assertIn("trace+x3media", x3_runner.wine_debug())
        self.assertNotIn("trace+quartz", x3_runner.wine_debug())

    def test_sound_diagnostics_trace_directshow_not_dsound(self):
        debug = x3_runner.wine_debug(sound=True)
        self.assertIn("trace+quartz", debug)
        self.assertNotIn("trace+dsound", debug)
        self.assertNotIn("trace+dsound3d", debug)

    def test_noise_is_dropped_whole_lines_only(self):
        log = x3_runner.WineLog(Path(tempfile.mkdtemp()) / "x3-wine.log", drop=x3_runner.SOUND_NOISE)
        first = (b"38485.944:0140:0144:trace:quartz:multimedia_stream_OpenFile (1C95EEB8/1C95EEB8)->(L\"mov\\\\00001.dat\",0)\n"
                 b"38485.945:0140:0144:trace:quartz:StdMediaSample2_AddRef (002C4AB8) ref=2\n"
                 b"38485.946:0140:0144:trace:quartz:filter_inner_Release filter 0B1E0028 L\"0001\", refcount 3.\n"
                 b"38485.977:0140:0144:trace:quartz:wg_parser_stream_seek stream 0x75, start_pos 0")
        kept = log.kept(first) + log.kept(b", stop_pos 30845009250\n") + log.kept(b"", final=True)
        self.assertIn(b"multimedia_stream_OpenFile", kept)
        self.assertIn(b"wg_parser_stream_seek stream 0x75, start_pos 0, stop_pos 30845009250\n", kept)
        self.assertNotIn(b"AddRef", kept)
        self.assertNotIn(b"filter_inner_Release", kept)
        self.assertEqual(log.fields["wine_log_dropped_lines"], 2)
        plain = x3_runner.WineLog(Path(tempfile.mkdtemp()) / "x3-wine.log")
        self.assertEqual(plain.kept(first), first)


class SavesTests(unittest.TestCase):
    """X3's Documents\\Egosoft must end up in /saves, whatever Wine did with Documents."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.prefix, self.saves, self.home = root / "prefix", root / "saves", root / "home"
        self.users = self.prefix / "drive_c" / "users"
        (self.users / "Public" / "Documents").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def run_persist(self):
        return x3_runner.persist_documents(self.prefix, self.saves)

    def test_dangling_home_link_is_followed(self):
        (self.users / "root").mkdir()
        (self.users / "root" / "Documents").symlink_to(self.home / "Documents")
        report = self.run_persist()
        self.assertEqual(report["users"], ["root"])
        entry = self.home / "Documents" / "Egosoft"
        self.assertEqual(os.readlink(entry), str(self.saves / "Egosoft"))
        (entry / "X3AP").mkdir()
        self.assertTrue((self.saves / "Egosoft" / "X3AP").is_dir())
        self.assertFalse((self.users / "Public" / "Documents" / "Egosoft").exists())

    def test_existing_saves_move_and_relaunch_is_idempotent(self):
        save = self.users / "root" / "Documents" / "Egosoft" / "X3AP" / "save" / "save_001.sav"
        save.parent.mkdir(parents=True)
        save.write_bytes(b"campaign")
        report = self.run_persist()
        self.assertEqual(report["migrated"], [{"user": "root", "to": str(self.saves / "Egosoft")}])
        self.assertEqual((self.saves / "Egosoft" / "X3AP" / "save" / "save_001.sav").read_bytes(), b"campaign")
        self.assertEqual(self.run_persist()["migrated"], [])
        self.assertEqual(save.read_bytes(), b"campaign")

    def test_never_overwrites_saves_already_kept(self):
        kept = self.saves / "Egosoft" / "X3AP" / "save" / "save_001.sav"
        kept.parent.mkdir(parents=True)
        kept.write_bytes(b"kept")
        stray = self.users / "root" / "Documents" / "Egosoft" / "X3AP" / "save" / "save_001.sav"
        stray.parent.mkdir(parents=True)
        stray.write_bytes(b"other")
        report = self.run_persist()
        moved = Path(report["migrated"][0]["to"])
        self.assertTrue(moved.name.startswith("Egosoft-from-root-"))
        self.assertEqual(kept.read_bytes(), b"kept")
        self.assertEqual((moved / "X3AP" / "save" / "save_001.sav").read_bytes(), b"other")
        self.assertEqual(stray.read_bytes(), b"kept")

    def test_new_prefix_without_users(self):
        report = x3_runner.persist_documents(Path(self.tmp.name, "empty"), self.saves)
        self.assertEqual(report["users"], [])
        self.assertTrue((self.saves / "Egosoft").is_dir())


if __name__ == "__main__":
    unittest.main()
