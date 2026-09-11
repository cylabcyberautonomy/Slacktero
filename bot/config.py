"""Config: read once from the environment, injected into everything else.

Own module so translator/uploader can import it without a cycle through app.py.
"""

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_FILE = Path(__file__).resolve().parent.parent / "slacktero.toml"


@dataclass(frozen=True)
class Config:
    slack_bot_token: str
    slack_app_token: str
    zotero_api_key: str
    zotero_group_id: str
    watched_domains: tuple[str, ...] = ()
    tags: dict[str, str] = field(default_factory=dict)
    projects: dict[str, tuple[str, ...]] = field(default_factory=dict)
    zotero_api_base: str = "https://api.zotero.org"
    translation_server_url: str = "http://translation-server:1969"
    log_level: str = "INFO"  # set LOG_LEVEL=DEBUG to see the per-add trace

    def save(self) -> None:
        lines = ["domains = ["]
        lines += [f'  "{d}",' for d in self.watched_domains]
        lines += ["]", "", "[tags]"]
        lines += [f'"{t}" = "{e}"' for t, e in self.tags.items()]
        lines += ["", "[projects]"]
        lines += [f'"{p}" = [' + ", ".join(f'"{t}"' for t in ts) + "]"
                  for p, ts in self.projects.items()]
        CONFIG_FILE.write_text("\n".join(lines) + "\n")

    @classmethod
    def from_env(cls) -> "Config":
        data = tomllib.loads(CONFIG_FILE.read_text())
        tags = data["tags"]
        projects = {name: tuple(t) for name, t in data["projects"].items()}

        unknown = sorted({t for ts in projects.values() for t in ts} - set(tags))
        if unknown:
            raise ValueError(f"[projects] uses tags absent from [tags]: {unknown}")
        emoji = list(tags.values())
        clashes = sorted({e for e in emoji if emoji.count(e) > 1})
        if clashes:
            raise ValueError(f"[tags] reuses emoji across tags: {clashes}")

        return cls(
            slack_bot_token=os.environ["SLACK_BOT_TOKEN"],
            slack_app_token=os.environ["SLACK_APP_TOKEN"],
            zotero_api_key=os.environ["ZOTERO_API_KEY"],
            zotero_group_id=os.environ["ZOTERO_GROUP_ID"],
            watched_domains=tuple(d.lower() for d in data["domains"]),
            tags=tags,
            projects=projects,
            zotero_api_base=os.environ.get("ZOTERO_API_BASE", cls.zotero_api_base),
            translation_server_url=os.environ.get(
                "TRANSLATION_SERVER_URL", cls.translation_server_url
            ),
            log_level=os.environ.get("LOG_LEVEL", cls.log_level).upper(),
        )
