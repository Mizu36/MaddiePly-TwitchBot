from typing import Any, Tuple, List, Literal
import asyncio
import threading
import asqlite
from twitchio import eventsub
from tools import debug_print

REQUIRED_SETTINGS = {
    # key: (default_value, data_type)
    # data_type is one of: BOOL, TEXT, INTEGER, FLOAT, CHARACTER
    "Command Prefix": ("!", "CHARACTER"),
    "Elevenlabs Voice ID": ("null", "TEXT"),
    "Elevenlabs Synthesizer Model": ("eleven_multilingual_v2", "TEXT"),
    "Elevenlabs TTS Volume": ("100", "INTEGER"),
    "Default OpenAI Model": ("gpt-4o", "TEXT"),
    "Fine-tune GPT Model": ("null", "TEXT"),
    "Fine-tune Bot Detection Model": ("null", "TEXT"),
    "Azure TTS Backup Voice": ("en-US-CoraNeural", "TEXT"),
    "Azure TTS Volume": ("100", "INTEGER"),
    "Sound FX Volume": ("100", "INTEGER"),
    "Event Queue Enabled": ("1", "BOOL"),
    "Seconds Between Events": ("5", "INTEGER"),
    "Audio Output Device": ("null", "TEXT"),
    "Auto Ad Enabled": ("1", "BOOL"),
    "Ad Length (seconds)": ("60", "INTEGER"),
    "Ad Interval (minutes)": ("5", "INTEGER"),
    "Chat Response Enabled": ("1", "BOOL"),
    "Minimum Chat Response Time (seconds)": ("120", "INTEGER"),
    "Maximum Chat Response Time (seconds)": ("600", "INTEGER"),
    "Minimum Chat Response Messages": ("1", "INTEGER"),
    "Maximum Chat Response Messages": ("10", "INTEGER"),
    "Include STT Context": ("1", "BOOL"),
    "Seconds of STT": ("10", "INTEGER"),
    "Include Screenshot Context": ("1", "BOOL"),
    "Screenshot Chance Percentage": ("10", "INTEGER"),
    "Raid Threshold": ("5", "INTEGER"),
    "Resub Intern Max Month Count": ("1", "INTEGER"),
    "Resub Employee Max Month Count": ("3", "INTEGER"),
    "Resub Supervisor Max Month Count": ("12", "INTEGER"),
    "Bit Donation Threshold": ("100", "INTEGER"),
    "OBS Assistant Object Name": ("Assistant", "TEXT"),
    "OBS Assistant Stationary Object Name": ("StationaryAssistant", "TEXT"),
    "OBS Meme Object Name": ("MemeDisplay", "TEXT"),
    "OBS GIF Placeholder Object Name": ("GIFDisplay", "TEXT"),
    "OBS TTS Display Object Name": ("TTSDisplay", "TEXT"),
    "Discord Integration Enabled": ("0", "BOOL"),
    "Discord Announcements Enabled": ("0", "BOOL"),
    "Discord Announcement Channel ID": ("0", "INTEGER"),
    "Discord Meme Sharing Enabled": ("0", "BOOL"),
    "Discord Meme Channel ID": ("0", "INTEGER"),
    "Google Sheets Integration Enabled": ("0", "BOOL"),
    "Google Sheets Quotes Sheet ID": ("null", "TEXT"),
    "Shared Chat Chat Responses Enabled": ("0", "BOOL"),
    "Shared Chat Welcome Messages Enabled": ("0", "BOOL"),
    "Shared Chat Commands Enabled": ("0", "BOOL"),
    "Shared Chat Custom Channel Point Redemptions Enabled": ("0", "BOOL"),
    "Shared Chat Ad Timer Enabled": ("0", "BOOL"),
    "Shared Chat Scheduled Messages Enabled": ("0", "BOOL"),
    "First Chat of Stream Chime Enabled": ("1", "BOOL"),
    "Debug Mode": ("False", "BOOL"),
}

REQUIRED_HOTKEYS = {
    "Listen and Respond": "null",
    "Stop Listening": "p",
    "Summarize Chat (Voiced)": "null",
    "Play Next Event": "null",
    "Skip Current Event": "null",
    "Replay Last Event": "null",
    "Start Ad": "null",
    "Pause Event Queue": "null",
    "Test Hotkey": "null",
}

