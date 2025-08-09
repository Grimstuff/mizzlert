import json
import os
from typing import Dict, List, Optional

CONFIG_FILE = 'config.json'

class StreamConfig:
    def __init__(self, kick_channel: str, discord_channels: List[Dict[str, str]]):
        self.kick_channel = kick_channel
        self.discord_channels = discord_channels  # List of dicts with channel_id and message

class BotConfig:
    def __init__(self):
        self.streams: Dict[str, StreamConfig] = {}
        self.token: Optional[str] = None
        self.load_config()

    def load_config(self):
        if not os.path.exists(CONFIG_FILE):
            self.save_config()
            return

        with open(CONFIG_FILE, 'r') as f:
            data = json.load(f)
            self.token = data.get('token')
            streams_data = data.get('streams', {})
            self.streams = {
                guild_id: StreamConfig(
                    stream_data['kick_channel'],
                    stream_data['discord_channels']
                )
                for guild_id, stream_data in streams_data.items()
            }

    def save_config(self):
        data = {
            'token': self.token,
            'streams': {
                guild_id: {
                    'kick_channel': config.kick_channel,
                    'discord_channels': config.discord_channels
                }
                for guild_id, config in self.streams.items()
            }
        }
        with open(CONFIG_FILE, 'w') as f:
            json.dump(data, f, indent=2)

    def set_token(self, token: str):
        self.token = token
        self.save_config()

    def add_stream(self, guild_id: str, kick_channel: str):
        if guild_id not in self.streams:
            self.streams[guild_id] = StreamConfig(kick_channel, [])
        else:
            self.streams[guild_id].kick_channel = kick_channel
        self.save_config()

    def remove_stream(self, guild_id: str):
        if guild_id in self.streams:
            del self.streams[guild_id]
            self.save_config()

    def add_channel(self, guild_id: str, channel_id: str, message: str):
        if guild_id in self.streams:
            # Remove existing config for this channel if it exists
            self.streams[guild_id].discord_channels = [
                c for c in self.streams[guild_id].discord_channels 
                if c['channel_id'] != channel_id
            ]
            self.streams[guild_id].discord_channels.append({
                'channel_id': channel_id,
                'message': message
            })
            self.save_config()

    def remove_channel(self, guild_id: str, channel_id: str):
        if guild_id in self.streams:
            self.streams[guild_id].discord_channels = [
                c for c in self.streams[guild_id].discord_channels 
                if c['channel_id'] != channel_id
            ]
            self.save_config()

config = BotConfig()
