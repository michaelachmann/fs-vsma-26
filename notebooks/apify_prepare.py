"""Convert archived Apify runs to explicit corpus submissions; never write raw.

See Clockworks' tiktok-scraper and tiktok-comments-scraper output schemas.
Private originals stay in the run folder. Public attachments omit access URLs.
"""
import fcntl
import hashlib
import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from apify_collection import atomic_json

ID = re.compile(r"[0-9]{1,32}\Z")
ACCOUNT = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]{0,63}\Z")
MAX_MEDIA_BYTES = 2 * 1024**3


def identifier(value):
    # JSON numeric IDs are accepted only as integers; floats may have lost digits.
    if isinstance(value, bool) or not isinstance(value, (str, int)) or not ID.fullmatch(str(value)):
        raise ValueError("Missing or invalid numeric TikTok ID")
    return str(value)


def normalize_post(item):
    author, video, music = item.get("authorMeta") or {}, item.get("videoMeta") or {}, item.get("musicMeta") or {}
    if not all(isinstance(value, dict) for value in (author, video, music)):
        raise ValueError("Unexpected Apify author/video/music metadata structure")
    if item.get("text") is not None and not isinstance(item["text"], str):
        raise ValueError("Unexpected post caption type")
    post_id = identifier(item.get("id"))
    account = author.get("name")
    if not isinstance(account, str) or not ACCOUNT.fullmatch(account) or account in {"_metadata", "_collections"}:
        raise ValueError("Missing or invalid TikTok creator handle")
    created = item.get("createTime")
    if created is None and item.get("createTimeISO"):
        from datetime import datetime
        created = int(datetime.fromisoformat(item["createTimeISO"].replace("Z", "+00:00")).timestamp())
    return {
        "id": post_id, "author": {"uniqueId": account}, "desc": item.get("text") or "",
        "createTime": created, "video": {"duration": video.get("duration")},
        "stats": {key: item.get(key) for key in ("playCount", "diggCount", "commentCount", "shareCount", "collectCount")},
        "music": {"title": music.get("musicName"), "original": music.get("musicOriginal")},
        "isAd": item.get("isAd"),
    }


def comment_post_id(item):
    for key in ("videoWebUrl", "submittedVideoUrl", "input"):
        value = item.get(key)
        if isinstance(value, str):
            match = re.fullmatch(r"https://(?:www\.)?tiktok\.com/@[^/]+/(?:video|photo)/(\d+)/?", value)
            if match:
                return identifier(match[1])
    raise ValueError("Comment lacks a full parent post URL")


def normalize_comment(item, run_id, retrieved_at):
    if item.get("text") is not None and not isinstance(item["text"], str):
        raise ValueError("Unexpected comment text type")
    parent = item.get("repliesToId")
    return {
        "record_type": "tiktok_comment", "schema_version": 1,
        "post_id": comment_post_id(item), "comment_id": identifier(item.get("cid")),
        "parent_comment_id": None if parent in (None, "", "0", 0) else identifier(parent),
        "text": item.get("text") or "", "username": item.get("uniqueId"),
        "created": item.get("createTimeISO"), "likes": item.get("diggCount"),
        "reply_count": item.get("replyCommentTotal"), "run_id": run_id, "retrieved_at": retrieved_at,
    }


def public_source(value):
    """Preserve non-URL source fields; access URLs stay in the private archive."""
    if isinstance(value, dict):
        return {key: public_source(v) for key, v in value.items()
                if not re.search(r"token|secret|password|authorization|cookie", key, re.I)}
    if isinstance(value, list):
        return [public_source(v) for v in value]
    if isinstance(value, str) and re.match(r"https?://", value):
        return "[access URL retained in private export]"
    return value