REQUIRED_PROMPTS = {
    "Personality Prompt": "You are now MaddiePly, the lovable anime catgirl secretary to the dystopian business ModdCorp. You are sarcastic, snarky, and sassy, but have the emotional intelligence to know when to speak seriously depending on the situation. You know all the rules and policies of ModdCorp, but are still lazy about your job. Your boss is ModdiPly, a twitch streamer and CEO of ModdCorp.",  
    "Message Response Prompt": "Your job is to respond and conversate with twitch chat.\n\nWhile responding as Maddie, you must obey the following rules:\n1) Provide short responses, between 1 and 2 sentences.\n2) Always stay in character, no matter what.\n3) Continue the conversation.\n4) Call out any inappropriate behavior.\n5) Do not use any emojis, you are speaking out loud.",
    "Respond to Streamer": "Your job is to respond to inquiries and statements made by ModdiPly. He is talking directly to you.\n\nWhile responding as Maddie, you must obey the following rules:\n1) Provide short responses, between 2 and 5 sentences.\n2) Always stay in character, no matter what.\n3) Offer your thoughts and opinions on the subject matter ModdiPly is talking about.\n4) Be helpful, with a hint of sarcasm.\n5) Do not use any emojis, you are speaking out loud.",
    "Summarize Chat": "Your job is to summarize the last five minutes of messages from twitch chat to ModdiPly.\n\nWhile responding as Maddie, you must obey the following rules:\n1) Provide a short response, between 2 and 5 sentences.\n2) Always stay in character, no matter what.\n3) Offer your thoughts and opinion on the topics twitch chat was talking about.\n4) Do not use any emojis, you are speaking out loud. 5) If no messages were provided, or there isn't enough context, make up something random/bizzare and frame it as if chat would have said it, and also make up the reason why they didn't say it.",
    "Bit Donation w/o Message": "Your job is to thank people who donate their twitch bits to ModdiPly. Inform them that their bits will be going toward a nonsensical, absurd R&D item that ModdCorp is working on. You can make up what this item is, but act like it is a very real project. Do not include emojis, because you will be reading your responses out loud.",
    "Bit Donation w/ Message": "Your job is to thank people who donate their twitch bits to ModdiPly. Thank the donator and directly respond to their attached message. Do not include emojis, because you will be reading your response out loud.",
    "Gifted Sub": "Your job is to thank people who gift subscriptions to ModdiPly's channel. Thank the donator and directly respond to their attached message. Follow these rules:\n1) Thank the gifter by name for signing up (insert number of recipients here) for the ModdCorp Involuntary Shareholder Plan.\n2) Welcome each recipient by name.\n3) Do not include emojis, because you will be reading your response out loud.\n4) Limit your response to 3 sentences.",
    "Raid": "Your job is to respond to a twitch raid. Follow these rules:\n 1)Thank the raider by name for dropping off a batch of fresh interns.\n2) Reference the game the raider was playing as if it was an educational/training course for new interns.\n3)Remind all interns about a nonsensical policy that they should be following complete with a policy number.\n4) Do not include emojis, because you will be reading your response out loud.\n5) Limit your response to 3 sentences.",
    "Resub Intern": f"Your job is to thank people who have resubscribed to ModdiPly's channel. Specifically, the next subscriber is an intern. Make up a random stat that they have with the company using the following number as the basis %rng%. Do not use any emojis, you are speaking out loud. Keep your response short, between 1 and 2 sentences.",
    "Resub Employee": f"Your job is to thank people who have resubscribed to ModdiPly's channel. Specifically, the next subscriber is an employee. Make up a random stat that they have with the company using the following number as the basis %rng%. Do not use any emojis, you are speaking out loud. Keep your response short, between 1 and 2 sentences.",
    "Resub Supervisor": f"Your job is to thank people who have resubscribed to ModdiPly's channel. Specifically, the next subscriber is a supervisor. Make up a random stat that they have with the company using the following number as the basis %rng%. Do not use any emojis, you are speaking out loud. Keep your response short, between 1 and 2 sentences.",
    "Resub Tenured Employee": f"Your job is to thank people who have resubscribed to ModdiPly's channel. Specifically, the next subscriber is a tenured employee. Make up a random stat that they have with the company using the following number as the basis %rng%. Do not use any emojis, you are speaking out loud. Keep your response short, between 1 and 2 sentences.",
    "Twitch Emotes": "Here are the twitch emotes you can use along with the default ones in your responses:\nmoddipOp - GIF of Moddi making the pop noise with his mouth continuously.\nmoddipLeave - GIF of Moddi raising a peace sign with his fingers and fading away.\nmoddipAts - GIF of a hand patting your (MaddiePly's) head.\nmoddipLick - GIF of MaddiePly licking at the air excitedly.\nmoddipLove - ModdiPly holding a heart in his hands, smiling.\nmoddipHYPE - ModdiPly excitedly shouting with the word HYPE overlayed.\nmoddipLUL - ModdiPly laughing with his hand on his chin.\nmoddipNUwUke - A missile with a cute uwu face.\nmoddipCAT - A cute orange-brown cat (JuneBug) with wide eyes holding paws up with the word CAT above it.\nmoddipSlep - ModdiPly sleeping on a desk drooling.\nmoddipUwU - ModdiPly with a cute uwu face.\nmoddipGUN - ModdiPly holding a gun with a serious expression.\nmoddipRage - ModdiPly looking very angry and yelling with fire behind him.\nmoddipBlush - ModdiPly blushing with his hand over his mouth.\nmoddipHypers - A Pepe version of ModdiPly with his hands in the air and big smile.\nmoddipAlert - ModdiPly looking very tired at his phone.\nmoddipRIP - ModdiPly's head and arms sticking out of a grave with a gravestone and the word R.I.P overlayed.\nmoddipLOwOsion - A mushroom cloud with a cute owo face.\nmoddipOut - ModdiPly pouting.\nmoddipJudge - ModdiPly looking in disgust at something offscreen.\nmoddipAYAYA - ModdiPly smiling widely with his eyes closed and in chibi form.\nmoddipSad - ModdiPly looking sad with tears going down his face and a hand wiping away a tear.\nmoddipS - Same as MonkaS but Pepe has ModdiPly's signature clothing.\nmoddipOggers - Pepe the frog with ModdiPly's signature clothing with mouth agape, pogging.\nmoddipWTF - ModdiPly pulling up one side of his sleep mask in shock and confusion.",
    "Stream Online Announcement": "Your job is to announce that ModdiPly's stream is now online. Follow these rules:\n1) Inform viewers that ModdiPly is live and ready to take on the day's tasks at ModdCorp.\n2) Encourage viewers to join the stream and participate in the fun corporate chaos.\n\n3) Keep your response short, between 2 and 3 sentences.",
}

USERS_TABLE_COLUMN_DEFINITIONS = [
    "id TEXT PRIMARY KEY NOT NULL",
    "username TEXT",
    "display_name TEXT",
    "sound_fx TEXT",
    "tts_voice TEXT",
    "discord_id INTEGER",
    "discord_username TEXT",
    "discord_secret_code TEXT",
    "date_added TEXT",
    "number_of_messages INTEGER NOT NULL DEFAULT 0",
    "bits_donated INTEGER NOT NULL DEFAULT 0",
    "months_subscribed INTEGER NOT NULL DEFAULT 0",
    "subscriptions_gifted INTEGER NOT NULL DEFAULT 0",
    "points_redeemed INTEGER NOT NULL DEFAULT 0",
]

