"""Slack event handlers: slice the message, run the pipeline, react.

Each add runs in a daemon thread so the Slack event returns within 3s, before
Slack retries and double-posts.
"""

import re
import random
import logging
import threading
from urllib.parse import urlsplit

import requests

from .config import Config
from .translator import Translator
from .filer import Filer

log = logging.getLogger("slacktero")


class Handler:
    LINK = re.compile(r"<(https?://[^>|\s]+)")
    FILE = re.compile(r"\bfile\b(?:\s+(\d+))?", re.I)
    VENUE = ("publicationTitle", "proceedingsTitle", "repository", "publisher")
    MAX_BACKLOG = 10

    SIGNOFFS = ["Cowabunga!", "Yowza!", "Tubular!",
                "I add links to Zotero. What's a Zotero, anyways?",
                "Kachow!", "You called?"]

    def __init__(self, translator: Translator, filer: Filer,
                 client, bot_user_id: str, cfg: Config):
        self.translator = translator
        self.filer = filer
        self.client = client
        self.bot_user_id = bot_user_id
        self.cfg = cfg

    def links(self, text: str) -> list[str]:
        return self.LINK.findall(text)

    def watched_links(self, text: str) -> list[str]:
        hosts = ((u, urlsplit(u).hostname or "") for u in self.links(text))
        return [u for u, h in hosts
                if any(h == d or h.endswith("." + d) for d in self.cfg.watched_domains)]

    def mentions_me(self, text: str) -> bool:
        return f"<@{self.bot_user_id}>" in text

    def thread_ts(self, event: dict) -> str:
        return event.get("thread_ts", event["ts"])

    def spawn(self, fn, *args) -> None:
        log.debug("%s spawning %s%s", type(self).__name__, fn.__name__, args)
        threading.Thread(target=fn, args=args, daemon=True).start()

    def add(self, url: str, channel: str, ts: str) -> None:
        try:
            item = self.translator.translate(url)
        except Exception:
            log.exception("translation failed for %s", url)
            item = None

        bare = not item
        if bare:
            item = {"itemType": "webpage", "title": url, "url": url}

        try:
            key = self.filer.file(item)
        except Exception as e:
            log.exception("add failed")
            self.react(channel, ts, self.reaction_for(e))
            return

        log.debug("filed %r -> %s (bare=%s)", item.get("title"), key, bare)
        self.react(channel, ts, "warning" if bare else "white_check_mark")
        self.palette(channel, ts)

    def palette(self, channel: str, ts: str) -> None:
        for emoji in self.cfg.tags.values():
            self.react(channel, ts, emoji)

    def help_reply(self, event: dict) -> None:
        domains = ", ".join(f"`{d}`" for d in self.cfg.watched_domains) or "_none_"
        self.client.chat_postMessage(
            channel=event["channel"],
            thread_ts=self.thread_ts(event),
            text="\n".join([
                "*Slacktero commands*",
                "`@Slacktero <link>` \u2014 file a link into the Zotero group",
                "`@Slacktero tags` \u2014 what each emoji tags a paper with",
                f"`@Slacktero file [n]` \u2014 list the n newest unfiled papers to tag "
                f"(default 5, max {self.MAX_BACKLOG})",
                "`@Slacktero help` \u2014 this message",
                "",
                f"DM me a link too. Links from {domains} are filed automatically, "
                "no mention needed.",
            ]),
        )

    def backlog(self, channel: str, count: int) -> None:
        try:
            items = self.filer.unfiled(min(count, self.MAX_BACKLOG))
        except Exception:
            log.exception("backlog fetch failed")
            return
        if not items:
            self.client.chat_postMessage(channel=channel, text="Nothing unfiled. :tada:")
            return
        for data in items:
            posted = self.client.chat_postMessage(channel=channel, text=self.citation(data))
            self.palette(channel, posted["ts"])

    def citation(self, data: dict) -> str:
        names = [c.get("lastName") or c.get("name", "") for c in data.get("creators", [])]
        authors = ", ".join(names[:3]) + (" et al." if len(names) > 3 else "")
        venue = next((data[k] for k in self.VENUE if data.get(k)), "")
        meta = " \u00b7 ".join(x for x in (authors, venue, data.get("date", "")) if x)
        url = data.get("url")
        lines = [f"*{data.get('title') or 'untitled'}*", meta,
                 f"<{url}>" if url else "",
                 f"https://www.zotero.org/groups/{self.cfg.zotero_group_id}/items/{data['key']}"]
        return "\n".join(x for x in lines if x)

    def react(self, channel: str, ts: str, name: str) -> None:
        log.debug("reacting :%s: on %s/%s", name, channel, ts)
        try:
            self.client.reactions_add(channel=channel, timestamp=ts, name=name)
        except Exception:
            log.exception("could not add reaction")

    def reaction_for(self, exc: Exception) -> str:
        status = getattr(exc, "status", None)
        if status is None and isinstance(exc, requests.HTTPError) and exc.response is not None:
            status = exc.response.status_code
        return "warning" if status and 500 <= status < 600 else "x"

    def usage_reply(self, event: dict) -> None:
        self.client.chat_postMessage(
            channel=event["channel"],
            thread_ts=self.thread_ts(event),
            text=f"Mention me with a link and I'll add it to the Zotero group. "
                 f"{random.choice(self.SIGNOFFS)}",
        )

    def tags_reply(self, event: dict) -> None:
        lines = [
            "*Slacktero's reactions*",
            ":white_check_mark:  filed, or already in the library",
            ":warning:  filed, but no metadata could be found",
            ":x:  could not be filed at all",
            "",
            "*Emoji \u2192 tag*",
        ]
        lines += [f":{e}:  `{t}`" for t, e in self.cfg.tags.items()]
        lines += ["", "*Project \u2192 tags*"]
        lines += [f"*{p}*  \u2192 " + ", ".join(f"`{t}`" for t in ts)
                  for p, ts in self.cfg.projects.items()]
        self.client.chat_postMessage(
            channel=event["channel"],
            thread_ts=self.thread_ts(event),
            text="\n".join(lines),
        )

    def handle(self, event: dict) -> None:
        raise NotImplementedError