def check_media_url(url):
    parts = urlsplit(url)
    host = parts.hostname or ""
    allowed = ("apify.com", "apifyusercontent.com", "tiktok.com", "tiktokcdn.com", "tiktokcdn-us.com", "tiktokcdn-eu.com", "byteoversea.com", "ibytedtos.com")
    if (parts.scheme != "https" or parts.username or parts.password or parts.port not in (None, 443)
            or not any(host == domain or host.endswith("." + domain) for domain in allowed)):
        raise ValueError("Media URL is outside the supported HTTPS media hosts")
    addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(addr[4][0]).is_global for addr in addresses):
        raise ValueError("Media URL does not resolve to public internet addresses")
    return parts


class MediaRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_media_url(newurl)
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected:
            # Authentication must not follow a redirect, even between allowed hosts.
            redirected.remove_header("Authorization")
        return redirected


def download(url, destination, token=None):
    """Bounded streaming download. Never include URLs/remote errors in receipts."""
    try:
        parts = check_media_url(url)
        headers = {}
        if parts.hostname == "api.apify.com" and parts.path.startswith("/v2/key-value-stores/") and token:
            headers["Authorization"] = "Bearer " + token
        with build_opener(MediaRedirects()).open(Request(url, headers=headers), timeout=60) as response:
            size = 0
            with destination.open("wb") as stream:
                while block := response.read(1024 * 1024):
                    size += len(block)
                    if size > MAX_MEDIA_BYTES:
                        raise ValueError("Media exceeds the corpus 2 GB file limit")
                    stream.write(block)
                stream.flush()
                os.fsync(stream.fileno())
        if not size:
            raise ValueError("Empty media download")
    except Exception:
        destination.unlink(missing_ok=True)
        raise ValueError("Media download failed; retry preparation or inspect private source URLs") from None


def probe(path, kind):
    result = subprocess.run([
        "ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe", "-show_entries",
        "stream=codec_type:format=format_name", "-of", "json", str(path),
    ], capture_output=True, timeout=60, check=True)
    data = json.loads(result.stdout)
    if not any(s.get("codec_type") == "video" for s in data.get("streams", [])):
        raise ValueError("Downloaded media has no visual stream")
    if kind == "video" and not set(data.get("format", {}).get("format_name", "").split(",")) & {"mov", "mp4", "matroska", "webm"}:
        raise ValueError("Downloaded video is not an MP4 or WebM container")


def obtain_media(url, target, token, image=False):
    """Reuse completed private downloads; convert images to the corpus JPEG convention."""
    if target.exists():
        probe(target, "image" if image else "video")
        return
    temporary = target.with_suffix(".download")
    download(url, temporary, token)
    try:
        probe(temporary, "image" if image else "video")
        if image:
            converted = target.with_suffix(".partial.jpg")
            try:
                subprocess.run(["ffmpeg", "-v", "error", "-protocol_whitelist", "file,pipe", "-i", str(temporary),
                                "-frames:v", "1", "-y", str(converted)], check=True, capture_output=True, timeout=60)
                probe(converted, "image")
                converted.replace(target)
            finally:
                converted.unlink(missing_ok=True)
        else:
            temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def existing_posts(raw):
    result = {}
    for path in sorted(raw.glob("*/*.json")):
        if path.parent.name in {"_collections", "_metadata"} or not ID.fullmatch(path.stem):
            continue
        if path.stem in result:
            raise ValueError("Corpus has duplicate post IDs across creator folders; ask the instructor")
        result[path.stem] = path
    return result


def write_lines(path, rows):
    with path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")