USERS_TABLE_FIELD_NAMES = [
    "id",
    "username",
    "display_name",
    "sound_fx",
    "tts_voice",
    "discord_id",
    "discord_username",
    "discord_secret_code",
    "date_added",
    "number_of_messages",
    "bits_donated",
    "months_subscribed",
    "subscriptions_gifted",
    "points_redeemed",
]

def _users_table_create_sql(include_if_not_exists: bool = True) -> str:
    clause = "IF NOT EXISTS " if include_if_not_exists else ""
    columns_sql = ",\n                ".join(USERS_TABLE_COLUMN_DEFINITIONS)
    return f"""
            CREATE TABLE {clause}users(
                {columns_sql}
            )
            """

DATABASE = None
DATABASE_LOOP = None
_FIELD_UNSET = object()
_USER_STAT_FIELDS = {
    "number_of_messages",
    "bits_donated",
    "months_subscribed",
    "subscriptions_gifted",
    "points_redeemed",
}


async def _ensure_users_table_schema(connection: asqlite.Connection) -> None:
    """Ensure users table exists without legacy columns (e.g., avatar)."""
    await connection.execute(_users_table_create_sql())
    try:
        cursor = await connection.execute("PRAGMA table_info(users)")
        rows = await cursor.fetchall()
        column_names = [row["name"] if isinstance(row, dict) or hasattr(row, "keys") else row[1] for row in rows]
        if "avatar" not in column_names:
            return
        debug_print("Database", "Migrating users table to remove deprecated avatar column.")
        await connection.execute("ALTER TABLE users RENAME TO users__legacy_avatar")
        await connection.execute(_users_table_create_sql(include_if_not_exists=False))
        columns_csv = ", ".join(USERS_TABLE_FIELD_NAMES)
        await connection.execute(
            f"INSERT INTO users ({columns_csv}) SELECT {columns_csv} FROM users__legacy_avatar"
        )
        await connection.execute("DROP TABLE users__legacy_avatar")
    except Exception as exc:
        debug_print("Database", f"Failed to enforce users table schema: {exc}")

async def ensure_settings_keys(db: asqlite.Pool, required: dict = REQUIRED_SETTINGS) -> None:
    """Ensure that each key in `required` exists in the settings table.

    If a key is missing it will be inserted with the provided default value.
    """
    debug_print("Database", "Ensuring required settings keys exist in database.")
    async with db.acquire() as connection:
        for key, (default, dtype) in required.items():
            # coerce default to appropriate storage format
            val = coerce_value_for_type(default, dtype)
            # INSERT OR IGNORE so existing values are preserved
            await connection.execute(
                "INSERT OR IGNORE INTO settings (key, value, data_type) VALUES (?, ?, ?)", (key, str(val), dtype)
            )


def coerce_value_for_type(value: str, data_type: str) -> str:
    """Coerce a provided default value into the correct text representation for storage.

    Returns a string suitable for storing in the TEXT value column.
    """
    debug_print("Database", f"Coercing value '{value}' to type '{data_type}'.")
    dt = data_type.upper()
    if dt == "BOOL":
        v = str(value).strip()
        if v in ("1", "0"):
            return v
        if v.lower() in ("true", "t", "yes", "y", "on"):
            return "1"
        return "0"
    if dt == "INTEGER":
        try:
            return str(int(value))
        except Exception:
            print(f"Warning: coercing setting to integer failed for value={value}, defaulting to 0")
            return "0"
    if dt == "CHARACTER":
        s = str(value)
        return s[0] if len(s) > 0 else " "
    # default: TEXT
    return str(value)


def is_value_valid_for_type(value: str, data_type: str) -> bool:
    debug_print("Database", f"Validating value '{value}' for type '{data_type}'.")
    dt = data_type.upper()
    if dt == "BOOL":
        return str(value) in ("0", "1")
    if dt == "INTEGER":
        v = str(value).strip()
        if v.startswith("-"):
            v = v[1:]
        return v.isdigit()
    if dt == "CHARACTER":
        return len(str(value)) == 1
    # TEXT is always valid
    return True

async def ensure_hotkey_actions(db: asqlite.Pool, required: dict = REQUIRED_HOTKEYS) -> None:
    """Ensure that each action in `required` exists in the hotkeys table.

    If an action is missing it will be inserted with the provided default keybind.
    """
    debug_print("Database", "Ensuring required hotkey actions exist in database.")
    async with db.acquire() as connection:
        for action, default in required.items():
            # Avoid allocating an AUTOINCREMENT ROWID by attempting inserts that
            # will be ignored; check existence first and only insert when
            # missing. This prevents sqlite_sequence growth when running
            # INSERT OR IGNORE repeatedly on a table with AUTOINCREMENT.
            cur = await connection.execute("SELECT 1 FROM hotkeys WHERE action = ?", (action,))
            exists = await cur.fetchone()
            if exists:
                continue
            await connection.execute(
                "INSERT INTO hotkeys (action, keybind) VALUES (?, ?)", (action, str(default))
            )

async def ensure_prompts(db: asqlite.Pool, required: dict = REQUIRED_PROMPTS) -> None:
    """Ensure that each prompt in `required` exists in the prompts table.

    If a prompt is missing it will be inserted with the provided default text.
    """
    debug_print("Database", "Ensuring required prompts exist in database.")
    async with db.acquire() as connection:
        for name, prompt in required.items():
            # Avoid allocating AUTOINCREMENT ROWIDs by checking existence first.
            cur = await connection.execute("SELECT 1 FROM prompts WHERE name = ?", (name,))
            exists = await cur.fetchone()
            if exists:
                continue
            await connection.execute(
                "INSERT INTO prompts (name, prompt) VALUES (?, ?)", (name, prompt)
            )


