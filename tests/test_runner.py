"""Unit tests for the rootfs-side supervisor (no Wine, Box64 or Android needed)."""
import json
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "runner"))

import client_audio  # noqa: E402
import pe_info  # noqa: E402
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

    def test_bad_options(self):
        for key, value in (("resolution", "999x999"), ("renderer", "virgl"), ("display_fps", 45),
                           ("audio", "yes"), ("arguments", "-skipintro"), ("turnip_driver", "1.0")):
            request = dict(self.request, **{key: value})
            with self.assertRaises(ValueError, msg=key):
                x3_runner.validate_request(request, self.game)

    def test_commands(self):
        args, cwd = x3_runner.build_command(self.request, {"kind": "exe"})
        self.assertEqual(args[2:], ["explorer", "/desktop=X3,1280x720", "D:\\X3AP.exe", "-skipintro"])
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


if __name__ == "__main__":
    unittest.main()
