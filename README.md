# slack-zotero-bot

Mention the bot with a link in Slack; it extracts the metadata and adds the
item to your Zotero group library (unfiled) if it isn't already there.

```
@biblio-bot https://arxiv.org/abs/2604.11978
  └─ "Added to the group library: HORIZON: ..."
```

## How it works

Two containers via `docker-compose`:

- **bot** — a Slack Bolt app running in Socket Mode (no public endpoint).
  On `app_mention` it parses the URL, calls the translation-server, checks the
  group for a duplicate, and writes the item.
- **translation-server** — Zotero's own translator engine, built locally from
  source as the `translation-server-local` image (see prerequisites). Turns a
  URL into Zotero-format item JSON, which the bot writes straight to the Web API.

It's stateless: deduplication queries the Zotero library itself, so there's no
database or volume.

## Prerequisites

You'll need four things set up before first run.

### 1. A Slack app (Socket Mode)

At <https://api.slack.com/apps> → Create New App → From scratch, then:

- **Socket Mode** → enable it. This generates an **App-Level Token**
  (`xapp-…`) with the `connections:write` scope → `SLACK_APP_TOKEN`.
- **OAuth & Permissions** → Bot Token Scopes → add `app_mentions:read` and
  `chat:write`. Install to the workspace → copy the **Bot User OAuth Token**
  (`xoxb-…`) → `SLACK_BOT_TOKEN`.
- **Event Subscriptions** → enable → Subscribe to bot events → add
  `app_mention`.
- Invite the bot into the target channel: `/invite @your-bot`.

### 2. A Zotero API key + group ID

- API key: <https://www.zotero.org/settings/keys> → create a key with
  **write** access to the group → `ZOTERO_API_KEY`.
- Group ID: the **numeric** ID of the group (visible on the API Keys page and
  in group URLs), not the group name → `ZOTERO_GROUP_ID`.

### 3. Docker

Docker Engine + Compose v2 (`docker compose`).

### 4. The translation-server image (build from source)

The compose file expects a locally-built image named `translation-server-local`,
so build it once before the first run:

```bash
git clone --recurse-submodules https://github.com/zotero/translation-server
cd translation-server && docker build -t translation-server-local . && cd ..
```

This is a one-time step. The image lives in your local Docker store afterward,
so the clone location doesn't matter and the `translation-server/` source isn't
part of this repo (it's gitignored). You only need to repeat this on a fresh
machine, or to pick up newer translators.

See [Why build from source](#why-build-from-source) below for the reasoning.

## Run

```bash
cp .env.example .env      # then fill in the four values
docker compose up --build
```

Mention the bot with a link in a channel it's in. Replies land in a thread.

## Why build from source

The published `zotero/translation-server` image isn't a good fit on x86:

- The `latest` tag is **arm64-only**, so on an x86 host the pull succeeds but
  the container can't exec (`exec format error`).
- The newest **amd64** tag, `2.0.4`, is years old. It runs, but its bundled
  Node can't parse the current translators (you'll see `SyntaxError` on the
  Embedded Metadata translator and other failures), so real translation breaks.

Building from source gives you a current Node runtime *and* current translators,
matched, natively on whatever architecture you're on — which is why the compose
file references `translation-server-local` rather than a published tag.

On Apple Silicon you *could* instead use `image: zotero/translation-server`
(the arm64 `latest`) and skip the build, but building from source keeps the
setup identical across machines.

## Known limitation: URL-only dedup

Deduplication is authoritative when the item has a **DOI** — the bot searches
the group for it and skips a match. For items without a DOI (blog posts, news,
some preprint landing pages), the Web API has no exact-URL filter, so the bot
falls back to a best-effort quicksearch that can miss near-duplicates.

If that becomes a problem, the upgrade is a small persistent index
(`normalized_url → itemKey`) written on each successful add — at the cost of
adding the stateful component this design currently avoids. For a DOI-heavy
research bibliography it likely won't be needed.

## Files

```
slack-zotero-bot/
├── docker-compose.yml      # bot + translation-server-local
├── .env.example            # copy to .env
├── .gitignore              # excludes .env and the translation-server source
└── bot/
    ├── Dockerfile
    ├── requirements.txt
    ├── app.py              # Slack handler + orchestration
    └── zotero.py           # translate(), find_existing(), add_item()
```