import asyncio
import json
from playwright.async_api import async_playwright

POLL_INTERVAL = 30  # seconds
DEBUG = True

API_URL = "https://kick.com/api/v2/channels/{username}"

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
                    pass

        page.on("response", handle_response)
        await page.goto(url, wait_until="networkidle")
        
        if DEBUG:
            print(f"\nRaw API Response for {username}:")
            print(json.dumps(response_data, indent=2))
            print("\n")
            
        response = json.dumps(response_data) if response_data else "{}"
        
        try:
            data = json.loads(response)
            if DEBUG:
                print(f"Parsed JSON data:")
                print(json.dumps(data, indent=2))
                print("\n")

            livestream = data.get("livestream")
            if livestream:
                return {
                    "is_live": True,
                    "title": livestream.get("session_title", "Untitled Stream")
                }
            else:
                return {"is_live": False, "title": None}
        except json.JSONDecodeError as e:
            print(f"Failed to parse JSON for {username}: {e}")
            return None
    except Exception as e:
        if DEBUG:
            print(f"[ERROR] Failed to fetch {username}: {e}")
        return None

async def poll_channels(usernames):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        while True:
            for username in usernames:
                status = await fetch_channel_status(page, username)
                if status:
                    if status["is_live"]:
                        print(f"[LIVE] {username} - '{status['title']}'")
                    else:
                        print(f"[OFFLINE] {username}")
            await asyncio.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    usernames_to_track = ["lospollostv"]
    asyncio.run(poll_channels(usernames_to_track))
