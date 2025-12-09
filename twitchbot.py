import asyncio
import twitchio
import os
import logging
import random
from dotenv import load_dotenv
from custom_channel_point_builder import CustomPointRedemptionBuilder
from db import setup_database, get_all_commands, get_prompt, get_setting, set_user_data, get_user_data, get_specific_user_data, increment_user_stat, user_exists
from google_api import add_quote, get_quote, get_random_quote, get_random_quote_containing_word
import asqlite
from twitchio import eventsub, HTTPException
from twitchio.ext import commands
from ai_logic import AssistantManager, AutoMod, ResponseTimer, EventManager, setup_gpt_manager
from message_scheduler import MessageScheduler
from tools import debug_print, set_debug, set_reference, get_reference, get_random_number
from light_discord import DiscordBot


load_dotenv()

def _sanitize_env_value(value: str) -> str:
    """Trim whitespace and wrapping quotes from .env values."""
    value = value.strip()
    if not value:
        return ""
    if (value.startswith("'") and value.endswith("'")) or (value.startswith('"') and value.endswith('"')):
        return value[1:-1].strip()
    return value

# Suppress noisy traceback logging for missing commands (CommandNotFound).
class _SuppressCommandNotFoundFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            ei = getattr(record, "exc_info", None)
            if ei:
                exc = ei[1] if isinstance(ei, tuple) and len(ei) >= 2 else None
                if exc is not None and exc.__class__.__name__ == "CommandNotFound":
                    return False
            # Also inspect the formatted message for known substrings
            msg = record.getMessage() if hasattr(record, "getMessage") else str(record)
            if "The command" in msg and "was not found" in msg:
                return False
        except Exception:
            pass
        return True

# Attach filter to twitchio command logger and root logger to be safe
try:
    logging.getLogger("twitchio.ext.commands.bot").addFilter(_SuppressCommandNotFoundFilter())
    logging.getLogger().addFilter(_SuppressCommandNotFoundFilter())
except Exception:
    pass

