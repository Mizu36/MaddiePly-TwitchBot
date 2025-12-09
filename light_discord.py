from discord.ext import commands
import discord
from dotenv import load_dotenv
import os
import threading
import asyncio
from typing import Optional
from tools import debug_print, set_reference

load_dotenv()
class DiscordBot():
    def __init__(self):
        self.token = os.getenv("DISCORD_TOKEN")
        intents = discord.Intents.default()
        intents.guilds = True
        intents.messages = True
        intents.message_content = True
        intents.members = True
        self.discord_bot = commands.Bot(command_prefix="!", intents=intents)
        self._thread: Optional[threading.Thread] = None
        set_reference("DiscordBot", self)

    def start_bot_background(self) -> threading.Thread:
        if self._thread and self._thread.is_alive():
            return self._thread
        self._thread = threading.Thread(target=self.discord_bot.run, args=(self.token,), daemon=True)
        self._thread.start()
        debug_print("DiscordBot", "Discord bot started in background thread.")
        return self._thread

    def _run_on_bot_loop(self, coro):
        loop = getattr(self.discord_bot, "loop", None)
        if loop is None or not loop.is_running():
            raise RuntimeError("Discord bot loop is not running. Call start_bot_background() first.")
        return asyncio.run_coroutine_threadsafe(coro, loop)

    async def _await_scheduled(self, coro):
        fut = self._run_on_bot_loop(coro)
        return await asyncio.wrap_future(fut, loop=asyncio.get_running_loop())

    async def send_message(self, channel_id, message) -> None:
        async def _send():
            await self.discord_bot.wait_until_ready()
            channel = self.discord_bot.get_channel(channel_id) or await self.discord_bot.fetch_channel(channel_id)
            if channel:
                await channel.send(message)
        await self._await_scheduled(_send())

    async def send_direct_message(self, user_id: int, message: str) -> None:
        async def _send_dm():
            await self.discord_bot.wait_until_ready()
            user = self.discord_bot.get_user(user_id) or await self.discord_bot.fetch_user(user_id)
            if user:
                await user.send(message)
        await self._await_scheduled(_send_dm())

    async def get_discord_user_name(self, user_id: int) -> str:
        async def _get_name():
            await self.discord_bot.wait_until_ready()
            user = self.discord_bot.get_user(user_id) or await self.discord_bot.fetch_user(user_id)
            return user.name if user else "Unknown"
        return await self._await_scheduled(_get_name())

    async def send_image(self, channel_id, image_path):
        async def _send_img():
            await self.discord_bot.wait_until_ready()
            channel = self.discord_bot.get_channel(channel_id) or await self.discord_bot.fetch_channel(channel_id)
            if channel:
                await channel.send(file=discord.File(image_path))
        await self._await_scheduled(_send_img())