"""Slack entry point (Socket Mode): wire up the handlers and route events."""

import logging

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from .config import Config
from .translator import Translator
from .uploader import Uploader
from .handlers import PingHandler, DMHandler, ChannelHandler


def main():
    cfg = Config.from_env()
    logging.basicConfig(level=cfg.log_level)
    app = App(token=cfg.slack_bot_token)
    bot_id = app.client.auth_test()["user_id"]

    translator, uploader = Translator(cfg), Uploader(cfg)
    ping = PingHandler(translator, uploader, app.client, bot_id)
    dm = DMHandler(translator, uploader, app.client, bot_id)
    channel = ChannelHandler(translator, uploader, app.client, bot_id)

    @app.event("app_mention")
    def _mention(event):
        ping.handle(event)

    @app.event("message")
    def _message(event):
        if event.get("subtype"):  # skip edits/joins/bot posts
            return
        (dm if event.get("channel_type") == "im" else channel).handle(event)

    SocketModeHandler(app, cfg.slack_app_token).start()
