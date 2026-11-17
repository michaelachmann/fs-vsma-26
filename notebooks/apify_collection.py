"""Manual Apify collection via REST; no credentials or corpus writes on disk.

Kept separate from the notebook so a future form/worker can reuse it.
"""
import hashlib
import json
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ACTORS = {
    "search": "clockworks/tiktok-scraper",
    "hashtag": "clockworks/tiktok-scraper",
    "comments": "clockworks/tiktok-comments-scraper",
}
TERMINAL = {"SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"}


def positive_int(value, name):
    if type(value) is not int or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def make_input(mode, values, *, limit=20, replies=0, download_media=False):
    """Build one documented collection mode; comments are a separate run."""
    if mode not in ACTORS:
        raise ValueError("Choose search, hashtag or comments")
    if not isinstance(values, list) or not values or any(
        not isinstance(v, str) or not v.strip() for v in values
    ):
        raise ValueError("Enter a nonempty list of search terms, hashtags or post URLs")
    values = [v.strip() for v in values]
    positive_int(limit, "limit")
    if mode == "comments":
        if type(replies) is not int or replies < 0:
            raise ValueError("replies must be a nonnegative integer")
        if any(not re.fullmatch(r"https://(?:www\.)?tiktok\.com/@[^/\s]+/(?:video|photo)/\d+/?", v) for v in values):
            raise ValueError("Use full TikTok post URLs, not profiles or shortened links")
        return {"postURLs": values, "commentsPerPost": limit, "maxRepliesPerComment": replies}
    result = {
        "resultsPerPage": limit,
        "shouldDownloadVideos": bool(download_media),
        "shouldDownloadCovers": bool(download_media),
        "shouldDownloadSlideshowImages": bool(download_media),
        "shouldDownloadAvatars": False,
        "shouldDownloadMusicCovers": False,
        "commentsPerPost": 0,
    }
    if mode == "search":
        result.update(searchQueries=values, searchSection="/video")
    else:
        tags = [v.lstrip("#") for v in values]
        if any(not v or re.search(r"[\s/#]", v) for v in tags):
            raise ValueError("Enter hashtag names, not URLs or phrases with spaces")
        result["hashtags"] = tags
    return result


def api(token, path, *, query=None, body=None):
    """One request. Never retry a POST: its outcome may be ambiguous."""
    url = "https://api.apify.com/v2/" + path
    if query:
        url += "?" + urlencode(query)
    request = Request(url, data=None if body is None else json.dumps(body).encode(), headers={
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json",
    })
    try:
        with urlopen(request, timeout=60) as response:
            return json.load(response)
    except HTTPError as exc:
        # Do not echo request headers or remote response bodies into notebook output.
        raise RuntimeError(f"Apify HTTP {exc.code}; check the account and run in Apify Console") from None
    except (URLError, TimeoutError, OSError):
        raise RuntimeError("Apify connection failed; check Console before starting another run") from None


def atomic_json(path, data):
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def run_record(run):
    # Leave account identity and access URLs out of our local run receipt.
    keys = ("id", "actId", "status", "startedAt", "finishedAt", "buildId", "buildNumber",
            "defaultDatasetId", "defaultKeyValueStoreId", "usageTotalUsd", "options")
    return {key: run[key] for key in keys if key in run}


def start_run(token, directory, *, mode, values, label, limit, replies=0,
              max_cost_usd, timeout_seconds=600, download_media=False):
    """Start once per directory, saving intent before the chargeable request.

An existing directory is deliberately refused, including after connection errors.
Recover the run ID from Console instead of blindly starting another run.
"""
    run_input = make_input(mode, values, limit=limit, replies=replies, download_media=download_media)
    if not isinstance(label, str) or not label.strip():
        raise ValueError("A collection label is required")
    try:
        cost = float(max_cost_usd)
    except (TypeError, ValueError):
        raise ValueError("Set a positive maximum run cost in USD") from None
    if not math.isfinite(cost) or cost <= 0:
        raise ValueError("Set a positive maximum run cost in USD")
    positive_int(timeout_seconds, "timeout_seconds")
    if not token or not token.strip():
        raise ValueError("Enter your own Apify token")
    directory = Path(directory).expanduser()
    directory.mkdir(parents=True, exist_ok=False, mode=0o700)
    atomic_json(directory / "request.json", {
        "schema_version": 1, "provider": "apify", "actor": ACTORS[mode],
        "mode": mode, "label": label.strip(), "input": run_input,
        "requested_at": datetime.now(timezone.utc).isoformat(),
        "max_cost_usd": cost, "timeout_seconds": timeout_seconds,
    })
    run = api(token, "actors/" + ACTORS[mode].replace("/", "~") + "/runs",
              query={"maxTotalChargeUsd": cost, "timeout": timeout_seconds,
                     "restartOnError": "false"}, body=run_input)["data"]
    atomic_json(directory / "run.json", run_record(run))
    return run_record(run)


