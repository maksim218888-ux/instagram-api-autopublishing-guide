#!/usr/bin/env python3
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("publisher", HERE / "instagram_publish_agent.py")
mod = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules["publisher"] = mod
SPEC.loader.exec_module(mod)


class PublisherTests(unittest.TestCase):
    def test_stable_hash_ignores_key_order(self):
        self.assertEqual(mod.stable_hash({"a": 1, "b": 2}), mod.stable_hash({"b": 2, "a": 1}))

    def test_redact_url_removes_query(self):
        value = mod.redact_url("https://cdn.example/file.mp4?sig=secret&expires=1")
        self.assertNotIn("secret", value)
        self.assertEqual(value, "https://cdn.example/file.mp4?[REDACTED]")

    def test_journal_duplicate_state_persists(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "journal.json"
            j = mod.Journal(path)
            j.event("hash", "PUBLISH_UNKNOWN", container_id="123")
            j2 = mod.Journal(path)
            self.assertEqual(j2.run("hash")["state"], "PUBLISH_UNKNOWN")

    def test_fps_parser(self):
        self.assertEqual(mod.fps_value("30/1"), 30.0)
        self.assertEqual(mod.fps_value("30000/1001"), 30000 / 1001)
        self.assertEqual(mod.fps_value("0/0"), 0.0)

    def test_image_smoke_check(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            media = td / "post.jpg"
            caption = td / "caption.txt"
            config = td / "config.json"
            caption.write_text("Проверочная подпись без публикации.", "utf-8")
            subprocess.run([
                "ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=white:s=1080x1350",
                "-frames:v", "1", "-y", str(media)
            ], check=True)
            config.write_text(json.dumps({
                "account_id": "17840000000000000",
                "expected_username": "example_business",
                "api_host": "graph.facebook.com",
                "api_version": "v27.0",
                "media_kind": "IMAGE",
                "media_path": str(media),
                "caption_path": str(caption),
                "asset_url": "https://assets.example.invalid/post.jpg?signature=placeholder",
                "mode": "NORMAL",
                "share_to_feed": True,
                "is_ai_generated": False
            }), "utf-8")
            cp = subprocess.run([sys.executable, str(HERE / "instagram_publish_agent.py"), "check", "--config", str(config)], capture_output=True, text=True)
            self.assertEqual(cp.returncode, 0, cp.stderr)
            report = json.loads(cp.stdout)
            self.assertTrue(report["ok"])
            self.assertFalse(report["live_action"])
            self.assertNotIn("signature=placeholder", cp.stdout)

    def test_reel_smoke_check_requires_faststart_and_valid_specs(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            media = td / "reel.mp4"
            caption = td / "caption.txt"
            config = td / "config.json"
            caption.write_text("Проверка Reel без публикации.", "utf-8")
            subprocess.run([
                "ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=720x1280:r=30:d=3",
                "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-shortest", "-t", "3",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-b:v", "2M", "-c:a", "aac", "-b:a", "128k",
                "-movflags", "+faststart", "-use_editlist", "0", "-y", str(media)
            ], check=True)
            config.write_text(json.dumps({
                "account_id": "17840000000000000", "expected_username": "example_business",
                "api_host": "graph.facebook.com", "api_version": "v27.0", "media_kind": "REELS",
                "media_path": str(media), "caption_path": str(caption),
                "asset_url": "https://assets.example.invalid/reel.mp4?signature=placeholder",
                "mode": "NORMAL", "share_to_feed": True, "is_ai_generated": False
            }), "utf-8")
            cp = subprocess.run([sys.executable, str(HERE / "instagram_publish_agent.py"), "check", "--config", str(config)], capture_output=True, text=True)
            self.assertEqual(cp.returncode, 0, cp.stderr)
            report = json.loads(cp.stdout)
            self.assertTrue(report["media"]["checks"]["moov_atom_at_front"])
            self.assertTrue(report["media"]["checks"]["no_edit_list"])
            self.assertTrue(report["media"]["checks"]["fps_23_to_60"])

    def test_carousel_config_fails_with_documented_boundary(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            config = td / "config.json"
            caption = td / "caption.txt"
            media = td / "not-used.jpg"
            caption.write_text("Карусель", "utf-8")
            media.write_bytes(b"x")
            config.write_text(json.dumps({
                "account_id": "1", "expected_username": "example", "api_host": "graph.facebook.com",
                "api_version": "v27.0", "media_kind": "CAROUSEL", "media_path": str(media),
                "caption_path": str(caption), "asset_url": "https://assets.example.invalid/a.jpg", "mode": "NORMAL"
            }), "utf-8")
            args = type("A", (), {"config": str(config)})()
            with self.assertRaisesRegex(ValueError, "STATE-MACHINE.md"):
                mod.load_inputs(args)

    def test_live_publish_is_locked_without_sentinel(self):
        old = os.environ.pop("IG_ENABLE_LIVE_PUBLISH", None)
        try:
            with self.assertRaisesRegex(RuntimeError, "live publishing is locked"):
                args = type("A", (), {"config": "missing", "confirm_hash": "x", "journal": "j"})()
                mod.command_publish(args)
        finally:
            if old is not None:
                os.environ["IG_ENABLE_LIVE_PUBLISH"] = old


if __name__ == "__main__":
    unittest.main(verbosity=2)
