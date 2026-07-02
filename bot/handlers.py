"""Slack event handlers: slice the message, run the pipeline, react.

Each add runs in a daemon thread so the Slack event returns within 3s, before
Slack retries and double-posts.
"""

import re
import random
import logging
import threading

import requests

from .translator import Translator
from .uploader import Uploader

log = logging.getLogger("slacktero")


class Handler:
    LINK = re.compile(r"<(https?://[^>|\s]+)")
    ARXIV = re.compile(r"<(https?://arxiv\.org/[^>|\s]+)", re.I)

    SIGNOFFS = ["Cowabunga!", "Yowza!", "Tubular!",
                "I add links to Zotero. What's a Zotero, anyways?",
                "Kachow!", "You called?"]

    def __init__(self, translator: Translator, uploader: Uploader,
                 client, bot_user_id: str):
        self.translator = translator
        self.uploader = uploader
        self.client = client
        self.bot_user_id = bot_user_id

    def links(self, text: str) -> list[str]:
        return self.LINK.findall(text)

    def arxiv_links(self, text: str) -> list[str]:
        return self.ARXIV.findall(text)

    def mentions_me(self, text: str) -> bool:
        return f"<@{self.bot_user_id}>" in text

    def thread_ts(self, event: dict) -> str:
        return event.get("thread_ts", event["ts"])

    def spawn(self, url: str, event: dict) -> None:
        log.debug("%s spawning add for %s", type(self).__name__, url)
        threading.Thread(
            target=self.add,
            args=(url, event["channel"], event["ts"]),
            daemon=True,
        ).start()

    def add(self, url: str, channel: str, ts: str) -> None:
        try:
            item = self.translator.translate(url)
            if not item:
                log.debug("no metadata for %s", url)
                self.react(channel, ts, "warning")
                return
            key = self.uploader.upload(item)
            log.debug("uploaded %r -> %s", item.get("title"), key)
        except Exception as e:
            log.exception("add failed")
            self.react(channel, ts, self.reaction_for(e))
            return
        self.react(channel, ts, "white_check_mark")

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

    def handle(self, event: dict) -> None:
        raise NotImplementedError


class PingHandler(Handler):
    def handle(self, event: dict) -> None:
        urls = self.links(event.get("text", ""))
        if not urls:
            self.usage_reply(event)
            return
        self.spawn(urls[0], event)


# Handles messages the same - extend if needed
class DMHandler(PingHandler):
    pass


class ChannelHandler(Handler):
    def handle(self, event: dict) -> None:
        text = event.get("text", "")
        if self.mentions_me(text):
            return  # a mention is PingHandler's job; don't double-add
        for url in self.arxiv_links(text):
            self.spawn(url, event)
