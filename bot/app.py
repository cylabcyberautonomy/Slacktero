"""Slack entry point (Socket Mode): wire up the handlers and route events."""

import logging

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from .config import Config
from .translator import Translator
from .filer import Filer
from .handlers import PingHandler, DMHandler, ChannelHandler, ReactionHandler


def main():
    cfg = Config.from_env()
    logging.basicConfig(level=cfg.log_level)
    app = App(token=cfg.slack_bot_token)
    bot_id = app.client.auth_test()["user_id"]

    args = (Translator(cfg), Filer(cfg), app.client, bot_id, cfg)
    ping, dm, channel = PingHandler(*args), DMHandler(*args), ChannelHandler(*args)
    reaction = ReactionHandler(*args)

    @app.event("app_mention")
    def _mention(event):
        ping.handle(event)

    @app.event("message")
    def _message(event):
        if event.get("subtype"):  # skip edits/joins/bot posts
            return
        (dm if event.get("channel_type") == "im" else channel).handle(event)

    @app.event("reaction_added")
    def _reaction_added(event):
        reaction.handle(event)

    @app.event("reaction_removed")
    def _reaction_removed(event):
        reaction.handle(event)

    SocketModeHandler(app, cfg.slack_app_token).start()
