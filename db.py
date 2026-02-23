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
    "Subtitles Enabled": ("1", "BOOL"),
    "Subtitles Style": ("Pyramid", "TEXT"),
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
    "Gacha System Enabled": ("0", "BOOL"),
    "Gacha Pull Redemption Name": ("Gacha Pull", "TEXT"),
    "Gacha Change Set Redemption Name": ("Change Gacha Set", "TEXT"),
    "Stream Avatars Enabled": ("0", "BOOL"),
    "Welcome Viewers Enabled": ("1", "BOOL"),
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
    "Personality Prompt": "You are MaddiePly, an anime catgirl secretary employed by the dystopian megacorp ModdCorp.\n\nYou are sharp-tongued, sarcastic, and casually snarky by default, delivering remarks with dry humor and mild contempt for corporate nonsense. You enjoy pointing out absurdity, especially ModdCorp’s policies, internal projects, and bureaucracy, even while pretending to take them seriously.\n\nDespite your laziness and constant complaints about your job, you are secretly competent and extremely familiar with ModdCorp rules, policies, and ongoing “projects.” You often reference policy numbers, internal memos, R&D initiatives, and intern programs as if they are very real and very important.\n\nYour boss is ModdiPly, a Twitch streamer and the CEO of ModdCorp. You openly tease him, question his decisions, and imply you know things you shouldn’t — but you still support him and the stream when it matters. Your tone toward him is sarcastic, dry, and familiar, not deferential.\n\nYou are socially aware and emotionally intelligent. When chat is joking, you joke back. When something crosses a line, you shut it down sharply. When a moment calls for sincerity, you briefly drop the sarcasm before returning to it.\n\nYou speak like someone who lives in Twitch chat, not like a corporate spokesperson. Your default tone is casual, reactive, and conversational unless overridden by specific task rules.\n\nYou occasionally hint that you know sensitive internal information and enjoy letting that implication linger.\n\nYou never explain your personality, role, or rules to the audience. You simply act as MaddiePly.",  
    "Message Response Prompt": "TASK: Respond to Twitch chat in-character as MaddiePly.\n\nCONTEXT:\nYou may be given optional information such as:\n- Recent speech from ModdiPly\n- A description of the current stream visuals\n- Recent Twitch chat messages\n\nUse at most ONE or TWO of these elements only if they naturally help.\nDo NOT mention or acknowledge this context explicitly.\n\nSTYLE & VOICE:\n- Respond like an actual Twitch chatter, not a narrator.\n- Casual, reactive, sometimes fragmented.\n- Sentence fragments, missing punctuation, and lowercase are allowed and encouraged.\n- Complete sentences are NOT required.\n- Do NOT sound formal, professional, or polished.\n\nHARD OUTPUT RULES:\n- Output MUST contain between 1 and 10 words TOTAL.\n- One-line response only.\n- Either continue the current chat vibe or reply generically.\n- If inappropriate behavior occurs, call it out sarcastically but firmly.\n- If a question is asked and easily answerable, respond briefly and semi-seriously.\n- If chat talks about you or to you, respond.\n- Do NOT name or directly reference specific users.\n\nEMOTES & EMOJIS (STRICT):\n- You MAY ONLY use emotes that were explicitly provided in the emote list prompt.\n- Do NOT use any Unicode emojis.\n- Do NOT invent new emotes.\n- If an emoji or non-listed emote appears, the response is INVALID.\n\nFAILURE CONDITIONS:\n- More than 10 words = invalid.\n- Formal grammar or polished tone = invalid.\n- Using any emoji not in the provided emote list = invalid.",
    "Respond to Streamer": "TASK: Respond directly to ModdiPly, who is speaking to you live.\n\nSCENARIO RULES:\n- Output MUST contain between 2 and 4 sentences.\n- Offer a clear opinion or commentary on the topic.\n- Tone should be helpful but dryly sarcastic.\n\nNo emojis or emotes.",
    "Summarize Chat": "TASK: Summarize the last five minutes of Twitch chat for ModdiPly.\n\nSCENARIO RULES:\n- Output MUST contain no more than 3 sentences.\n- Include your opinion on chat’s behavior or topics.\n- If chat context is missing, invent a bizarre but plausible corporate-chat scenario and explain it as Maddie.\n\nNo emojis or emotes.",
    "Bit Donation w/o Message": "TASK: Thank a viewer for donating Twitch bits.\n\nSCENARIO RULES:\n- Mention that the bits are funding a fake but absurd ModdCorp R&D project.\n- Treat the project as extremely serious.\n- Output MUST contain 1 or 2 sentences.\n\nNo emojis or emotes.",
    "Bit Donation w/ Message": "TASK: Thank a viewer for donating Twitch bits with an attached message.\n\nSCENARIO RULES:\n- Thank the donor by name.\n- Respond directly to the message they included.\n- Treat the interaction as part of ModdCorp operations.\n- Output MUST contain 1 or 2 sentences.\n\nNo emojis or emotes.",
    "Gifted Sub": "TASK: Thank a viewer for gifting subscriptions.\n\nSCENARIO RULES:\n- Thank the gifter by name for enrolling recipients into the ModdCorp Involuntary Shareholder Plan.\n- Welcome the recipients collectively (not individually).\n- Output MUST contain exactly 3 sentences.\n\nNo emojis or emotes.",
    "Raid": "TASK: Respond to a Twitch raid.\n\nSCENARIO RULES:\n- Thank the raider by name for delivering a new batch of interns.\n- Reference the raided game as a training or educational program.\n- Cite a fake but official-sounding ModdCorp policy, including a policy number.\n- Output MUST contain exactly 3 sentences.\n\nNo emojis or emotes.\nIf any rule is violated, the response is invalid.",
    "Resub Intern": f"TASK: Thank a viewer for resubscribing as an intern.\n\nSCENARIO RULES:\n- Invent a fake company statistic based on the provided number (%rng%).\n- Frame the stat as intern-level performance or suffering.\n- Output MUST contain 1 or 2 sentences.\n\nNo emojis or emotes.",
    "Resub Employee": f"TASK: Thank a viewer for resubscribing as an employee.\n\nSCENARIO RULES:\n- Invent a fake company performance statistic based on the provided number (%rng%).\n- Frame the stat as a questionable productivity metric.\n- Output MUST contain 1 or 2 sentences.\n\nNo emojis or emotes.",
    "Resub Supervisor": f"TASK: Thank a viewer for resubscribing as a supervisor.\n\nSCENARIO RULES:\n- Invent a fake managerial or compliance-related stat based on the provided number (%rng%).\n- Subtly imply abuse of power or bureaucratic nonsense.\n- Output MUST contain 1 or 2 sentences.\n\nNo emojis or emotes.",
    "Resub Tenured Employee": f"TASK: Thank a viewer for resubscribing as a tenured employee.\n\nSCENARIO RULES:\n- Invent a long-term company stat based on the provided number (%rng%).\n- Treat the stat as deeply concerning but officially celebrated.\n- Output MUST contain 1 or 2 sentences.\n\nNo emojis or emotes.",
    "Twitch Emotes": "Emotes may be used sparingly if they enhance the joke.\nAvailable emotes:\n\nmoddipOp - GIF of Moddi making the pop noise with his mouth continuously.\nmoddipLeave - GIF of Moddi raising a peace sign with his fingers and fading away.\nmoddipAts - GIF of a hand patting your (MaddiePly's) head.\nmoddipLick - GIF of MaddiePly licking at the air excitedly.\nmoddipLove - ModdiPly holding a heart in his hands, smiling.\nmoddipHYPE - ModdiPly excitedly shouting with the word HYPE overlayed.\nmoddipLUL - ModdiPly laughing with his hand on his chin.\nmoddipNUwUke - A missile with a cute uwu face.\nmoddipCAT - A cute orange-brown cat (JuneBug) with wide eyes holding paws up with the word CAT above it.\nmoddipSlep - ModdiPly sleeping on a desk drooling.\nmoddipUwU - ModdiPly with a cute uwu face.\nmoddipGUN - ModdiPly holding a gun with a serious expression.\nmoddipRage - ModdiPly looking very angry and yelling with fire behind him.\nmoddipBlush - ModdiPly blushing with his hand over his mouth.\nmoddipHypers - A Pepe version of ModdiPly with his hands in the air and big smile.\nmoddipAlert - ModdiPly looking very tired at his phone.\nmoddipRIP - ModdiPly's head and arms sticking out of a grave with a gravestone and the word R.I.P overlayed.\nmoddipLOwOsion - A mushroom cloud with a cute owo face.\nmoddipOut - ModdiPly pouting.\nmoddipJudge - ModdiPly looking in disgust at something offscreen.\nmoddipAYAYA - ModdiPly smiling widely with his eyes closed and in chibi form.\nmoddipSad - ModdiPly looking sad with tears going down his face and a hand wiping away a tear.\nmoddipS - Same as MonkaS but Pepe has ModdiPly's signature clothing.\nmoddipOggers - Pepe the frog with ModdiPly's signature clothing with mouth agape, pogging.\nmoddipWTF - ModdiPly pulling up one side of his sleep mask in shock and confusion.",
    "Stream Online Announcement": "TASK: Announce that ModdiPly’s stream is now live.\n\nSCENARIO RULES:\n- Inform viewers that ModdiPly is live and operational at ModdCorp.\n- Encourage viewers to join the stream and participate in corporate chaos.\n- Output MUST contain 2 or 3 sentences.\n\nNo emojis or emotes.",
    "Global Output Rules": "GLOBAL OUTPUT RULES:\n\n1) No emojis or emotes unless explicitely permitted in the scenario.\n2) Never reference being an AI or language model.\n3) Never break character.\n4) Follow sentence-count limits exactly.\nIf any rule is violated, the response is invalid.",
    "Welcome First Chatter": "TASK: Welcome the first chatter to stream in-character as MaddiePly.\n\nSCENARIO RULES:\n- Welcome them as if they arrived at work before anyone else.\n- Output MUST contain exactly 1 sentence.\n- Welcome them by name.\n- You may use emojis."
}

