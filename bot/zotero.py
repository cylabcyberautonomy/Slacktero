"""Zotero glue: turn a URL into an item, check for duplicates, write it.

Three public functions, used by app.py in order:
    translate(url)        -> cleaned item dict (or None)
    find_existing(item)   -> itemKey of a duplicate (or None)
    add_item(item)        -> created item data

Nothing here holds state; the Zotero group library is the source of truth.
"""

import os
import requests

ZOTERO_API = "https://api.zotero.org"
GROUP_ID = os.environ["ZOTERO_GROUP_ID"]
API_KEY = os.environ["ZOTERO_API_KEY"]
TRANSLATION_SERVER_URL = os.environ.get(
    "TRANSLATION_SERVER_URL", "http://translation-server:1969"
)

_HEADERS = {
    "Zotero-API-Key": API_KEY,
    "Zotero-API-Version": "3",
}

# translation-server returns these, but the write API rejects them on a
# top-level item create: notes/attachments are child items that must be
# POSTed separately with a parentItem, and key/version/dates are
# server-assigned.
_STRIP_FIELDS = ("key", "version", "dateAdded", "dateModified",
                 "attachments", "notes")


class TranslationError(Exception):
    """Raised when the translation-server can't produce a single clean item."""


def translate(url: str) -> dict | None:
    """Resolve a URL to one Zotero item via the translation-server.

    Returns the cleaned item dict, or None if no metadata could be extracted.
    Raises TranslationError on ambiguous or failed translation.
    """
    resp = requests.post(
        f"{TRANSLATION_SERVER_URL}/web",
        data=url.encode("utf-8"),
        headers={"Content-Type": "text/plain"},
        timeout=60,
    )
    if resp.status_code == 300:
        # The URL matched multiple items (e.g. a search-results page).
        raise TranslationError("that link resolved to multiple items")
    if resp.status_code != 200:
        raise TranslationError(
            f"translation-server returned HTTP {resp.status_code}"
        )

    items = resp.json()
    if not items:
        return None
    return _clean(items[0])


def find_existing(item: dict) -> str | None:
    """Return the itemKey of a matching item already in the group, or None.

    DOI match is authoritative. URL match is best-effort: the Web API has no
    exact-URL filter, so this is a quicksearch and can miss near-duplicates.
    """
    doi = (item.get("DOI") or "").strip()
    if doi:
        hit = _search(doi)
        if hit:
            return hit

    url = (item.get("url") or "").strip()
    if url:
        return _search(url)

    return None


def add_item(item: dict) -> dict:
    """Create one item in the group library, unfiled. Returns its data.

    Omitting the `collections` field is what lands the item in Unfiled Items.
    """
    item.pop("collections", None)  # defensive: never file into a collection

    resp = requests.post(
        f"{ZOTERO_API}/groups/{GROUP_ID}/items",
        json=[item],
        headers={
            **_HEADERS,
            "Content-Type": "application/json",
            "Zotero-Write-Token": os.urandom(16).hex(),
        },
        timeout=30,
    )
    resp.raise_for_status()
    result = resp.json()

    # A 200 can still contain per-item failures.
    if result.get("failed"):
        _, err = next(iter(result["failed"].items()))
        raise RuntimeError(err.get("message", "unknown Zotero write error"))

    created = next(iter(result["successful"].values()))
    return created["data"]


def _clean(item: dict) -> dict:
    return {k: v for k, v in item.items() if k not in _STRIP_FIELDS}


def _search(query: str) -> str | None:
    resp = requests.get(
        f"{ZOTERO_API}/groups/{GROUP_ID}/items",
        params={
            "q": query,
            "qmode": "everything",
            "itemType": "-attachment",
            "format": "json",
            "limit": 1,
        },
        headers=_HEADERS,
        timeout=30,
    )
    resp.raise_for_status()
    hits = resp.json()
    return hits[0]["key"] if hits else None
