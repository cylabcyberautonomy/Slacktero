"""Uploader: a Zotero item in, written to the group library (unfiled) if new."""

import os
import logging
import requests

from .config import Config

log = logging.getLogger("slacktero")


class Uploader:
    def __init__(self, cfg: Config):
        self.items_url = f"{cfg.zotero_api_base}/groups/{cfg.zotero_group_id}/items"
        self.headers = {
            "Zotero-API-Key": cfg.zotero_api_key,
            "Zotero-API-Version": "3",
        }

    # ponytail: returns the itemKey, not an ADDED/DUPLICATE enum — no caller
    # tells the two apart today (both are a green check).
    def upload(self, item: dict) -> str:
        existing = self.find_existing(item)
        if existing:
            log.debug("dedup hit: %s already in group", existing)
            return existing
        return self.add_item(item)["key"]

    def find_existing(self, item: dict) -> str | None:
        doi = (item.get("DOI") or "").strip()
        if doi:
            hit = self._search(doi)
            if hit:
                return hit

        url = (item.get("url") or "").strip()
        if url:
            return self._search(url)

        return None

    def add_item(self, item: dict) -> dict:
        item.pop("collections", None)  # omitting collections = lands in Unfiled Items

        resp = requests.post(
            self.items_url,
            json=[item],
            headers={
                **self.headers,
                "Content-Type": "application/json",
                "Zotero-Write-Token": os.urandom(16).hex(),
            },
            timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()

        # A 200 can still carry per-item failures.
        if result.get("failed"):
            _, err = next(iter(result["failed"].items()))
            raise RuntimeError(err.get("message", "unknown Zotero write error"))

        created = next(iter(result["successful"].values()))
        return created["data"]

    def _search(self, query: str) -> str | None:
        resp = requests.get(
            self.items_url,
            params={
                "q": query,
                "qmode": "everything",
                "itemType": "-attachment",
                "format": "json",
                "limit": 1,
            },
            headers=self.headers,
            timeout=30,
        )
        resp.raise_for_status()
        hits = resp.json()
        return hits[0]["key"] if hits else None
