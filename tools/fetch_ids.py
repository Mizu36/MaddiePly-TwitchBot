import asyncio
import twitchio
import os
from pathlib import Path
from dotenv import load_dotenv, set_key

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
ENV_FILE = str(ENV_PATH)
load_dotenv(dotenv_path=ENV_PATH)

CLIENT_ID: str = os.getenv("TWITCH_CLIENT_ID", "").strip()
if CLIENT_ID == "":
    print("Please set the TWITCH_CLIENT_ID environment variable in the .env file.")
CLIENT_SECRET: str = os.getenv("TWITCH_APP_SECRET", "").strip()
if CLIENT_SECRET == "":
    print("Please set the TWITCH_APP_SECRET environment variable in the .env file.")


async def main() -> None:
    # Ask the user for the channel and bot usernames (allow env fallback)
    default_channel = os.getenv("CHANNEL_LOGIN", "")
    default_bot = os.getenv("BOT_LOGIN", "")

    channel_login = input(f"Enter channel username [{default_channel}]: ") or default_channel
    bot_login = input(f"Enter bot username [{default_bot}]: ") or default_bot

    if not channel_login or not bot_login:
        print("Both channel and bot usernames are required.")
        return

    async with twitchio.Client(client_id=CLIENT_ID, client_secret=CLIENT_SECRET) as client:
        await client.login()
        users = await client.fetch_users(logins=[channel_login, bot_login])

        # Map lowercased login -> id
        found = {u.name.lower(): u.id for u in users}

        channel_id = found.get(channel_login.lower())
        bot_id = found.get(bot_login.lower())

        if not channel_id:
            print(f"Could not find user id for channel: {channel_login}")
        else:
            print(f"Found channel {channel_login} with ID: {channel_id}")
            set_key(ENV_FILE, "OWNER_ID", channel_id)

        if not bot_id:
            print(f"Could not find user id for bot: {bot_login}")
        else:
            print(f"Found bot {bot_login} with ID: {bot_id}")
            set_key(ENV_FILE, "BOT_ID", bot_id)

        print("Updated .env with OWNER_ID and BOT_ID where found.")

if __name__ == "__main__":
    asyncio.run(main())