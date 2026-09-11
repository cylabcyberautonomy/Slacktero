"""Filer: a Zotero item in, written to the group library (unfiled) if new.

Holds an in-memory index of the library, because Zotero's `q` search covers
title/creator/year only and cannot match on DOI or url.
"""

import os
import re
import logging
import threading

import requests

from .config import Config

log = logging.getLogger("slacktero")


class Filer:
    ARXIV_VERSION = re.compile(r"^(arxiv\.org/abs/[^/]+?)v\d+$")
    PAGE = 100
    SYNC_RETRIES = 5

    def __init__(self, cfg: Config):
        self.base = f"{cfg.zotero_api_base}/groups/{cfg.zotero_group_id}"
        self.headers = {
            "Zotero-API-Key": cfg.zotero_api_key,
            "Zotero-API-Version": "3",
        }
        self.projects = cfg.projects
        self.index: dict[str, tuple[str, str]] = {}
        self.collections: dict[str, str] = {}
        self.version = 0
        self.lock = threading.Lock()

    def norm(self, url: str | None) -> str:
        url = re.sub(r"^https?://", "", (url or "").strip().lower())
        return self.ARXIV_VERSION.sub(r"\1", re.sub(r"^www\.", "", url).rstrip("/"))

    def sync(self) -> None:
        for _ in range(self.SYNC_RETRIES):
            entries, versions, start = [], set(), 0

            while True:
                resp = requests.get(
                    f"{self.base}/items",
                    params={"format": "json", "itemType": "-attachment",
                            "since": self.version, "limit": self.PAGE, "start": start},
                    headers=self.headers,
                    timeout=30,
                )
                resp.raise_for_status()
                versions.add(int(resp.headers["Last-Modified-Version"]))
                page = resp.json()
                entries += page
                start += len(page)
                if len(page) < self.PAGE:
                    break

            resp = requests.get(
                f"{self.base}/items/trash",
                params={"format": "keys", "since": self.version},
                headers=self.headers,
                timeout=30,
            )
            resp.raise_for_status()
            versions.add(int(resp.headers["Last-Modified-Version"]))
            trashed = resp.text.split()

            resp = requests.get(
                f"{self.base}/deleted",
                params={"since": self.version},
                headers=self.headers,
                timeout=30,
            )
            resp.raise_for_status()
            versions.add(int(resp.headers["Last-Modified-Version"]))

            if len(versions) > 1:
                log.debug("library moved mid-sync %s, restarting", sorted(versions))
                continue

            for entry in entries:
                data = entry["data"]
                self.index[data["key"]] = (
                    (data.get("DOI") or "").strip().lower(), self.norm(data.get("url"))
                )
            for key in trashed + resp.json().get("items", []):
                self.index.pop(key, None)
            self.version = versions.pop()
            log.debug("index: %d items at version %d", len(self.index), self.version)
            return

        raise RuntimeError("Zotero library kept changing during sync")

    def collection_keys(self) -> dict[str, str]:
        if self.collections:
            return self.collections

        found, start = {}, 0
        while True:
            resp = requests.get(
                f"{self.base}/collections",
                params={"format": "json", "limit": self.PAGE, "start": start},
                headers=self.headers,
                timeout=30,
            )
            resp.raise_for_status()
            page = resp.json()
            for entry in page:
                name, key = entry["data"]["name"], entry["data"]["key"]
                if name in found:
                    raise RuntimeError(f"two collections named {name!r}")
                found[name] = key
            start += len(page)
            if len(page) < self.PAGE:
                break

        missing = [name for name in self.projects if name not in found]
        if missing:
            resp = requests.post(
                f"{self.base}/collections",
                json=[{"name": name, "parentCollection": False} for name in missing],
                headers={**self.headers, "Content-Type": "application/json"},
                timeout=30,
            )
            resp.raise_for_status()
            for created in resp.json()["successful"].values():
                found[created["data"]["name"]] = created["data"]["key"]
            log.debug("created collections: %s", missing)

        self.collections = {name: found[name] for name in self.projects}
        return self.collections

    def tag(self, key: str, name: str, add: bool) -> None:
        keys = self.collection_keys()
        managed = set(keys.values())

        for _ in range(self.SYNC_RETRIES):
            resp = requests.get(f"{self.base}/items/{key}", headers=self.headers, timeout=30)
            resp.raise_for_status()
            data = resp.json()["data"]

            tags = {t["tag"] for t in data.get("tags", [])}
            if add:
                tags.add(name)
            else:
                tags.discard(name)
            wanted = {keys[p] for p, ts in self.projects.items() if tags & set(ts)}

            resp = requests.patch(
                f"{self.base}/items/{key}",
                json={"tags": [{"tag": t} for t in sorted(tags)],
                      "collections": sorted((set(data.get("collections", [])) - managed) | wanted)},
                headers={**self.headers, "Content-Type": "application/json",
                         "If-Unmodified-Since-Version": str(data["version"])},
                timeout=30,
            )
            if resp.status_code == 412:
                continue
            resp.raise_for_status()
            log.debug("%s %r on %s", "tagged" if add else "untagged", name, key)
            return

        raise RuntimeError(f"item {key} kept changing during tag write")

    def unfiled(self, limit: int) -> list[dict]:
        found, start = [], 0
        while len(found) < limit:
            resp = requests.get(
                f"{self.base}/items/top",
                params={"format": "json", "itemType": "-attachment",
                        "sort": "dateAdded", "direction": "desc",
                        "limit": self.PAGE, "start": start},
                headers=self.headers,
                timeout=30,
            )
            resp.raise_for_status()
            page = resp.json()
            found += [e["data"] for e in page if not e["data"].get("collections")]
            start += len(page)
            if len(page) < self.PAGE:
                break
        return found[:limit]

    def find_existing(self, item: dict) -> str | None:
        self.sync()
        doi = (item.get("DOI") or "").strip().lower()
        url = self.norm(item.get("url"))
        hit = None
        for key, (d, u) in self.index.items():
            if doi and d == doi:
                return key
            if url and u == url:
                hit = hit or key
        return hit

    def file(self, item: dict) -> str:
        with self.lock:
            existing = self.find_existing(item)
            if existing:
                log.debug("dedup hit: %s already in group", existing)
                return existing
            data = self.add_item(item)
            self.index[data["key"]] = (
                (data.get("DOI") or "").strip().lower(), self.norm(data.get("url"))
            )
            return data["key"]

    def add_item(self, item: dict) -> dict:
        item.pop("collections", None)  # omitting collections = lands in Unfiled Items

        resp = requests.post(
            f"{self.base}/items",
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
