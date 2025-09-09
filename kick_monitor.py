import asyncio
import json
import discord
from datetime import datetime
from typing import Dict, Set, Optional

from playwright.async_api import async_playwright, Playwright
from config import config  # now used for poll_interval/debug settings

POLL_INTERVAL = config.poll_interval
DEBUG = config.debug
API_URL = "https://kick.com/api/v2/channels/{username}"


def debug_print(message: str):
    if DEBUG:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] {message}")


class KickMonitor:
    def __init__(self, bot):
        self.bot = bot
        self.channels_to_monitor: Set[str] = set()
        self.live_status: Dict[str, bool] = {}
        self._task: Optional[asyncio.Task] = None
        self._pw: Optional[Playwright] = None
        self._browser = None
        self._running = False

    async def start(self):
        if self._task:
            return
        await self._ensure_browser()
        self._running = True
        self._task = asyncio.create_task(self._monitor_channels())
        debug_print("KickMonitor started.")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._pw:
            await self._pw.stop()
            self._pw = None
        debug_print("KickMonitor stopped and cleaned up.")

    async def add_channel(self, username: str):
        self.channels_to_monitor.add(username)
        self.live_status.setdefault(username, False)
        debug_print(f"Added {username} to monitor list.")

    async def remove_channel(self, username: str):
        self.channels_to_monitor.discard(username)
        self.live_status.pop(username, None)
        debug_print(f"Removed {username} from monitor list.")

    async def _ensure_browser(self):
        if not self._pw:
            self._pw = await async_playwright().start()
        if not self._browser:
            self._browser = await self._pw.chromium.launch(headless=True)

    async def _monitor_channels(self):
        while self._running:
            if not self.channels_to_monitor:
                await asyncio.sleep(POLL_INTERVAL)
                continue

            tasks = [self._check_and_notify(username) for username in list(self.channels_to_monitor)]
            await asyncio.gather(*tasks, return_exceptions=True)

            debug_print(f"Sleeping for {POLL_INTERVAL} seconds...")
            await asyncio.sleep(POLL_INTERVAL)

    async def _check_and_notify(self, username: str):
        status = await self._fetch_channel_status(username)
        if status is None:
            return

        was_live = self.live_status.get(username, False)
        is_live = status["is_live"]

        if DEBUG:
            debug_print(f"Status for {username}: Live={is_live}, Title='{status.get('title', '')}'")

        if is_live and not was_live:
            debug_print(f"Stream just went live: {username} - Sending notification")
            await self._notify_discord(username, status)

        self.live_status[username] = is_live

    async def _fetch_channel_status(self, username: str) -> Optional[Dict]:
        """
        Uses a fresh Playwright page to request the channel's API endpoint and parse JSON.
        """
        await self._ensure_browser()
        page = await self._browser.new_page()

        url = API_URL.format(username=username)
        response_data = None

        async def handle_response(response):
            nonlocal response_data
            if response.url == url:
                try:
                    response_data = await response.json()
                except:
                    debug_print(f"Failed to parse response JSON for {username}")

        page.on("response", handle_response)

        try:
            headers = {
                'Accept': 'application/json',
                'Accept-Language': 'en-US,en;q=0.9',
                'Referer': 'https://kick.com/',
                'Origin': 'https://kick.com',
                'sec-ch-ua': '"Chromium";v="116"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Windows"',
                'User-Agent': (
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/116.0.0.0 Safari/537.36'
                )
            }
            await page.set_extra_http_headers(headers)
            debug_print(f"[DEBUG] Fetching {url} with headers: {json.dumps(headers)}")
            await page.goto(url, wait_until="networkidle")

            if response_data is None:
                debug_print(f"[ERROR] No response data received for {username}")
                return None
                
            data = response_data
            debug_print(f"[DEBUG] Raw API response for {username}: {json.dumps(data)[:200]}...")  # Print first 200 chars of response
            
            # The channel info is directly in the root of the response
            channel_data = data
            debug_print(f"[DEBUG] Channel data keys: {list(channel_data.keys())}")
            
            # Check if livestream data exists
            livestream = None
            if "livestream" in channel_data:
                livestream = channel_data["livestream"]
                debug_print(f"[DEBUG] Livestream data: {json.dumps(livestream)[:200] if livestream else 'None'}")
                # Add specific debug for thumbnail
                debug_print(f"[DEBUG] Thumbnail data: {json.dumps(livestream.get('thumbnail', {}))}")
            else:
                debug_print(f"[DEBUG] No livestream data found for {username}")
                return {"is_live": False, "title": None, "url": f"https://kick.com/{username}"}
            
            if livestream:
                # Get category data safely - it might not exist
                categories = livestream.get("categories", [])
                category_data = categories[0] if categories else {}
                # Get user data safely
                user_data = channel_data.get("user", {})
                # Try multiple possible thumbnail sources
                thumbnail_url = None
                
                # First try the livestream thumbnail
                thumbnail = livestream.get("thumbnail", {}) or {}
                thumbnail_url = thumbnail.get("url")
                
                # If no thumbnail, try video thumbnail
                if not thumbnail_url and "video_thumbnail" in livestream:
                    thumbnail_url = livestream.get("video_thumbnail")
                
                # If still no thumbnail, construct one from the channel
                if not thumbnail_url:
                    # Try to get a thumbnail from the channel's assets
                    channel_id = livestream.get("channel_id")
                    if channel_id:
                        thumbnail_url = f"https://thumb.kick.com/images/{channel_id}/thumbnail.jpg"
                        debug_print(f"[DEBUG] Using constructed thumbnail URL")
                
                debug_print(f"[DEBUG] Final thumbnail URL: {thumbnail_url}")
                
                return {
                    "is_live": True,
                    "title": livestream.get("session_title", "Untitled Stream"),
                    "avatar_url": user_data.get("profile_pic"),
                    "category_name": category_data.get("name", "No Category"),
                    "category_icon": category_data.get("icon"),
                    "thumbnail_url": thumbnail_url,
                    "url": f"https://kick.com/{username}"
                }
            else:
                return {"is_live": False, "title": None, "url": f"https://kick.com/{username}"}

        except Exception as e:
            debug_print(f"[ERROR] Failed to fetch {username}: {e}")
            debug_print(f"[ERROR] Full error details: {type(e).__name__}: {str(e)}")
            return None
        finally:
            await page.close()

    async def _notify_discord(self, username: str, status: dict):
        stream_url = status.get("url", f"https://kick.com/{username}")
        # Create the embed with all our enhancements
        embed = discord.Embed(
            description=f"**[{status['title']}]({stream_url})**",  # Make title a clickable link
            color=discord.Color.brand_green()
        )

        # Set author with avatar and username
        if status.get("avatar_url"):
            embed.set_author(
                name=username,  # Username next to avatar
                icon_url=status["avatar_url"], 
                url=stream_url
            )

        # Add category info directly under title (no extra spacing)
        if status.get("category_name"):
            category_text = f"**Category:** {status['category_name']}"
            embed.description = f"{embed.description}\n{category_text}"
            # Category icon in the corner
            if status.get("category_icon"):
                embed.set_thumbnail(url=status["category_icon"])

        # Add stream preview image if available
        if status.get("thumbnail_url"):
            embed.set_image(url=status["thumbnail_url"])

        view = discord.ui.View()
        button = discord.ui.Button(
            style=discord.ButtonStyle.green,
            label="Watch Stream",
            url=stream_url
        )
        view.add_item(button)

        found_config = False
        for guild_id, stream_config in config.streams.items():
            if stream_config.kick_channel == username:
                found_config = True
                for ch_conf in stream_config.discord_channels:
                    try:
                        channel = self.bot.get_channel(int(ch_conf['channel_id']))
                        if channel:
                            # Format the message with title and streamer info
                            message = ch_conf['message'].format(
                                streamer=username,
                                title=status['title'],
                                url=f"[Click to watch!]({stream_url})"  # URL as a clickable link
                            ).strip()
                            await channel.send(content=message, embed=embed, view=view)
                            # Always log successful notifications to console
                            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            print(f"[{timestamp}] ✅ Alert posted: {username} is live with '{status['title']}' in #{channel.name}")
                            debug_print(f"Notification sent successfully for {username} to {channel.id}")
                        else:
                            debug_print(f"Discord channel {ch_conf['channel_id']} not found for {username}")
                    except Exception as e:
                        debug_print(f"Error sending to {ch_conf.get('channel_id')}: {e}")

        if not found_config:
            debug_print(f"No configuration found for streamer {username}")