class Bot(commands.AutoBot):
    def __init__(self, *, database: asqlite.Pool, subs: list[eventsub.SubscriptionPayload], prefix: str) -> None:
        self.database = database
        self.prefix = prefix
        client_id_env: str = _sanitize_env_value(os.getenv("TWITCH_CLIENT_ID", ""))
        if client_id_env == "":
            print("Please set the TWITCH_CLIENT_ID environment variable in the .env file.")
        client_secret_env: str = _sanitize_env_value(os.getenv("TWITCH_APP_SECRET", ""))
        if client_secret_env == "":
            print("Please set the TWITCH_APP_SECRET environment variable in the .env file.")
        bot_id_env: str = _sanitize_env_value(os.getenv("BOT_ID", ""))
        if bot_id_env == "":
            print("Please set the BOT_ID environment variable in the .env file. If you don't know it, please run fetch_ids.py.")
        owner_id_env: str = _sanitize_env_value(os.getenv("OWNER_ID", ""))
        if owner_id_env == "":
            print("Please set the OWNER_ID environment variable in the .env file. If you dont know it, please run fetch_ids.py.")
        debug_print("AutoBot", f"Initializing bot with prefix: {prefix} and subscriptions: {subs}")
        self.custom_commands = {}

        super().__init__(
            client_id=client_id_env,
            client_secret=client_secret_env,
            bot_id=bot_id_env,
            owner_id=owner_id_env,
            prefix=prefix,
            subscriptions=subs,
            force_subscribe=True
        )
        debug_print("AutoBot", "AutoBot initialized.")

    async def setup_hook(self) -> None:
        await self.load_commands()
        self.command_handler = CommandHandler(self, self.prefix)
        set_reference("CommandHandler", self.command_handler)
        await self.add_component(self.command_handler)

    async def event_oauth_authorized(self, payload: twitchio.authentication.UserTokenPayload) -> None:
        await self.add_token(payload.access_token, payload.refresh_token)

        if not payload.user_id:
            debug_print("AutoBot", "No user id was passed with the payload.")
            return
        
        if payload.user_id == self.bot_id:
            debug_print("AutoBot", "User id matched the bot id; ensuring bot-level subscriptions.")
            try:
                resp: twitchio.MultiSubscribePayload = await self.multi_subscribe([
                    eventsub.WhisperReceivedSubscription(user_id=self.bot_id),
                ])
                if resp.errors:
                    debug_print("AutoBot", f"Failed to subscribe bot user to whispers: {resp.errors}")
            except Exception as exc:
                debug_print("AutoBot", f"Error subscribing bot user to whispers: {exc}")
            return
        
        subs: list[eventsub.SubscriptionPayload] = [
            eventsub.ChatMessageSubscription(broadcaster_user_id=payload.user_id, user_id=self.bot_id), #Receives chat messages
            eventsub.ChannelCheerSubscription(broadcaster_user_id=payload.user_id), #Receives bits cheers
            eventsub.ChannelSubscribeSubscription(broadcaster_user_id=payload.user_id), #Receives new subscriptions
            eventsub.ChannelSubscribeMessageSubscription(broadcaster_user_id=payload.user_id), #Receives subscription messages and resubs without messages
            eventsub.ChannelSubscriptionEndSubscription(broadcaster_user_id=payload.user_id), #Receives subscription end events
            eventsub.ChannelFollowSubscription(broadcaster_user_id=payload.user_id, moderator_user_id=self.bot_id), #Receives new followers
            eventsub.ChannelRaidSubscription(to_broadcaster_user_id=payload.user_id), #Receives raids to the channel
            eventsub.ChannelSubscriptionGiftSubscription(broadcaster_user_id=payload.user_id), #Receives gifted subscriptions
            eventsub.ChannelPointsAutoRedeemV2Subscription(broadcaster_user_id=payload.user_id), #Receives default channel points redemptions
            eventsub.ChannelPointsRedeemAddSubscription(broadcaster_user_id=payload.user_id), #Receives custom channel points redemptions
            eventsub.SuspiciousUserMessageSubscription(broadcaster_user_id=payload.user_id, moderator_user_id=self.bot_id), #Receives suspicious messages for AutoMod
            eventsub.SharedChatSessionBeginSubscription(broadcaster_user_id=payload.user_id), #Receives shared chat start events
            eventsub.SharedChatSessionUpdateSubscription(broadcaster_user_id=payload.user_id), #Receives shared chat update events
            eventsub.SharedChatSessionEndSubscription(broadcaster_user_id=payload.user_id), #Receives shared chat end events
            eventsub.StreamOnlineSubscription(broadcaster_user_id=payload.user_id), #Receives stream online events
            eventsub.StreamOfflineSubscription(broadcaster_user_id=payload.user_id), #Receives stream offline events
            eventsub.CharityCampaignStartSubscription(broadcaster_user_id=payload.user_id), #Receives charity campaign start events
            eventsub.CharityCampaignProgressSubscription(broadcaster_user_id=payload.user_id), #Receives charity campaign progress events
            eventsub.CharityCampaignStopSubscription(broadcaster_user_id=payload.user_id), #Receives charity campaign stop events
            eventsub.GoalBeginSubscription(broadcaster_user_id=payload.user_id), #Receives goal begin events
            eventsub.GoalProgressSubscription(broadcaster_user_id=payload.user_id), #Receives goal progress events
            eventsub.GoalEndSubscription(broadcaster_user_id=payload.user_id), #Receives goal end events
            eventsub.HypeTrainBeginSubscription(broadcaster_user_id=payload.user_id), #Receives hype train begin events
            eventsub.HypeTrainProgressSubscription(broadcaster_user_id=payload.user_id), #Receives hype train progress events
            eventsub.HypeTrainEndSubscription(broadcaster_user_id=payload.user_id), #Receives hype train end events
            eventsub.ChannelPollBeginSubscription(broadcaster_user_id=payload.user_id), #Receives channel poll begin events
            eventsub.ChannelPollProgressSubscription(broadcaster_user_id=payload.user_id), #Receives channel poll progress events
            eventsub.ChannelPollEndSubscription(broadcaster_user_id=payload.user_id), #Receives channel poll end events
            eventsub.ChannelPredictionBeginSubscription(broadcaster_user_id=payload.user_id), #Receives channel prediction begin events
            eventsub.ChannelPredictionProgressSubscription(broadcaster_user_id=payload.user_id), #Receives channel prediction progress events
            eventsub.ChannelPredictionLockSubscription(broadcaster_user_id=payload.user_id), #Receives channel prediction lock events
            eventsub.ChannelPredictionEndSubscription(broadcaster_user_id=payload.user_id), #Receives channel prediction end events
            eventsub.ShieldModeBeginSubscription(broadcaster_user_id=payload.user_id, moderator_user_id=self.bot_id), #Receives shield mode begin events
            eventsub.ShieldModeEndSubscription(broadcaster_user_id=payload.user_id, moderator_user_id=self.bot_id), #Receives shield mode end events
            eventsub.ShoutoutCreateSubscription(broadcaster_user_id=payload.user_id, moderator_user_id=self.bot_id), #Receives shoutout create events
            eventsub.ShoutoutReceiveSubscription(broadcaster_user_id=payload.user_id, moderator_user_id=self.bot_id), #Receives shoutout receive events
            eventsub.AutomodMessageHoldSubscription(broadcaster_user_id=payload.user_id, moderator_user_id=self.bot_id), #Receives AutoMod held messages
            eventsub.AdBreakBeginSubscription(broadcaster_user_id=payload.user_id), #Receives ad break begin events
        ]

        resp: twitchio.MultiSubscribePayload = await self.multi_subscribe(subs)
        if resp.errors:
            debug_print("AutoBot", f"Failed to subscribe to: {resp.errors}, for users: {payload.user_id}")

    async def add_token(self, token: str, refresh: str) -> twitchio.authentication.ValidateTokenPayload:
        resp: twitchio.authentication.ValidateTokenPayload = await super().add_token(token, refresh)

        query = """
        INSERT INTO tokens (user_id, token, refresh)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id)
        DO UPDATE SET
            token = excluded.token,
            refresh = excluded.refresh;
        """

        async with self.database.acquire() as connection:
            await connection.execute(query, (resp.user_id, token, refresh))

        debug_print("AutoBot", f"Added token to the database for user: {resp.user_id}")
        return resp
    
    async def send_chat(self, message: str) -> None:
        debug_print("AutoBot", f"Sending chat message: {message}")
        channel = self.create_partialuser(self.owner_id)
        await channel.send_message(sender=self.user, message=message)

    async def whisper(self, user: twitchio.PartialUser, message: str) -> None:
        debug_print("AutoBot", f"Sending whisper to {user.name}: {message}")
        bot_user = self.create_partialuser(self.bot_id)
        await bot_user.send_whisper(to_user=user, message=message)

    async def get_current_game(self) -> str:
        debug_print("AutoBot", f"Fetching current game for channel ID: {self.owner_id}")
        channel = await self.fetch_channel(broadcaster_id=self.owner_id)
        return channel.game_name
    
    async def get_game(self, partial_user: twitchio.PartialUser) -> str:
        channel = await partial_user.fetch_channel_info()
        return channel.game_name
    
    async def event_ready(self) -> None:
        debug_print("AutoBot", f"Bot is ready. Logged in as: {self.bot_id}")

    async def load_commands(self) -> None:
        self.custom_commands = await get_all_commands()
        debug_print("AutoBot", f"Loaded custom commands: {self.custom_commands.keys()}")

    async def fetch_follower_count(self) -> int:
        debug_print("AutoBot", f"Fetching follower count for channel ID: {self.owner_id}")
        user = await self.fetch_user(id=self.owner_id)
        channel_followers = await user.fetch_followers()
        return channel_followers.total
    
    async def fetch_viewer_count(self) -> int:
        debug_print("AutoBot", f"Fetching viewer count for channel ID: {self.owner_id}")
        streams = await self.fetch_streams(user_ids=[self.owner_id])
        if streams:
            stream = streams[0]
            viewer_count = stream.viewer_count
            return viewer_count
        
    async def fetch_subscriber_count(self) -> int:
        debug_print("AutoBot", f"Fetching subscriber count for channel ID: {self.owner_id}")
        user = await self.fetch_user(id=self.owner_id)
        channel_subscriptions = await user.fetch_broadcaster_subscriptions()
        return channel_subscriptions.total
    
    async def fetch_title(self) -> str:
        debug_print("AutoBot", f"Fetching current title for channel ID: {self.owner_id}")
        channel = await self.fetch_channel(broadcaster_id=self.owner_id)
        return channel.title
    
    async def timeout(self, username: str, duration: int, reason: str = "") -> None:
        debug_print("AutoBot", f"Timing out user: {username} for {duration} seconds. Reason: {reason}")
        broadcaster = self.create_partialuser(user_id=self.owner_id)
        #Check to see if username is a moderator or the broadcaster themselves
        user = await self.fetch_user(login=username)
        if not user:
            debug_print("AutoBot", f"User {username} not found; cannot timeout.")
            await self.send_chat(random.choice([f"Who?", "Huh?", "Never heard of them.", "Can't find that user.", "Are you sure that's a real user?", "That user doesn't seem to exist.", "I don't see that user anywhere.", "User not found.", "That user is invisible to me.", "Searching... No results found.", "That user must be a ghost.", "404 User Not Found.", "That user is beyond my reach.", "That user is lost in the void.", "I can't locate that user.", "That user is off the grid.", "That user is in another dimension.", "That user is hiding from me.", "That user is a mystery.", "That user is out of my sight.", "That user is in stealth mode."]))
            return
        if user.id == self.owner_id:
            debug_print("AutoBot", f"User {username} is the broadcaster; cannot timeout.")
            await self.send_chat(f"Cannot timeout {username}; they are the broadcaster.")
            return
        try:
            mods = await broadcaster.fetch_moderators(user_ids=[user.id], token_for=self.bot_id, first=1)
        except HTTPException as exc:
            debug_print("AutoBot", f"Failed to verify moderator status for {username}: {exc}")
            await self.send_chat(f"Cannot timeout {username}; unable to verify moderator status right now.")
            return
        except Exception as exc:
            debug_print("AutoBot", f"Unexpected error verifying moderator status for {username}: {exc}")
            await self.send_chat(f"Cannot timeout {username}; unable to verify moderator status right now.")
            return
        if mods is None:
            debug_print("AutoBot", f"Moderator fetch returned None for {username}; aborting timeout.")
            await self.send_chat(f"Cannot timeout {username}; unable to verify moderator status right now.")
            return
        if mods:
            debug_print("AutoBot", f"User {username} is a moderator; cannot timeout.")
            await self.send_chat(f"Cannot timeout {username}; they are a moderator.")
            return
        try:
            await broadcaster.timeout_user(moderator=self.bot_id, user=user, duration=duration, reason=reason)
        except Exception as e:
            debug_print("AutoBot", f"Failed to timeout user {username}: {e}")
    
    async def get_total_bits_donated(self, user_id) -> int:
        debug_print("AutoBot", f"Fetching total bits donated by user ID: {user_id}")
        broadcaster = self.create_partialuser(user_id=self.owner_id)
        try:
            leaderboard = await broadcaster.fetch_bits_leaderboard(user=user_id, count=1)
        except HTTPException as exc:
            debug_print(
                "AutoBot",
                f"Failed to fetch bits leaderboard for {user_id}: {exc}. Does the owner token include bits:read?",
            )
            return 0
        leader = next((l for l in leaderboard.leaders if str(l.user_id) == str(user_id)), None)
        return leader.score if leader else 0

    async def classify_users_for_purge(self, user_ids: list[str]) -> dict[str, str]:
        """Classify users as ok/banned/missing for purge decisions."""
        debug_print("AutoBot", f"Classifying {len(user_ids)} users for purge.")
        results: dict[str, str] = {}
        if not user_ids:
            return results
        protected_ids = {
            str(getattr(self, "owner_id", "") or ""),
            str(getattr(self, "bot_id", "") or ""),
        }
        protected_ids.discard("")
        chunk_size = 90
        for start in range(0, len(user_ids), chunk_size):
            raw_slice = user_ids[start:start + chunk_size]
            chunk: list[str] = []
            for raw in raw_slice:
                uid = str(raw or "").strip()
                if not uid or uid in protected_ids:
                    continue
                if not uid.isdigit():
                    # Skip obviously invalid Twitch identifiers; leave them untouched in DB
                    continue
                chunk.append(uid)
            if not chunk:
                continue
            existing: dict[str, twitchio.User] = {}
            user_lookup_failed = False
            try:
                users = await self.fetch_users(ids=chunk)
                for user in users or []:
                    existing[str(user.id)] = user
            except Exception as e:
                user_lookup_failed = True
                debug_print("AutoBot", f"Failed to fetch users for purge chunk: {e}")
            banned_ids: set[str] = set()
            broadcaster = self.create_partialuser(user_id=self.owner_id)
            banned_lookup_failed = False
            try:
                bans = await broadcaster.fetch_banned_user(user_ids=chunk, first=chunk_size)
                for ban in bans or []:
                    ban: twitchio.BannedUser = ban
                    if ban.expires_at:
                        continue # Skips timeouts
                    try:
                        banned_ids.add(str(ban.user.id))
                    except Exception:
                        continue
            except HTTPException as exc:
                banned_lookup_failed = True
                if getattr(exc, "status", None) == 401:
                    debug_print(
                        "AutoBot",
                        "fetch_banned_user requires moderation:read or moderator:manage:banned_users. Skipping banned classification.",
                    )
                else:
                    debug_print("AutoBot", f"fetch_banned_users failed during purge classification: {exc}")
            except Exception as e:
                banned_lookup_failed = True
                debug_print("AutoBot", f"fetch_banned_users failed during purge classification: {e}")
            for uid in chunk:
                if not banned_lookup_failed and uid in banned_ids:
                    results[uid] = "banned"
                elif not user_lookup_failed and uid not in existing:
                    results[uid] = "missing"
                else:
                    results[uid] = "ok"
        return results