def prepare_run(directory, *, raw=Path("/corpus/raw"), token=None, include_media=True, allow_partial=False):
    """Prepare privately; per-post errors are reported, never staged as successes.

Comment runs require posts already in raw and reuse their exact metadata bytes.
Repeated post observations also reuse canonical JSON; the new snapshot remains
in apify-source.jsonl. No existing raw metadata/media is overwritten.
"""
    directory, raw = Path(directory).expanduser(), Path(raw)
    if not raw.is_dir():
        raise ValueError("Set raw to the readable corpus raw folder")
    with (directory / "prepare.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return _prepare(directory, raw, token, include_media, allow_partial)


def _prepare(directory, raw, token, include_media, allow_partial):
    request = json.loads((directory / "request.json").read_text())
    exported = json.loads((directory / "export.json").read_text())
    with (directory / "items.jsonl").open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != exported["sha256"]:
            raise ValueError("Private export checksum mismatch")
    if exported["partial"] and not allow_partial:
        raise ValueError("Run was partial; review it and set allow_partial=True explicitly")
    if request.get("mode") not in {"search", "hashtag", "comments"}:
        raise ValueError("Unsupported collection mode")
    run_id = exported["run_id"]
    if not re.fullmatch(r"[A-Za-z0-9]+", run_id):
        raise ValueError("Invalid run ID")
    index = existing_posts(raw)
    cache = directory / "media"
    cache.mkdir(exist_ok=True, mode=0o700)
    output = directory / "prepared"
    # A failed retry must never leave an older prepared batch publishable.
    if output.exists():
        shutil.rmtree(output)
    report = {"schema_version": 1, "run_id": run_id, "mode": request["mode"],
              "include_media": include_media, "posts": [], "comments": 0, "errors": [], "partial_run": exported["partial"]}
    prepared = Path(tempfile.mkdtemp(prefix=".prepare-", dir=directory))
    snapshots, comments = [], []
    seen = set()
    try:
        with (directory / "items.jsonl").open() as stream:
            for line_number, line in enumerate(stream, 1):
                try:
                    item = json.loads(line)
                    if not isinstance(item, dict) or item.get("error") or item.get("errorCode"):
                        raise ValueError("Actor returned an error item")
                    if request["mode"] == "comments":
                        comment = normalize_comment(item, run_id, exported["retrieved_at"])
                        post_id = comment["post_id"]
                        if post_id not in index:
                            raise ValueError("Import the parent post before staging its comments")
                        canonical = index[post_id]
                        post = json.loads(canonical.read_text())
                    else:
                        post = normalize_post(item)
                        post_id = post["id"]
                        canonical = index.get(post_id)
                    if post_id not in seen:
                        bundle = Path(tempfile.mkdtemp(prefix=".post-", dir=directory))
                        try:
                            if canonical:
                                existing = json.loads(canonical.read_text())
                                if str(existing.get("id")) != post_id or existing.get("author", {}).get("uniqueId") != canonical.parent.name:
                                    raise ValueError("Existing corpus post metadata is invalid")
                                shutil.copyfile(canonical, bundle / f"{post_id}.json")
                            else:
                                atomic_json(bundle / f"{post_id}.json", post)
                            if include_media and request["mode"] != "comments":
                                _post_media(item, post_id, canonical, cache, bundle, token)
                            for file in bundle.iterdir():
                                file.replace(prepared / file.name)
                        finally:
                            shutil.rmtree(bundle)
                        seen.add(post_id)
                        report["posts"].append(post_id)
                    if request["mode"] == "comments":
                        comments.append(comment)
                    snapshots.append({"record_type": "apify_source", "schema_version": 1, "run_id": run_id,
                                      "post_id": post_id, "retrieved_at": exported["retrieved_at"], "item": public_source(item)})
                except (ValueError, TypeError, KeyError, OSError, subprocess.SubprocessError) as error:
                    # Detailed diagnostics stay private; public attachments only count failures.
                    report["errors"].append({"line": line_number, "reason": str(error)})
        report["comments"] = len(comments)
        if not seen:
            raise ValueError("No valid posts prepared; see preparation.json and the private export")
        write_lines(prepared / "apify-source.jsonl", snapshots)
        if comments:
            write_lines(prepared / "comments.jsonl", comments)
        run = json.loads((directory / "run.json").read_text())
        write_lines(prepared / "collection-info.jsonl", [{
            "record_type": "apify_collection", "schema_version": 1, "provider": "apify",
            "actor": request["actor"], "mode": request["mode"], "label": request["label"],
            "input": public_source(request["input"]), "run_id": run_id,
            "build_id": run.get("buildId"), "build_number": run.get("buildNumber"),
            "retrieved_at": exported["retrieved_at"], "source_sha256": exported["sha256"],
            "partial_run": exported["partial"], "skipped_records": len(report["errors"]),
        }])
        prepared.replace(output)
        report["files"] = {p.name: file_hash(p) for p in sorted(output.iterdir())}
        return report
    finally:
        atomic_json(directory / "preparation.json", report)
        if prepared.exists():
            shutil.rmtree(prepared)


def _post_media(item, post_id, canonical, cache, bundle, token):
    def add(url, name, image=False):
        if canonical and (canonical.parent / name).is_file():
            return  # Corpus already has the media; do not redownload or recopy it.
        if not isinstance(url, str) or not url:
            raise ValueError("Requested media URL is missing")
        target = cache / name
        obtain_media(url, target, token, image=image)
        shutil.copyfile(target, bundle / name)

    video = item.get("videoMeta") or {}
    slides = item.get("slideshowImageLinks") or []
    if item.get("isSlideshow"):
        if not slides:
            raise ValueError("Slideshow images missing")
        for i, slide in enumerate(slides):
            add(slide.get("downloadLink") or slide.get("tiktokLink"), f"{post_id}_{i}.jpg", image=True)
    else:
        urls = item.get("mediaUrls") or []
        if len(urls) > 1:
            raise ValueError("Ambiguous video media URL list; inspect the private record")
        add((urls[0] if urls else None) or video.get("downloadAddr"), f"{post_id}.mp4")
    cover = video.get("coverUrl") or video.get("originalCoverUrl")
    if not cover and slides:
        cover = slides[0].get("downloadLink") or slides[0].get("tiktokLink")
    add(cover, f"{post_id}_cover.jpg", image=True)


def file_hash(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def stage_run(directory, incoming_user_root):
    """Copy a verified, completed batch into the student's existing incoming root.

Reruns refuse an existing destination, including after import cleanup. No symlinks
or arbitrary filenames are published. Originals and private preparation survive.
"""
    directory, root = Path(directory).expanduser(), Path(incoming_user_root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Choose your existing incoming account folder")
    with (directory / "prepare.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        report = json.loads((directory / "preparation.json").read_text())
        if not report.get("files") or not report.get("posts"):
            raise ValueError("Prepare the run successfully first")
        if not re.fullmatch(r"[A-Za-z0-9]+", report["run_id"]):
            raise ValueError("Invalid run ID")
        destination = root / ("apify-" + report["run_id"])
        if destination.exists() or destination.is_symlink() or (directory / "staged.json").exists():
            raise ValueError("This run was already staged; use its ingestion receipt or a new deliberate collection")
        temporary = Path(tempfile.mkdtemp(prefix=".apify-", dir=root))
        try:
            for name, expected in report["files"].items():
                if not re.fullmatch(r"(?:\d+(?:_cover|_\d+)?\.(?:json|mp4|jpg)|(?:apify-source|collection-info|comments)\.jsonl)", name):
                    raise ValueError("Unexpected filename in prepared batch")
                source = directory / "prepared" / name
                if source.is_symlink() or file_hash(source) != expected:
                    raise ValueError("Prepared files changed; prepare again before staging")
                shutil.copyfile(source, temporary / name)
                if file_hash(temporary / name) != expected:
                    raise ValueError("Staging copy failed checksum verification")
                os.chmod(temporary / name, 0o644)
            # Public incoming folders follow the server's established read policy.
            os.chmod(temporary, 0o755)
            # Save intent first so a crash cannot silently cause a repeat submission.
            atomic_json(directory / "staged.json", {"run_id": report["run_id"], "folder": destination.name})
            temporary.rename(destination)
            return destination
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
