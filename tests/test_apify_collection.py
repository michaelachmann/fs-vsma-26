"""Synthetic transport tests; never contact Apify or start paid runs."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "notebooks"))
import apify_collection as collection


class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name) / "pilot"
        self.run = {"id": "run123", "actId": "actor123", "status": "RUNNING",
                    "defaultDatasetId": "data123", "defaultKeyValueStoreId": "store123"}

    def start(self):
        with patch.object(collection, "api", return_value={"data": self.run}) as api:
            collection.start_run("secret-token", self.directory, mode="search", values=["climate"],
                                 label="Climate", limit=2, max_cost_usd=1)
        return api

    def test_inputs(self):
        self.assertEqual(collection.make_input("search", ["climate"])["searchSection"], "/video")
        self.assertEqual(collection.make_input("hashtag", ["#climate"])["hashtags"], ["climate"])
        comments = collection.make_input("comments", ["https://www.tiktok.com/@creator/video/123"], replies=3)
        self.assertEqual(comments["maxRepliesPerComment"], 3)
        for mode, values, limit in [("wrong", ["x"], 2), ("search", [], 2),
                                    ("hashtag", ["#"], 2), ("search", ["x"], True),
                                    ("comments", ["https://example.com"], 2)]:
            with self.assertRaises(ValueError):
                collection.make_input(mode, values, limit=limit)

    def test_start_once_and_no_credentials_in_receipts(self):
        api = self.start()
        self.assertEqual(api.call_args.kwargs["query"]["maxTotalChargeUsd"], 1)
        self.assertNotIn("secret-token", "".join(p.read_text() for p in self.directory.iterdir()))
        with self.assertRaises(FileExistsError):
            self.start()

    def test_budget_required_before_request_or_directory(self):
        with patch.object(collection, "api") as api:
            for budget in [None, 0, -1, float("nan"), float("inf")]:
                with self.assertRaises(ValueError):
                    collection.start_run("token", self.directory, mode="search", values=["x"],
                                         label="X", limit=1, max_cost_usd=budget)
            api.assert_not_called()
        self.assertFalse(self.directory.exists())

    def test_unknown_start_outcome_keeps_intent_and_refuses_retry(self):
        with patch.object(collection, "api", side_effect=RuntimeError("connection failed")):
            with self.assertRaises(RuntimeError):
                collection.start_run("token", self.directory, mode="hashtag", values=["x"],
                                     label="X", limit=2, max_cost_usd=1)
        self.assertTrue((self.directory / "request.json").exists())
        with self.assertRaises(FileExistsError):
            self.start()

    def test_running_does_not_export(self):
        self.start()
        with patch.object(collection, "api", return_value={"data": self.run}) as api:
            result = collection.fetch_run("token", self.directory)
        self.assertFalse(result["exported"])
        self.assertEqual(api.call_count, 1)
        self.assertFalse((self.directory / "items.jsonl").exists())

    def test_pages_errors_partial_export_and_integrity(self):
        self.start()
        self.run["status"] = "TIMED-OUT"
        pages = [{"data": self.run}, [{"cid": "9999999999999999999", "text": "reply"}],
                 [{"errorCode": "POST_NOT_FOUND_OR_PRIVATE"}], []]
        with patch.object(collection, "api", side_effect=pages) as api:
            result = collection.fetch_run("token", self.directory, page_size=1)
        self.assertEqual([c.kwargs["query"]["offset"] for c in api.call_args_list[1:]], [0, 1, 2])
        self.assertTrue(result["partial"])
        self.assertEqual((result["items"], result["error_items"]), (2, 1))
        rows = [json.loads(row) for row in (self.directory / "items.jsonl").read_text().splitlines()]
        self.assertEqual(rows[0]["cid"], "9999999999999999999")
        with patch.object(collection, "api", return_value={"data": self.run}) as api:
            self.assertEqual(collection.fetch_run("token", self.directory), result)
            self.assertEqual(api.call_count, 1)
            (self.directory / "items.jsonl").write_text("tampered")
            with self.assertRaisesRegex(RuntimeError, "integrity"):
                collection.fetch_run("token", self.directory)

    def test_interrupted_download_restarts_without_new_actor(self):
        self.start()
        self.run["status"] = "SUCCEEDED"
        with patch.object(collection, "api", side_effect=[{"data": self.run}, [{"id": "1"}], RuntimeError("offline")]):
            with self.assertRaises(RuntimeError):
                collection.fetch_run("token", self.directory)
        self.assertFalse((self.directory / "export.json").exists())
        with patch.object(collection, "api", side_effect=[{"data": self.run}, [{"id": "1"}], []]) as api:
            self.assertEqual(collection.fetch_run("token", self.directory)["items"], 1)
        self.assertTrue(all("body" not in call.kwargs for call in api.call_args_list))

    def test_recovery_verifies_input_and_actor(self):
        self.start()
        (self.directory / "run.json").unlink()
        original = collection.make_input("search", ["climate"], limit=2)
        for recovered in [{"searchQueries": ["different"]}, original]:
            with patch.object(collection, "api", side_effect=[{"data": self.run}, {"data": {"id": "actor123"}}, recovered]):
                if recovered == original:
                    self.assertFalse(collection.fetch_run("token", self.directory, run_id="run123")["exported"])
                else:
                    with self.assertRaisesRegex(ValueError, "does not match"):
                        collection.fetch_run("token", self.directory, run_id="run123")

    def test_transport_uses_header_and_does_not_echo_response(self):
        with patch.object(collection, "urlopen", side_effect=HTTPError("https://api.apify.com", 401, "secret-token", {}, None)) as opened:
            with self.assertRaisesRegex(RuntimeError, "Apify HTTP 401") as error:
                collection.api("secret-token", "actor-runs/run123")
        self.assertNotIn("secret-token", str(error.exception))
        request = opened.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer secret-token")
        self.assertNotIn("secret-token", request.full_url)


if __name__ == "__main__":
    unittest.main()