def fetch_run(token, directory, *, run_id=None, page_size=100):
    """Check a run and archive its dataset once terminal, including error rows.

Call again while running or after an interrupted download. This never starts
an Actor. A failed/aborted run's export is explicitly marked as partial.
"""
    positive_int(page_size, "page_size")
    directory = Path(directory).expanduser()
    request = json.loads((directory / "request.json").read_text())
    receipt = directory / "run.json"
    saved = json.loads(receipt.read_text()) if receipt.exists() else {}
    if run_id and saved.get("id") and saved["id"] != run_id:
        raise ValueError("Run ID does not match this collection directory")
    run_id = run_id or saved.get("id")
    if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9]+", run_id):
        raise ValueError("Provide the existing run ID from Apify Console")
    run = api(token, "actor-runs/" + run_id)["data"]
    if not saved:
        # Confirm recovery attaches the intended Actor and exact input.
        actor = api(token, "actors/" + request["actor"].replace("/", "~"))["data"]
        original = api(token, "key-value-stores/" + run["defaultKeyValueStoreId"] + "/records/INPUT")
        if actor["id"] != run["actId"] or any(original.get(k) != v for k, v in request["input"].items()):
            raise ValueError("Recovered run does not match this collection request")
    atomic_json(receipt, run_record(run))
    if run["status"] not in TERMINAL:
        return {"run_id": run_id, "status": run["status"], "exported": False}
    dataset = run.get("defaultDatasetId")
    if not dataset or not re.fullmatch(r"[A-Za-z0-9]+", dataset):
        raise RuntimeError("Run has no usable dataset; inspect it in Apify Console")
    manifest_path = directory / "export.json"
    output = directory / "items.jsonl"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        with output.open("rb") as stream:
            checksum = hashlib.file_digest(stream, "sha256").hexdigest()
        if manifest["run_id"] != run_id or checksum != manifest["sha256"]:
            raise RuntimeError("Archived results failed integrity verification")
        return manifest
    temporary = directory / "items.jsonl.part"
    count = errors = 0
    digest = hashlib.sha256()
    with temporary.open("wb") as stream:
        while True:
            items = api(token, f"datasets/{dataset}/items", query={
                "format": "json", "clean": "false", "offset": count, "limit": page_size,
            })
            if not isinstance(items, list):
                raise RuntimeError("Unexpected dataset response; export remains incomplete")
            if not items:
                break
            for item in items:
                row = (json.dumps(item, ensure_ascii=False) + "\n").encode()
                stream.write(row)
                digest.update(row)
                errors += int(isinstance(item, dict) and bool(item.get("error") or item.get("errorCode")))
            count += len(items)
        stream.flush()
        os.fsync(stream.fileno())
    manifest = {
        "schema_version": 1, "run_id": run_id, "dataset_id": dataset,
        "status": run["status"], "exported": True,
        "partial": run["status"] != "SUCCEEDED", "items": count, "error_items": errors,
        "sha256": digest.hexdigest(), "retrieved_at": datetime.now(timezone.utc).isoformat(),
    }
    if output.exists():
        with output.open("rb") as stream:
            checksum = hashlib.file_digest(stream, "sha256").hexdigest()
        if checksum != manifest["sha256"]:
            raise RuntimeError("Uncommitted archive differs from dataset; preserve both for review")
        temporary.unlink()
    else:
        temporary.replace(output)
    atomic_json(manifest_path, manifest)
    return manifest
