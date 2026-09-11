"""Translator: a URL in, one clean Zotero item out, via the translation-server."""

import re
import logging
import requests

from .config import Config

log = logging.getLogger("slacktero")


class TranslationError(Exception):
    """`status` is the HTTP code behind the failure: 5xx server vs 4xx/300 link."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class Translator:
    ARXIV_PDF = re.compile(r"arxiv\.org/pdf/(\d{4}\.\d{4,5}(?:v\d+)?)", re.I)
    DOI = re.compile(r"10\.\d{4,9}/[^\s\"'<>?#]+", re.I)

    # The write API rejects these on a top-level create (child items / server-assigned).
    STRIP_FIELDS = ("key", "version", "dateAdded", "dateModified",
                    "attachments", "notes", "tags")

    def __init__(self, cfg: Config):
        self.server = cfg.translation_server_url

    def translate(self, url: str) -> dict | None:
        url = self.normalize(url)
        resp = requests.post(
            f"{self.server}/web",
            data=url.encode("utf-8"),
            headers={"Content-Type": "text/plain"},
            timeout=60,
        )
        log.debug("/web %s -> HTTP %d", url, resp.status_code)
        if resp.status_code == 300:
            raise TranslationError("that link resolved to multiple items", status=300)

        if resp.status_code == 200:
            items = resp.json()
            if items:
                return self._clean(items[0])

        # Fallback for pages the server can't fetch (e.g. ACM 403s): resolve any
        # DOI in the URL via Crossref, which the broken doi.org path mis-encodes.
        item = self._via_doi(url)
        if item:
            return item

        if resp.status_code != 200:
            raise TranslationError(
                f"translation-server returned HTTP {resp.status_code}",
                status=resp.status_code,
            )
        return None

    def normalize(self, url: str) -> str:
        """Rewrite known un-translatable URLs to a translatable equivalent."""
        m = self.ARXIV_PDF.search(url)
        return f"https://arxiv.org/abs/{m.group(1)}" if m else url

    def _via_doi(self, url: str) -> dict | None:
        m = self.DOI.search(url)
        if not m:
            return None
        log.debug("DOI fallback via /search: %s", m.group(0))
        resp = requests.post(
            f"{self.server}/search",
            data=m.group(0).encode("utf-8"),
            headers={"Content-Type": "text/plain"},
            timeout=60,
        )
        if resp.status_code != 200:
            return None
        items = resp.json()
        return self._clean(items[0]) if items else None

    def _clean(self, item: dict) -> dict:
        return {k: v for k, v in item.items() if k not in self.STRIP_FIELDS}