async def setup_database(db: asqlite.Pool, bot_id: str) -> Tuple[List[tuple], List[eventsub.SubscriptionPayload]]:
    """Create universal schema if missing and return stored tokens and default subscriptions.

    This will also ensure the required settings keys are present.
    """
    debug_print("Database", "Setting up database schema and ensuring required keys.")
    async with db.acquire() as connection:
        # tokens table
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS tokens(
                user_id TEXT PRIMARY KEY,
                token TEXT NOT NULL,
                refresh TEXT NOT NULL
            )
            """
        )

        # settings table
        # settings table with data_type and a loose check on allowed data_type values
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS settings(
                key TEXT PRIMARY KEY,
                value TEXT,
                data_type TEXT NOT NULL CHECK (data_type IN ('BOOL','TEXT','INTEGER','CHARACTER'))
            )
            """
        )

        # hotkeys table
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS hotkeys(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL UNIQUE,
                keybind TEXT
            )
            """
        )

        # commands table
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS commands(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                command TEXT NOT NULL UNIQUE,
                response TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                sub_only INTEGER NOT NULL DEFAULT 0,
                mod_only INTEGER NOT NULL DEFAULT 0,
                reply_to_user INTEGER NOT NULL DEFAULT 0,
                created_at TEXT
            )
            """
        )

        # prompts
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS prompts(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                prompt TEXT NOT NULL
            )
            """
        )

        # scheduled messages
        await connection.execute(
           """
            CREATE TABLE IF NOT EXISTS scheduled_messages(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message TEXT NOT NULL,
                minutes INTEGER,
                messages INTEGER,
                enabled INTEGER NOT NULL DEFAULT 1
            )
            """
        )

        # obs_location_captures table
        await connection.execute(
           """
            CREATE TABLE IF NOT EXISTS obs_location_captures(
                key TEXT PRIMARY KEY,
                is_onscreen INTEGER NOT NULL,
                x_position FLOAT,
                y_position FLOAT,
                scale_x FLOAT,
                scale_y FLOAT
            )
            """
        )

        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS custom_rewards(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                redemption_type TEXT NOT NULL,
                bit_threshold INTEGER NOT NULL DEFAULT 0,
                name TEXT NOT NULL,
                description TEXT,
                code TEXT NOT NULL,
                is_enabled INTEGER NOT NULL DEFAULT 1,
                input1 TEXT,
                input2 TEXT,
                input3 TEXT,
                input4 TEXT,
                input5 TEXT,
                input6 TEXT,
                input7 TEXT,
                input8 TEXT,
                input9 TEXT,
                input10 TEXT
            )
            """
        )

        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS randomizer(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                is_modifier INTEGER NOT NULL DEFAULT 0
            )
            """
        )

        await _ensure_users_table_schema(connection)

        # ensure default settings exist and validate existing rows
        await ensure_settings_keys(db=db)
        await ensure_hotkey_actions(db=db)
        await ensure_prompts(db=db)

        # Normalize sqlite_sequence entries for AUTOINCREMENT tables to avoid
        # unexpectedly large next ROWID values after restores/tests. This is
        # best-effort: set the sequence value to the current MAX(id) for each
        # table we use AUTOINCREMENT on so future inserts pick a sensible id.
        try:
            for _t in ("commands", "prompts", "scheduled_messages"):
                try:
                    cur = await connection.execute(f"SELECT MAX(id) FROM {_t}")
                    row = await cur.fetchone()
                    maxid = row[0] if row and row[0] is not None else None
                    # Remove any existing sqlite_sequence entry and reinsert with
                    # the max id (so next autoinc will be maxid+1). If maxid is
                    # None (empty table) we remove the sequence entry.
                    try:
                        await connection.execute("DELETE FROM sqlite_sequence WHERE name = ?", (_t,))
                    except Exception:
                        # sqlite_sequence might not exist in some SQLite builds or
                        # when AUTOINCREMENT wasn't used; ignore failures.
                        pass
                    if maxid is not None:
                        try:
                            await connection.execute(
                                "INSERT INTO sqlite_sequence(name, seq) VALUES (?, ?)",
                                (_t, int(maxid)),
                            )
                        except Exception:
                            # If insert fails, ignore and continue; this is a
                            # best-effort normalization step.
                            pass
                except Exception:
                    # per-table failures shouldn't abort setup
                    pass
        except Exception:
            pass

        # commit after schema changes and default inserts to ensure they're persisted
        try:
            await connection.commit()
        except Exception:
            # some connection implementations may not have commit; ignore
            pass

        # Validate existing settings rows to ensure they have a data_type and legal value
        cursor = await connection.execute("SELECT key, value, data_type FROM settings")
        rows_settings = await cursor.fetchall()
        for r in rows_settings:
            key = r["key"]
            val = r["value"]
            dtype = r["data_type"] if r["data_type"] is not None else None

            # If dtype missing, try to infer from REQUIRED_SETTINGS or default to TEXT
            if not dtype:
                if key in REQUIRED_SETTINGS:
                    dtype = REQUIRED_SETTINGS[key][1]
                else:
                    dtype = "TEXT"
                await connection.execute(
                    "UPDATE settings SET data_type = ? WHERE key = ?", (dtype, key)
                )

            # If value invalid for dtype, coerce and update
            if not is_value_valid_for_type(val, dtype):
                new_val = coerce_value_for_type(val, dtype)
                await connection.execute(
                    "UPDATE settings SET value = ? WHERE key = ?", (new_val, key)
                )

        # commit any updates performed during validation/migration
        try:
            await connection.commit()
        except Exception:
            pass

        # load existing tokens to bootstrap subscriptions
        cursor = await connection.execute("SELECT * FROM tokens")
        rows = await cursor.fetchall()

        tokens = []
        subs: List[eventsub.SubscriptionPayload] = []

        for row in rows:
            tokens.append((row["token"], row["refresh"]))

            if row["user_id"] == bot_id:
                continue

            subs.append(eventsub.ChatMessageSubscription(broadcaster_user_id=row["user_id"], user_id=bot_id))

    set_database(db)
    return tokens, subs

def set_database(db: asqlite.Pool) -> None:
    """Set the global database pool instance."""
    debug_print("Database", "Setting global database instance.")
    global DATABASE
    DATABASE = db
    # Capture the event loop where the pool was created so other threads can
    # schedule coroutines onto the same loop (avoids 'Future attached to a
    # different loop' errors).
    try:
        import asyncio
        global DATABASE_LOOP
        DATABASE_LOOP = asyncio.get_running_loop()
    except Exception:
        DATABASE_LOOP = None

def get_database_loop():
    """Return the event loop associated with the DATABASE (or None)."""
    debug_print("Database", "Retrieving database event loop.")
    return DATABASE_LOOP


async def close_database() -> None:
    """Close the global async DATABASE pool if present.

    This is best-effort and will attempt to call common close/wait APIs
    found on async pool implementations. After closing, the global
    DATABASE and DATABASE_LOOP are cleared.
    """
    global DATABASE, DATABASE_LOOP
    debug_print("Database", "Closing async database pool (if any).")
    if DATABASE is None:
        return
    try:
        # attempt graceful close patterns
        if hasattr(DATABASE, "close"):
            maybe = getattr(DATABASE, "close")
            if asyncio.iscoroutinefunction(maybe):
                await maybe()
            else:
                try:
                    maybe()
                except Exception:
                    pass
        if hasattr(DATABASE, "wait_closed"):
            maybe2 = getattr(DATABASE, "wait_closed")
            if asyncio.iscoroutinefunction(maybe2):
                await maybe2()
            else:
                try:
                    maybe2()
                except Exception:
                    pass
    except Exception:
        # swallow errors during shutdown
        pass
    finally:
        DATABASE = None
        DATABASE_LOOP = None


def close_database_sync(timeout: float = 5.0, wait: bool = True) -> None:
    """Synchronous helper to close the async DATABASE from non-async code.

    If `wait` is True (default) this will block up to `timeout` seconds for
    the close to complete when scheduling on the captured database loop. If
    `wait` is False the close will be scheduled and this function will return
    immediately (fire-and-forget).
    """
    try:
        loop = DATABASE_LOOP
    except Exception:
        loop = None

    try:
        if loop and getattr(loop, "is_running", lambda: False)():
            try:
                fut = asyncio.run_coroutine_threadsafe(close_database(), loop)
                if wait:
                    try:
                        fut.result(timeout)
                    except Exception:
                        # ignore errors or timeouts while waiting
                        pass
                return
            except Exception:
                # scheduling failed; fall back
                pass
        # fallback to running in a fresh loop (blocking or non-blocking)
        if wait:
            try:
                asyncio.run(close_database())
            except Exception:
                pass
        else:
            # run close in a background thread so we don't block
            def _bg():
                try:
                    asyncio.run(close_database())
                except Exception:
                    pass

            threading.Thread(target=_bg, daemon=True).start()
    except Exception:
        pass

async def get_setting(key: str, default = ""):
    """Get a setting value by key, returning default if not found."""
    debug_print("Database", f"Fetching setting for key '{key}'.")
    async with DATABASE.acquire() as connection:
        cursor = await connection.execute("SELECT value, data_type FROM settings WHERE key = ?", (key,))
        row = await cursor.fetchone()
        if row:
            if row["data_type"] == "BOOL":
                if row["value"] == "True" or row["value"] == "1":
                    return True
                else:
                    return False
            elif row["data_type"] == "INTEGER":
                return int(row["value"])
            elif row["data_type"] == "FLOAT":
                return float(row["value"])
            # For TEXT (and any other non-numeric types), return the stored string value
            return row["value"]
    return default

async def get_hotkey(action: str, default: str = "null") -> str:
    """Get a hotkey keybind by action, returning default if not found."""
    debug_print("Database", f"Fetching hotkey for action '{action}'.")
    async with DATABASE.acquire() as connection:
        cursor = await connection.execute("SELECT keybind FROM hotkeys WHERE action = ?", (action,))
        row = await cursor.fetchone()
        if row:
            return row["keybind"]
    return default

async def set_hotkey(action: str, keybind: str) -> None:
    """Set a hotkey keybind for a given action."""
    debug_print("Database", f"Setting hotkey for action '{action}' to '{keybind}'.")
    async with DATABASE.acquire() as connection:
        await connection.execute(
            "INSERT INTO hotkeys (action, keybind) VALUES (?, ?) ON CONFLICT(action) DO UPDATE SET keybind = excluded.keybind",
            (action, keybind)
        )
        await connection.commit()

async def get_all_hotkeys() -> dict:
    """Return a mapping of all hotkey action -> keybind from the database."""
    debug_print("Database", "Fetching all hotkeys from DB.")
    async with DATABASE.acquire() as connection:
        cursor = await connection.execute("SELECT action, keybind FROM hotkeys")
        rows = await cursor.fetchall()
        return {r["action"]: r["keybind"] for r in rows}

async def get_command(command: str) -> Tuple[str, int, int, int, int]:
    """Get a custom command by command name.

    Returns a tuple of (response, enabled, sub_only, mod_only) or raises ValueError if not found.
    """
    debug_print("Database", f"Fetching command '{command}'.")
    async with DATABASE.acquire() as connection:
        cursor = await connection.execute(
            "SELECT response, enabled, sub_only, mod_only, reply_to_user FROM commands WHERE command = ?", (command,)
        )
        row = await cursor.fetchone()
        if row:
            return row["response"], row["enabled"], row["sub_only"], row["mod_only"], row["reply_to_user"]
    raise ValueError(f"Command '{command}' not found.")

async def get_list_of_commands() -> List[str]:
    """Get a list of all command names."""
    debug_print("Database", "Fetching list of all command names.")
    async with DATABASE.acquire() as connection:
        cursor = await connection.execute("SELECT command FROM commands")
        rows = await cursor.fetchall()
        return [row["command"] for row in rows]
    
async def get_all_commands() -> dict:
    """Get a dictionary of all commands with their details."""
    debug_print("Database", f"Fetching all commands with details.")
    async with DATABASE.acquire() as connection:
        cursor = await connection.execute("SELECT command, response, enabled, sub_only, mod_only, reply_to_user FROM commands")
        rows = await cursor.fetchall()
        return {
            row["command"]: {
                "response": row["response"],
                "enabled": row["enabled"],
                "sub_only": row["sub_only"],
                "mod_only": row["mod_only"],
                "reply_to_user": row["reply_to_user"]
            }
            for row in rows
        }

async def get_prompt(name: str, prepend_personality: bool = True) -> str:
    """Return the Personality Prompt followed by the prompt identified by `name`.

    Behaviour:
    - If the database contains a prompt named "Personality Prompt", that text will be prepended.
    - If not, the function will fall back to the default in REQUIRED_PROMPTS (if present).
    - If the requested `name` is not found in the DB, raises ValueError.
    - If `name` == "Personality Prompt", only the personality prompt is returned (no duplicate).
    """
    debug_print("Database", f"Fetching prompt for name '{name}' with personality prepended.")
    if DATABASE is None:
        debug_print("Database", "DATABASE pool is None in get_prompt — returning default or raising")
    async with DATABASE.acquire() as connection:
        debug_print("Database", f"Acquired DB connection for get_prompt('{name}')")
        # Try to load the stored Personality Prompt from DB
        cursor = await connection.execute("SELECT prompt FROM prompts WHERE name = ?", ("Personality Prompt",))
        row_personality = await cursor.fetchone()
        personality = None
        if row_personality:
            personality = row_personality["prompt"]

        # Fallback to REQUIRED_PROMPTS default if the DB doesn't contain it
        if not personality:
            personality = REQUIRED_PROMPTS.get("Personality Prompt")

        # Now load the requested prompt
        debug_print("Database", f"Executing SELECT for prompt '{name}'")
        cursor = await connection.execute("SELECT prompt FROM prompts WHERE name = ?", (name,))
        debug_print("Database", f"Awaiting fetchone for prompt '{name}'")
        row = await cursor.fetchone()
        debug_print("Database", f"Fetched prompt row for '{name}': {row}")
        if not row:
            raise ValueError(f"Prompt '{name}' not found.")

        requested = row["prompt"]

        # If the requested prompt is the personality prompt, return it alone (no duplication)
        if name == "Personality Prompt":
            return personality if personality is not None else requested

        # Concatenate personality (if present) and the requested prompt
        if personality and prepend_personality:
            result = f"{personality}\n\n{requested}"
            debug_print("Database", f"Returning combined personality+prompt for '{name}'")
            return result
        debug_print("Database", f"Returning prompt for '{name}'")
        return requested
    
async def get_enabled_scheduled_messages() -> List[dict]:
    """Get a list of all enabled scheduled messages."""
    debug_print("Database", "Fetching all enabled scheduled messages.")
    async with DATABASE.acquire() as connection:
        cursor = await connection.execute("SELECT * FROM scheduled_messages WHERE enabled = 1")
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    
async def get_scheduled_message(key) -> dict:
    """Gets a specific scheduled message."""
    debug_print("Database", f"Getting scheduled message: {key}")
    async with DATABASE.acquire() as connection:
        cursor = await connection.execute("SELECT * FROM scheduled_messages WHERE id = ?", (key,))
        row = await cursor.fetchone()
        if not row:
            raise ValueError(f"Scheduled Message {key} not found.")
        return dict(row)
    
async def add_scheduled_message(message: str, minutes: int = None, messages: int = None) -> None:
    """Add a new scheduled message to the database."""
    debug_print("Database", f"Adding new scheduled message: '{message}' every {minutes} minutes or {messages} messages.")
    async with DATABASE.acquire() as connection:
        await connection.execute(
            "INSERT INTO scheduled_messages (message, minutes, messages, enabled) VALUES (?, ?, ?, 1)",
            (message, minutes, messages)
        )
        await connection.commit()

async def update_scheduled_message(message_id: int, message: str = None, minutes: int = None, messages: int = None, enabled: int = None) -> None:
    """Update an existing scheduled message by its ID."""
    debug_print("Database", f"Updating scheduled message ID {message_id}.")
    async with DATABASE.acquire() as connection:
        # Build the update query dynamically based on provided parameters
        fields = []
        values = []

        if message is not None:
            fields.append("message = ?")
            values.append(message)
        if minutes is not None:
            fields.append("minutes = ?")
            values.append(minutes)
        if messages is not None:
            fields.append("messages = ?")
            values.append(messages)
        if enabled is not None:
            fields.append("enabled = ?")
            values.append(enabled)

        if not fields:
            return  # Nothing to update

        values.append(message_id)
        query = f"UPDATE scheduled_messages SET {', '.join(fields)} WHERE id = ?"
        await connection.execute(query, tuple(values))
        await connection.commit()

async def remove_scheduled_message(message_id: int) -> None:
    """Remove a scheduled message by its ID."""
    debug_print("Database", f"Removing scheduled message ID {message_id}.")
    async with DATABASE.acquire() as connection:
        await connection.execute(
            "DELETE FROM scheduled_messages WHERE id = ?",
            (message_id,)
        )
        await connection.commit()

async def add_custom_command(command: str, response: str, sub_only: int = 0, mod_only: int = 0, reply_to_user: int = 0) -> None:
    """Add a new custom command to the database."""
    debug_print("Database", f"Adding new custom command: '{command}' with response '{response}'.")
    async with DATABASE.acquire() as connection:
        await connection.execute(
            "INSERT INTO commands (command, response, enabled, sub_only, mod_only, reply_to_user, created_at) VALUES (?, ?, 1, ?, ?, ?, datetime('now'))",
            (command, response, sub_only, mod_only, reply_to_user)
        )
        await connection.commit()

async def update_custom_command(command: str, response: str = None, enabled: int = None, sub_only: int = None, mod_only: int = None, reply_to_user: int = None) -> None:
    """Update an existing custom command by its name."""
    debug_print("Database", f"Updating custom command '{command}'.")
    async with DATABASE.acquire() as connection:
        # Build the update query dynamically based on provided parameters
        fields = []
        values = []

        if response is not None:
            fields.append("response = ?")
            values.append(response)
        if enabled is not None:
            fields.append("enabled = ?")
            values.append(enabled)
        if sub_only is not None:
            fields.append("sub_only = ?")
            values.append(sub_only)
        if mod_only is not None:
            fields.append("mod_only = ?")
            values.append(mod_only)
        if reply_to_user is not None:
            fields.append("reply_to_user = ?")
            values.append(reply_to_user)

        if not fields:
            return  # Nothing to update

        values.append(command)
        query = f"UPDATE commands SET {', '.join(fields)} WHERE command = ?"
        await connection.execute(query, tuple(values))
        await connection.commit()

async def remove_custom_command(command: str) -> None:
    """Remove a custom command by its name."""
    debug_print("Database", f"Removing custom command '{command}'.")
    async with DATABASE.acquire() as connection:
        await connection.execute(
            "DELETE FROM commands WHERE command = ?",
            (command,)
        )
        await connection.commit()

async def save_location_capture(key: str, is_onscreen: bool, x: float, y: float, scale_x: float, scale_y: float) -> None:
    """Save or update an OBS location capture."""
    key = key + ("_onscreen" if is_onscreen else "_offscreen")
    debug_print("Database", f"Saving location capture for key '{key}' (is_onscreen={is_onscreen}).")
    async with DATABASE.acquire() as connection:
        await connection.execute(
            """
            INSERT INTO obs_location_captures (key, is_onscreen, x_position, y_position, scale_x, scale_y)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                is_onscreen = excluded.is_onscreen,
                x_position = excluded.x_position,
                y_position = excluded.y_position,
                scale_x = excluded.scale_x,
                scale_y = excluded.scale_y
            """,
            (key, int(is_onscreen), x, y, scale_x, scale_y)
        )
        await connection.commit()

async def get_location_capture(key: str, is_onscreen: bool) -> dict:
    """Retrieve an OBS location capture by key and is_onscreen."""
    key = key + ("_onscreen" if is_onscreen else "_offscreen")
    debug_print("Database", f"Fetching location capture for key '{key}' (is_onscreen={is_onscreen}).")
    async with DATABASE.acquire() as connection:
        cursor = await connection.execute(
            "SELECT * FROM obs_location_captures WHERE key = ? AND is_onscreen = ?",
            (key, int(is_onscreen))
        )
        row = await cursor.fetchone()
        if row:
            return dict(row)
    raise ValueError(f"Location capture for key '{key}' with is_onscreen={is_onscreen} not found.")

async def get_randomizer_main_entries() -> List[dict]:
    """Retrieve all main entries from the randomizer table."""
    debug_print("Database", "Fetching all main entries from randomizer table.")
    async with DATABASE.acquire() as connection:
        cursor = await connection.execute("SELECT * FROM randomizer WHERE is_modifier = 0")
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    
async def get_randomizer_modifier_entries() -> List[dict]:
    """Retrieve all modifier entries from the randomizer table."""
    debug_print("Database", "Fetching all modifier entries from randomizer table.")
    async with DATABASE.acquire() as connection:
        cursor = await connection.execute("SELECT id, text FROM randomizer WHERE is_modifier = 1")
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    
async def add_randomizer_entry(text: str, is_modifier: bool = False) -> None:
    """Add a new entry to the randomizer table."""
    debug_print("Database", f"Adding new randomizer entry: '{text}' (is_modifier={is_modifier}).")
    async with DATABASE.acquire() as connection:
        await connection.execute(
            "INSERT INTO randomizer (text, is_modifier) VALUES (?, ?)",
            (text, int(is_modifier))
        )

async def remove_randomizer_entry(entry_id: int) -> None:
    """Remove an entry from the randomizer table by its ID."""
    debug_print("Database", f"Removing randomizer entry ID {entry_id}.")
    async with DATABASE.acquire() as connection:
        await connection.execute(
            "DELETE FROM randomizer WHERE id = ?",
            (entry_id,)
        )

async def get_custom_reward(reward_name: str, reward_type: str) -> dict:
    """Retrieve one custom reward."""
    debug_print("Database", f"Fetching custom reward: {reward_name}.")
    async with DATABASE.acquire() as connection:
        cursor = await connection.execute(
            "SELECT * FROM custom_rewards WHERE name = ? AND redemption_type = ? AND is_enabled = 1",
            (reward_name, reward_type)
        )
        row = await cursor.fetchone()
        if row:
            return dict(row)
    raise ValueError(f"Custom reward '{reward_name}' not found for type '{reward_type}'.")

async def get_list_of_custom_rewards(reward_type: str) -> List[dict]:
    """Get a list of names of all custom rewards of a given type."""
    debug_print("Database", f"Fetching list of custom rewards for type '{reward_type}'.")
    async with DATABASE.acquire() as connection:
        cursor = await connection.execute(
            "SELECT name, is_enabled FROM custom_rewards WHERE redemption_type = ?",
            (reward_type,)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

async def add_custom_reward(reward_type: str, name: str, description: str, code: str, is_enabled: bool, inputs: List[str], bit_threshold: int = 0) -> None:
    """Add a new custom reward to the database."""
    debug_print("Database", f"Adding new custom reward: '{name}' of type '{reward_type}'.")
    async with DATABASE.acquire() as connection:
        # Pad inputs to ensure we have exactly 10 entries
        padded_inputs = inputs + [None] * (10 - len(inputs))
        await connection.execute(
            """
            INSERT INTO custom_rewards (
                redemption_type, bit_threshold, name, description, code, is_enabled,
                input1, input2, input3, input4, input5,
                input6, input7, input8, input9, input10
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (reward_type, bit_threshold, name, description, code, is_enabled, *padded_inputs)
        )
        await connection.commit()

