"""Read raster images via Anki's documented-in-source media download protocol.

Only msync/begin and msync/downloadFiles are permitted. No media sync, upload,
deletion or local filesystem extraction is performed. Protocol reference:
ankitects/anki rslib/src/sync/{request/multipart.rs,media/{begin,download,zip}.rs}.
"""
from __future__ import annotations

import base64
import io
import json
import zipfile
from urllib.parse import urljoin, urlsplit

import httpx

from card_media import MAX_MEDIA_BYTES, MAX_TOTAL_BYTES, filename, raster, rich, validate_media
from cloud_sync import CloudSyncError, _validate_endpoint

MAX_ZIP = MAX_TOTAL_BYTES + 256 * 1024


def _response(client, base, method, key, payload, *, local=False):
    if method not in {"begin", "downloadFiles"}:
        raise CloudSyncError("Only read-only media requests are permitted.")
    url = base + "msync/" + method
    for _ in range(4):
        with client.stream("POST", url, data={"k": key, "c": "0", "v": "anki,26.9.3,AnkiAtlas"},
                           files={"data": ("data", json.dumps(payload).encode(), "application/json")}) as response:
            if response.status_code in {301, 302, 303, 307, 308}:
                target = urljoin(url, response.headers.get("location", ""))
                parsed = urlsplit(target)
                _validate_endpoint(f"{parsed.scheme}://{parsed.netloc}/", test_local_only=local)
                if parsed.path != "/msync/" + method or parsed.query or parsed.fragment:
                    raise CloudSyncError("Unsupported media redirect.")
                url = target
                continue
            response.raise_for_status()
            result = bytearray()
            limit = 64 * 1024 if method == "begin" else MAX_ZIP
            for chunk in response.iter_bytes():
                if len(result) + len(chunk) > limit:
                    raise CloudSyncError("Media response exceeds the image size limits.")
                result.extend(chunk)
            return bytes(result)
    raise CloudSyncError("Too many media redirects.")


def _unzip(data, requested):
    media = {}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        infos = archive.infolist()
        if len(infos) > len(requested) + 1 or len({i.filename for i in infos}) != len(infos):
            raise ValueError
        metadata = archive.getinfo("_meta")
        if metadata.file_size > 64 * 1024:
            raise ValueError
        with archive.open(metadata) as stream:
            mapping = json.loads(stream.read(64 * 1024 + 1))
        if (not isinstance(mapping, dict) or len(mapping) > len(requested)
                or set(mapping) != {i.filename for i in infos if i.filename != "_meta"}
                or len(set(mapping.values())) != len(mapping)):
            raise ValueError
        total = 0
        for key, name in mapping.items():
            if (not key.isdigit() or name not in requested or filename(name) != name):
                raise ValueError
            info = archive.getinfo(key)
            total += info.file_size
            if info.is_dir() or info.file_size > MAX_MEDIA_BYTES or total > MAX_TOTAL_BYTES:
                raise ValueError
            with archive.open(info) as stream:
                content = stream.read(MAX_MEDIA_BYTES + 1)
            if len(content) > MAX_MEDIA_BYTES:
                raise ValueError
            mime = raster(content)
            if mime:
                media[name] = {"mime": mime, "data": base64.b64encode(content).decode("ascii")}
    return validate_media(media)


def download_media(snapshot, hkey, endpoint=None, *, _test_endpoint=None):
    """Fetch only referenced raster images, with strict URL/archive/size limits."""
    base = _validate_endpoint(_test_endpoint or endpoint or "https://sync.ankiweb.net/",
                              test_local_only=_test_endpoint is not None)
    if not isinstance(hkey, str) or not hkey or len(hkey) > 4096 or any(not 33 <= ord(c) <= 126 for c in hkey):
        raise CloudSyncError("Set a valid AnkiWeb sync token.")
    names = set()
    for card in snapshot["cards"]:
        for side in ("front", "back"):
            _, refs = rich(card[side], answer_only=side == "back")
            names.update(refs)
    if len(names) > 500:
        raise CloudSyncError("More than 500 referenced images; narrow the collection query.")
    if not names:
        return {}
    try:
        with httpx.Client(timeout=httpx.Timeout(60, connect=10), follow_redirects=False,
                          trust_env=_test_endpoint is None) as client:
            begin = json.loads(_response(client, base, "begin", hkey, {}, local=_test_endpoint is not None))
            session = begin.get("data", {}).get("sk")
            if begin.get("err") or not isinstance(session, str) or not session or len(session) > 4096:
                raise ValueError
            ordered = sorted(names)
            media = {}
            for offset in range(0, len(ordered), 8):
                batch = ordered[offset:offset + 8]
                zipped = _response(client, base, "downloadFiles", session, {"files": batch}, local=_test_endpoint is not None)
                media.update(_unzip(zipped, set(batch)))
                validate_media(media)
            return media
    except CloudSyncError:
        raise
    except Exception:
        raise CloudSyncError("Read-only image download failed; no upload or media deletion was attempted.") from None