class CommandHandler(commands.Component):

    def __init__(self, bot: Bot, prefix: str) -> None:
        self.bot = bot
        self.response_manager: ResponseTimer = get_reference("ResponseTimer")
        self.prefix = prefix
        self.scheduler: MessageScheduler = get_reference("MessageScheduler")
        self.auto_mod: AutoMod = get_reference("AutoMod")
        self.assistant: AssistantManager = get_reference("AssistantManager")
        self.event_manager: EventManager = get_reference("EventManager")
        self.audio_manager = None
        self.shared_chat = False
        self.greeting_task = None
        self.message_queue = []
        self.message_timer = None
        self.first_user_greeted = False
        self.ignored_users = ["streamlabs", "streamelements", "nightbot", "moobot", "tangiabot", "maddieply", "soundalerts"]
        self.welcomed_users = []
        self.users_to_greet = []
        self.message_history = []
        self.discord_bot = None
        self.whisper_commands = ["!connectdiscord", "!confirmdiscord", "!disconnectdiscord", "!setdefaultvoice", "!getvoices", "!setchime", "!getchimes", "!commands", "!help", "!mystats"]
        for name, spec in self.bot.custom_commands.items():
            self.register_custom_command(name, spec)
        asyncio.create_task(self.scheduler.start_scheduled_messages())
        asyncio.create_task(self.ad_timer())
        self.discord_bot = DiscordBot()
        self.discord_bot.start_bot_background()
        self.custom_builder = None
        asyncio.create_task(self.start_custom_builder())
        asyncio.create_task(self.event_manager.start())
        debug_print("CommandHandler", "CommandHandler initialized.")

    async def start_custom_builder(self) -> None:
        self.custom_builder = CustomPointRedemptionBuilder()
        set_reference("PointBuilder", self.custom_builder)

    def get_message_history(self):
        debug_print("CommandHandler", f"Sending message history from Twitch bot.")
        return self.message_history

    async def make_discord_announcement(self, message: str) -> None:
        if not self.discord_bot:
            self.discord_bot = get_reference("DiscordBot")
        announcement_channel = await get_setting("Discord Announcement Channel ID", None)
        if self.discord_bot and announcement_channel:
            asyncio.create_task(self.discord_bot.send_message(channel_id=announcement_channel, message=message))

    def register_custom_command(self, name: str, spec: dict):
        """
        Dynamically create a TwitchIO command from a custom command spec.
        """
        async def custom_cmd(ctx):
            # Permission checks
            response = self.command_builder(ctx, spec.get("response", ""))
            if spec.get("mod_only") and not self._is_moderator(ctx):
                print(f"{ctx.author.name} tried to use mod-only command {name}")
                return

            if spec.get("sub_only") and not (self._is_subscriber(ctx) or self._is_moderator(ctx)):
                print(f"{ctx.author.name} tried to use sub-only command {name}")
                return

            response = self.command_builder(ctx, spec.get("response", ""))
            if spec.get("reply_to_user"):
                await ctx.reply(response)
            else:
                await ctx.send(response)

        cmd_obj = commands.Command(custom_cmd, name=name)

        # Unregister existing command first if it exists
        if name in self.bot.commands:
            self.bot.remove_command(name)

        self.bot.add_command(cmd_obj)
        debug_print("CommandHandler", f"Registered custom command: !{name}")

    def unregister_custom_command(self, name: str):
        """
        Safely remove a dynamically registered custom command.
        """
        if name in self.bot.commands:
            self.bot.remove_command(name)
            debug_print("CommandHandler", f"Unregistered custom command: !{name}")

    def _is_moderator(self, ctx: commands.Context) -> bool:
        # Prefer explicit attribute if available
        debug_print("CommandHandler", f"Checking if user is moderator: {getattr(ctx, 'author', None)}")
        try:
            author = getattr(ctx, "author", None)
            if author is None:
                return False
            # Broadcaster check: if the author is the channel owner, consider them a moderator
            try:
                # ctx.channel is usually available; fallback to message.channel
                channel = getattr(ctx, "channel", None) or getattr(ctx, "message", None) and getattr(ctx.message, "channel", None)
                if channel is not None and hasattr(author, "name") and hasattr(channel, "name"):
                    if author.name and channel.name and author.name.lower() == channel.name.lower():
                        return True
            except Exception:
                pass
            if hasattr(author, "is_mod"):
                return bool(getattr(author, "is_mod"))
            # Some versions expose is_broadcaster
            if hasattr(author, "is_broadcaster") and getattr(author, "is_broadcaster"):
                return True
            # Fallback: check badges if present
            badges = getattr(author, "badges", None)
            if isinstance(badges, dict):
                return any(k in badges for k in ("moderator", "broadcaster"))
            return False
        except Exception:
            return False

    def _is_subscriber(self, ctx: commands.Context) -> bool:
        debug_print("CommandHandler", f"Checking if user is subscriber: {getattr(ctx, 'author', None)}")
        try:
            author = getattr(ctx, "author", None)
            if author is None:
                return False
            if hasattr(author, "is_subscriber"):
                return bool(getattr(author, "is_subscriber"))
            badges = getattr(author, "badges", None)
            if isinstance(badges, dict):
                return "subscriber" in badges
            return False
        except Exception:
            return False
        
    def command_builder(self, ctx: commands.Context, response: str) -> str:
        # %bot% - bot's display name
        # %user% - user's display name
        # %channel% - channel name
        # %rng% - random number between 1 and 100
        # %rng:min:max% - random number between min and max (inclusive)
        debug_print("CommandHandler", f"Building command response for: {response}.")
        updated_response = response
        if "%" in updated_response:
            if "%bot%" in updated_response:
                try:
                    updated_response = updated_response.replace("%bot%", self.bot.user.name.capitalize())
                except Exception:
                    pass
            if "%user%" in updated_response:
                try:
                    author = getattr(ctx, "author", None)
                    if author is not None and hasattr(author, "display_name"):
                        updated_response = updated_response.replace("%user%", author.display_name)
                except Exception:
                    pass
            if "%channel%" in updated_response:
                try:
                    channel = getattr(ctx, "channel", None) or getattr(ctx, "message", None) and getattr(ctx.message, "channel", None)
                    if channel is not None and hasattr(channel, "name"):
                        updated_response = updated_response.replace("%channel%", channel.name)
                except Exception:
                    pass
            if "%rng%" in updated_response:
                random_number = str(get_random_number(1, 100))
                updated_response = updated_response.replace("%rng%", random_number)
            if "%rng:" in updated_response:
                import re
                pattern = r"%rng:(-?\d+):(-?\d+)%"
                matches = re.findall(pattern, updated_response)
                for match in matches:
                    try:
                        min_val = int(match[0])
                        max_val = int(match[1])
                        if min_val > max_val:
                            min_val, max_val = max_val, min_val
                        random_number = str(get_random_number(min_val, max_val))
                        updated_response = updated_response.replace(f"%rng:{min_val}:{max_val}%", random_number)
                    except Exception:
                        pass
        return updated_response
    
    async def handle_message(self) -> None:
        while True:
            if len(self.message_queue) > 0:
                if self.shared_chat:
                    if not await get_setting("Shared Chat Chat Responses Enabled", default=False):
                        self.message_queue.clear()
                        await asyncio.sleep(60)
                        continue
                payload: twitchio.ChatMessage = self.message_queue.pop(0)
            else:
                if self.shared_chat:
                    if not await get_setting("Shared Chat Chat Responses Enabled", default=False):
                        await asyncio.sleep(60)
                        continue
                await asyncio.sleep(.5)
                continue
            user_name = payload.chatter.name
            if user_name.lower() in self.ignored_users:
                continue
            if payload.text.startswith(self.prefix):
                continue
            increment = asyncio.create_task(self.scheduler.increment_message_count())
            if user_name not in self.welcomed_users and user_name not in self.users_to_greet:
                if not self.first_user_greeted:
                    self.first_user_greeted = True
                    user_id = payload.chatter.id
                    chime_enabled = await get_setting("First Chat of Stream Chime Enabled", True)
                    if chime_enabled:
                        try:
                            soundFX = await get_specific_user_data(user_id=user_id, field="sound_fx")
                            if soundFX == "off":
                                debug_print("CommandHandler", f"Sound FX is turned off for user {user_name}.")
                            elif soundFX == "on":
                                if not self.audio_manager:
                                    self.audio_manager = get_reference("AudioManager")
                                asyncio.create_task(self.audio_manager.play_random_sound_fx())
                            elif soundFX not in [None, "", "None", "null", "none", "NULL"]:
                                if not self.audio_manager:
                                    self.audio_manager = get_reference("AudioManager")
                                asyncio.create_task(self.audio_manager.play_sound_fx_by_name(soundFX))
                            else:
                                if not self.audio_manager:
                                    self.audio_manager = get_reference("AudioManager")
                                asyncio.create_task(self.audio_manager.play_random_sound_fx())
                        except Exception as e:
                            debug_print("CommandHandler", f"Error fetching sound FX for user {user_name}: {e}")
                    self.welcomed_users.append(user_name)
                    prompt = await get_prompt("Personality Prompt")
                    prompt += f"\nYour first task is to welcome {payload.chatter.display_name} as the first person to show up to work today at ModdCorp. Make it short and sweet, but still in character as MaddiePly. Respond in only 1 sentence."
                    if not self.assistant:
                        self.assistant = get_reference("AssistantManager")
                    response = await self.assistant.general_response(prompt)
                    await self.bot.send_chat(response)
                else:
                    self.users_to_greet.append(user_name)
                    if self.greeting_task is None or self.greeting_task.done():
                        self.greeting_task = asyncio.create_task(self.greet_newcomers())
            user_id = payload.chatter.id
            if not await user_exists(user_id=user_id):
                date = payload.timestamp.date().strftime("%Y-%m-%d")
                await set_user_data(user_id=user_id, username=payload.chatter.name, display_name=payload.chatter.display_name, number_of_messages=0, bits_donated=0, months_subscribed=0, subscriptions_gifted=0, points_redeemed=0, date_added=date)
            user_data = await get_user_data(user_id=user_id)
            if not user_data.get("username"):
                #Properly creates user if they were added through whisper commands.
                await set_user_data(user_id=user_id, username=payload.chatter.name, display_name=payload.chatter.display_name, number_of_messages=0, bits_donated=0, months_subscribed=0, subscriptions_gifted=0, points_redeemed=0)
            elif user_data.get("display_name") != payload.chatter.display_name or user_data.get("username") != payload.chatter.name:
                #Updated display name or username if they've changed.
                await set_user_data(user_id=user_id, username=payload.chatter.name, display_name=payload.chatter.display_name)
            await increment_user_stat(user_id=user_id, stat="messages")
            message = payload.text
            time = payload.timestamp.time().strftime("%Y-%m-%d %H:%M:%S")
            self.message_history.append({"user": user_name, "message": message, "time": payload.timestamp.time()})
            if len(self.message_history) > 50:
                self.message_history.pop(0)
            await increment
            await self.response_manager.handle_message(user_name, message, time)

    async def handle_whisper(self, payload: twitchio.Whisper) -> None:
        debug_print("CommandHandler", "Handling received whisper...")
        if not payload.text:
            return
        user_id = payload.sender.id
        if not await user_exists(user_id=user_id):
            date = payload.timestamp.date().strftime("%Y-%m-%d")
            await set_user_data(user_id=user_id, username=payload.sender.name, display_name=payload.sender.display_name, number_of_messages=0, bits_donated=0, months_subscribed=0, subscriptions_gifted=0, points_redeemed=0, date_added=date)
        message_parts = payload.text.strip().split()
        if not message_parts[0].lower().startswith("!"):
            if not message_parts[0].lower() in ["hi", "hello", "hey", "greetings", "sup", "yo", "howdy"]:
                await self.bot.whisper(payload.sender, "To use commands with me, please start your message with '!', to see commands, use !commands or !help.")
                return
            else:
                response = random.choice(["Hello!", "Hi there!", "Hey!", "Greetings!", "Sup!", "Yo!", "Howdy!", "Heyo!", "Hiya!", "Hello there!", 
                                          "Heyo there!", "Hi!", "Heya!", "Greetings and salutations!", "Howdy partner!", "Hey friend!", "Hello friend!", 
                                          "Hi friend!", "Hey buddy!", "Hello buddy!", "Hi buddy!", "Hey pal!", "Hello pal!", "Hi pal!", "Hey mate!", "Hello mate!", 
                                          "Hi mate!", "Hey champ!", "Hello champ!", "Hi champ!", "Hey superstar!", "Hello superstar!", "Hi superstar!", "Moddi is always getting on back.", 
                                          "I'm here if you need me!", "Maddie at your service!", "Ready to assist you!", "How can I help you today?", "At your command!", 
                                          "Your friendly bot is here!", "Maddie is listening!", "Here to help!", "Your wish is my command!", "Moddi is on the job!", 
                                          "Always happy to help!", "Moddi is ready to assist!", "Your personal bot assistant!"])
                await self.bot.whisper(payload.sender, response)
                return
        if message_parts[0].lower() not in self.whisper_commands:
            await self.bot.whisper(payload.sender, f"The command {message_parts[0]} is not recognized as a valid whisper command. To see available commands, use !commands or !help.")
            return
        if message_parts[0].lower() in ["!commands", "!help"]:
            temp_commands = self.whisper_commands.copy()
            temp_commands.pop(temp_commands.index("!commands"))
            temp_commands.pop(temp_commands.index("!help"))
            command_list_str = ", ".join(sorted(temp_commands))
            await self.bot.whisper(payload.sender, f"Available whisper commands are: {command_list_str}")
            return
        elif message_parts[0].lower() == "!connectdiscord":
            if len(message_parts) < 2:
                debug_print("CommandHandler", "No Discord user ID provided in whisper.")
                await self.bot.whisper(payload.sender, "Please provide your Discord User ID. Usage: !connectdiscord <Your Discord User ID> (DM's must be enabled and you must be in the community Discord server.)")
                return
            if message_parts[1].isdigit():
                discord_user_id = int(message_parts[1])
            else:
                debug_print("CommandHandler", "Invalid Discord user ID provided in whisper.")
                await self.bot.whisper(payload.sender, "The Discord User ID you provided is invalid. Please provide a valid numeric Discord User ID.")
                return
            if not self.discord_bot:
                self.discord_bot: DiscordBot = get_reference("DiscordBot")
            random_eight_digit_code = str(random.randint(10000000, 99999999))
            #replace up to 4 numbers with characters either lower or upper case
            code_list = list(random_eight_digit_code)
            indices = random.sample(range(8), 4)
            for index in indices:
                if random.choice([True, False]):
                    code_list[index] = chr(random.randint(65, 90)) #Uppercase A-Z
                else:
                    code_list[index] = chr(random.randint(97, 122)) #Lowercase a-z
            random_eight_digit_code = "".join(code_list)
            await set_user_data(user_id=payload.sender.id, discord_id=discord_user_id, discord_username="Unlinked", discord_secret_code=random_eight_digit_code)
            try:
                await self.discord_bot.send_direct_message(discord_user_id, f"Hello {payload.sender}, please dm me on twitch the following command !confirmdiscord {random_eight_digit_code} to link your Discord account to your Twitch account.")
            except Exception as e:
                debug_print("CommandHandler", f"Error sending Discord DM: {e}")
                await self.bot.whisper(payload.sender, "I was unable to send you a DM on Discord. Please ensure that your DMs are enabled, you are in the community Discord server, and you have not blocked me, then try again.")
            return
        elif message_parts[0].lower() == "!confirmdiscord":
            if len(message_parts) < 2:
                debug_print("CommandHandler", "No confirmation code provided in whisper.")
                await self.bot.whisper(payload.sender, "Please provide the confirmation code you received on Discord. Usage: !confirmdiscord <Confirmation Code>")
                return
            confirmation_code = message_parts[1]
            user_data = await get_user_data(user_id=payload.sender.id)
            if user_data.get("discord_secret_code") != confirmation_code:
                debug_print("CommandHandler", "Invalid confirmation code provided in whisper.")
                await self.bot.whisper(payload.sender, "The confirmation code you provided is invalid. Please check the code and try again.")
                return
            if not self.discord_bot:
                self.discord_bot: DiscordBot = get_reference("DiscordBot")
            discord_user_name = await self.discord_bot.get_discord_user_name(user_data.get("discord_id"))
            await set_user_data(user_id=payload.sender.id, discord_username=discord_user_name, discord_secret_code="null")
            await asyncio.gather(self.bot.whisper(payload.sender, "Your Twitch account has been successfully linked to your Discord account! Thank you."), self.discord_bot.send_direct_message(user_data.get("discord_id"), f"Hello {discord_user_name}, your Discord account has been successfully linked to your Twitch account {payload.sender.display_name}! Thank you."))
            return
        elif message_parts[0].lower() == "!disconnectdiscord":
            user_data = await get_specific_user_data(user_id=payload.sender.id, field="discord_username")
            if user_data in [None, "Unlinked"]:
                debug_print("CommandHandler", "No linked Discord account found for disconnect.")
                await self.bot.whisper(payload.sender, "You do not have a linked Discord account to disconnect.")
                return
            if not self.discord_bot:
                self.discord_bot: DiscordBot = get_reference("DiscordBot")
            await set_user_data(user_id=payload.sender.id, discord_username="null", discord_secret_code="null", discord_id=0)
            await self.bot.whisper(payload.sender, "Your Discord account has been successfully unlinked from your Twitch account.")
            return
        elif message_parts[0].lower() == "!setdefaultvoice":
            if len(message_parts) < 2:
                debug_print("CommandHandler", "No voice provided in whisper.")
                await self.bot.whisper(payload.sender, "Please provide the default voice you would like to set. Usage: !setdefaultvoice <Voice Name>")
                return
            default_voice = " ".join(message_parts[1:])
            azure_manager = get_reference("SpeechToTextManager")
            voices = ["Ava", "Andrew", "Emma", "Brian", "Jenny", "Guy", "Aria", "Davis", "Jane", "Jason", "Kai", "Luna", "Sara", "Tony", "Nancy", "Amber", "Ana", "Ashley", "Brandon", "Christopher", "Cora", "Elizabeth", "Eric", "Jacob", "Michelle", "Monica", "Roger", "Steffan", "Blue", "AIGenerate1", "AIGenerate2"]
            for voice in voices:
                if voice.lower() == default_voice.lower():
                    default_voice = f"en-US-{voice}Neural"
                    break
            is_valid, matched_voice = azure_manager.is_voice_valid(default_voice)
            if not is_valid:
                debug_print("CommandHandler", "Invalid voice provided in whisper.")
                await self.bot.whisper(payload.sender, f"The voice '{default_voice}' is not valid. Please check the available voices and try again. Note: Voice names are NOT case-sensitive.")
                return
            await set_user_data(user_id=payload.sender.id, tts_voice=matched_voice)
            await self.bot.whisper(payload.sender, f"Your default voice has been set to: {matched_voice}")
            return
        elif message_parts[0].lower() == "!getvoices":
            azure_manager = get_reference("SpeechToTextManager")
            voices = ["Ava", "Andrew", "Emma", "Brian", "Jenny", "Guy", "Aria", "Davis", "Jane", "Jason", "Kai", "Luna", "Sara", "Tony", "Nancy", "Amber", "Ana", "Ashley", "Brandon", "Christopher", "Cora", "Elizabeth", "Eric", "Jacob", "Michelle", "Monica", "Roger", "Steffan", "Blue", "AIGenerate1", "AIGenerate2"]
            #voices: list = azure_manager.get_list_of_voices()
            voice_list = ", ".join(voices)
            await self.bot.whisper(payload.sender, f"Available voices are: {voice_list}")
            return
        elif message_parts[0].lower() == "!setchime":
            if len(message_parts) < 2:
                debug_print("CommandHandler", "No chime option provided in whisper.")
                await self.bot.whisper(payload.sender, "Please provide the name of the chime you want to play, 'on' to play a random chime, or 'off' to disable chimes altogether. Usage: !setchime <name/on/off>. Note: Do not include file extensions.")
                return
            chime_option = message_parts[1].lower()
            if chime_option.lower() == "off":
                debug_print("CommandHandler", "Invalid chime option provided in whisper.")
                await set_user_data(user_id=payload.sender.id, sound_fx="null")
                await self.bot.whisper(payload.sender, "Your chime has been disabled.")
                return
            if not self.audio_manager:
                self.audio_manager = get_reference("AudioManager")
            if "." in chime_option:
                chime_option = chime_option.rsplit(".", 1)[0]
            if await self.audio_manager.check_sound_fx_exists(chime_option):
                await set_user_data(user_id=payload.sender.id, sound_fx=chime_option.lower())
            else:
                debug_print("CommandHandler", "Invalid chime option provided in whisper.")
                await self.bot.whisper(payload.sender, f"The chime '{chime_option}' does not exist. Please check the available chimes and try again. Note: Do not include file extensions. Name is NOT case-sensitive.")
                return
            await self.bot.whisper(payload.sender, f"Your TTS chime preference has been set to: {chime_option}")
            return
        elif message_parts[0].lower() == "!getchimes":
            if not self.audio_manager:
                self.audio_manager = get_reference("AudioManager")
            chime_list = await self.audio_manager.get_list_of_sound_fx()
            chime_list_str = ", ".join(chime_list)
            await self.bot.whisper(payload.sender, f"Available chimes are: {chime_list_str}. Use !setchime <name> to set your preferred chime. Join the discord to suggest more chimes.")
            return
        elif message_parts[0].lower() == "!mystats":
            user_data = await get_user_data(user_id=payload.sender.id)
            number_of_messages = user_data.get("number_of_messages", 0)
            bits_donated = user_data.get("bits_donated", 0)
            months_subscribed = user_data.get("months_subscribed", 0)
            subscriptions_gifted = user_data.get("subscriptions_gifted", 0)
            points_redeemed = user_data.get("points_redeemed", 0)
            if user_data["discord_id"] != 0 and user_data["discord_secret_code"] == "null":
                if not self.discord_bot:
                    self.discord_bot: DiscordBot = get_reference("DiscordBot")
                await self.discord_bot.send_direct_message(user_data["discord_id"], f"Hello {user_data['discord_username']}, here are your current Twitch stats:\nMessages Sent: {number_of_messages}\nBits Donated: {bits_donated}\nMonths Subscribed: {months_subscribed}\nSubscriptions Gifted: {subscriptions_gifted}\nChannel Points Redeemed: {points_redeemed}.\nNote: Number of messages and channel points redeemed do not take into account messages or redemptions made while the bot was offline or before the bot started tracking them.")
                await self.bot.whisper(payload.sender, "I have sent your stats to your linked Discord account via direct message.")
                return
            await self.bot.whisper(payload.sender, f"Your total stats: Messages Sent: {number_of_messages}, Bits Donated: {bits_donated}, Months Subscribed: {months_subscribed}, Subscriptions Gifted: {subscriptions_gifted}, Channel Points Redeemed: {points_redeemed}. Note: Number of messages and channel points redeemed do not take into account messages or redemptions made while the bot was offline or before the bot started tracking them.")
            return

    async def handle_custom_channel_points_redeems(self, payload: twitchio.ChannelPointsRedemptionAdd | twitchio.ChannelPointsAutoRedeemAdd) -> None:
        if isinstance(payload, twitchio.ChannelPointsAutoRedeemAdd):
            debug_print("CommandHandler", f"Handling auto channel points redeem from {payload.user.display_name}: {payload.reward.type}")
        elif isinstance(payload, twitchio.ChannelPointsRedemptionAdd):
            debug_print("CommandHandler", f"Handling custom channel points from {payload.user.display_name}: {payload.reward.title}")
        if self.shared_chat:
            if not await get_setting("Shared Chat Custom Channel Point Redemptions Enabled", default=False):
                debug_print("CommandHandler", "Channel points handler task aborted due to Shared Chat mode.")
                asyncio.create_task(payload.refund(token_for=self.bot.owner_id))
                asyncio.create_task(self.bot.send_chat(f"@{payload.user.display_name}, channel point redemptions are disabled in Shared Chat mode. Your redemption has been refunded."))
                return
        if not self.custom_builder:
            self.custom_builder = CustomPointRedemptionBuilder()
            set_reference("PointBuilder", self.custom_builder)
        asyncio.create_task(self.custom_builder.channel_points_redemption_handler(payload))
    
    async def ad_timer(self) -> None:
        while True:
            if await get_setting("Auto Ad Enabled"):
                if self.shared_chat:
                    if not await get_setting("Shared Chat Ad Timer Enabled", default=False):
                        debug_print("CommandHandler", "Ad timer task aborted due to Shared Chat mode.")
                        await asyncio.sleep(60)
                        continue
                ad_interval = await get_setting("Ad Interval (minutes)", default="15")
                try:
                    interval_minutes = int(ad_interval)
                    if interval_minutes <= 0:
                        interval_minutes = 30
                except ValueError:
                    interval_minutes = 30
                await asyncio.sleep(interval_minutes * 60)
                await self.play_ad()
            else:
                await asyncio.sleep(300)
    
    async def play_ad(self) -> None:
        debug_print("CommandHandler", "Starting ad break...")
        try:
            duration = await get_setting("Ad Length (seconds)", default="30")
            broadcaster = await self.bot.fetch_channel(broadcaster_id=self.bot.owner_id)
            await broadcaster.user.start_commercial(length=int(duration))
            #await self.bot.send_chat(message=f"/commercial {duration}")
            debug_print("CommandHandler", f"Started a {duration}-second ad break.")
        except Exception as e:
            print(f"Failed to start ad break: {e}")

    async def greet_newcomers(self) -> None:
        if self.shared_chat:
            debug_print("CommandHandler", "Greet newcomers task aborted due to Shared Chat mode.")
            return
        debug_print("CommandHandler", "Starting greet_newcomers task...")
        await asyncio.sleep(30)
        users = []
        self.welcomed_users.extend(self.users_to_greet)
        users.extend(self.users_to_greet)
        self.users_to_greet.clear()
        if len(users) == 1:
            response = f"Welcome {users[0]}! moddipLove"
        elif len(users) == 2:
            response = f"Welcome {users[0]} and {users[1]}! moddipLove"
        else:
            all_but_last = ", ".join(f"{name}" for name in users[:-1])
            last = f"{users[-1]}"
            response = f"Welcome {all_but_last}, and {last}! moddipLove"
        await self.bot.send_chat(response)

    async def handle_suspicious_message(self, payload: twitchio.SuspiciousUserMessage) -> None:
        debug_print("CommandHandler", f"Handling suspicious message from {payload.user.display_name}: {payload.message.text}")
        is_bot = self.auto_mod.bot_detection(payload.message.text)
        if is_bot:
            try:
                await self.bot.send_chat(sender=self.bot.user, message=f"/ban {payload.user.display_name} Automated ban by bot for suspected bot/scammer/spammer activity.")
                print(f"Banned user {payload.user.display_name} for suspected bot/scammer/spammer activity.")
            except Exception as e:
                print(f"Failed to ban user {payload.user.display_name}: {e}")

    async def toggle_shared_chat(self, shared: bool) -> None:
        debug_print("CommandHandler", f"Toggling Shared Chat mode to {'enabled' if shared else 'disabled'}.")
        self.shared_chat = shared
        if shared:
            unregister_all_commands()
            if not self.message_timer:
                self.message_timer = get_reference("MessageScheduler")
            self.message_timer.set_shared_chat(True)
            chat_response_enabled = await get_setting("Chat Response Enabled", False)
            if chat_response_enabled:
                if not self.response_manager:
                    self.response_manager = get_reference("ResponseTimer")
                await self.response_manager.end_timer()
        else:
            register_all_commands()
            if not self.message_timer:
                self.message_timer = get_reference("MessageScheduler")
            self.message_timer.set_shared_chat(False)
            chat_response_enabled = await get_setting("Chat Response Enabled", False)
            if chat_response_enabled:
                if not self.response_manager:
                    self.response_manager = get_reference("ResponseTimer")
                await self.response_manager.start_timer()

    async def handle_stream_online(self, payload: twitchio.StreamOnline) -> None:
        discord_integration = await get_setting("Discord Integration Enabled", default=False)
        if not discord_integration:
            return
        discord_announcements_enabled = await get_setting("Discord Announcements Enabled", default=False)
        if not discord_announcements_enabled:
            return
        stream_title =await self.bot.fetch_title()
        stream_game = await self.bot.get_current_game()
        if not self.discord_bot:
            self.discord_bot = get_reference("DiscordBot")
        if self.discord_bot:
            message = f"{payload.broadcaster.display_name} is now live on Twitch!\n\nTitle: {stream_title}\nGame: {stream_game if stream_game else 'Unknown'}\nWatch here: https://twitch.tv/{payload.broadcaster.name}"
            announcement_channel = await get_setting("Discord Announcement Channel ID", None)
            if announcement_channel:
                asyncio.create_task(self.discord_bot.send_message(channel_id=announcement_channel, message=message))

    @commands.Component.listener()
    async def event_message(self, payload: twitchio.ChatMessage) -> None:
        if not self.message_timer or self.message_timer.done():
            self.message_timer = asyncio.create_task(self.handle_message())
        self.message_queue.append(payload)

    @commands.Component.listener()
    async def event_cheer(self, payload: twitchio.ChannelCheer) -> None:
        debug_print("CommandHandler", f"Handling cheer from {payload.user.display_name}: {payload.bits} bits")
        if not self.custom_builder:
            self.custom_builder = CustomPointRedemptionBuilder()
            set_reference("PointBuilder", self.custom_builder)
        asyncio.create_task(self.custom_builder.handle_cheer(payload))

    @commands.Component.listener()
    async def event_channel_subscribe(self, payload: twitchio.ChannelSubscribe) -> None:
        debug_print("CommandHandler", f"Handling subscription from {payload.user.display_name}, gift: {payload.gift}")
        if payload.gift:
            self.assistant.recent_gifted_subscriptions.append(payload.user.display_name)
            return
        event = {"type": "sub", "user": payload.user.display_name, "event": payload}
        asyncio.create_task(self.assistant.generate_voiced_response(event))

    @commands.Component.listener()
    async def event_channel_subscribe_message(self, payload: twitchio.ChannelSubscriptionMessage) -> None:
        debug_print("CommandHandler", f"Handling resubscription from {payload.user.display_name}, months: {payload.months}")
        event = {"type": "resub", "user": payload.user.display_name, "event": payload}
        asyncio.create_task(self.assistant.generate_voiced_response(event))

    @commands.Component.listener()
    async def event_channel_subscription_end(self, payload: twitchio.ChannelSubscriptionEnd) -> None:
        debug_print("CommandHandler", f"User subscription ended: {payload.user.display_name}")
        event = {"type": "unsub", "user": payload.user.display_name, "event": payload}
        pass #Not implemented

    @commands.Component.listener()
    async def event_channel_follow(self, payload: twitchio.ChannelFollow) -> None:
        debug_print("CommandHandler", f"New follower: {payload.user.display_name}")
        event = {"type": "follow", "user": payload.user.display_name, "event": payload}
        pass #Not implemented

    @commands.Component.listener()
    async def event_channel_raid(self, payload: twitchio.ChannelRaid) -> None:
        debug_print("CommandHandler", f"Handling raid from {payload.from_broadcaster.display_name} with {payload.viewers} viewers")
        event = {"type": "raid", "user": payload.from_broadcaster.display_name, "event": payload}
        asyncio.create_task(self.assistant.generate_voiced_response(event))

    @commands.Component.listener()
    async def event_channel_gift_subscription(self, payload: twitchio.ChannelSubscriptionGift) -> None:
        debug_print("CommandHandler", f"Handling gifted subscription from {payload.user.display_name}.")
        event = {"type": "gift", "user": payload.user.display_name, "event": payload}
        asyncio.create_task(self.assistant.generate_voiced_response(event))

    @commands.Component.listener()
    async def event_channel_points_auto_redeem_v2(self, payload: twitchio.ChannelPointsAutoRedeemAdd) -> None:
        debug_print("CommandHandler", f"Handling channel points auto redeem from {payload.user.display_name} for reward {payload.reward.type}")
        asyncio.create_task(self.handle_custom_channel_points_redeems(payload))

    @commands.Component.listener()
    async def event_channel_points_redeem_add(self, payload: twitchio.ChannelPointsRedemptionAdd) -> None:
        debug_print("CommandHandler", f"Handling channel points redeem from {payload.user.display_name} for reward {payload.reward.title}")
        asyncio.create_task(self.handle_custom_channel_points_redeems(payload))

    @commands.Component.listener()
    async def event_suspicious_user_message(self, payload: twitchio.SuspiciousUserMessage) -> None:
        debug_print("CommandHandler", f"Suspicious message detected from {payload.user.display_name}: {payload.message.text}")
        asyncio.create_task(self.handle_suspicious_message(payload))

    @commands.Component.listener()
    async def event_shared_chat_session_begin(self, payload: twitchio.SharedChatSessionBegin) -> None:
        asyncio.create_task(self.toggle_shared_chat(shared=True))

    @commands.Component.listener()
    async def event_shared_chat_session_update(self, payload: twitchio.SharedChatSessionUpdate) -> None:
        debug_print("CommandHandler", "Updated Shared Chat mode.")
        pass #Not implemented

    @commands.Component.listener()
    async def event_shared_chat_session_end(self, payload: twitchio.SharedChatSessionEnd) -> None:
        asyncio.create_task(self.toggle_shared_chat(shared=False))

    @commands.Component.listener()
    async def event_stream_online(self, payload: twitchio.StreamOnline) -> None:
        debug_print("CommandHandler", f"Stream went online for broadcaster: {payload.broadcaster.display_name}")
        asyncio.create_task(self.handle_stream_online(payload))

    @commands.Component.listener()
    async def event_stream_offline(self, payload: twitchio.StreamOffline) -> None:
        debug_print("CommandHandler", f"Stream went offline for broadcaster: {payload.broadcaster.display_name}")
        pass #Not implemented

    @commands.Component.listener()
    async def event_charity_campaign_start(self, payload: twitchio.CharityCampaignStart) -> None:
        debug_print("CommandHandler", f"Charity campaign started for broadcaster: {payload.broadcaster.display_name}")
        pass #Not implemented

    @commands.Component.listener()
    async def event_charity_campaign_progress(self, payload: twitchio.CharityCampaignProgress) -> None:
        debug_print("CommandHandler", f"Charity campaign progress for broadcaster: {payload.broadcaster.display_name}")
        pass #Not implemented

    @commands.Component.listener()
    async def event_charity_campaign_stop(self, payload: twitchio.CharityCampaignStop) -> None:
        debug_print("CommandHandler", f"Charity campaign stopped for broadcaster: {payload.broadcaster.display_name}")
        pass #Not implemented

    @commands.Component.listener()
    async def event_goal_begin(self, payload: twitchio.GoalBegin) -> None:
        debug_print("CommandHandler", f"Goal began for broadcaster: {payload.broadcaster.display_name}")
        pass #Not implemented

    @commands.Component.listener()
    async def event_goal_progress(self, payload: twitchio.GoalProgress) -> None:
        debug_print("CommandHandler", f"Goal progress for broadcaster: {payload.broadcaster.display_name}")
        pass #Not implemented

    @commands.Component.listener()
    async def event_goal_end(self, payload: twitchio.GoalEnd) -> None:
        debug_print("CommandHandler", f"Goal ended for broadcaster: {payload.broadcaster.display_name}")
        pass #Not implemented

    @commands.Component.listener()
    async def event_hype_train_begin(self, payload: twitchio.HypeTrainBegin) -> None:
        debug_print("CommandHandler", f"Hype train began for broadcaster: {payload.broadcaster.display_name}")
        pass #Not implemented

    @commands.Component.listener()
    async def event_hype_train_progress(self, payload: twitchio.HypeTrainProgress) -> None:
        debug_print("CommandHandler", f"Hype train progress for broadcaster: {payload.broadcaster.display_name}")
        pass #Not implemented

    @commands.Component.listener()
    async def event_hype_train_end(self, payload: twitchio.HypeTrainEnd) -> None:
        debug_print("CommandHandler", f"Hype train ended for broadcaster: {payload.broadcaster.display_name}")
        pass #Not implemented

    @commands.Component.listener()
    async def event_channel_poll_begin(self, payload: twitchio.ChannelPollBegin) -> None:
        debug_print("CommandHandler", f"Channel poll began for broadcaster: {payload.broadcaster.display_name}")
        pass #Not implemented

    @commands.Component.listener()
    async def event_channel_poll_progress(self, payload: twitchio.ChannelPollProgress) -> None:
        debug_print("CommandHandler", f"Channel poll progress for broadcaster: {payload.broadcaster.display_name}")
        pass #Not implemented

    @commands.Component.listener()
    async def event_channel_poll_end(self, payload: twitchio.ChannelPollEnd) -> None:
        debug_print("CommandHandler", f"Channel poll ended for broadcaster: {payload.broadcaster.display_name}")
        pass #Not implemented

    @commands.Component.listener()
    async def event_channel_prediction_begin(self, payload: twitchio.ChannelPredictionBegin) -> None:
        debug_print("CommandHandler", f"Channel prediction began for broadcaster: {payload.broadcaster.display_name}")
        pass #Not implemented

    @commands.Component.listener()
    async def event_channel_prediction_progress(self, payload: twitchio.ChannelPredictionProgress) -> None:
        debug_print("CommandHandler", f"Channel prediction progress for broadcaster: {payload.broadcaster.display_name}")
        pass #Not implemented

    @commands.Component.listener()
    async def event_channel_prediction_lock(self, payload: twitchio.ChannelPredictionLock) -> None:
        debug_print("CommandHandler", f"Channel prediction locked for broadcaster: {payload.broadcaster.display_name}")
        pass #Not implemented

    @commands.Component.listener()
    async def event_channel_prediction_end(self, payload: twitchio.ChannelPredictionEnd) -> None:
        debug_print("CommandHandler", f"Channel prediction ended for broadcaster: {payload.broadcaster.display_name}")
        pass #Not implemented

    @commands.Component.listener()
    async def event_shield_mode_begin(self, payload: twitchio.ShieldModeBegin) -> None:
        debug_print("CommandHandler", f"Shield mode began for broadcaster: {payload.broadcaster.display_name}")
        pass #Not implemented

    @commands.Component.listener()
    async def event_shield_mode_end(self, payload: twitchio.ShieldModeEnd) -> None:
        debug_print("CommandHandler", f"Shield mode ended for broadcaster: {payload.broadcaster.display_name}")
        pass #Not implemented

    @commands.Component.listener()
    async def event_shoutout_create(self, payload: twitchio.ShoutoutCreate) -> None:
        debug_print("CommandHandler", f"Shoutout created by broadcaster: {payload.broadcaster.display_name}")
        pass #Not implemented

    @commands.Component.listener()
    async def event_shoutout_receive(self, payload: twitchio.ShoutoutReceive) -> None:
        debug_print("CommandHandler", f"Shoutout received by broadcaster: {payload.broadcaster.display_name}")
        pass #Not implemented

    @commands.Component.listener()
    async def event_automod_message_hold(self, payload: twitchio.AutomodMessageHold) -> None:
        debug_print("CommandHandler", f"AutoMod held message from {payload.user.display_name}: {payload.text}. Severity: {payload.level}. Reason: {payload.reason}")
        pass #Not implemented

    @commands.Component.listener()
    async def event_ad_break_begin(self, payload: twitchio.ChannelAdBreakBegin) -> None:
        debug_print("CommandHandler", f"Ad break began for broadcaster: {payload.broadcaster.display_name}")
        pass #Not implemented

    def _dispatch_whisper_payload(self, payload: twitchio.Whisper) -> None:
        debug_print("CommandHandler", f"Whisper received from user: {payload.sender.display_name}: {payload.text}")
        asyncio.create_task(self.handle_whisper(payload))

    @commands.Component.listener()
    async def event_whisper_received(self, payload: twitchio.Whisper) -> None:
        self._dispatch_whisper_payload(payload)

    @commands.Component.listener()
    async def event_message_whisper(self, payload: twitchio.Whisper) -> None:
        self._dispatch_whisper_payload(payload)

    @commands.Component.listener()
    async def event_command_error(self, *args) -> None:
        """Handle command errors dispatched by TwitchIO.

        TwitchIO may call this listener with either a single `error` arg or
        with `(ctx, error)`. This handler normalizes both forms, unwraps the
        framework's CommandErrorPayload if present, suppresses
        `CommandNotFound`, and logs other command errors.
        """
        ctx = None
        error = None
        payload = None

        # Normalize args: either (error,) or (ctx, error)
        try:
            if len(args) == 1:
                error = args[0]
            elif len(args) >= 2:
                ctx, error = args[0], args[1]
        except Exception:
            error = args[-1] if args else None

        # If twitchio passed a CommandErrorPayload-like object, try to unwrap it.
        try:
            if error is not None and "CommandErrorPayload" in error.__class__.__name__:
                payload = error
                inner = getattr(payload, "error", None) or getattr(payload, "exception", None) or getattr(payload, "exc", None) or getattr(payload, "original", None)
                if inner is not None:
                    error = inner
                try:
                    ctx = getattr(payload, "ctx", None) or getattr(payload, "context", None) or ctx
                except Exception:
                    pass
        except Exception:
            # If introspection fails, continue with whatever we have
            pass

        if error is None:
            return

        # Suppress CommandNotFound by class name to avoid noisy tracebacks
        try:
            if error.__class__.__name__ == "CommandNotFound":
                invoked = None
                try:
                    invoked = getattr(ctx, "invoked_with", None) or (getattr(ctx, "message", None) and getattr(ctx.message, "content", None)) or getattr(payload, "invoked_with", None)
                except Exception:
                    invoked = None
                debug_print("CommandHandler", f"Ignored CommandNotFound for {invoked}.")
                return
        except Exception:
            # In case of odd error objects, fall through and log them
            pass

        # Log other command-related errors for diagnostics
        try:
            debug_print("CommandHandler", f"Command error in context {ctx}: {error}")
        except Exception:
            try:
                print(f"Command error: {error}")
            except Exception:
                pass

    @commands.command(aliases=["so", "shout-out"])
    async def shoutout(self, ctx: commands.Context) -> None:
        if not self._is_moderator(ctx):
            print(f"{ctx.author.name} tried to use shoutout command without being a mod")
            return

        parts = ctx.message.text.split()
        if len(parts) < 2:
            print("Shoutout command called without a username")
            return

        target_username = parts[1].lstrip("@").lower()

        try:
            users = await self.bot.fetch_users(logins=[target_username])

            if not users:
                print(f"Could not find user: {target_username}")
                return

            target_user = users[0]

            channel = getattr(ctx, "channel", None) or (getattr(ctx, "message", None) and getattr(ctx.message, "channel", None))
            if channel is None or not hasattr(channel, "name"):
                print("Could not determine the channel name.")
                return

            # Fetch target user's channel info and current game using the existing objects.
            channel_info = await target_user.fetch_channel_info()
            game = await channel_info.fetch_game()
            response = (
                f"Shoutout to {target_user.display_name}! Check out their channel at https://twitch.tv/{target_user.name} "
                f"and give them a follow! They were last seen streaming {game or 'absolutely nothing.'}"
            )

            await ctx.send(response)
        except Exception as e:
            print(f"An error occurred while trying to perform the shoutout: {e}")


    @commands.command()
    async def quote(self, ctx: commands.Context) -> None:
        #!quote add <quote text>
        #!quote random
        #!quote r
        #!quote <word>
        #!quote <id>
        if self.shared_chat:
            if not await get_setting("Shared Chat Commands Enabled", default=False):
                debug_print("CommandHandler", "Quote command ignored due to Shared Chat mode.")
                return
        parts = ctx.message.text.split(maxsplit=2)
        if len(parts) < 2:
            await ctx.send("Usage: !quote add <quote text> | !quote random | !quote <id> | !quote <word>")
            return
        if parts[1].lower() == "add":
            if len(parts) < 3:
                await ctx.send("Please provide the quote text to add.")
                return
            quote_text = parts[2].strip()
            if not quote_text:
                await ctx.send("Quote text cannot be empty.")
                return
            author = getattr(ctx, "author", None)
            user = author.name if author and hasattr(author, "name") else "Unknown"
            quote_id = add_quote(user, quote_text)
            await ctx.send(f"Quote added with ID #{quote_id}.")
            return
        elif parts[1].lower() in ("random", "r"):
            quote = get_random_quote()
            if not quote:
                await ctx.send("No quotes exist.")
                return
            await ctx.send(f"Quote #{quote["ID"]}: \"{quote["Quote"]}\" - Added on {quote["Date Added"]} during a {quote["Category"]} stream.")
            return
        else:
            identifier = parts[1].strip()
            if identifier.isdigit():
                quote_id = int(identifier)
                quote = get_quote(quote_id)
                if not quote:
                    await ctx.send(f"No quote found with ID #{quote_id}.")
                    return
                await ctx.send(f"Quote #{quote["ID"]}: \"{quote["Quote"]}\" - Added on {quote["Date Added"]} during a {quote["Category"]} stream.")
                return
            else:
                word = identifier
                quote = get_random_quote_containing_word(word)
                if not quote:
                    await ctx.send(f"No quotes found containing the word '{word}'.")
                    return
                await ctx.send(f"Quote #{quote["ID"]}: \"{quote["Quote"]}\" - Added on {quote["Date Added"]} during a {quote["Category"]} stream.")
                return


    #@commands.command(aliases=list(CUSTOM_COMMANDS.keys()))
    async def custom(self, ctx: commands.Context) -> None:
        # Determine the alias the user invoked (e.g. 'test') — ctx.command.name is the handler name.
        if self.shared_chat:
            if not await get_setting("Shared Chat Commands Enabled", default=False):
                debug_print("CommandHandler", "Custom commands ignored due to Shared Chat mode.")
                return
        debug_print("CommandHandler", f"Custom commands method entered! Context: {ctx}")
        invoked = getattr(ctx, "invoked_with", None) or getattr(ctx.command, "name", None)
        if invoked is None:
            invoked = ctx.command.name
        key = invoked.lower()

        spec = self.bot.custom_commands.get(key)
        # Backwards compatibility: allow plain string responses
        if isinstance(spec, str):
            spec = {"response": spec, "mod_only": False, "sub_only": False}

        if not spec:
            await ctx.send(f"Command '{invoked}' not found.")
            return

        # Enforce mod/sub restrictions
        if spec.get("mod_only") and not self._is_moderator(ctx):
            print(f"{ctx.author.name} tried to use mod-only command {invoked}")
            return

        # Allow moderators (and broadcaster) to use subscriber-only commands as well.
        if spec.get("sub_only") and not (self._is_subscriber(ctx) or self._is_moderator(ctx)):
            print(f"{ctx.author.name} tried to use sub-only command {invoked}")
            return
        
        response = self.command_builder(ctx, spec.get("response", ""))

        if spec.get("reply_to_user"):
            await ctx.reply(response)
            return

        await ctx.send(response)