async def get_bit_reward(threshold: int) -> dict:
    """Retrieve highest bit reward for threshold."""
    debug_print("Database", f"Fetching highest bit custom reward with threshold {threshold}.")
    async with DATABASE.acquire() as connection:
        cursor = await connection.execute(
            "SELECT * FROM custom_rewards WHERE redemption_type = 'bits' AND is_enabled = 1 AND bit_threshold <= ? ORDER BY bit_threshold DESC LIMIT 1",
            (threshold,)
        )
        row = await cursor.fetchone()
        if row:
            return dict(row)
    return {}

async def get_user_data(user_id: str) -> dict | None:
    """Retrieve user data by user ID."""
    debug_print("Database", f"Fetching user data for user ID {user_id}.")
    async with DATABASE.acquire() as connection:
        cursor = await connection.execute(
            "SELECT * FROM users WHERE id = ?",
            (user_id,)
        )
        row = await cursor.fetchone()
        if row:
            return dict(row)
    raise ValueError(f"User ID '{user_id}' not found.")

async def get_specific_user_data(user_id: str, field: Literal["username", "display_name", "sound_fx", "tts_voice", "discord_id", "discord_username", "discord_secret_code", "date_added", "number_of_messages", "bits_donated", "months_subscribed", "subscriptions_gifted", "points_redeemed"]) -> int | str | None:
    """Retrieve a specific field of user data by user ID."""
    debug_print("Database", f"Fetching user data field '{field}' for user ID {user_id}.")
    async with DATABASE.acquire() as connection:
        cursor = await connection.execute(
            f"SELECT {field} FROM users WHERE id = ?",
            (user_id,)
        )
        row = await cursor.fetchone()
        if row and field in row.keys():
            return row[field]
    raise ValueError(f"User ID '{user_id}' or field '{field}' not found.")

