import asyncio
import discord
from discord import app_commands
from discord.ext import commands
import signal
from typing import Optional

from config import config, StreamConfig
from kick_monitor import KickMonitor


class MizzlertBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)
        self.kick_monitor: Optional[KickMonitor] = None

    async def setup_hook(self):
        self.kick_monitor = KickMonitor(self)

        # Load any existing configured channels
        for guild_config in config.streams.values():
            await self.kick_monitor.add_channel(guild_config.kick_channel)

        await self.kick_monitor.start()

    async def close(self):
        """Ensure KickMonitor shuts down cleanly on bot close."""
        if self.kick_monitor:
            await self.kick_monitor.stop()
        await super().close()


bot = MizzlertBot()


@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name}')
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Failed to sync commands: {e}")


@bot.tree.command(name="follow", description="Follow a Kick.com channel and set up notifications")
@app_commands.checks.has_permissions(administrator=True)
async def follow(interaction: discord.Interaction, kick_channel: str):
    guild_id = str(interaction.guild_id)

    config.add_stream(guild_id, kick_channel)
    await bot.kick_monitor.add_channel(kick_channel)

    await interaction.response.send_message(
        f"Now following {kick_channel}! Use `/configure` to set up notification channels.",
        ephemeral=True
    )


@bot.tree.command(name="unfollow", description="Stop following a Kick.com channel")
@app_commands.checks.has_permissions(administrator=True)
async def unfollow(interaction: discord.Interaction):
    guild_id = str(interaction.guild_id)

    if guild_id in config.streams:
        kick_channel = config.streams[guild_id].kick_channel
        config.remove_stream(guild_id)
        await bot.kick_monitor.remove_channel(kick_channel)
        await interaction.response.send_message(
            f"Stopped following {kick_channel}!",
            ephemeral=True
        )
    else:
        await interaction.response.send_message(
            "This server is not following any Kick.com channels!",
            ephemeral=True
        )


@bot.tree.command(name="configure", description="Configure notification settings for a Discord channel")
@app_commands.checks.has_permissions(administrator=True)
async def configure(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    message: str = "{streamer} is now live: {title}"
):
    guild_id = str(interaction.guild_id)

    if guild_id not in config.streams:
        await interaction.response.send_message(
            "Please use `/follow` first to set up a Kick.com channel to follow!",
            ephemeral=True
        )
        return

    config.add_channel(guild_id, str(channel.id), message)

    await interaction.response.send_message(
        f"Configuration saved! Notifications will be posted in {channel.mention}\n"
        f"Message format: {message}\n"
        "Available variables: {streamer}, {title}, {url}",
        ephemeral=True
    )


@bot.tree.command(name="remove_channel", description="Remove notifications from a Discord channel")
@app_commands.checks.has_permissions(administrator=True)
async def remove_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    guild_id = str(interaction.guild_id)

    if guild_id in config.streams:
        config.remove_channel(guild_id, str(channel.id))
        await interaction.response.send_message(
            f"Removed notifications from {channel.mention}!",
            ephemeral=True
        )
    else:
        await interaction.response.send_message(
            "This server is not following any Kick.com channels!",
            ephemeral=True
        )


def run_bot():
    if not config.token:
        token = input("Please enter your Discord bot token: ").strip()
        config.set_token(token)

    try:
        bot.run(config.token)
    except KeyboardInterrupt:
        print("Shutting down...")
        # Ensure KickMonitor is stopped
        if bot.kick_monitor:
            asyncio.run(bot.kick_monitor.stop())
    finally:
        # Close bot cleanly
        try:
            asyncio.run(bot.close())
        except RuntimeError:
            pass


if __name__ == "__main__":
    run_bot()