BOT: Bot = None

def register_all_commands() -> None:
    debug_print("CommandHandler", "Registering all custom commands.")
    handler: CommandHandler = get_reference("CommandHandler")
    if handler:
        for command, spec in handler.bot.custom_commands.items():
            handler.register_custom_command(command, spec)

def unregister_all_commands() -> None:
    debug_print("CommandHandler", "Unregistering all custom commands.")
    handler: CommandHandler = get_reference("CommandHandler")
    if handler:
        for command in list(handler.bot.custom_commands.keys()):
            handler.unregister_custom_command(command)

def add_command(command, response, sub_only, mod_only, reply_to_user) -> None:
    debug_print("CommandHandler", f"Adding command: {command}")
    twitch_bot = get_reference("TwitchBot")
    twitch_bot.custom_commands.update({command: {"response": response, "mod_only": mod_only, "sub_only": sub_only, "reply_to_user": reply_to_user}})

    handler: CommandHandler = get_reference("CommandHandler")
    if handler:
        handler.register_custom_command(command, twitch_bot.custom_commands[command])
    
def remove_command(command) -> None:
    debug_print("CommandHandler", f"Removing command: {command}")
    twitch_bot = get_reference("TwitchBot")
    twitch_bot.custom_commands.pop(command, None)
    handler: CommandHandler = get_reference("CommandHandler")
    if handler:
        handler.unregister_custom_command(command)

