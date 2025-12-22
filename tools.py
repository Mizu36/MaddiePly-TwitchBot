import datetime
import random
import sys
from pathlib import Path
from typing import Literal
DEBUG = False
_PROJECT_ROOT = Path(__file__).resolve().parent
TWITCH_BOT = None
COMMAND_HANDLER = None
TIMER = None
SCHEDULER = None
DISCORD_BOT = None
ELEVENLABS_MANAGER = None
SPEECH_TO_TEXT_MANAGER = None
ASSISTANT_MANAGER = None
EVENT_MANAGER = None
AUTOMOD = None
AUDIO_MANAGER = None
OBS_MANAGER = None
GPT_MANAGER = None
POINT_BUILDER = None
ONLINE_DATABASE = None
ONLINE_STORAGE = None
GACHA_HANDLER = None

def get_debug() -> bool:
    """Fetches the DEBUG setting from the database."""
    return DEBUG

async def set_debug(value) -> None:
    """Sets the global DEBUG variable for entire project"""
    global DEBUG
    if value in [True, "True", "true", 1, "1"]:
        DEBUG = True
    else:
        DEBUG = False

def debug_print(module_name: str = None, text: str = None):
    if not module_name or not text:
        print("debug_print called without required parameters.")
        return
    time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if text is None:
        text = "This module forgot to include the module name."
    if DEBUG:
        print(f"[{time}][DEBUG][{module_name}] {text}")

def get_random_number(min: int, max: int) -> int:
    return random.randint(min, max)

def get_random_from_list(items: list):
    if not items:
        return None
    return random.choice(items)

def get_app_root() -> Path:
    """Return the folder that holds runtime data (repo root when unfrozen, exe folder when bundled)."""
    if getattr(sys, "frozen", False):  # Running under PyInstaller/Freeze
        return Path(sys.executable).resolve().parent
    return _PROJECT_ROOT

def path_from_app_root(*parts: str) -> Path:
    """Join paths relative to the runtime root."""
    return get_app_root().joinpath(*parts)

def set_reference(name: str, reference) -> None:
    """Sets a global reference by name"""
    success = "successfully."
    if name == "TwitchBot":
        global TWITCH_BOT
        TWITCH_BOT = reference
        if not TWITCH_BOT:
            success = "to None."
    elif name == "ResponseTimer":
        global TIMER
        TIMER = reference
        if not TIMER:
            success = "to None."
    elif name == "DiscordBot":
        global DISCORD_BOT
        DISCORD_BOT = reference
        if not DISCORD_BOT:
            success = "to None."
    elif name == "ElevenLabsManager":
        global ELEVENLABS_MANAGER
        ELEVENLABS_MANAGER = reference
        if not ELEVENLABS_MANAGER:
            success = "to None."
    elif name == "SpeechToTextManager":
        global SPEECH_TO_TEXT_MANAGER
        SPEECH_TO_TEXT_MANAGER = reference
        if not SPEECH_TO_TEXT_MANAGER:
            success = "to None."
    elif name == "AssistantManager":
        global ASSISTANT_MANAGER
        ASSISTANT_MANAGER = reference
        if not ASSISTANT_MANAGER:
            success = "to None."
    elif name == "EventManager":
        global EVENT_MANAGER
        EVENT_MANAGER = reference
        if not EVENT_MANAGER:
            success = "to None."
    elif name == "AutoMod":
        global AUTOMOD
        AUTOMOD = reference
        if not AUTOMOD:
            success = "to None."
    elif name == "AudioManager":
        global AUDIO_MANAGER
        AUDIO_MANAGER = reference
        if not AUDIO_MANAGER:
            success = "to None."
    elif name == "OBSManager":
        global OBS_MANAGER
        OBS_MANAGER = reference
        if not OBS_MANAGER:
            success = "to None."
    elif name == "GPTManager":
        global GPT_MANAGER
        GPT_MANAGER = reference
        if not GPT_MANAGER:
            success = "to None."
    elif name == "PointBuilder":
        global POINT_BUILDER
        POINT_BUILDER = reference
        if not POINT_BUILDER:
            success = "to None."
    elif name == "MessageScheduler":
        global SCHEDULER
        SCHEDULER = reference
        if not SCHEDULER:
            success = "to None."
    elif name == "CommandHandler":
        global COMMAND_HANDLER
        COMMAND_HANDLER = reference
        if not COMMAND_HANDLER:
            success = "to None."
    elif name == "OnlineDatabase":
        global ONLINE_DATABASE
        ONLINE_DATABASE = reference
        if not ONLINE_DATABASE:
            success = "to None."
    elif name == "OnlineStorage":
        global ONLINE_STORAGE
        ONLINE_STORAGE = reference
        if not ONLINE_STORAGE:
            success = "to None."
    elif name == "GachaHandler":
        global GACHA_HANDLER
        GACHA_HANDLER = reference
        if not GACHA_HANDLER:
            success = "to None."
    debug_print("Tools", f"{name} reference set {success}")

