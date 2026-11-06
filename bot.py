"""Discord bot that replies to CS2 crosshair codes with a rendered image of the crosshair."""

from __future__ import annotations

import io
import logging
import os

import discord
from discord import app_commands

import crosshair

log = logging.getLogger("crosshair-bot")

# Reply to codes pasted in normal messages (needs the Message Content intent in the developer portal).
LISTEN_TO_MESSAGES = os.getenv("LISTEN_TO_MESSAGES", "true").lower() in ("1", "true", "yes")
MAX_CODES_PER_MESSAGE = 3


def build_reply(code: str) -> tuple[discord.Embed, discord.File]:
    ch = crosshair.decode(code)
    data, ext = crosshair.render_card(ch)
    filename = f"crosshair.{ext}"
    file = discord.File(io.BytesIO(data), filename=filename)
    embed = discord.Embed(
        title=ch.style_name,
        description=f"`{ch.code}`",
        color=discord.Color.from_rgb(ch.red, ch.green, ch.blue),
    )
    embed.set_image(url="attachment://crosshair.png")
    return embed, file


class CrosshairBot(discord.Client):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = LISTEN_TO_MESSAGES
        super().__init__(intents=intents, allowed_mentions=discord.AllowedMentions.none())
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self) -> None:
        guild_id = os.getenv("DISCORD_GUILD_ID")
        if guild_id:
            # Guild sync is instant; global sync can take up to an hour to appear.
            guild = discord.Object(id=int(guild_id))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()

    async def on_ready(self) -> None:
        log.info("Logged in as %s (%s)", self.user, self.user.id if self.user else "?")

    async def on_message(self, message: discord.Message) -> None:
        if not LISTEN_TO_MESSAGES or message.author.bot:
            return
        codes = list(dict.fromkeys(crosshair.SHARE_CODE_RE.findall(message.content)))
        for code in codes[:MAX_CODES_PER_MESSAGE]:
            try:
                embed, file = build_reply(code)
            except crosshair.InvalidCrosshairCode as e:
                await message.reply(f"Couldn't read `{code}`: {e}", mention_author=False)
                continue
            except Exception:
                log.exception("Failed to render %s", code)
                continue
            await message.reply(embed=embed, file=file, mention_author=False)


bot = CrosshairBot()


@bot.tree.command(name="crosshair", description="Show a picture of a CS2 crosshair code")
@app_commands.describe(code="Crosshair share code, e.g. CSYqwankGFrU2WEqDZA8pnnRjWpidUoFULhD9oqt8vmxYC")
async def crosshair_command(interaction: discord.Interaction, code: str) -> None:
    try:
        embed, file = build_reply(code)
    except crosshair.InvalidCrosshairCode as e:
        await interaction.response.send_message(f"Couldn't read that code: {e}", ephemeral=True)
        return
    await interaction.response.send_message(embed=embed, file=file)


def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise SystemExit("DISCORD_TOKEN is not set")
    bot.run(token, log_handler=None)


if __name__ == "__main__":
    main()