def testing() -> None:
    debug_print("TwitchBot", "Testing function called.")
    pass

def main() -> None:
    async def runner() -> None:
        data_dir = os.path.join(os.path.dirname(__file__), "data")
        os.makedirs(data_dir, exist_ok=True)
        db_path = os.path.join(data_dir, "maddieply.db")
        bot_id = os.getenv("BOT_ID", "").strip()
        if not bot_id:
            raise ValueError("BOT_ID environment variable is not set.")

        async with asqlite.create_pool(db_path) as tdb:
            tokens, subs = await setup_database(tdb, bot_id)
            await set_debug(await get_setting("Debug Mode", "False"))
            try:
                await setup_gpt_manager()
            except Exception as e:
                debug_print("AutoBot", f"[ERROR] Failed to run setup_gpt_manager(): {e}")
            prefix = await get_setting("Command Prefix", "!")

            async with Bot(database=tdb, subs=subs, prefix=prefix) as bot:
                for pair in tokens:
                    await bot.add_token(*pair)
                set_reference("TwitchBot", bot)
                await bot.start(load_tokens=False)

    try:
        asyncio.run(runner())
    except KeyboardInterrupt:
        debug_print("AutoBot", "Shutting down due to KeyboardInterrupt")

if __name__ == "__main__":
    main()