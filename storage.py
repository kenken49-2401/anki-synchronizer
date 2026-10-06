"""Remote encrypted state. A database lease fences writers across restarts/instances."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import httpx
from cryptography.fernet import Fernet
from key_value.aio.stores.base import BaseStore, ManagedEntry
from fastmcp.exceptions import ToolError


class StorageError(ToolError):
    pass


class Supabase:
    def __init__(self, url: str, key: str):
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith(".supabase.co") or parsed.path not in ("", "/"):
            raise ValueError("SUPABASE_URL must be a standard HTTPS Supabase project URL")
        self.url = url.rstrip("/") + "/rest/v1"
        self.headers = {"apikey": key, "Authorization": f"Bearer {key}"}

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            with httpx.Client(timeout=30, headers=self.headers) as client:
                res = client.request(method, self.url + path, **kwargs)
                res.raise_for_status()
                return res.json() if res.content else None
        except (httpx.HTTPError, ValueError):
            # Do not expose request bodies, tokens, database errors, or card contents.
            raise StorageError("保存先に接続できません。休止状態・設定・使用量を確認してください。") from None

    async def arequest(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            async with httpx.AsyncClient(timeout=30, headers=self.headers) as client:
                res = await client.request(method, self.url + path, **kwargs)
                res.raise_for_status()
                return res.json() if res.content else None
        except (httpx.HTTPError, ValueError):
            raise StorageError("認証情報の保存先に接続できません。") from None

    def acquire(self, lease: str) -> dict:
        return self.request("POST", "/rpc/anki_acquire", json={"p_lease": lease})

    def commit(self, lease: str, revision: int, payload: str) -> int:
        return self.request("POST", "/rpc/anki_commit", json={
            "p_lease": lease, "p_revision": revision, "p_payload": payload,
        })

    def release(self, lease: str) -> None:
        self.request("POST", "/rpc/anki_release", json={"p_lease": lease})


class EncryptedOAuthStore(BaseStore):
    """Keep OAuth registrations and token mappings alive across Render spin-downs."""
    def __init__(self, db: Supabase, key: str):
        super().__init__(stable_api=True)
        self.db = db
        self.cipher = Fernet(key.encode())

    async def _get_managed_entry(self, *, collection: str, key: str) -> ManagedEntry | None:
        rows = await self.db.arequest("GET", "/anki_oauth", params={
            "collection": "eq." + collection, "key": "eq." + key, "select": "payload,created_at,expires_at",
        })
        if not rows:
            return None
        row = rows[0]
        value = json.loads(self.cipher.decrypt(row["payload"].encode()))
        return ManagedEntry(value=value,
            created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
            expires_at=datetime.fromisoformat(row["expires_at"]) if row["expires_at"] else None)

    async def _put_managed_entry(self, *, collection: str, key: str, managed_entry: ManagedEntry) -> None:
        encrypted = self.cipher.encrypt(json.dumps(dict(managed_entry.value)).encode()).decode()
        await self.db.arequest("POST", "/rpc/anki_oauth_put", json={
            "p_collection": collection, "p_key": key, "p_payload": encrypted,
            "p_created_at": managed_entry.created_at_isoformat,
            "p_expires_at": managed_entry.expires_at_isoformat,
        })

    async def _delete_managed_entry(self, *, collection: str, key: str) -> bool:
        rows = await self.db.arequest("DELETE", "/anki_oauth", params={
            "collection": "eq." + collection, "key": "eq." + key,
        }, headers={**self.db.headers, "Prefer": "return=representation"})
        return bool(rows)
