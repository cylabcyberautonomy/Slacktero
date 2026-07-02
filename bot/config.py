"""Config: read once from the environment, injected into everything else.

Own module so translator/uploader can import it without a cycle through app.py.
"""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    slack_bot_token: str
    slack_app_token: str
    zotero_api_key: str
    zotero_group_id: str
    zotero_api_base: str = "https://api.zotero.org"
    translation_server_url: str = "http://translation-server:1969"
    log_level: str = "INFO"  # set LOG_LEVEL=DEBUG to see the per-add trace

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            slack_bot_token=os.environ["SLACK_BOT_TOKEN"],
            slack_app_token=os.environ["SLACK_APP_TOKEN"],
            zotero_api_key=os.environ["ZOTERO_API_KEY"],
            zotero_group_id=os.environ["ZOTERO_GROUP_ID"],
            zotero_api_base=os.environ.get("ZOTERO_API_BASE", cls.zotero_api_base),
            translation_server_url=os.environ.get(
                "TRANSLATION_SERVER_URL", cls.translation_server_url
            ),
            log_level=os.environ.get("LOG_LEVEL", cls.log_level).upper(),
        )
