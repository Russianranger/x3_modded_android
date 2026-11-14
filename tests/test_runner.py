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

    def test_codec_that_needs_gstreamer_is_disabled(self):
        overrides = {}
        for group in x3_runner.DLL_OVERRIDES.split(";"):
            names, _, value = group.partition("=")
            overrides.update({name: value for name in names.split(",")})
        self.assertEqual(overrides["ir50_32"], "")
        self.assertEqual(overrides["winegstreamer"], "")

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
            sample = x3_runner.process_threads(4300, proc=proc, launch_token=token, game_name="X3AP.exe")
        self.assertTrue(sample["game_running"])
        self.assertEqual(sample["processes"], 2)      # the unmarked X3AP.exe is not ours
        self.assertEqual(sorted(t["pid"] for t in sample["threads"]), [4100, 4300])


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