def get_reference(name: Literal["TwitchBot", "ResponseTimer", "DiscordBot", "ElevenLabsManager", "SpeechToTextManager", "AssistantManager", "EventManager", "AutoMod", "AudioManager", "OBSManager", "GPTManager", "PointBuilder", "MessageScheduler", "CommandHandler", "OnlineDatabase", "OnlineStorage", "GachaHandler"]):
    """Gets a global reference by name"""
    if name == "TwitchBot":
        if not TWITCH_BOT:
            debug_print("Tools", "TwitchBot reference requested but not set.")
        return TWITCH_BOT
    elif name == "ResponseTimer":
        if not TIMER:
            debug_print("Tools", "ResponseTimer reference requested but not set.")
        return TIMER
    elif name == "DiscordBot":
        if not DISCORD_BOT:
            debug_print("Tools", "DiscordBot reference requested but not set.")
        return DISCORD_BOT
    elif name == "ElevenLabsManager":
        if not ELEVENLABS_MANAGER:
            debug_print("Tools", "ElevenLabsManager reference requested but not set.")
        return ELEVENLABS_MANAGER
    elif name == "SpeechToTextManager":
        if not SPEECH_TO_TEXT_MANAGER:
            debug_print("Tools", "SpeechToTextManager reference requested but not set.")
        return SPEECH_TO_TEXT_MANAGER
    elif name == "AssistantManager":
        if not ASSISTANT_MANAGER:
            debug_print("Tools", "AssistantManager reference requested but not set.")
        return ASSISTANT_MANAGER
    elif name == "EventManager":
        if not EVENT_MANAGER:
            debug_print("Tools", "EventManager reference requested but not set.")
        return EVENT_MANAGER
    elif name == "AutoMod":
        if not AUTOMOD:
            debug_print("Tools", "AutoMod reference requested but not set.")
        return AUTOMOD
    elif name == "AudioManager":
        if not AUDIO_MANAGER:
            debug_print("Tools", "AudioManager reference requested but not set.")
        return AUDIO_MANAGER
    elif name == "OBSManager":
        if not OBS_MANAGER:
            debug_print("Tools", "OBSManager reference requested but not set.")
        return OBS_MANAGER
    elif name == "GPTManager":
        if not GPT_MANAGER:
            debug_print("Tools", "GPTManager reference requested but not set.")
        return GPT_MANAGER
    elif name == "PointBuilder":
        if not POINT_BUILDER:
            debug_print("Tools", "PointBuilder reference requested but not set.")
        return POINT_BUILDER
    elif name == "MessageScheduler":
        if not SCHEDULER:
            debug_print("Tools", "MessageScheduler reference requested but not set.")
        return SCHEDULER
    elif name == "CommandHandler":
        if not COMMAND_HANDLER:
            debug_print("Tools", "CommandHandler reference requested but not set.")
        return COMMAND_HANDLER
    elif name == "OnlineDatabase":
        if not ONLINE_DATABASE:
            debug_print("Tools", "OnlineDatabase reference requested but not set.")
        return ONLINE_DATABASE
    elif name == "OnlineStorage":
        if not ONLINE_STORAGE:
            debug_print("Tools", "OnlineStorage reference requested but not set.")
        return ONLINE_STORAGE
    elif name == "GachaHandler":
        if not GACHA_HANDLER:
            debug_print("Tools", "GachaHandler reference requested but not set.")
        return GACHA_HANDLER