# CS2 Crosshair Bot

A Discord bot that replies with an image of a CS2 crosshair when someone posts a crosshair code (the current `CS` + 44 characters format, e.g. `CSYqwankGFrU2WEqDZA8pnnRjWpidUoFULhD9oqt8vmxYC`). It replies in the same channel.

- Paste a code anywhere in a message and the bot replies with the image.
- Or use `/crosshair code:<code>`.

## Discord setup

1. Go to https://discord.com/developers/applications, then **New Application**, then **Bot**, then **Reset Token** and copy the token.
2. On the **Bot** page, turn on **Message Content Intent**. It's needed for auto-replies to pasted codes. Skip it if you set `LISTEN_TO_MESSAGES=false` and only use `/crosshair`.
3. Under **OAuth2 → URL Generator**, tick the `bot` and `applications.commands` scopes and these permissions: *Send Messages*, *Embed Links*, *Attach Files*, *Read Message History*. Open the generated URL to invite the bot.

## Run in a container

```bash
cp .env.example .env   # then put your token in DISCORD_TOKEN
docker compose up -d --build
```

Or without compose:

```bash
docker build -t cs2-crosshair-bot .
docker run -d --restart unless-stopped -e DISCORD_TOKEN=xxxxx cs2-crosshair-bot
```

### Using the prebuilt image

Every push to `main` or `dev` runs the tests and publishes an image to GitHub Container Registry ([.github/workflows/ci.yml](.github/workflows/ci.yml)):

| Branch | Tags |
|---|---|
| `main` | `latest`, `prod-<sha>` |
| `dev` | `dev`, `dev-<sha>` |

To host it without the source, using your own bot token:

```bash
docker run -d --restart unless-stopped -e DISCORD_TOKEN=xxxxx ghcr.io/<github-owner>/cs2-crosshair-bot:latest
```

The package is private when first published. To let anyone pull it, go to GitHub → your profile → **Packages** → `cs2-crosshair-bot` → **Package settings** → **Change visibility** → Public.

### Settings

| Variable | Default | |
|---|---|---|
| `DISCORD_TOKEN` | required | Bot token |
| `DISCORD_GUILD_ID` | empty | Server ID so `/crosshair` registers instantly. Global registration can take up to an hour. |
| `LISTEN_TO_MESSAGES` | `true` | Auto-reply to codes pasted in chat |
| `LOG_LEVEL` | `INFO` | |

## Notes

- The decoding follows the `cs2-v1` layout in [akiver/csgo-sharecode](https://github.com/akiver/csgo-sharecode). Old `CSGO-xxxxx-…` codes aren't supported, because CS2 rejects them too.
- Length, gap and thickness are pixels at the code's screen height. The preview draws them on a pixel grid, scaled up.
- Static and dynamic cross styles and dot-only render accurately. Dynamic styles are drawn at rest. Circle and quad styles, plus the *half* outline, are approximations.

## Development

```bash
pip install -r requirements.txt ruff pytest
ruff check .
pytest
```
