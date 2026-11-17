"""Preparation/staging checks using synthetic records and media transport."""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "notebooks"))
import apify_prepare as prepare


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.run = root / "run"
        self.run.mkdir()
        self.raw = root / "raw"
        self.raw.mkdir()
        self.incoming = root / "incoming"
        self.incoming.mkdir()
        self.post = {"id": "123", "authorMeta": {"name": "creator"}, "text": "caption",
                     "createTime": 1700000000, "playCount": 50,
                     "videoMeta": {"duration": 5, "coverUrl": "https://api.apify.com/cover?token=secret"},
                     "mediaUrls": ["https://api.apify.com/video"], "musicMeta": {"musicName": "sound"}}
        self.archive([self.post])

    def archive(self, rows, mode="search", partial=False):
        source = "".join(json.dumps(row) + "\n" for row in rows)
        (self.run / "items.jsonl").write_text(source)
        (self.run / "request.json").write_text(json.dumps({"mode": mode, "actor": "clockworks/tiktok-scraper",
                                                         "label": "Climate", "input": {"searchQueries": ["climate"]}}))
        (self.run / "export.json").write_text(json.dumps({"run_id": "run123", "sha256": hashlib.sha256(source.encode()).hexdigest(),
                                                        "partial": partial, "retrieved_at": "2026-11-17T12:00:00+00:00"}))
        (self.run / "run.json").write_text(json.dumps({"id": "run123", "buildNumber": "1.2.3"}))

    def test_metadata_mapping_private_original_and_public_source(self):
        report = prepare.prepare_run(self.run, raw=self.raw, include_media=False)
        post = json.loads((self.run / "prepared/123.json").read_text())
        self.assertEqual(post["author"]["uniqueId"], "creator")
        self.assertEqual(post["stats"]["playCount"], 50)
        self.assertEqual(post["desc"], "caption")
        self.assertIn("secret", (self.run / "items.jsonl").read_text())
        self.assertNotIn("secret", (self.run / "prepared/apify-source.jsonl").read_text())
        self.assertEqual(report["posts"], ["123"])
        self.assertEqual(list(self.raw.iterdir()), [])

    def test_failed_media_does_not_publish_half_a_post(self):
        with patch.object(prepare, "obtain_media", side_effect=ValueError("failed")):
            with self.assertRaisesRegex(ValueError, "No valid posts"):
                prepare.prepare_run(self.run, raw=self.raw)
        self.assertFalse((self.run / "prepared").exists())
        report = json.loads((self.run / "preparation.json").read_text())
        self.assertEqual(len(report["errors"]), 1)
        with self.assertRaises(ValueError):
            prepare.stage_run(self.run, self.incoming)

    def test_partial_runs_need_opt_in_and_source_integrity(self):
        self.archive([self.post], partial=True)
        with self.assertRaisesRegex(ValueError, "partial"):
            prepare.prepare_run(self.run, raw=self.raw, include_media=False)
        prepare.prepare_run(self.run, raw=self.raw, include_media=False, allow_partial=True)
        (self.run / "items.jsonl").write_text("changed")
        with self.assertRaisesRegex(ValueError, "checksum"):
            prepare.prepare_run(self.run, raw=self.raw)

    def test_existing_metadata_reused_without_conflict(self):
        (self.raw / "oldhandle").mkdir()
        original = '{"id":"123","author":{"uniqueId":"oldhandle"},"desc":"original"}\n'
        (self.raw / "oldhandle/123.json").write_text(original)
        prepare.prepare_run(self.run, raw=self.raw, include_media=False)
        self.assertEqual((self.run / "prepared/123.json").read_text(), original)
        self.assertIn("caption", (self.run / "prepared/apify-source.jsonl").read_text())

    def test_staging_verifies_and_is_once_only(self):
        prepare.prepare_run(self.run, raw=self.raw, include_media=False)
        destination = prepare.stage_run(self.run, self.incoming)
        self.assertEqual(destination.name, "apify-run123")
        self.assertEqual((destination / "123.json").read_bytes(), (self.run / "prepared/123.json").read_bytes())
        self.assertTrue((self.run / "items.jsonl").exists())
        with self.assertRaisesRegex(ValueError, "already staged"):
            prepare.stage_run(self.run, self.incoming)

    def test_changed_prepared_files_are_not_staged(self):
        prepare.prepare_run(self.run, raw=self.raw, include_media=False)
        (self.run / "prepared/123.json").write_text("changed")
        with self.assertRaisesRegex(ValueError, "changed"):
            prepare.stage_run(self.run, self.incoming)
        self.assertEqual(list(self.incoming.iterdir()), [])

    def test_comment_import_requires_existing_post_preserves_reply(self):
        comment = {"cid": "456", "repliesToId": "455", "videoWebUrl": "https://www.tiktok.com/@creator/video/123",
                   "text": "reply", "uniqueId": "commenter", "diggCount": 5}
        self.archive([comment], mode="comments")
        with self.assertRaisesRegex(ValueError, "No valid posts"):
            prepare.prepare_run(self.run, raw=self.raw)
        (self.raw / "creator").mkdir()
        (self.raw / "creator/123.json").write_text(json.dumps({"id": "123", "author": {"uniqueId": "creator"}}))
        with patch.object(prepare, "obtain_media") as media:
            report = prepare.prepare_run(self.run, raw=self.raw)
        media.assert_not_called()
        self.assertEqual(report["comments"], 1)
        row = json.loads((self.run / "prepared/comments.jsonl").read_text())
        self.assertEqual((row["post_id"], row["comment_id"], row["parent_comment_id"]), ("123", "456", "455"))

    def test_supported_media_hosts_and_private_addresses(self):
        public = [(None, None, None, None, ("8.8.8.8", 443))]
        with patch.object(prepare.socket, "getaddrinfo", return_value=public):
            self.assertEqual(prepare.check_media_url("https://api.apify.com/v2/key-value-stores/store/records/video").hostname, "api.apify.com")
            for url in ["http://api.apify.com/x", "https://api.apify.com.evil.test/x", "https://127.0.0.1/x", "https://user:pass@api.apify.com/x"]:
                with self.assertRaises(ValueError):
                    prepare.check_media_url(url)
        with patch.object(prepare.socket, "getaddrinfo", return_value=[(None, None, None, None, ("127.0.0.1", 443))]):
            with self.assertRaises(ValueError):
                prepare.check_media_url("https://api.apify.com/x")


if __name__ == "__main__":
    unittest.main()
