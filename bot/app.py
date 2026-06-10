"""Slack entry point: listen for @mentions, hand the URL to the Zotero pipeline.

Runs in Socket Mode, so there's no public endpoint — the app opens an
outbound WebSocket to Slack. The actual translate -> dedup -> write work
happens in a background thread so the event returns immediately and Slack
doesn't retry (and double-post) on slow translations.
"""

import os
import re
import logging
import threading

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

import zotero

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("slack-zotero-bot")

app = App(token=os.environ["SLACK_BOT_TOKEN"])

# Slack wraps links as <https://example.com> or <https://example.com|label>.
URL_RE = re.compile(r"<(https?://[^>|\s]+)")


def process(url: str, thread_ts: str, say) -> None:
    """Translate -> dedup -> write, reporting the outcome back in-thread."""
    try:
        item = zotero.translate(url)
    except zotero.TranslationError as e:
        say(text=f"Couldn't add that link — {e}.", thread_ts=thread_ts)
        return
    except Exception:
        log.exception("translation failed")
        say(text="Couldn't reach the metadata service. Try again shortly.",
            thread_ts=thread_ts)
        return

    if not item:
        say(text="I couldn't pull any metadata from that link.",
            thread_ts=thread_ts)
        return

    title = item.get("title") or "(untitled)"

    try:
        if zotero.find_existing(item):
            say(text=f"Already in the library: *{title}*", thread_ts=thread_ts)
            return
        zotero.add_item(item)
    except Exception:
        log.exception("zotero write failed")
        say(text=f"Found *{title}* but couldn't save it to Zotero.",
            thread_ts=thread_ts)
        return

    say(text=f"Added to the group library: *{title}*", thread_ts=thread_ts)


@app.event("app_mention")
def handle_mention(event, say):
    # Reply inside the existing thread if there is one, else start one.
    thread_ts = event.get("thread_ts", event["ts"])

    match = URL_RE.search(event.get("text", ""))
    if not match:
        say(text="Mention me with a link and I'll add it to the Zotero group.",
            thread_ts=thread_ts)
        return

    threading.Thread(
        target=process,
        args=(match.group(1), thread_ts, say),
        daemon=True,
    ).start()


if __name__ == "__main__":
    SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"]).start()