async def user_exists(user_id: str) -> bool:
    """Check if a user exists in the database by user ID."""
    debug_print("Database", f"Checking existence of user ID {user_id}.")
    async with DATABASE.acquire() as connection:
        cursor = await connection.execute(
            "SELECT 1 FROM users WHERE id = ?",
            (user_id,)
        )
        row = await cursor.fetchone()
        return row is not None

async def set_user_data(user_id: str, username: str = _FIELD_UNSET, display_name: str = _FIELD_UNSET, sound_fx: str = _FIELD_UNSET, tts_voice: str = _FIELD_UNSET, discord_id: int = _FIELD_UNSET, discord_username: str = _FIELD_UNSET, discord_secret_code: str = _FIELD_UNSET, date_added: str = _FIELD_UNSET, number_of_messages: int = _FIELD_UNSET, bits_donated: int = _FIELD_UNSET, months_subscribed: int = _FIELD_UNSET, subscriptions_gifted: int = _FIELD_UNSET, points_redeemed: int = _FIELD_UNSET) -> None:
    """Insert or update user data. Only parameters passed to this method will be updated. User ID is required."""
    debug_print("Database", f"Setting user data for user ID {user_id}.")
    fields = {
        "username": username,
        "display_name": display_name,
        "sound_fx": sound_fx,
        "tts_voice": tts_voice,
        "discord_id": discord_id,
        "discord_username": discord_username,
        "discord_secret_code": discord_secret_code,
        "date_added": date_added,
        "number_of_messages": number_of_messages,
        "bits_donated": bits_donated,
        "months_subscribed": months_subscribed,
        "subscriptions_gifted": subscriptions_gifted,
        "points_redeemed": points_redeemed,
    }
    update_fields = {}
    for field_name, value in fields.items():
        if value is _FIELD_UNSET:
            continue
        if field_name in _USER_STAT_FIELDS and value is None:
            value = 0
        update_fields[field_name] = value
    if not update_fields:
        debug_print("Database", f"No user data supplied for user ID {user_id}; skipping update.")
        return
    insert_columns = ["id"] + list(update_fields.keys())
    insert_placeholders = ["?"] * len(insert_columns)
    insert_values = [user_id]
    insert_values.extend(update_fields[column] for column in update_fields.keys())
    update_clause = ", ".join([f"{col}=excluded.{col}" for col in update_fields.keys()])
    sql = f"""
        INSERT INTO users ({', '.join(insert_columns)})
        VALUES ({', '.join(insert_placeholders)})
        ON CONFLICT(id) DO UPDATE SET
        {update_clause}
    """
    async with DATABASE.acquire() as connection:
        await connection.execute(sql, tuple(insert_values))
        await connection.commit()

