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


@bot.tree.command(name="test", description="Send a test notification to this channel")
@app_commands.checks.has_permissions(administrator=True)
async def test_notification(interaction: discord.Interaction):
    guild_id = str(interaction.guild_id)
    channel_id = str(interaction.channel_id)
    
    if guild_id not in config.streams:
        await interaction.response.send_message(
            "This server is not following any Kick.com channels! Use `/follow` first.",
            ephemeral=True
        )
        return

    # Create test status data
    test_status = {
        "is_live": True,
        "title": "Test Stream",
        "avatar_url": "https://static.kick.com/images/user-avatar.png",
        "category_name": "Just Chatting",
        "category_icon": "https://static.kick.com/categories/just-chatting.png",
        "thumbnail_url": "https://static.kick.com/video-thumbnails/test-thumbnail.png",
        "url": f"https://kick.com/{config.streams[guild_id].kick_channel}"
    }

    # Defer the response since we'll be making API calls
    await interaction.response.defer(ephemeral=True)

    # Send test notification
    stream_config = config.streams[guild_id]
    username = stream_config.kick_channel
    
    # Create the embed with test data
    embed = discord.Embed(
        description=f"**[{test_status['title']}]({test_status['url']})**",
        color=discord.Color.brand_green()
    )

    # Set author with avatar and username
    embed.set_author(
        name=username,
        icon_url=test_status["avatar_url"],
        url=test_status["url"]
    )

    # Add category info
    category_text = f"**Category:** {test_status['category_name']}"
    embed.description = f"{embed.description}\n{category_text}"
    embed.set_thumbnail(url=test_status["category_icon"])

    # Add stream preview image
    embed.set_image(url=test_status["thumbnail_url"])

    # Create view with button
    view = discord.ui.View()
    button = discord.ui.Button(
        style=discord.ButtonStyle.green,
        label="Watch Stream",
        url=test_status["url"]
    )
    view.add_item(button)

    # Format the notification message
    message = None
    for ch_conf in stream_config.discord_channels:
        if ch_conf['channel_id'] == channel_id:
            message = ch_conf['message'].format(
                streamer=username,
                title=test_status['title'],
                url=f"[Click to watch]({test_status['url']})"
            )
            break

    if message is None:
        message = f"**{username}** is live with **{test_status['title']}** [Click to watch]({test_status['url']})"

    # Send the test notification
    await interaction.channel.send(content=message, embed=embed, view=view)
    await interaction.followup.send("Test notification sent!", ephemeral=True)


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
