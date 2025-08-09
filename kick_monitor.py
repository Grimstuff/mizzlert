import asyncio
import json
import discord
from datetime import datetime
from playwright.async_api import async_playwright
from typing import Dict, Set
from discord.ui import Button, View

POLL_INTERVAL = 30  # seconds
DEBUG = True  # Set to False for production

API_URL = "https://kick.com/api/v2/channels/{username}"

def debug_print(message):
    """Print debug messages with timestamp"""
    if DEBUG:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] {message}")

class KickMonitor:
    def __init__(self, bot):
        self.bot = bot
        self.channels_to_monitor: Set[str] = set()
        self.live_status: Dict[str, bool] = {}
        self._task = None
        self._browser = None
        self._page = None

    async def start(self):
        """Start monitoring channels"""
        self._task = asyncio.create_task(self._monitor_channels())

    async def stop(self):
        """Stop monitoring channels"""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._page:
            await self._page.close()
        if self._browser:
            await self._browser.close()

    def get_thumbnail_url(self, data):
        """Extract thumbnail URL from livestream data"""
        try:
            return data.get("livestream", {}).get("thumbnail", {}).get("url")
        except (KeyError, AttributeError):
            return None

    async def _notify_discord(self, username: str, status: dict):
        """Send notifications to Discord channels"""
        from config import config
        
        stream_url = f"https://kick.com/{username}"
        
        embed = discord.Embed(
            title=f"**{username}**",  # Streamer name as main title, bold
            url=stream_url,  # Make title clickable
            description=f"**{status['title']}**",  # Stream title as description, bold
            color=discord.Color.brand_green()  # Kick's green color
        )
        
        # Set author with avatar (appears next to streamer name)
        if status.get("avatar_url"):
            embed.set_author(name=username, icon_url=status["avatar_url"], url=stream_url)
        
        # Add category info if available
        if status.get("category_name"):
            category_text = f"**Category:** {status['category_name']}"
            embed.add_field(name="", value=category_text, inline=False)
            
            # Add category icon in the corner if available
            if status.get("category_icon"):
                embed.set_thumbnail(url=status["category_icon"])
        
        # Add stream preview image (using set_image for bigger size)
        if self._page and status.get("thumbnail_url"):
            embed.set_image(url=status.get("thumbnail_url"))
        
        found_config = False
        # Send notifications to all configured channels
        for guild_id, stream_config in config.streams.items():
            if stream_config.kick_channel == username:
                found_config = True
                for channel_config in stream_config.discord_channels:
                    try:
                        channel_id = channel_config['channel_id']
                        channel = self.bot.get_channel(int(channel_id))
                        if channel:
                            # Create a View with a button
                            view = discord.ui.View()
                            button = discord.ui.Button(
                                style=discord.ButtonStyle.green,
                                label="Watch Stream",
                                url=f"https://kick.com/{username}"
                            )
                            view.add_item(button)
                            
                            message = channel_config['message'].format(
                                streamer=username,
                                title=status['title'],
                                url=f"https://kick.com/{username}"
                            )
                            await channel.send(content=message, embed=embed, view=view)
                            debug_print(f"Notification sent successfully for {username}")
                        else:
                            debug_print(f"Could not find Discord channel {channel_id} for {username}")
                    except Exception as e:
                        debug_print(f"Error sending notification for {username}: {str(e)}")
        
        if not found_config:
            debug_print(f"No configuration found for streamer {username}")

    async def add_channel(self, channel: str):
        """Add a channel to monitor"""
        self.channels_to_monitor.add(channel)

    async def remove_channel(self, channel: str):
        """Remove a channel from monitoring"""
        self.channels_to_monitor.discard(channel)
        self.live_status.pop(channel, None)

    async def _monitor_channels(self):
        """Main monitoring loop"""
        async with async_playwright() as p:
            self._browser = await p.chromium.launch(headless=True)
            self._page = await self._browser.new_page()

            while True:
                for username in self.channels_to_monitor:
                    try:
                        status = await fetch_channel_status(self._page, username)
                        if status:
                            debug_print(f"Status for {username}: Live={status['is_live']}, Title='{status.get('title', '')}'")
                            was_live = self.live_status.get(username, False)
                            is_live = status["is_live"]
                            
                            # Only notify if stream just went live
                            if is_live and not was_live:
                                debug_print(f"Stream just went live: {username} - Preparing notification")
                                # Get thumbnail URL
                                if self._page:
                                    response_data = None
                                    try:
                                        response = await self._page.evaluate("document.body.innerText")
                                        response_data = json.loads(response)
                                    except:
                                        pass
                                    
                                    thumbnail_url = self.get_thumbnail_url(response_data)
                                    status["thumbnail_url"] = thumbnail_url
                                
                                await self._notify_discord(username, status)
                            
                            self.live_status[username] = is_live
                            debug_print(f"Channel {username} is currently [{'LIVE' if is_live else 'OFFLINE'}]")
                    except Exception as e:
                        debug_print(f"Error monitoring {username}: {str(e)}")
                        continue
                
                debug_print(f"Sleeping for {POLL_INTERVAL} seconds...")
                await asyncio.sleep(POLL_INTERVAL)

async def fetch_channel_status(page, username):
    url = API_URL.format(username=username)
    try:
        # Set headers to mimic a real browser request
        await page.set_extra_http_headers({
            'Accept': 'application/json',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': 'https://kick.com/',
            'Origin': 'https://kick.com',
            'sec-ch-ua': '"Chromium";v="116"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36'
        })
        
        # Listen for the API response
        response_data = None
        async def handle_response(response):
            nonlocal response_data
            if response.url == url:
                try:
                    response_data = await response.json()
                except:
                    debug_print("Failed to parse response JSON")

        page.on("response", handle_response)
        await page.goto(url, wait_until="networkidle")
        
        response = json.dumps(response_data) if response_data else "{}"
        
        try:
            data = json.loads(response)
            livestream = data.get("livestream")
            if livestream:
                debug_print(f"Livestream data found for {username}")
                channel_data = data.get("user", {})
                category_data = livestream.get("categories", [{}])[0] if livestream.get("categories") else {}
                return {
                    "is_live": True,
                    "title": livestream.get("session_title", "Untitled Stream"),
                    "avatar_url": channel_data.get("profile_pic"),
                    "category_name": category_data.get("name", "No Category"),
                    "category_icon": category_data.get("icon", None)
                }
            else:
                debug_print(f"No livestream data found for {username}")
                return {"is_live": False, "title": None}
        except json.JSONDecodeError as e:
            debug_print(f"Failed to parse JSON for {username}: {str(e)}")
            return None
    except Exception as e:
        debug_print(f"[ERROR] Failed to fetch {username}: {str(e)}")
        return None
