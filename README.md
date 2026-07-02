# Slacktero

A simple Slack bot that automatically files links into a Zotero group lib.

![Demonstration of Slacktero usage](img/slacktero_1.gif)

Slacktero will file any link presented to it in three ways: 
1) **@mention** the bot with a link (any link)
2) **DM** it a link (any link)
3) **post** a link in any channel that the bot's in (*arxiv links only*, no mention needed)

Slacktero uses Zotero's prebuilt translation server to populate metadata for each link (which runs locally in a Docker container.)

It reacts to your message based on the outcome:

- ✅ added (or already in the library)
- ⚠️ server error, or the page had no metadata
- ❌ bad/ambiguous link, or a local error

Slacktero uploads links to the "Unfiled" section of your group library. It will check for and prevent duplicate links within that section.

## Install & run

**1. Slack app** (Socket Mode) at <https://api.slack.com/apps> → Create New App:

- **Socket Mode** → enable → copy the App-Level Token (`xapp-…`) → `SLACK_APP_TOKEN`.
- **OAuth & Permissions** → Bot Token Scopes: `app_mentions:read`, `chat:write`,
  `reactions:write`, `channels:history`, `groups:history`, `im:history`.
  Install to the workspace → copy the Bot Token (`xoxb-…`) → `SLACK_BOT_TOKEN`.
- **Event Subscriptions** → subscribe to bot events: `app_mention`,
  `message.channels`, `message.groups`, `message.im`.
- `/invite` the bot into the channel you want it to watch.

**2. Zotero** at <https://www.zotero.org/settings/keys>:

- An API key with **write** access to the group → `ZOTERO_API_KEY`.
- The group's **numeric** ID → `ZOTERO_GROUP_ID`.

**3. Docker** — Engine + Compose v2.

**4. Run:**

```bash
cp .env.example .env      # fill in the four values above
docker compose up --build
```

The first build compiles the translation-server from source (no manual step).
Set `LOG_LEVEL=DEBUG` in `.env` for a per-add trace.

## Architecture

```
slacktero/
├── main.py                     entry point → bot.app.main()
├── docker-compose.yml          the two services: bot + translation-server
├── .env.example                config template; copy to .env
├── docker/
│   ├── bot.Dockerfile
│   └── translation-server.Dockerfile   builds Zotero's server from source
└── bot/                        
    ├── requirements.txt
    ├── app.py                  load config, wire handlers, route Slack events
    ├── config.py               Config dataclass, read from env
    ├── handlers.py             Handler base + Ping/DM/Channel: slice message, run pipeline, react to message when finished
    ├── translator.py           URL → metadata conversion via the translation-server (+ DOI fallback)
    └── uploader.py             metadata →  dedup against the group, then write the item to
```

## Used by

[<img src="https://www.cylab.cmu.edu/_files/images/logos/cyber-autonomy-initiative-logo.png">](https://www.cylab.cmu.edu/research/cyber-autonomy-initiative/index.html)