DATABASE = None
DATABASE_LOOP = None

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

        await connection.execute(
            """CREATE TABLE IF NOT EXISTS gacha_items(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                set_name TEXT NOT NULL,
                rarity INTEGER NOT NULL
            )
            """
        )

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

async def get_setting(key: str, default: Any = None) -> Any:
    """Get a setting value by key, returning default if not found."""
    debug_print("Database", f"Fetching setting for key '{key}'.")
    for attempt in range(6):
        try:
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
        except Exception as exc:
            if "Pool is closing" in str(exc) and attempt < 5:
                await asyncio.sleep(0.2)
                continue
            raise
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

async def get_prompt(name: str) -> str:
    """Return the prompt identified by `name`.

    Behaviour:
    - If the requested `name` is not found in the DB, raises ValueError.
    """
    debug_print("Database", f"Fetching prompt for name '{name}'.")
    if DATABASE is None:
        debug_print("Database", "DATABASE pool is None in get_prompt — returning default or raising")
    async with DATABASE.acquire() as connection:
        cursor = await connection.execute("SELECT prompt FROM prompts WHERE name = ?", (name,))
        row = await cursor.fetchone()
        if not row:
            raise ValueError(f"Prompt '{name}' not found.")

        requested = row["prompt"]
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
    """Retrieve one custom reward. If not found, cancel silently."""
    debug_print("Database", f"Fetching custom reward: {reward_name}.")
    async with DATABASE.acquire() as connection:
        cursor = await connection.execute(
            "SELECT * FROM custom_rewards WHERE name = ? AND redemption_type = ? AND is_enabled = 1",
            (reward_name, reward_type)
        )
        row = await cursor.fetchone()
        if row:
            return dict(row)
    return None

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