class PingHandler(Handler):
    def handle(self, event: dict) -> None:
        text = event.get("text", "")
        urls = self.links(text)
        words = text.lower().split()
        wants_backlog = self.FILE.search(text)
        if urls:
            self.spawn(self.add, urls[0], event["channel"], event["ts"])
        elif "help" in words:
            self.help_reply(event)
        elif "tags" in words:
            self.tags_reply(event)
        elif wants_backlog:
            self.spawn(self.backlog, event["channel"], int(wants_backlog.group(1) or 5))
        else:
            self.usage_reply(event)


# Handles messages the same - extend if needed
class DMHandler(PingHandler):
    pass


class ChannelHandler(Handler):
    def handle(self, event: dict) -> None:
        text = event.get("text", "")
        if self.mentions_me(text):
            return  # a mention is PingHandler's job; don't double-add
        for url in self.watched_links(text):
            self.spawn(self.add, url, event["channel"], event["ts"])


class ReactionHandler(Handler):
    ZOTERO_ITEM = re.compile(r"zotero\.org/groups/\d+/items/([A-Z0-9]{8})", re.I)

    def handle(self, event: dict) -> None:
        if event.get("user") == self.bot_user_id:
            return
        emoji = event.get("reaction", "").split("::")[0]
        tag = next((t for t, e in self.cfg.tags.items() if e == emoji), None)
        item = event.get("item") or {}
        if not tag or item.get("type") != "message":
            return
        self.spawn(self.apply, item["channel"], item["ts"], tag,
                   event.get("type") == "reaction_added")

    def apply(self, channel: str, ts: str, tag: str, add: bool) -> None:
        try:
            resp = self.client.conversations_history(
                channel=channel, latest=ts, oldest=ts, inclusive=True, limit=1)
            messages = resp.get("messages") or []
            if not messages:
                log.debug("no message at %s/%s", channel, ts)
                return
            text = messages[0].get("text", "")
            keys = set(self.ZOTERO_ITEM.findall(text))
            for url in self.links(text):
                key = self.filer.find_existing({"url": self.translator.normalize(url)})
                if key:
                    keys.add(key)
            log.debug("reaction %r -> items %s", tag, sorted(keys))
            for key in keys:
                self.filer.tag(key, tag, add)
        except Exception:
            log.exception("reaction apply failed")