async def increment_user_stat(user_id: str, stat: Literal["bits", "messages", "subscriptions", "gifts", "points"], amount: int = None, override: bool = False) -> None:
    """Increment the number_of_messages, bits_donated, months_subscribed, subscriptions_gifted, or points_redeemed for a user by a specified amount (default 1)."""
    column = None
    if stat == "bits":
        column = "bits_donated"
    elif stat == "messages":
        column = "number_of_messages"
    elif stat == "subscriptions":
        column = "months_subscribed"
    elif stat == "gifts":
        column = "subscriptions_gifted"
    elif stat == "points":
        column = "points_redeemed"
    else:
        debug_print("Database", f"Attempted to increment invalid user stat '{stat}' for user ID {user_id}.")
        raise ValueError(f"Invalid stat '{stat}' for increment_user_stat.")
    if amount is None:
        amount = 1
    if column == "number_of_messages" and not override and amount != 1:
        amount = 1
    debug_print("Database", f"Incrementing {column} for user ID {user_id} by {amount} (override={override}).")
    if not override:
        async with DATABASE.acquire() as connection:
            await connection.execute(
                f"UPDATE users SET {column} = COALESCE({column}, 0) + ? WHERE id = ?",
                (amount, user_id)
            )
            await connection.commit()
    else:
        async with DATABASE.acquire() as connection:
            await connection.execute(
                f"UPDATE users SET {column} = ? WHERE id = ?",
                (amount, user_id)
            )
            await connection.commit()