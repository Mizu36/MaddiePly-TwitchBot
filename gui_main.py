import os
import sys
import threading
import sqlite3
import asyncio
import datetime
import string
import random
import json
import time
import tkinter as tk
from tkinter import ttk, messagebox
import tkinter.font as tkfont
import textwrap
from tkinter.scrolledtext import ScrolledText
from db import (
    save_location_capture,
    get_setting,
    get_hotkey,
    set_hotkey,
    close_database_sync,
    REQUIRED_SETTINGS,
    REQUIRED_HOTKEYS,
    get_randomizer_main_entries,
    get_randomizer_modifier_entries,
    add_randomizer_entry,
    remove_randomizer_entry,
)
from tkinter import simpledialog
from ai_logic import start_timer_manager_in_background
from tools import set_debug, debug_print, get_random_number, get_reference, path_from_app_root
from db import get_database_loop
import typing
import testing

# Pending coroutines that need to be scheduled on the DB/bot loop when it
# becomes available. Stored as list of (coro, description) for debugging.
_PENDING_HOTKEY_COROS: list = []
_PENDING_HOTKEY_LOCK = threading.Lock()

def _start_pending_coros_poller(timeout: float = 15.0, poll_interval: float = 0.2):
    """Background thread that waits for the DB event loop and schedules pending coroutines.

    This avoids creating a separate asyncio loop that would conflict with the
    async DB pool's loop (causing "Future attached to a different loop").
    """
    def _poller():
        import time as _time
        start = _time.time()
        while _time.time() - start < timeout:
            try:
                loop = get_database_loop()
                if loop is not None:
                    with _PENDING_HOTKEY_LOCK:
                        coros = list(_PENDING_HOTKEY_COROS)
                        _PENDING_HOTKEY_COROS.clear()
                    for c in coros:
                        try:
                            debug_print("GUIHotkey", "Flushing pending hotkey coroutine to DB loop")
                            __import__("asyncio").run_coroutine_threadsafe(c, loop)
                        except Exception as _e:
                            debug_print("GUIHotkey", f"Failed to schedule pending hotkey coro: {_e}")
                    return
            except Exception:
                pass
            _time.sleep(poll_interval)
        # Timeout expired; log and drop remaining coros
        with _PENDING_HOTKEY_LOCK:
            if _PENDING_HOTKEY_COROS:
                debug_print("GUIHotkey", f"Pending hotkey coroutines dropped after {timeout}s timeout: {len(_PENDING_HOTKEY_COROS)}")
                _PENDING_HOTKEY_COROS.clear()

    threading.Thread(target=_poller, daemon=True).start()
from hotkey_listener import GlobalHotkeyListener, set_global_listener, get_global_listener


DB_FILENAME = str(path_from_app_root("data", "maddieply.db"))
ELEVEN_LABS_VOICE_MODELS = ["eleven_v3", "eleven_multilingual_v2", "eleven_flash_v2_5", "eleven_flash_v2", "eleven_turbo_v2_5", "eleven_turbo_v2"]
ELEVEN_LABS_VOICES = []
AUDIO_DEVICES = []
AZURE_TTS_VOICES = ["en-US-AvaNeural", "en-US-EmmaNeural", "en-US-JennyNeural", "en-US-AriaNeural", "en-US-JaneNeural", "en-US-LunaNeural", "en-US-SaraNeural", "en-US-NancyNeural", "en-US-AmberNeural", "en-US-AnaNeural", "en-US-AshleyNeural", "en-US-CoraNeural", "en-US-ElizabethNeural", "en-US-MichelleNeural", "en-US-AvaMultilingualNeural", "en-US-MonicaNeural", "en-US-BlueNeural", "en-US-AmandaMultilingualNeural", "en-US-LolaMultilingualNeural", "en-US-NancyMultilingualNeural", "en-US-ShimmerTurboMultilingualNeural", "en-US-SerenaMultilingualNeural", "en-US-PhoebeMultilingualNeural", "en-US-NovaTurboMultilingualNeural", "en-US-EvelynMultilingualNeural", "en-US-JennyMultilingualNeural", "en-US-EmmaMultilingualNeural", "en-US-CoraMultilingualNeural", "en-US-Aria:DragonHDLatestNeural", "en-US-Ava:DragonHDLatestNeural", "en-US-Emma:DragonHDLatestNeural", "en-US-Emma2:DragonHDLatestNeural", "en-US-Jenny:DragonHDLatestNeural"]
GPT_MODELS = ['gpt-4o']
CUSTOM_BUILDER = [
    {"Automatic Voiced Response": {"code": "AV", "input": str, "input_label": "Enter the text Maddie should speak:", "voiced": True}},
    {
        "AI Generated Voiced Response": {
            "code": "AI",
            "input": str,
            "input_label": "Enter the AI prompt for the voiced response:",
            "Use Personality": bool,
            "code w/ true": "API",
            "voiced": True,
        }
    },
    {"Automatic Chat Response": {"code": "AC", "input": str, "input_label": "Enter the exact chat message to send:"}},
    {
        "AI Generated Chat Response": {
            "code": "IC",
            "input": str,
            "input_label": "Enter the AI prompt for the chat response:",
            "Use Personality": bool,
            "code w/ true": "IPA",
        }
    },
    {"Generate Meme Image": {"code": "GM", "input": None}},
    {
        "Play Audio File": {
            "code": "AU",
            "input": str,
            "input_label": "Enter the audio filename (media/soundFX):",
        }
    },
    {
        "Animate Onscreen Element": {
            "code": "AN",
            "input": str,
            "input_label": "Enter the image/GIF filename (media/images_and_gifs):",
        }
    },
    {"Wait For Seconds": {"code": "WT", "input": int, "input_label": "Enter the number of seconds to wait:"}},
    {"Voiced Message": {"code": "VO", "input": None, "forced_input": "<user_input>", "voiced": True}},
    {
        "Timeout User": {
            "code": "TO",
            "input": int,
            "input_label": "Enter the timeout duration (seconds):",
            "requires_user_message": True,
            "user_message_hint": "Viewer message should start with the username to timeout (optionally followed by a reason).",
        }
    },
]

TESTING_BUTTON_GROUPS = [
    (
        "Chat / Cheers / Subs",
        [
            ("Chat Message", testing.test_chat_message),
            ("Channel Cheer", testing.test_channel_cheer),
            ("Channel Subscribe", testing.test_channel_subscribe),
            ("Resub Message", testing.test_channel_subscribe_message),
            ("Subscription End", testing.test_channel_subscription_end),
            ("Channel Follow", testing.test_channel_follow),
            ("Channel Raid", testing.test_channel_raid),
            ("Gifted Subscription", testing.test_gift_subscription_bundle),
        ],
    ),
    (
        "Channel Points",
        [
            ("Custom Redemption", testing.test_channel_points_redeem),
            ("Auto Redemption", testing.test_channel_points_auto_redeem),
        ],
    ),
    (
        "Shared Chat",
        [
            ("Session Begin", testing.test_shared_chat_session_begin),
            ("Session Update", testing.test_shared_chat_session_update),
            ("Session End", testing.test_shared_chat_session_end),
        ],
    ),
    (
        "Stream Lifecycle",
        [
            ("Stream Online", testing.test_stream_online),
            ("Stream Offline", testing.test_stream_offline),
        ],
    ),
    (
        "Charity",
        [
            ("Campaign Start", testing.test_charity_campaign_start),
            ("Campaign Progress", testing.test_charity_campaign_progress),
            ("Campaign Stop", testing.test_charity_campaign_stop),
        ],
    ),
    (
        "Goals",
        [
            ("Goal Begin", testing.test_goal_begin),
            ("Goal Progress", testing.test_goal_progress),
            ("Goal End", testing.test_goal_end),
        ],
    ),
    (
        "Hype Train",
        [
            ("Hype Train Begin", testing.test_hype_train_begin),
            ("Hype Train Progress", testing.test_hype_train_progress),
            ("Hype Train End", testing.test_hype_train_end),
        ],
    ),
    (
        "Channel Polls",
        [
            ("Poll Begin", testing.test_channel_poll_begin),
            ("Poll Progress", testing.test_channel_poll_progress),
            ("Poll End", testing.test_channel_poll_end),
        ],
    ),
    (
        "Predictions",
        [
            ("Prediction Begin", testing.test_channel_prediction_begin),
            ("Prediction Progress", testing.test_channel_prediction_progress),
            ("Prediction Lock", testing.test_channel_prediction_lock),
            ("Prediction End", testing.test_channel_prediction_end),
        ],
    ),
    (
        "Shield Mode",
        [
            ("Shield Mode Begin", testing.test_shield_mode_begin),
            ("Shield Mode End", testing.test_shield_mode_end),
        ],
    ),
    (
        "Shoutouts",
        [
            ("Shoutout Create", testing.test_shoutout_create),
            ("Shoutout Receive", testing.test_shoutout_receive),
        ],
    ),
    (
        "Moderation & Ads",
        [
            ("Suspicious Message", testing.test_suspicious_user_message),
            ("AutoMod Hold", testing.test_automod_message_hold),
            ("Ad Break Begin", testing.test_ad_break_begin),
        ],
    ),
]

ROW_STRIPE_LIGHT = "#ffffff"
ROW_STRIPE_DARK = "#f6f6f6"


class CollapsibleSection(ttk.Frame):
    def __init__(self, parent, title: str, *, initially_open: bool = False):
        super().__init__(parent)
        self._title = title
        self._expanded = tk.BooleanVar(value=initially_open)
        header = ttk.Frame(self)
        header.pack(fill=tk.X)
        self._toggle_btn = ttk.Button(header, text=self._button_text(), command=self._toggle)
        self._toggle_btn.pack(side=tk.LEFT, padx=2, pady=2)
        self.body_frame = ttk.Frame(self)
        if initially_open:
            self.body_frame.pack(fill=tk.BOTH, expand=True)

    def _button_text(self) -> str:
        return f"{'[-]' if self._expanded.get() else '[+]'} {self._title}"

    def _toggle(self) -> None:
        if self._expanded.get():
            self.body_frame.pack_forget()
            self._expanded.set(False)
        else:
            self.body_frame.pack(fill=tk.BOTH, expand=True)
            self._expanded.set(True)
        self._toggle_btn.configure(text=self._button_text())

def display_boolean_value(key: str, raw: str) -> str:
    """Convert stored DB raw value to a display value for boolean settings.

    Stored values expected: '1' or '0' (or other truthy/falsy forms).
    Displayed values: 'True' or 'False'.
    """
    debug_print("GUI", f"Converting boolean value for key '{key}': raw='{raw}'")
    if raw is None:
        return "False"
    if str(raw).strip() in ("1", "True", "true", "yes", "on"):
        return "True"
    return "False"


def parse_boolean_input(s: str) -> str:
    """Parse user input and return '1' or '0'. Accepts True/False/1/0 (case-insensitive).

    Raises ValueError if input is not recognized as a boolean.
    """
    debug_print("GUI", f"Parsing boolean input: s='{s}'")
    if s is None:
        raise ValueError("No value provided")
    v = str(s).strip().lower()
    if v in ("1", "true", "t", "yes", "y", "on"):
        return "1"
    if v in ("0", "false", "f", "no", "n", "off"):
        return "0"
    raise ValueError(f"Invalid boolean value: {s}")


def _format_type_examples(data_type: str) -> str:
    """Return example values / guidance for a given data_type for messages.

    Keeps examples short and useful for end-users.
    """
    dt = (data_type or "TEXT").upper()
    if dt == "BOOL":
        return "Acceptable values: True/False, 1/0, yes/no (case-insensitive)."
    if dt == "INTEGER":
        return "Enter a positive integer (greater than 0), e.g. 1, 42, 3."
    if dt == "CHARACTER":
        return "Enter a single character, e.g. 'A' or 'x'."
    # TEXT or default
    return "Any text is allowed."


def _validation_message(key: str, data_type: str, attempted: str | None) -> str:
    """Construct a friendly validation error message for a setting key/type/value."""
    attempted_display = "<empty>" if attempted is None or str(attempted) == "" else str(attempted)
    return (
        f"Value '{attempted_display}' is not valid for setting '{key}' (expected {data_type}).\n"
        + _format_type_examples(data_type)
    )


class ConsoleRedirector:
    def __init__(self, text_widget: ScrolledText):
        self.text_widget = text_widget

    def write(self, s):
        if not s:
            return
        try:
            self.text_widget.configure(state="normal")
            self.text_widget.insert(tk.END, s)
            self.text_widget.see(tk.END)
            self.text_widget.configure(state="disabled")
        except Exception:
            pass

    def flush(self):
        pass


class DBEditor(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("MaddiePly Twitch Bot")
        self.geometry("1000x700")
        self.users_tree = None
        self.users_count_var = tk.StringVar(self, value="Total Viewers: 0")
        self.users_row_data: dict[str, dict] = {}
        self.users_frame: ttk.Frame | None = None
        self.users_tab_id: str | None = None
        self._users_tooltip = None
        self._users_tooltip_label = None
        self._purge_users_thread = None
        self.purge_users_btn = None
        self._users_font = None
        self._event_tab_refresh_job = None
        self._obs_warning_label: tk.Label | None = None
        self._obs_warning_job: str | None = None
        self._google_credentials_valid = True
        self._google_credentials_error = ""
        self._settings_tooltip = None
        self._settings_tooltip_label = None
        self._openai_model_choices: list[str] | None = None

        # Ensure we close DB and other resources on window close
        try:
            self.protocol("WM_DELETE_WINDOW", self._on_close)
        except Exception:
            pass

        # Notebook
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill=tk.BOTH, expand=True)
        try:
            self.nb.bind("<<NotebookTabChanged>>", self._on_tab_changed)
        except Exception:
            pass

        self._init_obs_warning_banner()

        # Style for alternating rows in treeviews
        style = ttk.Style(self)
        try:
            style.configure("Treeview", rowheight=20)
        except Exception:
            pass

        # Tabs to create
        self.tables = [
            ("settings", "Settings"),
            ("commands", "Commands"),
            ("scheduled_messages", "Scheduled Messages"),
            ("prompts", "Prompts"),
        ]

        self.frames = {}
        try:
            self._evaluate_google_credentials()
        except Exception as exc:
            debug_print("GUI", f"Google Sheets credential validation failed: {exc}")
        try:
            try:
                audio_manager = get_reference("AudioManager")
                devices = audio_manager.list_output_devices()
            except Exception:
                devices = []
            if devices:
                AUDIO_DEVICES.clear()
                AUDIO_DEVICES.extend(devices)
            debug_print("GUI", f"Discovered audio devices: {AUDIO_DEVICES}")
        except Exception as e:
            debug_print("GUI", f"Error listing audio devices: {e}")

        try:
            def _fetch_elevenlabs_models():
                print("[GUI] Starting fetch of ElevenLabs models...")
                try:
                    try:
                        elevenlabs_manager = get_reference("ElevenLabsManager")
                        elevenlabs_models = elevenlabs_manager.get_list_of_models()
                    except TypeError:
                        elevenlabs_models = []
                    except Exception:
                        elevenlabs_models = []

                    # Normalize returned model objects/dicts into a list of string ids
                    normalized = []
                    for m in elevenlabs_models:
                        try:
                            if isinstance(m, dict):
                                if "model_id" in m:
                                    normalized.append(str(m["model_id"]))
                                elif "id" in m:
                                    normalized.append(str(m["id"]))
                                elif "name" in m:
                                    normalized.append(str(m["name"]))
                                else:
                                    normalized.append(str(m))
                            else:
                                # try attribute access
                                mid = getattr(m, "model_id", None) or getattr(m, "id", None) or getattr(m, "name", None)
                                if mid:
                                    normalized.append(str(mid))
                                else:
                                    # fallback to repr
                                    normalized.append(str(m))
                        except Exception:
                            try:
                                normalized.append(str(m))
                            except Exception:
                                pass

                    if normalized:
                        ELEVEN_LABS_VOICE_MODELS.clear()
                        ELEVEN_LABS_VOICE_MODELS.extend(normalized)
                        debug_print("GUI", f"Discovered Elevenlabs synthesizer models ({len(ELEVEN_LABS_VOICE_MODELS)}): {ELEVEN_LABS_VOICE_MODELS}")
                    else:
                        debug_print("GUI", "No Elevenlabs models returned (empty list).")
                except Exception as e:
                    import traceback
                    print("[GUI] Error listing Elevenlabs synthesizer models:")
                    print(traceback.format_exc())

                # After updating the global list, refresh inline controls on the
                # main thread so any comboboxes get rebuilt with new options.
                try:
                    self.after(0, lambda: self.refresh_settings_inline())
                except Exception:
                    pass

            try:
                threading.Thread(target=_fetch_elevenlabs_models, daemon=True).start()
            except Exception as e:
                debug_print("GUI", f"Failed to start thread to fetch Elevenlabs models: {e}")
        except Exception as e:
            # Outer guard to match original structure — log any unexpected errors
            debug_print("GUI", f"Error while initiating Elevenlabs models fetch: {e}")

        try:
            azure_manager = get_reference("SpeechToTextManager")
            if azure_manager is not None:
                try:
                    voices = azure_manager.get_list_of_voices()
                except Exception:
                    voices = []
            else:
                voices = []
            if voices:
                AZURE_TTS_VOICES.clear()
                AZURE_TTS_VOICES.extend(voices)
        except Exception as e:
            debug_print("GUI", f"Error getting SpeechToTextManager voices: {e}")

        for tbl, label in self.tables:
            frame = ttk.Frame(self.nb)
            self.frames[tbl] = frame
            self.nb.add(frame, text=label)
            self._build_table_frame(frame, tbl)

        try:
            self._build_users_tab()
        except Exception as e:
            debug_print("GUI", f"Failed to build Twitch Users tab: {e}")

        # Tools tab
        tools_frame = ttk.Frame(self.nb)
        self.nb.add(tools_frame, text="Tools")
        tools_toolbar = ttk.Frame(tools_frame)
        tools_toolbar.pack(fill=tk.X, padx=6, pady=6)

        btn_capture_on = ttk.Button(
            tools_toolbar,
            text="Capture Assistant Onscreen Location",
            command=lambda: self.start_capture_location(None, True),
        )
        btn_capture_on.pack(side=tk.LEFT, padx=4)

        btn_capture_off = ttk.Button(
            tools_toolbar,
            text="Capture Assistant Offscreen Location",
            command=lambda: self.start_capture_location(None, False),
        )
        btn_capture_off.pack(side=tk.LEFT, padx=4)

        # ElevenLabs models refresh (diagnostic) - lets user force a fetch and see results in Console
        btn_refresh_eleven = ttk.Button(
            tools_toolbar,
            text="Refresh ElevenLabs Models",
            command=lambda: self._refresh_elevenlabs_models()
        )
        btn_refresh_eleven.pack(side=tk.LEFT, padx=4)

        # Scrollable body so long tool groups remain accessible at smaller window sizes.
        tools_body = ttk.Frame(tools_frame)
        tools_body.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 6))

        tools_canvas = tk.Canvas(tools_body, borderwidth=0, highlightthickness=0)
        tools_scrollbar = ttk.Scrollbar(tools_body, orient=tk.VERTICAL, command=tools_canvas.yview)
        tools_canvas.configure(yscrollcommand=tools_scrollbar.set)
        tools_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        tools_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        tools_scrollable = ttk.Frame(tools_canvas)
        tools_window = tools_canvas.create_window((0, 0), window=tools_scrollable, anchor="nw")

        def _update_tools_scrollregion(_event):
            tools_canvas.configure(scrollregion=tools_canvas.bbox("all"))

        def _resize_tools_canvas(event):
            try:
                tools_canvas.itemconfigure(tools_window, width=event.width)
            except Exception:
                pass

        def _on_tools_mousewheel(event):
            try:
                widget = event.widget
                inside_tools = False
                while widget is not None:
                    if widget is tools_scrollable or widget is tools_frame:
                        inside_tools = True
                        break
                    widget = getattr(widget, "master", None)
                if not inside_tools:
                    return
                if hasattr(event, "delta") and event.delta:
                    tools_canvas.yview_scroll(int(-event.delta / 120), "units")
                elif getattr(event, "num", None) in (4, 5):
                    direction = -1 if event.num == 4 else 1
                    tools_canvas.yview_scroll(direction, "units")
            except Exception:
                pass
            return "break"

        tools_scrollable.bind("<Configure>", _update_tools_scrollregion)
        tools_canvas.bind("<Configure>", _resize_tools_canvas)
        self.bind_all("<MouseWheel>", _on_tools_mousewheel, add="+")
        self.bind_all("<Button-4>", _on_tools_mousewheel, add="+")
        self.bind_all("<Button-5>", _on_tools_mousewheel, add="+")

        self._build_testing_tools(tools_scrollable)

        # Hotkeys tab
        hotkeys_frame = ttk.Frame(self.nb)
        self.nb.add(hotkeys_frame, text="Hotkeys")
        hotkeys_container = ttk.Frame(hotkeys_frame)
        hotkeys_container.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        self.hotkey_widgets = {}  # action -> {label_var, change_btn, clear_btn}
        # Create rows for each hotkey action found in the database. If the
        # DB isn't available or contains no rows yet, fall back to the
        # REQUIRED_HOTKEYS keys as a safeguard (db.setup ensures these exist
        # later when the async pool is initialized).
        HOTKEY_ACTIONS = []
        try:
            conn = self.connect()
            try:
                cur = conn.execute("SELECT action FROM hotkeys ORDER BY action")
                rows = cur.fetchall()
                HOTKEY_ACTIONS = [r[0] for r in rows]
            finally:
                conn.close()
        except Exception:
            HOTKEY_ACTIONS = []
        if not HOTKEY_ACTIONS:
            HOTKEY_ACTIONS = list(REQUIRED_HOTKEYS.keys())

        for i, action in enumerate(HOTKEY_ACTIONS):
            lbl = ttk.Label(hotkeys_container, text=action)
            lbl.grid(row=i, column=0, sticky=tk.W, padx=6, pady=4)

            var = tk.StringVar(value="(loading)")
            val_lbl = ttk.Label(hotkeys_container, textvariable=var, width=24)
            val_lbl.grid(row=i, column=1, sticky=tk.W, padx=6)

            btn_change = ttk.Button(hotkeys_container, text="Change", command=lambda a=action: self.open_hotkey_dialog(a))
            btn_change.grid(row=i, column=2, padx=6)

            btn_clear = ttk.Button(hotkeys_container, text="Clear", command=lambda a=action: self.clear_hotkey(a))
            btn_clear.grid(row=i, column=3, padx=6)

            self.hotkey_widgets[action] = {"var": var, "change": btn_change, "clear": btn_clear}

        # load current hotkeys
        self.refresh_hotkeys()
        # Start global hotkey listener and expose it globally for other modules
        try:
            self.hotkey_listener = GlobalHotkeyListener()
            self.hotkey_listener.start()
            # expose globally so other modules can register callbacks
            try:
                set_global_listener(self.hotkey_listener)
            except Exception:
                pass
            # Register hotkey handlers for specific actions
            def _schedule_coro(coro):
                """Schedule coroutine on bot loop if available, otherwise run in new loop."""
                try:
                    # Prefer the database/bot loop so coroutines that touch the
                    # async DB pool or bot objects run on the right event loop.
                    loop = None
                    try:
                        loop = get_database_loop()
                        if loop is not None:
                            debug_print("GUIHotkey", "Scheduling hotkey coroutine on DB event loop")
                    except Exception:
                        loop = None
                    if loop is None:
                        bot = get_reference("TwitchBot")
                        if bot is not None:
                            loop = getattr(bot, "loop", None) or getattr(bot, "_loop", None) or getattr(bot, "bot_loop", None)
                            if loop is not None:
                                debug_print("GUIHotkey", "Scheduling hotkey coroutine on bot loop")
                    if loop is not None:
                        try:
                            __import__("asyncio").run_coroutine_threadsafe(coro, loop)
                            return
                        except Exception as e:
                            debug_print("GUIHotkey", f"run_coroutine_threadsafe failed: {e}")
                    # Fallback: run in a new background thread with its own loop
                    # DB loop not available — enqueue the coroutine so it can be
                    # scheduled once the DB event loop is created. This avoids
                    # running the coroutine on a separate asyncio loop which
                    # causes cross-loop Future errors when the coroutine uses
                    # the async DB pool.
                    try:
                        with _PENDING_HOTKEY_LOCK:
                            _PENDING_HOTKEY_COROS.append(coro)
                        debug_print("GUIHotkey", "DB loop not available; enqueued hotkey coroutine for later scheduling")
                        _start_pending_coros_poller()
                        return
                    except Exception as _e:
                        debug_print("GUIHotkey", f"Failed to enqueue pending hotkey coroutine: {_e}")
                except Exception as e:
                    debug_print("GUIHotkey", f"Error scheduling coroutine: {e}")

            def _get_assistant_manager():
                # Prefer the assistant attached to the timer_manager (created
                # at startup by start_timer_manager_in_background). Fall back
                # to the bot object's response_manager.assistant if present.
                try:
                    assistant_manager = get_reference("AssistantManager")
                    if assistant_manager is not None:
                        return assistant_manager
                except Exception:
                    pass

            def _get_event_manager():
                # Prefer timer_manager's assistant.event_manager, fall back to bot's response_manager.assistant.event_manager
                try:
                    event_manager = get_reference("EventManager")
                    if event_manager is not None:
                        return event_manager
                except Exception:
                    pass

            # Map actions to handlers. Instead of registering raw handlers that
            # may run before runtime managers (bot/timer) are available, wrap
            # handlers so they retry resolving needed managers and schedule
            # coroutines on the bot/timer loop via _schedule_coro.

            def _resolve_with_retries(resolve_fn, attempts: int = 10, delay: float = 0.12):
                for i in range(attempts):
                    try:
                        res = resolve_fn()
                        if res is not None:
                            return res
                    except Exception:
                        pass
                    try:
                        time.sleep(delay)
                    except Exception:
                        pass
                return None

            # Build wrapper handlers for common action types
            def _wrap_event_call(method_name: str):
                def handler(action: str):
                    try:
                        em = _resolve_with_retries(_get_event_manager, attempts=8)
                        if em is None:
                            debug_print("GUIHotkey", f"{method_name}: no event manager available after retries")
                            return
                        method = getattr(em, method_name, None)
                        if method:
                            _schedule_coro(method())
                        else:
                            debug_print("GUIHotkey", f"Event manager has no method '{method_name}'")
                    except Exception as e:
                        debug_print("GUIHotkey", f"{method_name} handler error: {e}")
                return handler

            def _wrap_pause_toggle(action: str):
                try:
                    em = _resolve_with_retries(_get_event_manager, attempts=8)
                    if em is None:
                        debug_print("GUIHotkey", "Pause Event Queue: no event manager available after retries")
                        return
                    try:
                        if getattr(em, "paused", False):
                            em.resume()
                            debug_print("GUIHotkey", "Event queue resumed via hotkey")
                        else:
                            em.pause()
                            debug_print("GUIHotkey", "Event queue paused via hotkey")
                    except Exception as e:
                        debug_print("GUIHotkey", f"Pause toggle error: {e}")
                except Exception as e:
                    debug_print("GUIHotkey", f"Pause Event Queue handler error: {e}")

            def _wrap_listen_and_respond(action: str):
                try:
                    am = _resolve_with_retries(_get_assistant_manager, attempts=8)
                    if am is None:
                        debug_print("GUIHotkey", "Listen and Respond: no assistant manager available after retries")
                        return
                    if hasattr(am, "listen_and_respond"):
                        _schedule_coro(am.listen_and_respond())
                except Exception as e:
                    debug_print("GUIHotkey", f"Listen and Respond handler error: {e}")

            def _wrap_summarize_chat(action: str):
                try:
                    am = _resolve_with_retries(_get_assistant_manager, attempts=8)
                    if am is None:
                        debug_print("GUIHotkey", "Summarize Chat: no assistant manager available after retries")
                        return
                    if hasattr(am, "summarize_chat"):
                        _schedule_coro(am.summarize_chat())
                except Exception as e:
                    debug_print("GUIHotkey", f"Summarize Chat handler error: {e}")

            def _wrap_play_ad(action: str):
                try:
                    def _resolve_bot():
                        try:
                            return get_reference("TwitchBot")
                        except Exception:
                            return None
                    bot = _resolve_with_retries(_resolve_bot, attempts=8)
                    if bot is None:
                        debug_print("GUIHotkey", "Play Ad: no bot available after retries")
                        return
                    # Some implementations expose play_ad on the CommandHandler
                    # (bot.command_handler.play_ad). Try that first, then bot.play_ad.
                    command_handler = get_reference("CommandHandler")
                    debug_print("GUIHotkey", f"Play Ad invoked for action='{action}'; bot_present={bot is not None}, command_handler_present={command_handler is not None}")
                    if command_handler:
                        debug_print("GUIHotkey", "Play Ad: scheduling command_handler.play_ad()")
                        _schedule_coro(command_handler.play_ad())
                        return
                except Exception as e:
                    debug_print("GUIHotkey", f"Play Ad handler error: {e}")

            # Action -> handler mapping (wrapped)
            action_map = {
                "Play Next Event": _wrap_event_call("play_next"),
                "Skip Current Event": lambda a: (  # cancel then play next
                    (lambda: (_wrap_event_call("cancel_current_event")(a) if hasattr(_get_event_manager() or {}, "cancel_current_event") else None))(),
                    _wrap_event_call("play_next")(a),
                ),
                "Replay Last Event": _wrap_event_call("play_previous"),
                "Pause Event Queue": _wrap_pause_toggle,
                "Listen and Respond": _wrap_listen_and_respond,
                "Summarize Chat (Voiced)": _wrap_summarize_chat,
                "Start Ad": _wrap_play_ad,
                "Test Hotkey": lambda a: (print("[Hotkey] Test Hotkey pressed!"), debug_print("GUIHotkey", "Test Hotkey pressed!")),
            }

            for act in list(self.hotkey_widgets.keys()):
                try:
                    handler = action_map.get(act)
                    if handler:
                        self.hotkey_listener.register_callback(act, handler)
                    else:
                        self.hotkey_listener.register_callback(act, lambda a=act: debug_print("GUIHotkey", f"Hotkey triggered: {a}"))
                except Exception:
                    pass

            # Load mappings from DB (if DB loop available)
            try:
                self.hotkey_listener.reload_from_db()
            except Exception:
                pass
        except Exception:
            debug_print("GUI", "Failed to start global hotkey listener.")

        # Randomizer tab
        try:
            randomizer_frame = ttk.Frame(self.nb)
            self.nb.add(randomizer_frame, text="Randomizer")

            # Random number generator section
            rng_frame = ttk.LabelFrame(randomizer_frame, text="Random Number")
            rng_frame.pack(fill=tk.X, padx=6, pady=(6, 4))
            ttk.Label(rng_frame, text="Min:").grid(row=0, column=0, padx=6, pady=6, sticky=tk.W)
            rng_min = tk.StringVar(value="1")
            ttk.Entry(rng_frame, textvariable=rng_min, width=10).grid(row=0, column=1, padx=6, pady=6)
            ttk.Label(rng_frame, text="Max:").grid(row=0, column=2, padx=6, pady=6, sticky=tk.W)
            rng_max = tk.StringVar(value="10")
            ttk.Entry(rng_frame, textvariable=rng_max, width=10).grid(row=0, column=3, padx=6, pady=6)
            rng_result_var = tk.StringVar(value="")
            def _generate_random_number():
                try:
                    lo = int(rng_min.get())
                    hi = int(rng_max.get())
                    if lo > hi:
                        messagebox.showerror("Randomizer", "Minimum must be <= Maximum", parent=self)
                        return
                    # use tools.get_random_number for uniform selection
                    val = get_random_number(lo, hi)
                    rng_result_var.set(str(val))
                except Exception as e:
                    messagebox.showerror("Randomizer", f"Invalid min/max: {e}", parent=self)

            ttk.Button(rng_frame, text="Generate", command=_generate_random_number).grid(row=0, column=4, padx=8)
            ttk.Label(rng_frame, textvariable=rng_result_var, font=(None, 12, "bold")).grid(row=0, column=5, padx=8)

            # Combined choice display (appears between RNG and the lists)
            combined_choice_var = tk.StringVar(value="")
            # center the combined choice text across the full width
            ttk.Label(randomizer_frame, textvariable=combined_choice_var, foreground="blue", anchor="center", justify="center").pack(fill=tk.X, padx=6, pady=(4,6))

            # Two-list randomizer: main entries and modifiers
            lists_container = ttk.Frame(randomizer_frame)
            lists_container.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

            # Main entries
            main_frame = ttk.LabelFrame(lists_container, text="Main Entries")
            main_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0,6))
            main_listbox = tk.Listbox(main_frame, selectmode=tk.EXTENDED)
            main_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=4, pady=4)
            main_scroll = ttk.Scrollbar(main_frame, orient=tk.VERTICAL, command=main_listbox.yview)
            main_scroll.pack(side=tk.LEFT, fill=tk.Y)
            main_listbox.config(yscrollcommand=main_scroll.set)
            main_btn_frame = ttk.Frame(main_frame)
            main_btn_frame.pack(fill=tk.X, padx=4, pady=(0,6))
            # Choose button spans the width of the two small buttons below
            choose_main = ttk.Button(main_btn_frame, text="Choose Random", command=lambda: self._rand_choose(False))
            choose_main.grid(row=0, column=0, columnspan=2, sticky="ew", padx=4, pady=(0,4))
            add_btn = ttk.Button(main_btn_frame, text="Add", command=lambda: self._rand_add(False))
            add_btn.grid(row=1, column=0, sticky="ew", padx=(0,4))
            remove_btn = ttk.Button(main_btn_frame, text="Remove", command=lambda: self._rand_remove(False))
            remove_btn.grid(row=1, column=1, sticky="ew", padx=(4,0))
            main_btn_frame.columnconfigure(0, weight=1)
            main_btn_frame.columnconfigure(1, weight=1)
            main_choice_var = tk.StringVar(value="")

            # Modifiers
            mod_frame = ttk.LabelFrame(lists_container, text="Modifier Entries")
            mod_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(6,0))
            mod_listbox = tk.Listbox(mod_frame, selectmode=tk.EXTENDED)
            mod_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=4, pady=4)
            mod_scroll = ttk.Scrollbar(mod_frame, orient=tk.VERTICAL, command=mod_listbox.yview)
            mod_scroll.pack(side=tk.LEFT, fill=tk.Y)
            mod_listbox.config(yscrollcommand=mod_scroll.set)
            mod_btn_frame = ttk.Frame(mod_frame)
            mod_btn_frame.pack(fill=tk.X, padx=4, pady=(0,6))
            # Choose button spans the width of the two small buttons below
            choose_mod = ttk.Button(mod_btn_frame, text="Choose Random", command=lambda: self._rand_choose(True))
            choose_mod.grid(row=0, column=0, columnspan=2, sticky="ew", padx=4, pady=(0,4))
            add_mod = ttk.Button(mod_btn_frame, text="Add", command=lambda: self._rand_add(True))
            add_mod.grid(row=1, column=0, sticky="ew", padx=(0,4))
            remove_mod = ttk.Button(mod_btn_frame, text="Remove", command=lambda: self._rand_remove(True))
            remove_mod.grid(row=1, column=1, sticky="ew", padx=(4,0))
            mod_btn_frame.columnconfigure(0, weight=1)
            mod_btn_frame.columnconfigure(1, weight=1)
            mod_choice_var = tk.StringVar(value="")

            # Store references
            self.randomizer_widgets = {
                "main_listbox": main_listbox,
                "mod_listbox": mod_listbox,
                "main_rows": [],
                "mod_rows": [],
                "main_choice_var": main_choice_var,
                "mod_choice_var": mod_choice_var,
                "combined_choice_var": combined_choice_var,
            }

            # Initial load
            try:
                self.refresh_randomizer_lists()
            except Exception:
                pass
        except Exception:
            debug_print("GUI", "Failed to initialize Randomizer tab")

        # Custom Redemption Builder tab
        try:
            cr_frame = ttk.Frame(self.nb)
            self.nb.add(cr_frame, text="Custom Redemption Builder")

            cr_toolbar = ttk.Frame(cr_frame)
            cr_toolbar.pack(fill=tk.X, padx=6, pady=6)
            ttk.Button(cr_toolbar, text="Add", command=lambda: self.open_custom_redemption_editor(mode="add")).pack(side=tk.LEFT, padx=4)
            ttk.Button(cr_toolbar, text="Edit", command=lambda: self.open_custom_redemption_editor(mode="edit")).pack(side=tk.LEFT, padx=4)
            ttk.Button(cr_toolbar, text="Delete", command=lambda: self.delete_selected_custom_redemption()).pack(side=tk.LEFT, padx=4)
            ttk.Button(cr_toolbar, text="Enable/Disable", command=lambda: self.toggle_selected_custom_redemption()).pack(side=tk.LEFT, padx=4)

            container = ttk.Frame(cr_frame)
            container.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

            # Top area for the two lists (keeps shared description visible below)
            top_lists_frame = ttk.Frame(container)
            top_lists_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

            # Bits Donations section
            bits_frame = ttk.LabelFrame(top_lists_frame, text="Bit Donations")
            bits_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0,6))
            bits_listbox = tk.Listbox(bits_frame, selectmode=tk.BROWSE, height=10)
            bits_listbox.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=4, pady=(4,2))

            # Channel Points section
            cp_frame = ttk.LabelFrame(top_lists_frame, text="Channel Point Redemptions")
            cp_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(6,0))
            cp_listbox = tk.Listbox(cp_frame, selectmode=tk.BROWSE, height=10)
            cp_listbox.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=4, pady=(4,2))

            # Shared description area below both lists (fixed height clipped frame)
            shared_desc_frame = ttk.Frame(container, height=120)
            shared_desc_frame.pack(side=tk.TOP, fill=tk.X, padx=6, pady=(4,6))
            shared_desc_frame.pack_propagate(False)
            shared_desc = ScrolledText(shared_desc_frame, height=6, wrap=tk.WORD, state="disabled")
            shared_desc.pack(fill=tk.BOTH, expand=True)

            # store references
            self.frames["custom_bits_listbox"] = bits_listbox
            self.frames["custom_cp_listbox"] = cp_listbox
            self.frames["custom_bits_rows"] = []
            self.frames["custom_cp_rows"] = []
            self.frames["custom_desc"] = shared_desc

            def _on_bits_select(evt):
                try:
                    # clear selection in channel points list to avoid conflicting selections
                    try:
                        cp_listbox.selection_clear(0, tk.END)
                    except Exception:
                        pass
                    sel = bits_listbox.curselection()
                    shared = self.frames.get("custom_desc")
                    if shared:
                        shared.configure(state="normal")
                        shared.delete("1.0", tk.END)
                        if sel:
                            idx = sel[0]
                            rows = self.frames.get("custom_bits_rows", [])
                            if 0 <= idx < len(rows):
                                shared.insert(tk.END, rows[idx].get("description") or "(No description)")
                        else:
                            shared.insert(tk.END, "(No description)")
                        shared.configure(state="disabled")
                except Exception:
                    pass

            def _on_cp_select(evt):
                try:
                    # clear selection in bits list to avoid conflicting selections
                    try:
                        bits_listbox.selection_clear(0, tk.END)
                    except Exception:
                        pass
                    sel = cp_listbox.curselection()
                    shared = self.frames.get("custom_desc")
                    if shared:
                        shared.configure(state="normal")
                        shared.delete("1.0", tk.END)
                        if sel:
                            idx = sel[0]
                            rows = self.frames.get("custom_cp_rows", [])
                            if 0 <= idx < len(rows):
                                shared.insert(tk.END, rows[idx].get("description") or "(No description)")
                        else:
                            shared.insert(tk.END, "(No description)")
                        shared.configure(state="disabled")
                except Exception:
                    pass

            bits_listbox.bind("<<ListboxSelect>>", _on_bits_select)
            cp_listbox.bind("<<ListboxSelect>>", _on_cp_select)

            # Use a class-level refresher so other methods (like Save) can call it
            def _start_background_refresh():
                try:
                    self.refresh_custom_redemptions()
                except Exception:
                    pass

            threading.Thread(target=_start_background_refresh, daemon=True).start()
        except Exception:
            debug_print("GUI", "Failed to initialize Custom Redemption Builder tab")

        # Event Manager tab
        try:
            ev_frame = ttk.Frame(self.nb)
            self.nb.add(ev_frame, text="Event Manager")

            ev_toolbar = ttk.Frame(ev_frame)
            ev_toolbar.pack(fill=tk.X, padx=6, pady=6)

            btn_delete = ttk.Button(ev_toolbar, text="Delete Selected", command=lambda: self._event_delete_selected())
            btn_delete.pack(side=tk.LEFT, padx=4)
            btn_clear = ttk.Button(ev_toolbar, text="Clear Events", command=lambda: self._event_clear_and_refresh())
            btn_clear.pack(side=tk.LEFT, padx=4)

            container = ttk.Frame(ev_frame)
            container.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

            queued_lab = ttk.LabelFrame(container, text="Queued Events")
            queued_lab.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0,6))
            queued_list = tk.Listbox(queued_lab, selectmode=tk.BROWSE, height=15)
            queued_list.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

            played_lab = ttk.LabelFrame(container, text="Played Events")
            played_lab.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(6,0))
            played_list = tk.Listbox(played_lab, selectmode=tk.BROWSE, height=15)
            played_list.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

            # store references
            self.frames["event_queued_list"] = queued_list
            self.frames["event_played_list"] = played_list

            def _schedule_on_db(coro):
                try:
                    db_loop = get_database_loop()
                    if db_loop and getattr(db_loop, "is_running", lambda: False)():
                        try:
                            asyncio.run_coroutine_threadsafe(coro, db_loop)
                            return True
                        except Exception as e:
                            debug_print("GUIEvent", f"run_coroutine_threadsafe failed: {e}")
                except Exception:
                    pass
                debug_print("GUIEvent", "No DB loop available to schedule event manager coroutine")
                return False

            def _refresh_event_tab():
                try:
                    evm = get_reference("EventManager")
                    if not evm:
                        debug_print("GUIEvent", "EventManager reference not available for refresh.")
                        return
                    queued_sel = queued_list.curselection()
                    queued_sel_idx = queued_sel[0] if queued_sel else None
                    queued_sel_text = queued_list.get(queued_sel_idx) if queued_sel else None
                    played_sel = played_list.curselection()
                    played_sel_idx = played_sel[0] if played_sel else None
                    played_sel_text = played_list.get(played_sel_idx) if played_sel else None

                    queued_list.delete(0, tk.END)
                    played_list.delete(0, tk.END)
                    # Build display names from event_type key
                    for ev in getattr(evm, "event_queue", []):
                        name = ev.get("event_type") if isinstance(ev, dict) else str(ev)
                        queued_list.insert(tk.END, name)
                    for ev in getattr(evm, "played_events", []):
                        name = ev.get("event_type") if isinstance(ev, dict) else str(ev)
                        played_list.insert(tk.END, name)
                    self._apply_listbox_stripes(queued_list)
                    self._apply_listbox_stripes(played_list)

                    def _restore_selection(listbox, prev_idx, prev_text):
                        if prev_idx is None and prev_text is None:
                            return
                        size = listbox.size()
                        target = None
                        if prev_idx is not None and prev_idx < size:
                            if prev_text is None or listbox.get(prev_idx) == prev_text:
                                target = prev_idx
                        if target is None and prev_text is not None:
                            for idx in range(size):
                                if listbox.get(idx) == prev_text:
                                    target = idx
                                    break
                        if target is not None:
                            listbox.selection_clear(0, tk.END)
                            listbox.selection_set(target)
                            listbox.see(target)

                    _restore_selection(queued_list, queued_sel_idx, queued_sel_text)
                    _restore_selection(played_list, played_sel_idx, played_sel_text)
                except Exception as e:
                    debug_print("GUIEvent", f"Error refreshing event tab: {e}")

            # Attach helper methods to self so buttons can reference them
            def _event_play_selected(played_override: bool | None = None, index_override: int | None = None):
                try:
                    evm = get_reference("EventManager")
                    if not evm:
                        debug_print("GUIEvent", "EventManager not available for play action")
                        return
                    if index_override is not None and played_override is not None:
                        idx = index_override
                        played = played_override
                    else:
                        sel = queued_list.curselection()
                        played = False
                        if not sel:
                            sel = played_list.curselection()
                            played = True
                        if not sel:
                            return
                        idx = sel[0]
                    coro = evm.play_specific(played, idx)
                    _schedule_on_db(coro)
                except Exception as e:
                    debug_print("GUIEvent", f"Error scheduling play/replay action: {e}")

            def _event_delete_selected():
                try:
                    evm = get_reference("EventManager")
                    if not evm:
                        debug_print("GUIEvent", "EventManager not available for delete action")
                        return
                    # prefer queued selection, otherwise played
                    sel = queued_list.curselection()
                    played = False
                    if not sel:
                        sel = played_list.curselection()
                        played = True
                    if not sel:
                        return
                    idx = sel[0]
                    coro = evm.remove_event(played, idx)
                    futok = _schedule_on_db(coro)
                    if futok:
                        # refresh after a small delay to allow removal to complete
                        self.after(200, _refresh_event_tab)
                    else:
                        _refresh_event_tab()
                except Exception as e:
                    debug_print("GUIEvent", f"Error scheduling delete action: {e}")

            def _event_clear_and_refresh():
                try:
                    evm = get_reference("EventManager")
                    if not evm:
                        debug_print("GUIEvent", "EventManager not available for clear action")
                        return
                    coro = evm.clear_events()
                    futok = _schedule_on_db(coro)
                    if futok:
                        self.after(300, _refresh_event_tab)
                    else:
                        _refresh_event_tab()
                except Exception as e:
                    debug_print("GUIEvent", f"Error scheduling clear action: {e}")

            def _bind_double_click(listbox: tk.Listbox, played_flag: bool):
                def _on_double_click(event):
                    sel = event.widget.curselection()
                    if not sel:
                        return
                    _event_play_selected(played_override=played_flag, index_override=sel[0])

                listbox.bind("<Double-Button-1>", _on_double_click)

            _bind_double_click(queued_list, False)
            _bind_double_click(played_list, True)

            # expose on self
            self._event_play_selected = _event_play_selected
            self._event_delete_selected = _event_delete_selected
            self._event_clear_and_refresh = _event_clear_and_refresh
            def _poll_event_lists():
                try:
                    _refresh_event_tab()
                finally:
                    try:
                        self._event_tab_refresh_job = self.after(3000, _poll_event_lists)
                    except Exception:
                        self._event_tab_refresh_job = None

            try:
                _refresh_event_tab()
                self._event_tab_refresh_job = self.after(3000, _poll_event_lists)
            except Exception:
                pass
        except Exception:
            debug_print("GUI", "Failed to initialize Event Manager tab")

        # Create Console tab as the last tab so it appears at the end of the Notebook.
        try:
            console_frame = ttk.Frame(self.nb)
            self.nb.add(console_frame, text="Console")
            self.console_text = ScrolledText(console_frame, state="disabled", wrap=tk.WORD)
            self.console_text.pack(fill=tk.BOTH, expand=True)
            try:
                sys.stdout = ConsoleRedirector(self.console_text)
                sys.stderr = ConsoleRedirector(self.console_text)
            except Exception:
                pass
        except Exception:
            pass

        self._apply_tab_order()

    def _apply_tab_order(self) -> None:
        """Ensure the Notebook tabs follow the preferred left-to-right order."""
        try:
            desired_order = [
                "Settings",
                "Event Manager",
                "Commands",
                "Scheduled Messages",
                "Custom Redemption Builder",
                "Twitch Users",
                "Randomizer",
                "Hotkeys",
                "Prompts",
                "Tools",
                "Console",
            ]
            existing_tabs = {}
            for tab_id in self.nb.tabs():
                label = self.nb.tab(tab_id, "text")
                # Keep only the first occurrence per label
                existing_tabs.setdefault(label, tab_id)
            for index, label in enumerate(desired_order):
                tab_id = existing_tabs.get(label)
                if tab_id is None:
                    continue
                self.nb.insert(index, tab_id)
        except Exception as exc:
            debug_print("GUI", f"Failed to apply tab order: {exc}")

    def _schedule_async_task(self, coro: typing.Awaitable[typing.Any] | None, source: str = "GUITesting") -> bool:
        """Attempt to schedule a coroutine on the bot/database loop."""
        if coro is None:
            debug_print(source, "No coroutine provided for scheduling.")
            return False
        loops: list = []
        try:
            loop = get_database_loop()
            if loop and getattr(loop, "is_running", lambda: True)():
                loops.append(loop)
        except Exception:
            pass
        try:
            bot = get_reference("TwitchBot")
        except Exception:
            bot = None
        if bot:
            for attr in ("loop", "_loop", "bot_loop"):
                loop = getattr(bot, attr, None)
                if loop and loop not in loops and getattr(loop, "is_running", lambda: True)():
                    loops.append(loop)
        for loop in loops:
            try:
                asyncio.run_coroutine_threadsafe(coro, loop)
                debug_print(source, "Scheduled coroutine on running loop.")
                return True
            except Exception as exc:
                debug_print(source, f"Failed to schedule coroutine: {exc}")
        return False

    def _run_testing_helper(
        self,
        coro_factory: typing.Callable[[], typing.Awaitable[typing.Any]],
        label: str,
    ) -> None:
        try:
            coro = coro_factory()
        except Exception as exc:
            debug_print("GUITesting", f"Failed to prepare '{label}' test: {exc}")
            messagebox.showerror("Event Simulation", f"Could not prepare '{label}' test.\n{exc}")
            return
        if not self._schedule_async_task(coro, f"GUITesting::{label}"):
            messagebox.showwarning(
                "Event Simulation",
                f"Unable to schedule '{label}' test. Ensure the bot is running and try again.",
            )

    def _build_testing_tools(self, parent: ttk.Frame) -> None:
        try:
            section = CollapsibleSection(parent, "Simulate Twitch Events", initially_open=False)
            section.pack(fill=tk.X, expand=False, padx=6, pady=6)
            for group_label, test_buttons in TESTING_BUTTON_GROUPS:
                group_box = ttk.LabelFrame(section.body_frame, text=group_label)
                group_box.pack(fill=tk.X, expand=True, padx=4, pady=4)
                for idx, (btn_label, factory) in enumerate(test_buttons):
                    btn = ttk.Button(
                        group_box,
                        text=btn_label,
                        command=lambda f=factory, title=btn_label: self._run_testing_helper(f, title),
                    )
                    row, col = divmod(idx, 3)
                    btn.grid(row=row, column=col, padx=3, pady=3, sticky="ew")
                for col in range(3):
                    group_box.columnconfigure(col, weight=1)
        except Exception as exc:
            debug_print("GUITesting", f"Failed to build testing tools: {exc}")

    def open_custom_redemption_editor(self, mode: str = "add") -> None:
        """Open the Custom Redemption Add/Edit builder.

        mode: "add" or "edit". For edit, the currently selected item in either
        the bits or channel_points list will be edited.
        """
        try:
            # determine edit target if editing
            target_row = None
            target_id = None
            target_type = None
            bits_threshold_value = ""
            if mode == "edit":
                # check bits selection
                lb_bits = self.frames.get("custom_bits_listbox")
                lb_cp = self.frames.get("custom_cp_listbox")
                rows_bits = self.frames.get("custom_bits_rows", [])
                rows_cp = self.frames.get("custom_cp_rows", [])
                sel_bits = lb_bits.curselection() if lb_bits else ()
                sel_cp = lb_cp.curselection() if lb_cp else ()
                if sel_bits:
                    idx = sel_bits[0]
                    if 0 <= idx < len(rows_bits):
                        target_row = rows_bits[idx]
                        target_id = target_row.get("id")
                        target_type = "bits"
                elif sel_cp:
                    idx = sel_cp[0]
                    if 0 <= idx < len(rows_cp):
                        target_row = rows_cp[idx]
                        target_id = target_row.get("id")
                        target_type = "channel_points"
                else:
                    messagebox.showinfo("Edit", "Please select a redemption to edit.", parent=self)
                    return

            # Build dialog
            dlg = tk.Toplevel(self)
            dlg.transient(self)
            dlg.grab_set()
            dlg.title("Add Custom Redemption" if mode == "add" else f"Edit Custom Redemption: {target_row.get('name') if target_row else ''}")
            dlg.geometry("900x600")

            # Left: slots area (max 10). Each slot is a frame that can contain 1-2 step blocks.
            # Use responsive layout: left and center expand with dialog, right is a sidebar
            left_frame = ttk.Frame(dlg)
            left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=6, pady=6)

            # Center: step input editor (fixed moderate width so it doesn't force layout shifts)
            center_frame = ttk.Frame(dlg, width=360)
            center_frame.pack(side=tk.LEFT, fill=tk.Y, expand=False, padx=6, pady=6)
            # keep the center editor at a fixed width so opening inputs doesn't
            # change surrounding layout. Allow internal widgets to manage height.
            try:
                center_frame.pack_propagate(False)
            except Exception:
                pass

            # Right: available options list (sidebar)
            right_frame = ttk.Frame(dlg, width=260)
            right_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=6, pady=6)
            try:
                right_frame.pack_propagate(False)
            except Exception:
                pass

            # Right list of builder options
            ttk.Label(right_frame, text="Options").pack(anchor=tk.W)
            options_listbox = tk.Listbox(right_frame, width=32)
            options_listbox.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=(0,4), pady=(2,4))
            options_scroll = ttk.Scrollbar(right_frame, orient=tk.VERTICAL, command=options_listbox.yview)
            options_scroll.pack(side=tk.RIGHT, fill=tk.Y)
            options_listbox.config(yscrollcommand=options_scroll.set)
            # populate from CUSTOM_BUILDER names
            option_names = []
            for entry in CUSTOM_BUILDER:
                # each entry is a dict with single key
                try:
                    name = list(entry.keys())[0]
                    option_names.append(name)
                    options_listbox.insert(tk.END, name)
                except Exception:
                    pass

            add_btn = ttk.Button(right_frame, text="<- Add", state="normal")
            add_btn.pack(side=tk.TOP, fill=tk.X, pady=(6,2))
            make_parallel_btn = ttk.Button(right_frame, text="Add Parallel to Selected Slot", state="normal")
            make_parallel_btn.pack(side=tk.TOP, fill=tk.X, pady=(2,6))

            # center editor widgets (populated when a step is selected)
            editor_title = ttk.Label(center_frame, text="Step Editor")
            editor_title.pack(anchor=tk.W)
            # A dedicated content area for dynamic editor widgets so placeholders
            # and buttons remain fixed below it.
            center_content = ttk.Frame(center_frame)
            center_content.pack(fill=tk.BOTH, expand=True)

            # Placeholders: always-visible reference area in the center column
            try:
                ph_text = (
                    "%user% - redeemer username\n"
                    "%reward% - reward name\n"
                    "%channel% - channel name\n"
                    "%viewers% - current viewer count\n"
                    "%followers% - current follower count\n"
                    "%subscribers% - current subscriber count\n"
                    "%title% - current stream title\n"
                    "%game% - current game\n"
                    "%message% - message content (if applicable)\n"
                    "%bits% - number of bits cheered (if applicable)\n"
                    "%rng% - random number\n"
                    "%rng:min-max% - random number between min and max"
                )
                # bottom_static will hold placeholders above the center buttons
                bottom_static = ttk.Frame(center_frame)
                bottom_static.pack(side=tk.BOTTOM, fill=tk.X, pady=(8,4))
                ph_label = tk.Label(bottom_static, text=ph_text, justify=tk.CENTER, anchor='center')
                try:
                    ph_label.configure(wraplength=300)
                except Exception:
                    pass
                ph_label.pack(fill=tk.X, padx=4)
            except Exception:
                bottom_static = None
                pass
            editor_widgets = {}

            def _step_identifier(meta: dict | None, name: str | None) -> str:
                """Return a stable identifier for a builder step so duplicates can be detected."""
                if meta and meta.get("code"):
                    return str(meta.get("code"))
                return name or ""

            def _reset_center_editor(message: str | None = "Select a step to edit") -> None:
                """Clear the center editor and optionally show a placeholder message."""
                for w in center_content.winfo_children():
                    w.destroy()
                editor_widgets.clear()
                if message:
                    ttk.Label(center_content, text=message).pack(anchor=tk.W)

            _reset_center_editor()

            # Data model for slots: list of slots, each slot is list of 1-2 step dicts
            slots: list = []

            def render_slots():
                # redraw left_frame content
                for w in left_frame.winfo_children():
                    w.destroy()
                for si, slot in enumerate(slots):
                    slot_frame = ttk.Frame(left_frame, relief="groove", borderwidth=1)
                    slot_frame.pack(fill=tk.X, pady=4, padx=2)
                    # container for up to 2 blocks
                    for bi, step in enumerate(slot):
                        # fixed-size block so left column remains uniform
                        # make blocks share available space so widths are uniform
                        block = ttk.Frame(slot_frame, relief="ridge", borderwidth=2)
                        block.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=4, pady=4)
                        # Allow removing an individual step directly from the slot.
                        ttk.Button(
                            block,
                            text="X",
                            width=2,
                            command=lambda s=si, b=bi: remove_step(s, b),
                        ).pack(anchor=tk.NE, padx=2, pady=2)
                        lbl = ttk.Label(block, text=step.get("name", ""), wraplength=260, justify=tk.LEFT)
                        lbl.pack(anchor=tk.W, padx=4, pady=2, fill=tk.BOTH, expand=True)
                        # visually indicate selection
                        try:
                            if selected_slot.get("sidx") == si and selected_slot.get("bidx") == bi:
                                block.config(style="Selected.TFrame")
                        except Exception:
                            pass
                        # store slot/bi index on the widget for click handler
                        def make_on_click(sidx=si, bidx=bi):
                            def _on_click(evt=None):
                                select_step(sidx, bidx)
                            return _on_click
                        block.bind("<Button-1>", make_on_click())
                        lbl.bind("<Button-1>", make_on_click())
                    # if slot has only one block, show placeholder to allow parallel drop
                    if len(slot) == 1:
                        spacer = ttk.Frame(slot_frame)
                        spacer.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=4, pady=4)
                    # Move Up/Down controls for slot ordering
                    ctrl = ttk.Frame(slot_frame)
                    ctrl.pack(side=tk.RIGHT, padx=4)
                    def _move_up(sidx=si):
                        if sidx <= 0:
                            return
                        slots[sidx - 1], slots[sidx] = slots[sidx], slots[sidx - 1]
                        selected_slot["sidx"] = max(0, selected_slot.get("sidx") - 1) if selected_slot.get("sidx") is not None else None
                        render_slots()
                    def _move_down(sidx=si):
                        if sidx >= len(slots) - 1:
                            return
                        slots[sidx + 1], slots[sidx] = slots[sidx], slots[sidx + 1]
                        selected_slot["sidx"] = selected_slot.get("sidx") + 1 if selected_slot.get("sidx") is not None else None
                        render_slots()
                    ttk.Button(ctrl, text="↑", width=2, command=lambda s=si: _move_up(s)).pack(side=tk.TOP, pady=2)
                    ttk.Button(ctrl, text="↓", width=2, command=lambda s=si: _move_down(s)).pack(side=tk.TOP, pady=2)

            selected_slot = {"sidx": None, "bidx": None}

            def select_step(sidx: int, bidx: int):
                # set selection and populate center editor
                selected_slot["sidx"] = sidx
                selected_slot["bidx"] = bidx
                step = slots[sidx][bidx]
                # clear only the dynamic content area (keep title, placeholders, buttons)
                _reset_center_editor(message=None)
                ttk.Label(center_content, text=f"Editing: {step.get('name')}").pack(anchor=tk.W)
                meta = step.get("meta", {})
                # input field
                input_type = meta.get("input")
                if input_type is not None:
                    input_label_text = meta.get("input_label")
                    if not input_label_text:
                        if input_type == str:
                            input_label_text = "Enter the text value:"
                        elif input_type == int:
                            input_label_text = "Enter the numeric value:"
                        else:
                            input_label_text = "Input:"
                    ttk.Label(center_content, text=input_label_text).pack(anchor=tk.W, pady=(6,0))
                    if input_type == str:
                        # use a ScrolledText for multi-line input and make it fill the content area
                        txt = ScrolledText(center_content, height=6, wrap=tk.WORD)
                        txt.pack(fill=tk.X, expand=False)
                        if step.get("input") is not None:
                            try:
                                txt.insert(tk.END, str(step.get("input")))
                            except Exception:
                                pass
                        editor_widgets["input"] = txt
                    elif input_type == int:
                        ent = ttk.Entry(center_content)
                        ent.pack(fill=tk.X)
                        if step.get("input") is not None:
                            ent.insert(0, str(step.get("input")))
                        editor_widgets["input"] = ent
                    else:
                        # fallback for other types if ever added
                        ent = ttk.Entry(center_content)
                        ent.pack(fill=tk.X)
                        if step.get("input") is not None:
                            ent.insert(0, str(step.get("input")))
                        editor_widgets["input"] = ent
                else:
                    ttk.Label(center_content, text="No input required for this step").pack(anchor=tk.W)
                    editor_widgets.pop("input", None)

                if meta.get("requires_user_message"):
                    hint = meta.get("user_message_hint") or "This step also reads the viewer's redemption message (first word is treated as the target)."
                    ttk.Label(
                        center_content,
                        text=hint,
                        wraplength=320,
                        foreground="#555555",
                        justify=tk.LEFT,
                    ).pack(anchor=tk.W, pady=(6, 0))

                # boolean options
                bool_vars = {}
                for k, v in meta.items():
                    if k in ("code", "input", "code w/ true", "forced_input", "voiced", "requires_user_message"):
                        # skip internal/forced keys and the special `voiced` flag
                        continue
                    # meta may use the `bool` type as a marker; accept either bool instances or `bool` type
                    if v is bool or isinstance(v, bool):
                        var = tk.BooleanVar(value=step.get("bools", {}).get(k, False))
                        cb = ttk.Checkbutton(center_content, text=k, variable=var)
                        cb.pack(anchor=tk.W, pady=(4,0))
                        bool_vars[k] = var
                editor_widgets["bools"] = bool_vars

                # save step edits button
                def save_step_edits():
                    try:
                        if "input" in editor_widgets:
                            # support both Entry (no args) and ScrolledText (requires indices)
                            w = editor_widgets["input"]
                            try:
                                val = w.get("1.0", tk.END).rstrip("\n")
                            except Exception:
                                try:
                                    val = w.get().strip()
                                except Exception:
                                    val = ""
                            # Validation: required and type
                            if meta.get("input") is not None:
                                if val == "":
                                    messagebox.showerror("Input Required", "This action requires an input value.", parent=dlg)
                                    return
                                if meta.get("input") == int:
                                    try:
                                        ival = int(val)
                                    except Exception:
                                        messagebox.showerror("Invalid Input", "Please enter a valid integer.", parent=dlg)
                                        return
                                    slots[selected_slot["sidx"]][selected_slot["bidx"]]["input"] = ival
                                else:
                                    slots[selected_slot["sidx"]][selected_slot["bidx"]]["input"] = val
                            else:
                                # no input expected
                                if val == "":
                                    slots[selected_slot["sidx"]][selected_slot["bidx"]]["input"] = None
                                else:
                                    slots[selected_slot["sidx"]][selected_slot["bidx"]]["input"] = val
                        # bools
                        bv = {}
                        for bn, var in editor_widgets.get("bools", {}).items():
                            bv[bn] = bool(var.get())
                        slots[selected_slot["sidx"]][selected_slot["bidx"]]["bools"] = bv
                        # play a feedback sound and unselect the edited block
                        try:
                            dlg.bell()
                        except Exception:
                            pass
                        selected_slot["sidx"] = None
                        selected_slot["bidx"] = None
                        _reset_center_editor()
                        render_slots()
                    except Exception:
                        pass

                ttk.Button(center_content, text="Save Step", command=save_step_edits).pack(pady=(8,0))

            def remove_step(sidx: int, bidx: int) -> None:
                """Remove a step from the specified slot and refresh UI."""
                if sidx < 0 or sidx >= len(slots):
                    return
                slot = slots[sidx]
                if bidx < 0 or bidx >= len(slot):
                    return

                removing_selected = (
                    selected_slot["sidx"] == sidx and selected_slot["bidx"] == bidx
                )

                slot.pop(bidx)
                slot_empty = len(slot) == 0
                if slot_empty:
                    slots.pop(sidx)

                if selected_slot["sidx"] is not None:
                    if slot_empty and selected_slot["sidx"] == sidx:
                        selected_slot["sidx"] = None
                        selected_slot["bidx"] = None
                    elif selected_slot["sidx"] == sidx:
                        if removing_selected:
                            selected_slot["sidx"] = None
                            selected_slot["bidx"] = None
                        elif selected_slot["bidx"] > bidx:
                            selected_slot["bidx"] -= 1
                        elif selected_slot["bidx"] >= len(slot):
                            selected_slot["bidx"] = max(0, len(slot) - 1)
                    elif selected_slot["sidx"] > sidx:
                        selected_slot["sidx"] -= 1

                if removing_selected or selected_slot["sidx"] is None:
                    _reset_center_editor()

                render_slots()

            def add_option_to_slots(as_parallel_slot: int | None = None):
                # add selected option from options_listbox; if as_parallel_slot is not None, add as second block
                sel = options_listbox.curselection()
                if not sel:
                    return
                name = option_names[sel[0]]
                meta = None
                for e in CUSTOM_BUILDER:
                    if list(e.keys())[0] == name:
                        meta = e[name]
                        break
                if meta is None:
                    return
                # enforce max 10 slots
                total_slots = len(slots)
                if as_parallel_slot is None and total_slots >= 10:
                    messagebox.showerror("Limit", "Maximum of 10 steps/slots allowed.", parent=dlg)
                    return
                # create step dict
                step = {"name": name, "meta": meta, "input": None, "bools": {}}
                if as_parallel_slot is not None:
                    # add as second block into that slot if possible
                    if 0 <= as_parallel_slot < len(slots) and len(slots[as_parallel_slot]) == 1:
                        # Prevent placing two voiced steps into the same parallel slot
                        try:
                            existing_meta = slots[as_parallel_slot][0].get("meta", {})
                            if existing_meta.get("voiced") and meta.get("voiced"):
                                messagebox.showerror("Voiced Conflict", "Cannot place two voiced steps in the same parallel slot.", parent=dlg)
                                return
                        except Exception:
                            pass
                        existing_ids = {
                            _step_identifier(existing_step.get("meta"), existing_step.get("name"))
                            for existing_step in slots[as_parallel_slot]
                        }
                        new_id = _step_identifier(meta, name)
                        if new_id in existing_ids:
                            messagebox.showerror(
                                "Duplicate",
                                "Cannot place two of the same action in the same step.",
                                parent=dlg,
                            )
                            return
                        slots[as_parallel_slot].append(step)
                    else:
                        messagebox.showerror("Parallel", "Cannot add parallel step here.", parent=dlg)
                else:
                    slots.append([step])
                # auto-select the newly added block and open editor
                try:
                    new_sidx = len(slots) - 1 if as_parallel_slot is None else as_parallel_slot
                    new_bidx = 0 if as_parallel_slot is None else len(slots[as_parallel_slot]) - 1
                    selected_slot["sidx"] = new_sidx
                    selected_slot["bidx"] = new_bidx
                    render_slots()
                    # ensure editor is populated for the new selection
                    select_step(new_sidx, new_bidx)
                except Exception:
                    render_slots()

            add_btn.config(command=lambda: add_option_to_slots(None))
            make_parallel_btn.config(command=lambda: add_option_to_slots(selected_slot["sidx"]))

            # If editing, load existing code and inputs into slots
            if mode == "edit" and target_row:
                # fetch full row from DB by id to get code and inputs
                try:
                    conn = self.connect()
                    cur = conn.execute("SELECT * FROM custom_rewards WHERE id = ?", (int(target_id),))
                    row = cur.fetchone()
                except Exception:
                    row = None
                finally:
                    try:
                        if conn:
                            conn.close()
                    except Exception:
                        pass
                if row:
                    code = row["code"] if "code" in row.keys() else row["reward_code"] if "reward_code" in row.keys() else row[2]
                    # build list of inputs from input1..input10
                    inputs = []
                    for i in range(1, 11):
                        key = f"input{i}"
                        try:
                            inputs.append(row[key])
                        except Exception:
                            inputs.append(None)
                    # decode code into slots using same separators (:: and ++)
                    try:
                        seq = str(code).split("::") if code else []
                        inp_idx = 0
                        for token in seq:
                            parts = token.split("++")
                            slot = []
                            for p in parts:
                                # find builder entry matching code or code w/ true
                                found_name = None
                                found_meta = None
                                for e in CUSTOM_BUILDER:
                                    n = list(e.keys())[0]
                                    m = e[n]
                                    c = m.get("code")
                                    c_true = m.get("code w/ true")
                                    if p == c or (c_true and p == c_true):
                                        found_name = n
                                        found_meta = m
                                        break
                                step = {"name": found_name or p, "meta": found_meta or {"code": p}, "input": None, "bools": {}}
                                # assign input if meta requires or forced_input
                                if found_meta:
                                    if found_meta.get("forced_input") is not None:
                                        step["input"] = found_meta.get("forced_input")
                                    elif found_meta.get("input") is not None:
                                        # consume from inputs list
                                        if inp_idx < len(inputs):
                                            step["input"] = inputs[inp_idx]
                                            inp_idx += 1
                                        else:
                                            step["input"] = None
                                    # If this token used the alternate "code w/ true" variant,
                                    # populate the corresponding boolean flag so the checkbox shows checked.
                                    try:
                                        c_true = found_meta.get("code w/ true")
                                        if c_true and p == c_true:
                                            # find any bool-named keys in meta and mark them True
                                            for bk, bv in found_meta.items():
                                                if (bv is bool) or isinstance(bv, bool):
                                                    step.setdefault("bools", {})[bk] = True
                                        else:
                                            # ensure bool keys exist (unchecked) so UI can read them
                                            for bk, bv in found_meta.items():
                                                if (bv is bool) or isinstance(bv, bool):
                                                    step.setdefault("bools", {}).setdefault(bk, False)
                                    except Exception:
                                        pass
                                slot.append(step)
                            slots.append(slot)
                        # capture bit threshold for editing so the meta dialog can prefill
                        try:
                            bt_raw = row.get("bit_threshold") if isinstance(row, dict) or hasattr(row, 'keys') else None
                            if bt_raw is None:
                                bits_threshold_value = ""
                            else:
                                bits_threshold_value = str(bt_raw)
                        except Exception:
                            try:
                                # fallback attempt
                                bits_threshold_value = str(row["bit_threshold"]) if row and "bit_threshold" in row.keys() else ""
                            except Exception:
                                bits_threshold_value = ""
                    except Exception:
                        pass
                render_slots()

            # Save handler: encode slots -> code and inputs and insert/update DB
            def _save_all():
                if not slots:
                    messagebox.showerror(
                        "No Steps",
                        "Add at least one step before saving this redemption.",
                        parent=dlg,
                    )
                    return
                # name, redemption_type, description fields
                # Prefill dialogs with existing values when editing
                default_name = ""
                default_description = ""
                default_type = "channel_points"
                try:
                    if mode == "edit":
                        if target_row:
                            default_name = target_row.get("name") or ""
                            default_description = target_row.get("description") or ""
                        # prefer explicit target_type (bits/channel_points) if available
                        if 'target_type' in locals() and target_type:
                            default_type = target_type or default_type
                        else:
                            # fallback to any redemption_type stored on the shallow target_row
                            default_type = (target_row.get("redemption_type") if target_row and isinstance(target_row, dict) else None) or default_type
                except Exception:
                    pass

                # Use a custom modal dialog so we can provide a combobox for type selection
                name = None
                redemption_type = "channel_points"
                description = ""

                def _open_meta_dialog():
                    nonlocal name, redemption_type, description
                    meta = tk.Toplevel(dlg)
                    meta.transient(dlg)
                    meta.grab_set()
                    meta.title("Redemption Metadata")
                    # center smaller dialog relative to parent
                    try:
                        meta.geometry("480x260")
                    except Exception:
                        pass

                    ttk.Label(meta, text="Name:").pack(anchor=tk.W, padx=8, pady=(8,0))
                    name_var = tk.StringVar(value=default_name)
                    name_ent = ttk.Entry(meta, textvariable=name_var)
                    name_ent.pack(fill=tk.X, padx=8, pady=(0,6))

                    ttk.Label(meta, text="Type:").pack(anchor=tk.W, padx=8)
                    type_display_map = {"Bit Donation": "bits", "Channel Point Reward": "channel_points"}
                    inv_map = {v: k for k, v in type_display_map.items()}
                    type_var = tk.StringVar(value=inv_map.get(default_type, "Channel Point Reward"))
                    type_combo = ttk.Combobox(meta, values=list(type_display_map.keys()), textvariable=type_var, state="readonly")
                    type_combo.pack(fill=tk.X, padx=8, pady=(0,6))

                    ttk.Label(meta, text="Description:").pack(anchor=tk.W, padx=8)
                    desc_txt = ScrolledText(meta, height=6, wrap=tk.WORD)
                    desc_txt.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 6))
                    # Bits threshold value holder (widget will be created inside button row)
                    bits_var = tk.StringVar(value=bits_threshold_value)
                    try:
                        desc_txt.insert(tk.END, default_description)
                    except Exception:
                        pass

                    btn_frame = ttk.Frame(meta)
                    btn_frame.pack(fill=tk.X, padx=8, pady=6)

                    # left container for bits threshold (so it appears on the left of the buttons)
                    left_container = ttk.Frame(btn_frame)
                    left_container.pack(side=tk.LEFT, anchor=tk.W)

                    # create bits_frame as a child of left_container so it will be visible on the same row
                    bits_frame = ttk.Frame(left_container)
                    ttk.Label(bits_frame, text="Bits Threshold:").pack(anchor=tk.W, side=tk.LEFT)
                    bits_ent = ttk.Entry(bits_frame, textvariable=bits_var, width=12)
                    bits_ent.pack(side=tk.LEFT, padx=(6,0))
                    def _on_meta_ok():
                        nonlocal name, redemption_type, description, bits_threshold_value
                        nm = name_var.get().strip()
                        if not nm:
                            messagebox.showerror("Missing", "Name is required.", parent=meta)
                            return
                        disp = type_var.get()
                        redemption_type = type_display_map.get(disp, "channel_points")
                        description = desc_txt.get("1.0", tk.END).rstrip("\n")
                        # validate bits threshold if applicable
                        if redemption_type == "bits":
                            bt = bits_var.get().strip()
                            if not bt:
                                messagebox.showerror("Missing", "Bits Threshold is required for Bit Donation.", parent=meta)
                                return
                            try:
                                # accept integer value
                                int(bt)
                            except Exception:
                                messagebox.showerror("Invalid", "Bits Threshold must be an integer.", parent=meta)
                                return
                            bits_threshold_value = bt

                        name = nm
                        try:
                            meta.destroy()
                        except Exception:
                            pass

                    def _on_meta_cancel():
                        try:
                            meta.destroy()
                        except Exception:
                            pass

                    # Swap positions: Cancel on the right, OK to its left (user requested swapped order)
                    ttk.Button(btn_frame, text="Cancel", command=_on_meta_cancel).pack(side=tk.RIGHT)
                    ttk.Button(btn_frame, text="OK", command=_on_meta_ok).pack(side=tk.RIGHT, padx=(4,0))

                    # show/hide bits_frame when type changes; pack into left_container when shown
                    def _on_type_change(event=None):
                        try:
                            sel = type_var.get()
                            if sel == "Bit Donation":
                                if not bits_frame.winfo_ismapped():
                                    bits_frame.pack(in_=left_container, side=tk.LEFT, padx=(0, 8))
                            else:
                                if bits_frame.winfo_ismapped():
                                    bits_frame.pack_forget()
                        except Exception:
                            pass

                    type_combo.bind('<<ComboboxSelected>>', _on_type_change)
                    # ensure initial visibility matches default selection
                    _on_type_change()
                    # center window and focus
                    try:
                        self.center_window(meta)
                    except Exception:
                        pass
                    name_ent.focus_set()
                    meta.wait_window()

                _open_meta_dialog()
                if not name:
                    # user cancelled or did not provide a name
                    return

                # Validate all step inputs before building code/inputs
                for si, slot in enumerate(slots):
                    for bi, s in enumerate(slot):
                        meta = s.get("meta", {})
                        if meta.get("input") is not None:
                            val = s.get("input")
                            if val is None or (isinstance(val, str) and val.strip() == ""):
                                messagebox.showerror("Missing Input", "One or more steps require an input. Please fill required inputs.", parent=dlg)
                                # select the offending step so user can fix it
                                try:
                                    selected_slot["sidx"] = si
                                    selected_slot["bidx"] = bi
                                    render_slots()
                                    select_step(si, bi)
                                except Exception:
                                    pass
                                return
                            if meta.get("input") == int:
                                # ensure it's an int (allow strings that convert)
                                try:
                                    if isinstance(val, str):
                                        int(val)
                                except Exception:
                                    messagebox.showerror("Invalid Input", "One or more integer inputs are invalid. Please enter valid integers.", parent=dlg)
                                    try:
                                        selected_slot["sidx"] = si
                                        selected_slot["bidx"] = bi
                                        render_slots()
                                        select_step(si, bi)
                                    except Exception:
                                        pass
                                    return

                # build code and inputs
                tokens = []
                inputs_flat: list = []
                for slot in slots:
                    if len(slot) == 1:
                        s = slot[0]
                        meta = s.get("meta", {})
                        code = meta.get("code")
                        # handle bools that change code
                        for bn, bv in s.get("bools", {}).items():
                            # if meta defines an alternate code for true, use it
                            if bv and meta.get("code w/ true"):
                                code = meta.get("code w/ true")
                        tokens.append(code)
                        # inputs: only store values for steps that require a user-provided input.
                        # Steps with a `forced_input` (e.g. "<user_input>") are runtime-provided
                        # and must NOT consume an input slot in the DB; storing them here
                        # caused later inputs to shift left during decode.
                        if meta.get("input") is not None:
                            inputs_flat.append(s.get("input"))
                    elif len(slot) == 2:
                        parts = []
                        for s in slot:
                            meta = s.get("meta", {})
                            code = meta.get("code")
                            for bn, bv in s.get("bools", {}).items():
                                if bv and meta.get("code w/ true"):
                                    code = meta.get("code w/ true")
                            parts.append(code)
                            # for parallel steps only store user-provided inputs
                            if meta.get("input") is not None:
                                inputs_flat.append(s.get("input"))
                        tokens.append("++".join(parts))
                code_str = "::".join(tokens)
                # pad inputs to 10
                inputs_flat = inputs_flat[:10]
                while len(inputs_flat) < 10:
                    inputs_flat.append(None)

                # persist
                try:
                    conn = self.connect()
                    if mode == "add":
                        # New redemptions default to disabled
                        cols = ["redemption_type", "bit_threshold", "name", "description", "code", "is_enabled"] + [f"input{i}" for i in range(1, 11)]
                        try:
                            bt_val = int(bits_threshold_value) if bits_threshold_value and str(bits_threshold_value).strip() != "" else 0
                        except Exception:
                            bt_val = 0
                        vals = [redemption_type, bt_val, name, description, code_str, 0] + inputs_flat
                        placeholders = ",".join(["?"] * len(vals))
                        conn.execute(f"INSERT INTO custom_rewards ({','.join(cols)}) VALUES ({placeholders})", tuple(vals))
                    else:
                        # update existing
                        if not target_id:
                            messagebox.showerror("Edit", "Missing target id for edit.", parent=dlg)
                            return
                        set_parts = ["redemption_type = ?", "bit_threshold = ?", "name = ?", "description = ?", "code = ?"] + [f"input{i} = ?" for i in range(1, 11)]
                        try:
                            bt_val = int(bits_threshold_value) if bits_threshold_value and str(bits_threshold_value).strip() != "" else 0
                        except Exception:
                            bt_val = 0
                        vals = [redemption_type, bt_val, name, description, code_str] + inputs_flat + [int(target_id)]
                        conn.execute(f"UPDATE custom_rewards SET {', '.join(set_parts)} WHERE id = ?", tuple(vals))
                    conn.commit()
                except Exception as e:
                    messagebox.showerror("DB", f"Failed to save: {e}", parent=dlg)
                finally:
                    try:
                        if conn:
                            conn.close()
                    except Exception:
                        pass

                # feedback sound on successful save
                try:
                    dlg.bell()
                except Exception:
                    pass

                # refresh UI lists and close
                try:
                    self.refresh_randomizer_lists()
                except Exception:
                    pass
                try:
                    # refresh custom list in background to avoid blocking UI
                    threading.Thread(target=self.refresh_custom_redemptions, daemon=True).start()
                except Exception:
                    pass
                dlg.destroy()

            # Place Save/Cancel in the center editor area below the placeholders
            try:
                # place center buttons inside bottom_static (so they appear below placeholders)
                if bottom_static is not None:
                    center_btn_row = ttk.Frame(bottom_static)
                    center_btn_row.pack(side=tk.BOTTOM, fill=tk.X, pady=(6,4))
                else:
                    center_btn_row = ttk.Frame(center_frame)
                    center_btn_row.pack(side=tk.BOTTOM, fill=tk.X, pady=(6,4))
                c_sp_left = ttk.Frame(center_btn_row)
                c_sp_left.pack(side=tk.LEFT, expand=True)
                save_btn = ttk.Button(center_btn_row, text="Save", command=_save_all)
                save_btn.pack(side=tk.LEFT, padx=6)
                ttk.Button(center_btn_row, text="Cancel", command=dlg.destroy).pack(side=tk.LEFT, padx=6)
                c_sp_right = ttk.Frame(center_btn_row)
                c_sp_right.pack(side=tk.LEFT, expand=True)
            except Exception:
                # fallback: create bottom buttons on dialog if center_frame unavailable
                try:
                    btn_row = ttk.Frame(dlg)
                    btn_row.pack(side=tk.BOTTOM, fill=tk.X, pady=6)
                    spacer = ttk.Frame(btn_row)
                    spacer.pack(side=tk.LEFT, expand=True)
                    save_btn = ttk.Button(btn_row, text="Save", command=_save_all)
                    save_btn.pack(side=tk.LEFT, padx=6)
                    ttk.Button(btn_row, text="Cancel", command=dlg.destroy).pack(side=tk.LEFT, padx=6)
                    spacer2 = ttk.Frame(btn_row)
                    spacer2.pack(side=tk.LEFT, expand=True)
                except Exception:
                    pass

            # initial render and placeholder
            render_slots()
            shared = self.frames.get("custom_desc")
            if shared:
                shared.configure(state="normal")
                shared.delete("1.0", tk.END)
                shared.insert(tk.END, "(No description)")
                shared.configure(state="disabled")

            # center the dialog
            try:
                self.center_window(dlg)
            except Exception:
                pass

        except Exception as e:
            debug_print("GUI", f"open_custom_redemption_editor error: {e}")

        # Console tab was created earlier to capture startup logs

            # NOTE: bot start is scheduled from main() so it isn't tied to
            # opening the custom redemption editor.

    def center_window(self, win: tk.Toplevel) -> None:
        """Center a Toplevel window over the main application window.

        This computes the main window's position/size and places the dialog
        so it's centered over the parent. Use after widgets have been added
        so the dialog has a realistic requested size.
        """
        try:
            self.update_idletasks()
            win.update_idletasks()
            px = self.winfo_rootx()
            py = self.winfo_rooty()
            pw = self.winfo_width()
            ph = self.winfo_height()
            ww = win.winfo_width() or win.winfo_reqwidth()
            wh = win.winfo_height() or win.winfo_reqheight()
            x = px + max(0, (pw - ww) // 2)
            y = py + max(0, (ph - wh) // 2)
            win.geometry(f"+{x}+{y}")
        except Exception:
            # best-effort; ignore failures so dialogs still appear
            pass

    def _evaluate_google_credentials(self) -> None:
        """Validate credentials.json and disable Google Sheets integration when invalid."""
        required_keys = ("type", "project_id", "private_key_id", "private_key")
        credential_path = path_from_app_root("credentials.json")
        is_valid = True
        message = ""

        if not credential_path.exists():
            is_valid = False
            message = "Google Sheets credentials.json is missing. Integration disabled until the file is added."
        else:
            try:
                with open(credential_path, "r", encoding="utf-8") as cred_file:
                    payload = json.load(cred_file)
                if not isinstance(payload, dict):
                    raise ValueError("Root JSON value must be an object.")
                missing = [key for key in required_keys if not payload.get(key)]
                if missing:
                    is_valid = False
                    message = f"Missing credential fields: {', '.join(missing)}."
            except Exception as exc:
                is_valid = False
                message = f"Unable to read credentials.json ({exc})."

        self._google_credentials_valid = is_valid
        self._google_credentials_error = message

        if not is_valid:
            self._force_disable_google_setting(
                "Google Sheets Integration Enabled",
                message or "Google Sheets credentials.json is missing or invalid."
            )
        else:
            debug_print("GUI", "Google Sheets credentials validated; integration checkbox enabled.")

    def _force_disable_google_setting(self, key: str, reason: str) -> None:
        """Persist a disabled value for a setting when prerequisites are not met."""
        conn = None
        try:
            conn = self.connect()
            try:
                cur = conn.execute("SELECT value FROM settings WHERE key = ?", (key,))
                row = cur.fetchone()
            except sqlite3.Error as exc:
                debug_print("GUI", f"Unable to read setting '{key}': {exc}")
                return

            if row is None:
                debug_print("GUI", f"Setting '{key}' not found while enforcing Google Sheets requirement.")
                return

            try:
                current_val = str(row["value"])
            except Exception:
                current_val = str(row[0]) if len(row) else ""

            if current_val in ("0", "False", "false"):
                debug_print("GUI", f"'{key}' already disabled due to invalid credentials.")
                return

            conn.execute(
                "UPDATE settings SET value = '0', data_type = 'BOOL' WHERE key = ?",
                (key,),
            )
            conn.commit()
            debug_print("GUI", f"Automatically disabled '{key}': {reason}")
        except sqlite3.Error as exc:
            debug_print("GUI", f"Unable to disable '{key}': {exc}")
        except Exception as exc:
            debug_print("GUI", f"Unexpected error disabling '{key}': {exc}")
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
        

    def _build_table_frame(self, parent: ttk.Frame, table_name: str) -> None:
        toolbar = ttk.Frame(parent)
        toolbar.pack(fill=tk.X)

        btn_refresh = ttk.Button(toolbar, text="Refresh", command=lambda: self.refresh_table(table_name))
        btn_refresh.pack(side=tk.LEFT, padx=4, pady=4)

        btn_add = None
        if table_name != "settings":
            btn_add = ttk.Button(toolbar, text="Add", command=lambda: self.open_edit_dialog(table_name))
            btn_add.pack(side=tk.LEFT, padx=4, pady=4)

        btn_edit = ttk.Button(toolbar, text="Edit", command=lambda: self.edit_selected_row(table_name))
        btn_edit.pack(side=tk.LEFT, padx=4, pady=4)

        # Prompts tab uses a specialized Listbox + editor UI and does not
        # support the generic "Edit" flow; remove the Edit button for that tab.
        if table_name == "prompts":
            try:
                btn_edit.destroy()
            except Exception:
                try:
                    btn_edit.pack_forget()
                except Exception:
                    pass

        if table_name != "settings":
            btn_delete = ttk.Button(toolbar, text="Delete", command=lambda: self.delete_selected_row(table_name))
            btn_delete.pack(side=tk.LEFT, padx=4, pady=4)

        # Special UI for prompts: left list of names, right large editable prompt text
        if table_name == "prompts":
            container = ttk.Frame(parent)
            container.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

            left = ttk.Frame(container)
            left.pack(side=tk.LEFT, fill=tk.Y)
            lbl_list = ttk.Label(left, text="Prompts")
            lbl_list.pack(anchor=tk.W)
            lb_frame = ttk.Frame(left)
            lb_frame.pack(fill=tk.Y, expand=True)
            lb_scroll = ttk.Scrollbar(lb_frame, orient=tk.VERTICAL)
            listbox = tk.Listbox(
                lb_frame,
                yscrollcommand=lb_scroll.set,
                width=30,
                exportselection=False,
            )
            lb_scroll.config(command=listbox.yview)
            lb_scroll.pack(side=tk.RIGHT, fill=tk.Y)
            listbox.pack(side=tk.LEFT, fill=tk.Y, expand=True)

            right = ttk.Frame(container)
            right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(8,0))
            lbl = ttk.Label(right, text="Prompt Text")
            lbl.pack(anchor=tk.W)
            prompt_text = ScrolledText(right, wrap=tk.WORD)
            prompt_text.pack(fill=tk.BOTH, expand=True)

            btn_frame = ttk.Frame(right)
            btn_frame.pack(fill=tk.X, pady=(6,0))
            def _save_prompt():
                sel = listbox.curselection()
                if not sel:
                    messagebox.showinfo("Save", "Select a prompt to save", parent=self)
                    return
                idx = sel[0]
                rows = self.frames.get("prompts_rows", [])
                if idx < 0 or idx >= len(rows):
                    return
                row = rows[idx]
                pid = row.get("id")
                new_text = prompt_text.get("1.0", tk.END).rstrip("\n")
                self.frames["prompts_selected_id"] = pid
                conn = self.connect()
                try:
                    conn.execute("UPDATE prompts SET prompt = ? WHERE id = ?", (new_text, pid))
                    conn.commit()
                finally:
                    conn.close()
                self.refresh_table("prompts")

            ttk.Button(btn_frame, text="Save", command=_save_prompt).pack(side=tk.LEFT)

            # selection handler
            def _on_select(evt):
                sel = listbox.curselection()
                if not sel:
                    prompt_text.configure(state="normal")
                    prompt_text.delete("1.0", tk.END)
                    prompt_text.configure(state="disabled")
                    return
                idx = sel[0]
                rows = self.frames.get("prompts_rows", [])
                if idx < 0 or idx >= len(rows):
                    return
                row = rows[idx]
                self.frames["prompts_selected_id"] = row.get("id")
                text = row.get("prompt") or ""
                # wrap and set height based on content
                wrapped = textwrap.fill(str(text), width=80)
                lines = wrapped.count("\n") + 1 if wrapped else 1
                prompt_text.configure(state="normal")
                prompt_text.delete("1.0", tk.END)
                prompt_text.insert(tk.END, text)
                prompt_text.configure(state="normal")
                prompt_text.configure(height=min(max(6, lines), 40))

            try:
                listbox.bind("<<ListboxSelect>>", lambda e: _on_select(e))
            except Exception:
                pass

            # store references for refresh_table to populate
            self.frames[table_name + "_listbox"] = listbox
            self.frames[table_name + "_text"] = prompt_text
            self.frames["prompts_rows"] = []
            self.frames["prompts_selected_id"] = None
            # schedule an initial refresh so the listbox is populated after
            # the UI finishes layout (use after to avoid racing during init)
            try:
                self.after(10, lambda tn=table_name: self.refresh_table(tn))
            except Exception:
                try:
                    self.refresh_table(table_name)
                except Exception:
                    pass
            return

        # Treeview
        cols, _, _ = self.get_table_info(table_name)
        tree = ttk.Treeview(parent, columns=cols, show="headings", selectmode="browse")
        for c in cols:
            # For user-friendly display, rename certain column headings in the
            # settings table (don't change underlying column names used by DB).
            heading_text = c
            if table_name == "settings":
                if c.lower() == "key":
                    heading_text = "Setting"
                elif c.lower() == "value":
                    heading_text = "Value"
            tree.heading(c, text=heading_text)
            tree.column(c, width=150, anchor=tk.W)

        # Configure tag styles for alternating rows (odd/even)
        try:
            tree.tag_configure('odd', background='#ffffff')
            tree.tag_configure('even', background='#f6f6f6')
        except Exception:
            # Older tkinter versions or certain themes may ignore tag configs; ignore failures
            pass

        # Don't display the id column in the UI but keep it in the item's values so
        # editing/deleting can still use the id. This keeps internal indexing stable.
        display_cols = [c for c in cols if c.lower() != "id" and c.lower() != "data_type"]
        try:
            tree["displaycolumns"] = display_cols
        except Exception:
            # older tkinter versions may behave differently; ignore failure
            pass

        tree.pack(fill=tk.BOTH, expand=True)
        self.frames[table_name + "_tree"] = tree

        # For commands table, add a preview area below the tree that shows the wrapped response
        preview_widget = None
        if table_name == "commands":
            preview_frame = ttk.Frame(parent)
            preview_frame.pack(fill=tk.X, padx=6, pady=(4, 8))
            lbl = ttk.Label(preview_frame, text="Response preview:")
            lbl.pack(anchor=tk.W)
            preview_widget = ScrolledText(preview_frame, height=3, wrap=tk.WORD, state="disabled")
            preview_widget.pack(fill=tk.X)
            self.frames[table_name + "_preview"] = preview_widget

            # Update preview when a command row is selected
            def _update_commands_preview(event, t=tree, preview=preview_widget):
                try:
                    sel = t.selection()
                    if not sel:
                        if preview:
                            preview.configure(state="normal")
                            preview.delete("1.0", tk.END)
                            preview.configure(state="disabled")
                        return
                    item = t.item(sel[0])
                    vals = item.get("values", [])
                    cols_full, _, _ = self.get_table_info("commands")
                    try:
                        resp_idx = cols_full.index("response")
                        resp = vals[resp_idx] if resp_idx < len(vals) else ""
                    except Exception:
                        resp = ""
                    wrapped = textwrap.fill(str(resp), width=100)
                    lines = wrapped.count("\n") + 1 if wrapped else 1
                    if preview:
                        preview.configure(state="normal")
                        preview.delete("1.0", tk.END)
                        preview.insert(tk.END, wrapped)
                        preview.configure(state="disabled")
                        preview.configure(height=min(max(3, lines), 20))
                except Exception:
                    pass

            try:
                tree.bind("<<TreeviewSelect>>", _update_commands_preview)
            except Exception:
                pass

        # Double-click any row to open the edit dialog for that table (convenience)
        try:
            tree.bind("<Double-1>", lambda e, t=table_name: self.edit_selected_row(t))
        except Exception:
            pass

    # For commands table, allow clicking boolean columns to toggle them inline
        if table_name == "commands":
            def _is_truthy(val):
                return str(val) in ("1", "True", "true")

            def on_tree_click(event, t=tree):
                # identify clicked item and displayed column
                item_id = t.identify_row(event.y)
                if not item_id:
                    return
                col_id = t.identify_column(event.x)  # like '#1'
                try:
                    col_index = int(col_id.lstrip('#')) - 1
                except Exception:
                    return
                # map displayed column index to actual DB column name using displaycolumns
                full_cols = list(t["columns"]) if t["columns"] else []
                disp_cols = list(t["displaycolumns"]) if t["displaycolumns"] else full_cols
                if col_index < 0 or col_index >= len(disp_cols):
                    return
                col_name = disp_cols[col_index]
                if col_name not in ("enabled", "sub_only", "mod_only", "reply_to_user"):
                    return
                vals = t.item(item_id).get("values", [])
                # find command identifier (use command name) from full columns ordering
                try:
                    cmd_idx = full_cols.index("command")
                    cmd_name = vals[cmd_idx]
                except Exception:
                    return

                # perform toggle in DB
                conn = self.connect()
                cur = conn.execute(f"SELECT {col_name}, sub_only, mod_only FROM commands WHERE command = ?", (cmd_name,))
                row = cur.fetchone()
                if not row:
                    return
                cur_val = row[0]
                new_val = 0 if _is_truthy(cur_val) else 1
                # enforce mutual exclusivity: if setting sub_only True, clear mod_only; and vice versa
                if col_name == "sub_only" and new_val == 1:
                    conn.execute("UPDATE commands SET sub_only = ?, mod_only = ? WHERE command = ?", (1, 0, cmd_name))
                elif col_name == "mod_only" and new_val == 1:
                    conn.execute("UPDATE commands SET mod_only = ?, sub_only = ? WHERE command = ?", (1, 0, cmd_name))
                else:
                    conn.execute(f"UPDATE commands SET {col_name} = ? WHERE command = ?", (new_val, cmd_name))
                conn.commit()

                cur2 = conn.execute("SELECT response, enabled, sub_only, mod_only, reply_to_user FROM commands WHERE command = ?", (cmd_name,))
                r2 = cur2.fetchone()
                if not r2:
                    debug_print("GUI", f"No DB row found for {cmd_name}.")
                    return
                
                response, enabled, sub_only, mod_only, reply_to_user = r2

                try:
                    # Prefer runtime bot methods via get_reference; fall back to twitchbot module functions
                    if col_name == "enabled":
                        if new_val == 1:
                            debug_print("GUI", f"Enabling command '{cmd_name}' with values: {response} - {sub_only} - {mod_only} - {reply_to_user}")
                            from twitchbot import add_command as _add_cmd
                            _add_cmd(cmd_name, response, sub_only, mod_only, reply_to_user)
                        else:
                            debug_print("GUI", f"Disabling command '{cmd_name}' (removing from runtime).")
                            from twitchbot import remove_command as _rem_cmd
                            _rem_cmd(cmd_name)
                    elif col_name in ("sub_only", "mod_only", "reply_to_user"):
                        if enabled:
                            debug_print("GUI", f"Re-registering {cmd_name} after {col_name} change")
                            from twitchbot import remove_command as _rem_cmd, add_command as _add_cmd
                            _rem_cmd(cmd_name)
                            _add_cmd(cmd_name, response, sub_only, mod_only, reply_to_user)
                except KeyError:
                    debug_print("GUI", f"Tried to remove '{cmd_name}' but it wasn’t registered yet.")
                    pass
                except Exception as e:
                    debug_print("GUI", f"Error syncing enabled toggle for {cmd_name}: {repr(e)}")
                finally:
                    conn.close()


                # refresh commands table to reflect change
                try:
                    self.refresh_table("commands")
                except Exception:
                    pass

            try:
                tree.bind("<Button-1>", on_tree_click)
            except Exception:
                pass

        # For scheduled_messages table, allow toggling the 'enabled' column inline
        if table_name == "scheduled_messages":
            def _is_truthy(val):
                return str(val) in ("1", "True", "true")

            def on_sched_click(event, t=tree):
                item_id = t.identify_row(event.y)
                if not item_id:
                    return
                col_id = t.identify_column(event.x)
                try:
                    col_index = int(col_id.lstrip('#')) - 1
                except Exception:
                    return
                full_cols = list(t["columns"]) if t["columns"] else []
                disp_cols = list(t["displaycolumns"]) if t["displaycolumns"] else full_cols
                if col_index < 0 or col_index >= len(disp_cols):
                    return
                col_name = disp_cols[col_index]
                if col_name != "enabled":
                    return
                vals = t.item(item_id).get("values", [])
                # find primary key id
                try:
                    id_idx = full_cols.index("id")
                    row_id = vals[id_idx]
                except Exception:
                    return

                conn = self.connect()
                try:
                    cur = conn.execute("SELECT enabled FROM scheduled_messages WHERE id = ?", (row_id,))
                    r = cur.fetchone()
                    if not r:
                        return
                    cur_val = r[0]
                    new_val = 0 if _is_truthy(cur_val) else 1
                    conn.execute("UPDATE scheduled_messages SET enabled = ? WHERE id = ?", (new_val, row_id))
                    conn.commit()
                finally:
                    conn.close()

                # If turned on -> start task; if turned off -> end task
                try:
                    if new_val == 1:
                        debug_print("GUI", f"Starting scheduled message id={row_id}")
                        try:
                            self._scheduler_call_start(int(row_id))
                        except Exception as e:
                            debug_print("GUI", f"Failed to start scheduled message: {e}")
                    else:
                        debug_print("GUI", f"Stopping scheduled message id={row_id}")
                        try:
                            self._scheduler_call_end(int(row_id))
                        except Exception as e:
                            debug_print("GUI", f"Failed to end scheduled message: {e}")
                except Exception:
                    pass

                try:
                    self.refresh_table("scheduled_messages")
                except Exception:
                    pass

            try:
                tree.bind("<Button-1>", on_sched_click)
            except Exception:
                pass

            # selection -> update preview
            def _on_select(event, t=tree, preview=preview_widget):
                sel = t.selection()
                if not sel:
                    if preview:
                        preview.configure(state="normal")
                        preview.delete("1.0", tk.END)
                        preview.configure(state="disabled")
                    return
                item = t.item(sel[0])
                vals = item.get("values", [])
                cols_full, _, _ = self.get_table_info("commands")
                try:
                    resp_idx = cols_full.index("response")
                    resp = vals[resp_idx] if resp_idx < len(vals) else ""
                except Exception:
                    resp = ""
                wrapped = textwrap.fill(str(resp), width=100)
                lines = wrapped.count("\n") + 1 if wrapped else 1
                if preview:
                    preview.configure(state="normal")
                    preview.delete("1.0", tk.END)
                    preview.insert(tk.END, wrapped)
                    preview.configure(state="disabled")
                    preview.configure(height=min(max(3, lines), 20))

            try:
                tree.bind("<<TreeviewSelect>>", _on_select)
            except Exception:
                pass

        # For settings table, add an inline editor area below the tree for quick edits
        if table_name == "settings":
            inline = ttk.Frame(parent)
            inline.pack(fill=tk.X, padx=6, pady=(4, 8))
            self.frames["settings_inline"] = inline

        self.refresh_table(table_name)
        debug_print("GUI", f"Built table frame for '{table_name}' with columns: {cols}")

    def connect(self):
        debug_print("GUI", f"Connecting to database.")
        os.makedirs(os.path.dirname(DB_FILENAME), exist_ok=True)
        conn = sqlite3.connect(DB_FILENAME)
        conn.row_factory = sqlite3.Row
        return conn

    def refresh_custom_redemptions(self) -> None:
        """Refresh the Bits and Channel Points custom redemption lists from DB.

        This is safe to call from background threads; the UI update is scheduled
        onto the main thread via `after(0, ...)`.
        """
        bits_rows = []
        cp_rows = []
        conn = None
        try:
            conn = self.connect()
            # Order by id so the earliest-created row is considered first when enforcing uniqueness
            cur = conn.execute("SELECT id, name, description, is_enabled, bit_threshold FROM custom_rewards WHERE redemption_type = 'bits' ORDER BY id")
            bits_rows = [{"id": r[0], "name": r[1], "description": r[2], "is_enabled": r[3], "bit_threshold": r[4]} for r in cur.fetchall()]
            # Enforce single-enabled-per-threshold invariant: keep the first enabled per threshold, disable others
            try:
                seen = {}
                to_disable = []
                for r in bits_rows:
                    bt = r.get("bit_threshold")
                    is_en = not (str(r.get("is_enabled", 1)) in ("0", "False", "false"))
                    if is_en:
                        if bt in seen:
                            to_disable.append(r.get("id"))
                        else:
                            seen[bt] = r.get("id")
                if to_disable:
                    # disable extras
                    q = ",".join(["?"] * len(to_disable))
                    conn.execute(f"UPDATE custom_rewards SET is_enabled = 0 WHERE id IN ({q})", tuple(to_disable))
                    conn.commit()
                    # reflect in local list
                    for r in bits_rows:
                        if r.get("id") in to_disable:
                            r["is_enabled"] = 0
            except Exception:
                pass
            try:
                def _bits_sort_key(row):
                    bt = row.get("bit_threshold")
                    try:
                        bt_val = int(bt)
                    except Exception:
                        bt_val = None
                    # Place entries with numeric thresholds first (descending), then nulls/invalids using id fallback
                    return (
                        0 if bt_val is not None else 1,
                        -(bt_val if bt_val is not None else 0),
                        row.get("id") or 0,
                    )

                bits_rows.sort(key=_bits_sort_key)
            except Exception:
                pass
            cur2 = conn.execute("SELECT id, name, description, is_enabled FROM custom_rewards WHERE redemption_type = 'channel_points' ORDER BY name")
            cp_rows = [{"id": r[0], "name": r[1], "description": r[2], "is_enabled": r[3]} for r in cur2.fetchall()]
        except Exception:
            bits_rows = []
            cp_rows = []
        finally:
            try:
                if conn:
                    conn.close()
            except Exception:
                pass

        def apply():
            try:
                bits_listbox = self.frames.get("custom_bits_listbox")
                cp_listbox = self.frames.get("custom_cp_listbox")
                shared = self.frames.get("custom_desc")

                self.frames["custom_bits_rows"] = bits_rows
                if bits_listbox:
                    bits_listbox.delete(0, tk.END)
                    for r in bits_rows:
                        name = r.get("name", "")
                        enabled = not (str(r.get("is_enabled", 1)) in ("0", "False", "false"))
                        bt = r.get("bit_threshold")
                        try:
                            bt_display = f" - {int(bt)} Bits" if bt is not None else ""
                        except Exception:
                            bt_display = ""
                        display = f"{name}{bt_display}"
                        if not enabled:
                            display = f"{display} [disabled]"
                        bits_listbox.insert(tk.END, display)
                        # soft highlight: green for enabled, red for disabled
                        try:
                            idx = bits_listbox.size() - 1
                            bg = "#e8f8e8" if enabled else "#ffecec"
                            fg = "#085808" if enabled else "#660000"
                            bits_listbox.itemconfig(idx, bg=bg, fg=fg)
                        except Exception:
                            pass

                self.frames["custom_cp_rows"] = cp_rows
                if cp_listbox:
                    cp_listbox.delete(0, tk.END)
                    for r in cp_rows:
                        name = r.get("name", "")
                        enabled = not (str(r.get("is_enabled", 1)) in ("0", "False", "false"))
                        display = name if enabled else f"{name} [disabled]"
                        cp_listbox.insert(tk.END, display)
                        # soft highlight: green for enabled, red for disabled
                        try:
                            idx = cp_listbox.size() - 1
                            bg = "#e8f8e8" if enabled else "#ffecec"
                            fg = "#085808" if enabled else "#660000"
                            cp_listbox.itemconfig(idx, bg=bg, fg=fg)
                        except Exception:
                            pass

                if shared:
                    shared.configure(state="normal")
                    shared.delete("1.0", tk.END)
                    shared.insert(tk.END, "(No description)")
                    shared.configure(state="disabled")
            except Exception:
                pass

        try:
            self.after(0, apply)
        except Exception:
            apply()

    def delete_selected_custom_redemption(self) -> None:
        """Delete the currently selected custom redemption(s) from the DB and refresh lists.

        This will look at the Bits list first, then the Channel Points list. If nothing
        is selected, the user is prompted to select an item.
        """
        try:
            bits_listbox = self.frames.get("custom_bits_listbox")
            cp_listbox = self.frames.get("custom_cp_listbox")
            bits_rows = self.frames.get("custom_bits_rows", [])
            cp_rows = self.frames.get("custom_cp_rows", [])

            # Prefer bits selection if present
            sel_ids: list[int] = []
            try:
                if bits_listbox:
                    sels = bits_listbox.curselection()
                    for idx in sels:
                        if 0 <= idx < len(bits_rows):
                            rid = bits_rows[idx].get("id")
                            if rid is not None:
                                sel_ids.append(int(rid))
            except Exception:
                pass

            if not sel_ids:
                try:
                    if cp_listbox:
                        sels = cp_listbox.curselection()
                        for idx in sels:
                            if 0 <= idx < len(cp_rows):
                                rid = cp_rows[idx].get("id")
                                if rid is not None:
                                    sel_ids.append(int(rid))
                except Exception:
                    pass

            if not sel_ids:
                messagebox.showinfo("Delete", "Please select a redemption to delete.", parent=self)
                return

            # Confirm
            if len(sel_ids) == 1:
                msg = "Delete selected redemption?"
            else:
                msg = f"Delete {len(sel_ids)} selected redemptions?"
            if not messagebox.askyesno("Delete", msg, parent=self):
                return

            # Perform deletion
            conn = None
            try:
                conn = self.connect()
                for rid in sel_ids:
                    try:
                        conn.execute("DELETE FROM custom_rewards WHERE id = ?", (rid,))
                    except Exception:
                        pass
                conn.commit()
            except Exception as e:
                messagebox.showerror("DB", f"Failed to delete redemption(s): {e}", parent=self)
            finally:
                try:
                    if conn:
                        conn.close()
                except Exception:
                    pass

            # Refresh UI
            try:
                threading.Thread(target=self.refresh_custom_redemptions, daemon=True).start()
            except Exception:
                try:
                    self.refresh_custom_redemptions()
                except Exception:
                    pass
        except Exception as e:
            debug_print("GUI", f"delete_selected_custom_redemption error: {e}")

    def toggle_selected_custom_redemption(self) -> None:
        """Toggle the `is_enabled` flag on the selected custom redemption(s).

        Works like `delete_selected_custom_redemption` for selection semantics.
        """
        try:
            bits_listbox = self.frames.get("custom_bits_listbox")
            cp_listbox = self.frames.get("custom_cp_listbox")
            bits_rows = self.frames.get("custom_bits_rows", [])
            cp_rows = self.frames.get("custom_cp_rows", [])

            sel_ids: list[int] = []
            try:
                if bits_listbox:
                    sels = bits_listbox.curselection()
                    for idx in sels:
                        if 0 <= idx < len(bits_rows):
                            rid = bits_rows[idx].get("id")
                            if rid is not None:
                                sel_ids.append(int(rid))
            except Exception:
                pass

            if not sel_ids:
                try:
                    if cp_listbox:
                        sels = cp_listbox.curselection()
                        for idx in sels:
                            if 0 <= idx < len(cp_rows):
                                rid = cp_rows[idx].get("id")
                                if rid is not None:
                                    sel_ids.append(int(rid))
                except Exception:
                    pass

            if not sel_ids:
                messagebox.showinfo("Enable/Disable", "Please select a redemption to enable/disable.", parent=self)
                return

            conn = None
            try:
                conn = self.connect()
                for rid in sel_ids:
                    try:
                        cur = conn.execute("SELECT is_enabled, redemption_type, bit_threshold, name FROM custom_rewards WHERE id = ?", (rid,))
                        row = cur.fetchone()
                        if not row:
                            continue
                        cur_val = row[0]
                        r_type = row[1] if len(row) > 1 else None
                        r_bt = row[2] if len(row) > 2 else None
                        r_name = row[3] if len(row) > 3 else None
                        # normalize truthy/falsy
                        cur_enabled = True if str(cur_val) in ("1", "True", "true") else False
                        new_val = 0 if cur_enabled else 1
                        # If enabling a bits redemption, check for conflict and block enabling
                        if new_val == 1 and r_type == "bits":
                            try:
                                cur2 = conn.execute(
                                    "SELECT id, name FROM custom_rewards WHERE redemption_type = 'bits' AND bit_threshold = ? AND is_enabled = 1 AND id != ? LIMIT 1",
                                    (r_bt, rid)
                                )
                                conflict = cur2.fetchone()
                                if conflict:
                                    # found an already-enabled reward with same threshold -> block
                                    try:
                                        conflict_name = conflict[1] if len(conflict) > 1 else str(conflict[0])
                                    except Exception:
                                        conflict_name = str(conflict[0])
                                    messagebox.showinfo("Enable", f"Cannot enable this Bit Donation because '{conflict_name}' is already enabled for {r_bt} bits. Disable that reward first.", parent=self)
                                    # skip enabling this one
                                    continue
                            except Exception:
                                pass

                        if new_val == 1 and r_name:
                            try:
                                r_type_normalized = r_type or "channel_points"
                                cur3 = conn.execute(
                                    """
                                    SELECT id FROM custom_rewards
                                    WHERE redemption_type = ?
                                      AND is_enabled = 1
                                      AND id != ?
                                      AND LOWER(name) = LOWER(?)
                                    LIMIT 1
                                    """,
                                    (r_type_normalized, rid, r_name),
                                )
                                name_conflict = cur3.fetchone()
                                if name_conflict:
                                    messagebox.showinfo(
                                        "Enable",
                                        f"Cannot enable '{r_name}' because another {r_type_normalized.replace('_', ' ')} reward with the same name is already enabled.",
                                        parent=self,
                                    )
                                    continue
                            except Exception:
                                pass

                        conn.execute("UPDATE custom_rewards SET is_enabled = ? WHERE id = ?", (new_val, rid))
                    except Exception:
                        pass
                conn.commit()
            except Exception as e:
                messagebox.showerror("DB", f"Failed to toggle enabled state: {e}", parent=self)
            finally:
                try:
                    if conn:
                        conn.close()
                except Exception:
                    pass

            # Refresh UI
            try:
                threading.Thread(target=self.refresh_custom_redemptions, daemon=True).start()
            except Exception:
                try:
                    self.refresh_custom_redemptions()
                except Exception:
                    pass
        except Exception as e:
            debug_print("GUI", f"toggle_selected_custom_redemption error: {e}")

    def get_table_info(self, table: str):
        debug_print("GUI", f"Getting table info for '{table}'")
        conn = self.connect()
        try:
            cur = conn.execute(f"PRAGMA table_info('{table}')")
            rows = cur.fetchall()
            cols = [r[1] for r in rows]
            pk = None
            pk_type = None
            for r in rows:
                if r[5] == 1:
                    pk = r[1]
                    pk_type = r[2]
                    break
            # Treat INTEGER primary key as auto-generated (SQLite INTEGER PRIMARY KEY)
            pk_autoinc = False
            if pk and pk_type and isinstance(pk_type, str) and 'INT' in pk_type.upper():
                pk_autoinc = True
            return cols, pk, pk_autoinc
        finally:
            conn.close()

    def refresh_table(self, table: str):
        debug_print("GUI", f"Refreshing table '{table}'")
        # Special handling for prompts: fill the left listbox and right editor
        if table == "prompts":
            listbox = self.frames.get(table + "_listbox")
            prompt_text = self.frames.get(table + "_text")
            conn = self.connect()
            try:
                cur = conn.execute("SELECT id, name, prompt FROM prompts ORDER BY name")
                rows = cur.fetchall()
            finally:
                conn.close()
            rows_list = [{"id": r[0], "name": r[1], "prompt": r[2]} for r in rows]
            # Ensure 'Personality Prompt' (case-insensitive) appears first
            try:
                pp_idx = next((i for i, rr in enumerate(rows_list) if (rr.get("name") or "").strip().lower() == "personality prompt"), None)
                if pp_idx is not None and pp_idx != 0:
                    pp_item = rows_list.pop(pp_idx)
                    rows_list.insert(0, pp_item)
            except Exception:
                pass
            self.frames["prompts_rows"] = rows_list
            selected_id = self.frames.get("prompts_selected_id")
            selected_idx = 0
            if rows_list and selected_id is not None:
                try:
                    selected_idx = next(
                        (i for i, rr in enumerate(rows_list) if rr.get("id") == selected_id),
                        0,
                    )
                except Exception:
                    selected_idx = 0
            if listbox is not None:
                listbox.delete(0, tk.END)
                for r in rows_list:
                    listbox.insert(tk.END, r.get("name") or "(unnamed)")
                self._apply_listbox_stripes(listbox)
                if rows_list:
                    if selected_idx >= len(rows_list):
                        selected_idx = 0
                    listbox.selection_clear(0, tk.END)
                    listbox.selection_set(selected_idx)
                    listbox.activate(selected_idx)
                    listbox.see(selected_idx)
                    if prompt_text is not None:
                        text = rows_list[selected_idx].get("prompt") or ""
                        wrapped = textwrap.fill(str(text), width=80)
                        lines = wrapped.count("\n") + 1 if wrapped else 1
                        prompt_text.configure(state="normal")
                        prompt_text.delete("1.0", tk.END)
                        prompt_text.insert(tk.END, text)
                        prompt_text.configure(height=min(max(6, lines), 40))
                else:
                    if prompt_text is not None:
                        prompt_text.configure(state="normal")
                        prompt_text.delete("1.0", tk.END)
                        prompt_text.configure(state="disabled")
            return

        tree: ttk.Treeview = self.frames.get(table + "_tree")
        if tree is None:
            return
        for i in tree.get_children():
            tree.delete(i)

        # get table column info so we can render columns in DB order
        cols, pk, pk_autoinc = self.get_table_info(table)

        conn = self.connect()
        try:
            cur = conn.execute(f"SELECT * FROM {table}")
            rows = cur.fetchall()
            # If settings table, filter out keys that are edited inline (BOOL keys and specific combobox keys)
            if table == "settings":
                inline_combobox_keys = [
                    "Elevenlabs Synthesizer Model",
                    "Azure TTS Backup Voice",
                    "Audio Output Device",
                    "Default OpenAI Model",
                ]
                inline_slider_keys = ["Elevenlabs TTS Volume", "Azure TTS Volume", "Sound FX Volume"]
                inline_hidden_keys = set(inline_combobox_keys + inline_slider_keys)
                filtered_rows = []
                for r in rows:
                    dtype = (r["data_type"] if "data_type" in r.keys() and r["data_type"] else "TEXT").upper()
                    if dtype == "BOOL":
                        # skip boolean keys (they are edited inline)
                        continue
                    if r["key"] in inline_hidden_keys:
                        # skip inline-managed keys (comboboxes/sliders)
                        continue
                    filtered_rows.append(r)
            else:
                filtered_rows = rows

            for idx, row in enumerate(filtered_rows):
                vals = []
                for c in cols:
                    if table == "settings" and c == "value":
                        # For settings table, display booleans as True/False when configured
                        dtype = row["data_type"] if "data_type" in row.keys() else None
                        if dtype and dtype.upper() == "BOOL":
                            key_for_display = row["key"] if "key" in row.keys() else ""
                            vals.append(display_boolean_value(key_for_display, row[c]))
                            continue
                    # For commands table, render boolean flags as checkbox glyphs
                    if table == "commands" and c.lower() in ("enabled", "sub_only", "mod_only", "reply_to_user"):
                        try:
                            vals.append("☑" if str(row[c]) in ("1", "True", "true") else "☐")
                        except Exception:
                            vals.append("☐")
                        continue
                    # For scheduled_messages table, show enabled as checkbox glyph
                    if table == "scheduled_messages" and c.lower() == "enabled":
                        try:
                            vals.append("☑" if str(row[c]) in ("1", "True", "true") else "☐")
                        except Exception:
                            vals.append("☐")
                        continue
                    vals.append(row[c])
                tag = 'even' if (idx % 2 == 0) else 'odd'
                tree.insert("", tk.END, values=vals, tags=(tag,))
        except Exception as e:
            print(f"Error refreshing {table}: {e}\n")
        finally:
            conn.close()


        # Autosize columns for commands table (schedule briefly to allow UI update)
        if table == "commands":
            try:
                self.after(10, lambda t=tree: self.autosize_columns(t))
            except Exception:
                try:
                    self.autosize_columns(tree)
                except Exception:
                    pass

    def autosize_columns(self, tree: ttk.Treeview) -> None:
        """Autosize treeview columns to fit their content (headers + values)."""
        try:
            font = tkfont.nametofont("TkDefaultFont")
        except Exception:
            font = tkfont.Font()
        padding = 16
        cols = list(tree["columns"]) if tree["columns"] else []
        for col in cols:
            try:
                header = tree.heading(col).get("text", str(col))
            except Exception:
                header = str(col)
            maxw = font.measure(str(header)) + padding
            for iid in tree.get_children():
                try:
                    txt = str(tree.set(iid, col) or "")
                except Exception:
                    # fallback to values mapping
                    try:
                        vals = tree.item(iid).get("values", [])
                        idx = cols.index(col)
                        txt = str(vals[idx]) if idx < len(vals) else ""
                    except Exception:
                        txt = ""
                w = font.measure(txt) + padding
                if w > maxw:
                    maxw = w
            # cap width to a reasonable maximum to avoid overly wide columns
            maxw = min(maxw, 800)
            try:
                tree.column(col, width=maxw)
            except Exception:
                pass
            pass

        

    def edit_selected_row(self, table: str):
        debug_print("GUI", f"Editing selected row in table '{table}'")
        tree: ttk.Treeview = self.frames.get(table + "_tree")
        sel = tree.selection()
        if not sel:
            messagebox.showinfo("Edit", "Please select a row to edit", parent=self)
            return
        item = tree.item(sel[0])
        values = item["values"]
        cols, pk, pk_autoinc = self.get_table_info(table)
        pk_hidden = bool(pk and (pk_autoinc or pk.lower() == "id"))
        # If we have a primary key, fetch the full row from the DB to avoid
        # relying on Treeview value ordering (which can change when displaycolumns
        # hide fields like data_type). This prevents KeyError('data_type') and
        # ensures we have the complete row data.
        row = None
        if pk:
            try:
                pk_index = cols.index(pk)
                pk_val = values[pk_index]
                conn = self.connect()
                try:
                    cur = conn.execute(f"SELECT * FROM {table} WHERE {pk} = ?", (pk_val,))
                    fetched = cur.fetchone()
                    if fetched:
                        # sqlite3.Row supports mapping protocol; convert to plain dict
                        row = dict(fetched)
                finally:
                    conn.close()
            except Exception:
                row = None

        # Fallback: if we couldn't fetch from DB, try to reconstruct from values
        if row is None:
            try:
                row = {cols[i]: values[i] for i in range(min(len(cols), len(values)))}
            except Exception:
                row = None

        self.open_edit_dialog(table, row=row)

    def delete_selected_row(self, table: str):
        debug_print("GUI", f"Deleting selected row in table '{table}'")
        # Fetch table info early so `pk` is always available for the DELETE query
        cols, pk, pk_autoinc = self.get_table_info(table)
        # Prompts use a Listbox UI, not a Treeview. Handle that specially.
        if table == "prompts":
            listbox = self.frames.get("prompts_listbox")
            rows = self.frames.get("prompts_rows", [])
            if listbox is None:
                messagebox.showinfo("Delete", "No prompt list available to delete from.", parent=self)
                return
            sel = listbox.curselection()
            if not sel:
                messagebox.showinfo("Delete", "Please select a prompt to delete", parent=self)
                return
            idx = sel[0]
            if idx < 0 or idx >= len(rows):
                messagebox.showinfo("Delete", "Invalid selection", parent=self)
                return
            row = rows[idx]
            rowid = row.get("id")
            if not rowid:
                messagebox.showerror("Delete", "Cannot delete prompt: no primary key", parent=self)
                return
            if not messagebox.askyesno("Delete", f"Delete prompt '{row.get('name')}' (id={rowid})?", parent=self):
                return
        else:
            tree: ttk.Treeview = self.frames.get(table + "_tree")
            if tree is None:
                messagebox.showinfo("Delete", "Please select a row to delete", parent=self)
                return
            sel = tree.selection()
            if not sel:
                messagebox.showinfo("Delete", "Please select a row to delete", parent=self)
                return
            item = tree.item(sel[0])
            values = item["values"]
            pk_hidden = bool(pk and (pk_autoinc or pk.lower() == "id"))
            if not pk:
                messagebox.showerror("Delete", "Cannot delete row: no primary key", parent=self)
                return
            rowid = values[cols.index(pk)]
        # If deleting a scheduled message that is enabled, stop its scheduler task first
        try:
            if table == "scheduled_messages":
                try:
                    conn_tmp = self.connect()
                    try:
                        cur_check = conn_tmp.execute("SELECT enabled FROM scheduled_messages WHERE id = ?", (rowid,))
                        rr = cur_check.fetchone()
                        if rr and str(rr[0]) in ("1", "True", "true"):
                            try:
                                self._scheduler_call_end(int(rowid))
                            except Exception:
                                pass
                    finally:
                        conn_tmp.close()
                except Exception:
                    pass
        except Exception:
            pass

        conn = self.connect()
        try:
            # If deleting a command that is currently enabled, unregister it
            if table == "commands":
                try:
                    cur = conn.execute(f"SELECT command, enabled FROM {table} WHERE {pk} = ?", (rowid,))
                    crow = cur.fetchone()
                    if crow:
                        try:
                            cmd_name = crow[0]
                            enabled_flag = crow[1]
                        except Exception:
                            # sqlite3.Row may also allow dict-like access
                            cmd_name = crow.get("command") if isinstance(crow, dict) else None
                            enabled_flag = crow.get("enabled") if isinstance(crow, dict) else None

                        try:
                            truthy = str(enabled_flag) in ("1", "True", "true")
                        except Exception:
                            truthy = False

                        if truthy and cmd_name:
                            try:
                                bot = get_reference("TwitchBot")
                                if bot and hasattr(bot, "remove_command"):
                                    try:
                                        bot.remove_command(cmd_name)
                                    except Exception:
                                        from twitchbot import remove_command as _rem_cmd
                                        _rem_cmd(cmd_name)
                                else:
                                    from twitchbot import remove_command as _rem_cmd
                                    _rem_cmd(cmd_name)
                            except Exception:
                                # best-effort: log but don't abort delete
                                print(f"Warning: failed to unregister command before delete: {cmd_name}")
                except Exception:
                    pass

            conn.execute(f"DELETE FROM {table} WHERE {pk} = ?", (rowid,))
            conn.commit()
            self.refresh_table(table)
        except Exception as e:
            messagebox.showerror("Delete", str(e), parent=self)
        finally:
            conn.close()

    def open_edit_dialog(self, table: str, row: dict | None = None):
        debug_print("GUI", f"Opening edit dialog for table '{table}', row: {row}")
        cols, pk, pk_autoinc = self.get_table_info(table)
        pk_hidden = bool(pk and (pk_autoinc or pk.lower() == "id"))

        dlg = tk.Toplevel(self)
        dlg.transient(self)
        dlg.grab_set()
        dlg.title(f"Edit {table}" if row else f"Add to {table}")

        entries = {}
        # placeholders for command booleans (declared early so on_save can reference safely)
        enabled_var = None
        sub_var = None
        mod_var = None
        reply_var = None
        # We'll support a special UI for the `settings` table so we can show checkboxes for
        # boolean keys and validate duplicate keys on insert.
        r = 0
        if table == "settings":
            key_col = "key"
            val_col = "value"

            # Key field
            ttk.Label(dlg, text=key_col).grid(row=r, column=0, sticky=tk.W, padx=4, pady=2)
            key_ent = ttk.Entry(dlg)
            key_ent.grid(row=r, column=1, sticky=tk.EW, padx=4, pady=2)
            entries[key_col] = key_ent
            if row and key_col in row:
                key_ent.insert(0, "" if row[key_col] is None else str(row[key_col]))
                # don't allow changing the key for existing rows (primary key)
                key_ent.configure(state="disabled")
            r += 1

            # If adding a new setting (row is None), show a data_type combobox so the user
            # can choose between TEXT, INTEGER, BOOL, CHARACTER. For edits we infer/keep
            # the existing data_type and do not show the combobox.
            data_type_cb = None
            if row is None:
                ttk.Label(dlg, text="data_type").grid(row=r, column=0, sticky=tk.W, padx=4, pady=2)
                data_type_cb = ttk.Combobox(dlg, values=["TEXT", "INTEGER", "BOOL", "CHARACTER"], state="readonly")
                data_type_cb.grid(row=r, column=1, sticky=tk.EW, padx=4, pady=2)
                data_type_cb.set("TEXT")
                entries["data_type"] = data_type_cb
                r += 1

            # Value field: create both an Entry and a Checkbutton (hidden unless key is boolean)
            ttk.Label(dlg, text=val_col).grid(row=r, column=0, sticky=tk.W, padx=4, pady=2)
            val_ent = ttk.Entry(dlg)
            val_ent.grid(row=r, column=1, sticky=tk.EW, padx=4, pady=2)
            entries[val_col] = val_ent

            bool_var = tk.BooleanVar(value=False)
            bool_cb = ttk.Checkbutton(dlg, variable=bool_var, text="True/False")
            # start hidden; we'll grid it when needed and grid_remove when not
            bool_cb.grid(row=r, column=1, sticky=tk.W, padx=4, pady=2)
            bool_cb.grid_remove()

            # initialize value widgets based on existing row, explicit combobox selection, or key
            def update_value_widget(_event=None):
                # Priority: explicit combobox selection (when adding), then existing row, then REQUIRED_SETTINGS inference
                if entries.get("data_type") is not None:
                    data_type = entries["data_type"].get().upper()
                elif row and "data_type" in row and row["data_type"]:
                    data_type = row["data_type"].upper()
                else:
                    # Try to infer from REQUIRED_SETTINGS by key name
                    key_text = key_ent.get().strip()
                    if key_text in REQUIRED_SETTINGS:
                        data_type = REQUIRED_SETTINGS[key_text][1].upper()
                    else:
                        data_type = "TEXT"

                if data_type == "BOOL":
                    # show checkbox, hide entry
                    raw = None
                    if row and val_col in row:
                        raw = row[val_col]
                    else:
                        raw = val_ent.get()
                    try:
                        bool_val = display_boolean_value(key_ent.get().strip(), raw) == "True"
                    except Exception:
                        bool_val = False
                    bool_var.set(bool_val)
                    val_ent.grid_remove()
                    bool_cb.grid()
                else:
                    # show entry, hide checkbox
                    if row and val_col in row:
                        val_ent.delete(0, tk.END)
                        val_ent.insert(0, "" if row[val_col] is None else str(row[val_col]))
                    bool_cb.grid_remove()
                    val_ent.grid()

            # bind updates: when key changes, swap widgets
            key_ent.bind("<KeyRelease>", update_value_widget)
            key_ent.bind("<FocusOut>", update_value_widget)
            # if we have a combobox for data_type, watch selection changes too
            if data_type_cb is not None:
                data_type_cb.bind("<<ComboboxSelected>>", update_value_widget)

            # call once to setup initial state
            update_value_widget()

            r += 1

        elif table == "commands":
            # Custom form for commands table with specialized validation and boolean checkboxes
            # Fields: command (no leading special char), response (required), enabled (BOOL), sub_only (BOOL), mod_only (BOOL), reply_to_user (BOOL)
            ttk.Label(dlg, text="command").grid(row=r, column=0, sticky=tk.W, padx=4, pady=2)
            cmd_ent = ttk.Entry(dlg)
            cmd_ent.grid(row=r, column=1, sticky=tk.EW, padx=4, pady=2)
            entries["command"] = cmd_ent
            if row and "command" in row:
                cmd_ent.insert(0, "" if row["command"] is None else str(row["command"]))
                # don't allow changing the command name for existing rows
                cmd_ent.configure(state="disabled")
            r += 1

            ttk.Label(dlg, text="response").grid(row=r, column=0, sticky=tk.NW, padx=4, pady=2)
            # Use a multi-line scrolled text widget for responses (likely multi-sentence)
            resp_widget = ScrolledText(dlg, height=6, wrap=tk.WORD)
            resp_widget.grid(row=r, column=1, sticky=tk.EW, padx=4, pady=2)
            entries["response"] = resp_widget
            if row and "response" in row:
                try:
                    resp_widget.delete("1.0", tk.END)
                    resp_widget.insert(tk.END, "" if row["response"] is None else str(row["response"]))
                except Exception:
                    pass
            r += 1

            hint_lines = [
                "%bot%  - bot's display name",
                "%user% - user's display name",
                "%channel% - channel name",
                "%rng% - random number between 1 and 100",
                "%rng:min:max% - random number between min and max (inclusive)",
                "%input#% - text following the command in the user's message, replace # with number (e.g. %input1% for first input), inputs seperated by commas in command usage",
            ]
            hint_text = "\n".join(hint_lines)
            ttk.Label(
                dlg,
                text=f"Placeholders:\n{hint_text}",
                justify=tk.LEFT,
                foreground="#555555",
            ).grid(row=r, column=0, columnspan=2, sticky=tk.W, padx=4, pady=(0, 6))
            r += 1

            # Boolean flags: only show in Add dialog (row is None). For Edit, booleans are edited inline in the Commands tab.
            if row is None:
                enabled_var = tk.BooleanVar(value=True)
                sub_var = tk.BooleanVar(value=False)
                mod_var = tk.BooleanVar(value=False)
                reply_var = tk.BooleanVar(value=False)

                # Layout checkbuttons in a row
                cb_frame = ttk.Frame(dlg)
                cb_frame.grid(row=r, column=0, columnspan=2, sticky=tk.W, padx=4, pady=2)
                ttk.Checkbutton(cb_frame, text="enabled", variable=enabled_var).pack(side=tk.LEFT, padx=6)
                ttk.Checkbutton(cb_frame, text="sub_only", variable=sub_var).pack(side=tk.LEFT, padx=6)
                ttk.Checkbutton(cb_frame, text="mod_only", variable=mod_var).pack(side=tk.LEFT, padx=6)
                ttk.Checkbutton(cb_frame, text="reply_to_user", variable=reply_var).pack(side=tk.LEFT, padx=6)

                # If sub_only is checked, ensure mod_only is unchecked and vice-versa
                def _on_sub_changed(*_):
                    try:
                        if sub_var.get():
                            mod_var.set(False)
                    except Exception:
                        pass

                def _on_mod_changed(*_):
                    try:
                        if mod_var.get():
                            sub_var.set(False)
                    except Exception:
                        pass

                sub_var.trace_add("write", lambda *_: _on_sub_changed())
                mod_var.trace_add("write", lambda *_: _on_mod_changed())

                r += 1
            else:
                # Edit mode: do not create boolean widgets here; editing booleans is in the commands tab itself
                enabled_var = None
                sub_var = None
                mod_var = None
                reply_var = None
        else:
            # Generic form for other tables
            if table == "scheduled_messages":
                # Custom form: message (text), minutes (int >=0), messages (int >=0). Do not include enabled here.
                ttk.Label(dlg, text="message").grid(row=r, column=0, sticky=tk.W, padx=4, pady=2)
                msg_ent = ttk.Entry(dlg)
                msg_ent.grid(row=r, column=1, sticky=tk.EW, padx=4, pady=2)
                entries["message"] = msg_ent
                if row and "message" in row:
                    msg_ent.insert(0, "" if row["message"] is None else str(row["message"]))
                r += 1

                ttk.Label(dlg, text="minutes").grid(row=r, column=0, sticky=tk.W, padx=4, pady=2)
                minutes_ent = ttk.Entry(dlg)
                minutes_ent.grid(row=r, column=1, sticky=tk.EW, padx=4, pady=2)
                entries["minutes"] = minutes_ent
                if row and "minutes" in row:
                    minutes_ent.insert(0, "" if row["minutes"] is None else str(row["minutes"]))
                r += 1

                ttk.Label(dlg, text="messages").grid(row=r, column=0, sticky=tk.W, padx=4, pady=2)
                messages_ent = ttk.Entry(dlg)
                messages_ent.grid(row=r, column=1, sticky=tk.EW, padx=4, pady=2)
                entries["messages"] = messages_ent
                if row and "messages" in row:
                    messages_ent.insert(0, "" if row["messages"] is None else str(row["messages"]))
                r += 1
                # enabled checkbox for Add dialog only
                enabled_var = None
                if row is None:
                    enabled_var = tk.BooleanVar(value=True)
                    cbf = ttk.Frame(dlg)
                    cbf.grid(row=r, column=0, columnspan=2, sticky=tk.W, padx=4, pady=2)
                    ttk.Checkbutton(cbf, text="enabled", variable=enabled_var).pack(side=tk.LEFT, padx=6)
                    r += 1
                # done custom scheduled_messages form
            else:
                for col in cols:
                    # Hide the primary key field from add/edit forms when it's auto-generated or named 'id'
                    if pk and col == pk and pk_hidden:
                        continue
                    # Do not show created_at in the commands add/edit form
                    if table == "commands" and col.lower() == "created_at":
                        continue
                    ttk.Label(dlg, text=col).grid(row=r, column=0, sticky=tk.W, padx=4, pady=2)
                    val = ""
                    if row and col in row:
                        val = row[col]
                    # If primary key and autogenerated, disable editing when adding
                    ent = ttk.Entry(dlg)
                    ent.grid(row=r, column=1, sticky=tk.EW, padx=4, pady=2)
                    ent.insert(0, "" if val is None else str(val))
                    entries[col] = ent
                    r += 1

        def on_save():
            debug_print("GUI", f"Saving edits for table '{table}', row: {row}")
            conn = self.connect()
            pending_setting_key = None
            pending_setting_value = None
            try:
                # Special-case commands table: custom validation and insert/update
                if table == "commands":
                    try:
                        cmd = entries.get("command").get().strip() if entries.get("command") else ""
                    except Exception:
                        cmd = ""
                    try:
                        resp_widget = entries.get("response")
                        if resp_widget is None:
                            resp = ""
                        else:
                            # ScrolledText uses index-based get; Entry uses simple get()
                            if isinstance(resp_widget, ScrolledText):
                                resp = resp_widget.get("1.0", tk.END).strip()
                            else:
                                # fallback for Entry
                                resp = resp_widget.get()
                    except Exception:
                        resp = ""
                    # required fields
                    if not cmd:
                        try:
                            dlg.lift(); dlg.focus_force()
                        except Exception:
                            pass
                        messagebox.showerror("Save", "Command name is required.", parent=dlg)
                        return
                    if not resp or str(resp).strip() == "":
                        try:
                            dlg.lift(); dlg.focus_force()
                        except Exception:
                            pass
                        messagebox.showerror("Save", "Response text is required.", parent=dlg)
                        return
                    # first character must not be a special/punctuation character
                    first = cmd[0]
                    if first in string.punctuation:
                        try:
                            dlg.lift(); dlg.focus_force()
                        except Exception:
                            pass
                        messagebox.showerror("Save", "Command must not start with a special character.", parent=dlg)
                        return
                    if row is None:
                        if any(ch.isspace() for ch in cmd):
                            try:
                                dlg.lift(); dlg.focus_force()
                            except Exception:
                                pass
                            messagebox.showerror("Save", "Command name must be a single word (no spaces).", parent=dlg)
                            return
                        reserved_names = {"so", "shoutout", "quote", "rng"}
                        if cmd.lower() in reserved_names:
                            try:
                                dlg.lift(); dlg.focus_force()
                            except Exception:
                                pass
                            messagebox.showerror(
                                "Save",
                                "Commands !so, !shoutout, !quote, and !rng are built-in and cannot be recreated.",
                                parent=dlg,
                            )
                            return
                    # Determine boolean values: from Add-dialog widgets if creating, else from existing row
                    if row is None:
                        en = 1 if (enabled_var and enabled_var.get()) else 0
                        sub = 1 if (sub_var and sub_var.get()) else 0
                        mod = 1 if (mod_var and mod_var.get()) else 0
                        reply = 1 if (reply_var and reply_var.get()) else 0
                    else:
                        en = 1 if row.get("enabled") in (1, "1", "True", "true") else 0
                        sub = 1 if row.get("sub_only") in (1, "1", "True", "true") else 0
                        mod = 1 if row.get("mod_only") in (1, "1", "True", "true") else 0
                        reply = 1 if row.get("reply_to_user") in (1, "1", "True", "true") else 0
                    try:
                        if row is None:
                            created = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            conn.execute(
                                "INSERT INTO commands (command, response, enabled, sub_only, mod_only, reply_to_user, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                                (cmd, resp, en, sub, mod, reply, created)
                            )
                        else:
                            conn.execute(
                                "UPDATE commands SET response = ?, enabled = ?, sub_only = ?, mod_only = ?, reply_to_user = ? WHERE command = ?",
                                (resp, en, sub, mod, reply, cmd)
                            )
                        conn.commit()
                        dlg.destroy()
                        self.refresh_table("commands")
                        try:
                            from twitchbot import remove_command, add_command
                            if en:
                                # when enabling: remove existing registration then add
                                if row is not None:
                                    remove_command(cmd)
                                add_command(cmd, resp, mod, sub, reply)
                            else:
                                remove_command(cmd)
                        except Exception as e:
                            print(f"[GUI] Error updating runtime command list: {e}")
                        return
                    except Exception as e:
                        import traceback
                        print(traceback.format_exc())
                        try:
                            dlg.lift(); dlg.focus_force()
                        except Exception:
                            pass
                        messagebox.showerror("Save", f"Error saving command: {e}", parent=dlg)
                        return

                # Special-case scheduled_messages: validate integers and manage scheduler
                if table == "scheduled_messages":
                    # read fields
                    try:
                        msg = entries.get("message").get().strip() if entries.get("message") else ""
                    except Exception:
                        msg = ""
                    try:
                        minutes_raw = entries.get("minutes").get().strip() if entries.get("minutes") else "0"
                        minutes_val = int(minutes_raw)
                        if minutes_val < 0:
                            raise ValueError("minutes must be >= 0")
                    except Exception:
                        try:
                            dlg.lift(); dlg.focus_force()
                        except Exception:
                            pass
                        messagebox.showerror("Save", "'minutes' must be a non-negative integer.", parent=dlg)
                        return
                    try:
                        messages_raw = entries.get("messages").get().strip() if entries.get("messages") else "0"
                        messages_val = int(messages_raw)
                        if messages_val < 0:
                            raise ValueError("messages must be >= 0")
                    except Exception:
                        try:
                            dlg.lift(); dlg.focus_force()
                        except Exception:
                            pass
                        messagebox.showerror("Save", "'messages' must be a non-negative integer.", parent=dlg)
                        return

                    # both can't be 0 at the same time
                    if minutes_val == 0 and messages_val == 0:
                        try:
                            dlg.lift(); dlg.focus_force()
                        except Exception:
                            pass
                        messagebox.showerror("Save", "'minutes' and 'messages' cannot both be 0. One may be 0 but not both.", parent=dlg)
                        return

                    if row is None:
                        # INSERT new scheduled message; include enabled from the Add dialog checkbox
                        try:
                            enabled_val = 1 if (enabled_var and enabled_var.get()) else 0
                            cur = conn.execute("INSERT INTO scheduled_messages (message, minutes, messages, enabled) VALUES (?, ?, ?, ?)", (msg, minutes_val, messages_val, enabled_val))
                            conn.commit()
                            new_id = cur.lastrowid
                            dlg.destroy()
                            self.refresh_table("scheduled_messages")
                            # start scheduler only if enabled was checked
                            if enabled_val == 1:
                                try:
                                    self._scheduler_call_start(int(new_id))
                                except Exception as e:
                                    debug_print("GUI", f"Error starting scheduled message: {e}")
                            return
                        except Exception as e:
                            try:
                                dlg.lift(); dlg.focus_force()
                            except Exception:
                                pass
                            messagebox.showerror("Save", f"Error saving scheduled message: {e}", parent=dlg)
                            return
                    else:
                        # UPDATE existing row
                        if not pk:
                            try:
                                dlg.lift(); dlg.focus_force()
                            except Exception:
                                pass
                            messagebox.showerror("Save", "Cannot update scheduled message: no primary key", parent=dlg)
                            return
                        pk_val = row[pk]
                        # determine if previously enabled
                        prev_enabled = 1 if row.get("enabled") in (1, "1", "True", "true") else 0
                        # If previously enabled, stop the old task before updating
                        try:
                            if prev_enabled:
                                self._scheduler_call_end(int(pk_val))
                        except Exception:
                            pass
                        try:
                            conn.execute("UPDATE scheduled_messages SET message = ?, minutes = ?, messages = ? WHERE id = ?", (msg, minutes_val, messages_val, pk_val))
                            conn.commit()
                            # If previously enabled, restart task with new settings
                            try:
                                if prev_enabled:
                                    self._scheduler_call_start(int(pk_val))
                            except Exception:
                                pass
                            dlg.destroy()
                            self.refresh_table("scheduled_messages")
                            return
                        except Exception as e:
                            try:
                                dlg.lift(); dlg.focus_force()
                            except Exception:
                                pass
                            messagebox.showerror("Save", f"Error updating scheduled message: {e}", parent=dlg)
                            return

                if row is None:
                    # INSERT
                    cols_insert = []
                    vals = []
                    for col in cols:
                        # Skip primary key column if hidden/auto-generated
                        if pk and col == pk and pk_hidden:
                            continue
                        # Get value depending on widget type
                        if table == "settings":
                            # settings table has columns like key, value, data_type. The dialog
                            # only provides inputs for key/value (and a checkbox for BOOL).
                            # For missing columns (e.g. data_type) infer sensible defaults.
                            if col == "key":
                                v = entries["key"].get()
                            elif col == "value":
                                # Determine data_type preference: combobox (for add) -> REQUIRED_SETTINGS inference -> default TEXT
                                if entries.get("data_type") is not None:
                                    dty = entries["data_type"].get().upper()
                                else:
                                    try:
                                        key_text = entries["key"].get().strip()
                                    except Exception:
                                        key_text = ""
                                    if key_text in REQUIRED_SETTINGS:
                                        dty = REQUIRED_SETTINGS[key_text][1].upper()
                                    else:
                                        dty = "TEXT"
                                if dty == "BOOL":
                                    # use checkbox state when BOOL selected
                                    v = "1" if bool_var.get() else "0"
                                else:
                                    v = entries[col].get()
                            elif col == "data_type":
                                # If the add-dialog provided an explicit data_type combobox, use that.
                                if entries.get("data_type") is not None:
                                    v = entries["data_type"].get().upper()
                                else:
                                    # infer data_type from the key if possible
                                    try:
                                        key_text = entries["key"].get().strip()
                                    except Exception:
                                        key_text = ""
                                    if key_text in REQUIRED_SETTINGS:
                                        v = REQUIRED_SETTINGS[key_text][1].upper()
                                    else:
                                        v = "TEXT"
                            else:
                                # any other column: try to fetch from entries if present
                                widget = entries.get(col)
                                v = widget.get() if widget is not None else None
                        else:
                            widget = entries.get(col)
                            v = widget.get() if widget is not None else None
                        if table == "settings":
                            if col == "key":
                                pending_setting_key = v
                            elif col == "value":
                                pending_setting_value = v
                        # If inserting into settings and this key is a boolean key, convert to '1'/'0'
                        if table == "settings" and col == "value":
                            # determine dtype used for this insertion (combobox takes precedence)
                            dtype_for_row = None
                            if entries.get("data_type") is not None:
                                dtype_for_row = entries["data_type"].get().upper()
                            else:
                                key_for_row = entries.get("key") and entries["key"].get()
                                if key_for_row in REQUIRED_SETTINGS:
                                    dtype_for_row = REQUIRED_SETTINGS[key_for_row][1].upper()
                            if dtype_for_row == "BOOL":
                                if v not in ("1", "0"):
                                    try:
                                        v = parse_boolean_input(v)
                                    except ValueError as ve:
                                        # Show a clearer message explaining accepted boolean forms
                                        key_name = (entries.get("key").get() if entries.get("key") else "(unknown)")
                                        try:
                                            dlg.lift()
                                            dlg.focus_force()
                                        except Exception:
                                            pass
                                        messagebox.showerror("Save", _validation_message(key_name, "BOOL", v), parent=dlg)
                                        return
                            elif dtype_for_row == "INTEGER":
                                # validate integer form and ensure positive (>0)
                                try:
                                    if v is None or str(v).strip() == "":
                                        raise ValueError("Empty value")
                                    iv = int(str(v).strip())
                                    if iv <= 0:
                                        raise ValueError("Not positive")
                                except Exception:
                                    key_name = (entries.get("key").get() if entries.get("key") else "(unknown)")
                                    try:
                                        dlg.lift()
                                        dlg.focus_force()
                                    except Exception:
                                        pass
                                    messagebox.showerror("Save", _validation_message(key_name, "INTEGER", v), parent=dlg)
                                    return
                            elif dtype_for_row == "CHARACTER":
                                # ensure at least one character
                                if v is None or len(str(v)) == 0:
                                    key_name = (entries.get("key").get() if entries.get("key") else "(unknown)")
                                    try:
                                        dlg.lift()
                                        dlg.focus_force()
                                    except Exception:
                                        pass
                                    messagebox.showerror("Save", _validation_message(key_name, "CHARACTER", v), parent=dlg)
                                    return
                            # Special-case: Command Prefix must be a single special character and not '@'
                            try:
                                key_name_check = entries.get("key").get().strip() if entries.get("key") else ""
                            except Exception:
                                key_name_check = ""
                            if key_name_check == "Command Prefix":
                                val_text = "" if v is None else str(v)
                                if len(val_text) != 1 or val_text == "@" or val_text.isalnum():
                                    try:
                                        dlg.lift()
                                        dlg.focus_force()
                                    except Exception:
                                        pass
                                    messagebox.showerror("Save", "Command Prefix must be a single special character (e.g. '!', '&', '?'). The '@' character is not allowed.", parent=dlg)
                                    return
                        # Validate duplicate key when inserting
                        if table == "settings" and col == "key":
                            # check for existing key
                            cur = conn.execute("SELECT 1 FROM settings WHERE key = ?", (v,))
                            if cur.fetchone() is not None:
                                try:
                                    dlg.lift()
                                    dlg.focus_force()
                                except Exception:
                                    pass
                                messagebox.showerror("Save", f"A setting with key '{v}' already exists.", parent=dlg)
                                return
                        # skip primary key if it's autoincrement/hidden
                        cols_insert.append(col)
                        vals.append(v)
                    placeholders = ",".join(["?" for _ in cols_insert])
                    conn.execute(f"INSERT INTO {table} ({','.join(cols_insert)}) VALUES ({placeholders})", vals)
                else:
                    # UPDATE using pk
                    if not pk:
                        try:
                            dlg.lift()
                            dlg.focus_force()
                        except Exception:
                            pass
                        messagebox.showerror("Save", "Cannot update row: no primary key", parent=dlg)
                        return
                    pk_val = row[pk]
                    if table == "settings":
                        try:
                            pending_setting_key = row["key"]
                        except Exception:
                            try:
                                pending_setting_key = row.get("key") if isinstance(row, dict) else None
                            except Exception:
                                pending_setting_key = None
                    set_parts = []
                    vals = []
                    for col in cols:
                        if col == pk:
                            continue
                        # Special handling for settings table columns
                        if table == "settings" and col == "data_type":
                            # Determine data_type from existing row or REQUIRED_SETTINGS or default to TEXT
                            key_for_row = (row["key"] if row and "key" in row.keys() else None)
                            if not key_for_row:
                                key_for_row = (entries.get("key").get() if entries.get("key") else None)
                            if key_for_row and key_for_row in REQUIRED_SETTINGS:
                                val_to_store = REQUIRED_SETTINGS[key_for_row][1].upper()
                            else:
                                val_to_store = (row["data_type"] if row and "data_type" in row.keys() and row["data_type"] else "TEXT")
                        # handle boolean conversion for settings.value
                        elif table == "settings" and col == "value":
                            # If editing an existing row, row contains the key
                            key_for_row = (row["key"] if row and "key" in row.keys() else None)
                            # Determine dtype from existing row (editing) or REQUIRED_SETTINGS
                            if key_for_row and key_for_row in REQUIRED_SETTINGS:
                                dty = REQUIRED_SETTINGS[key_for_row][1].upper()
                            else:
                                dty = (row["data_type"].upper() if row and "data_type" in row.keys() and row["data_type"] else "TEXT")
                            if dty == "BOOL":
                                val_to_store = "1" if bool_var.get() else "0"
                            elif dty == "INTEGER":
                                    # ensure integer with friendly error on failure
                                    widget = entries.get(col)
                                    try:
                                        raw = widget.get() if widget is not None else None
                                        if raw is None or str(raw).strip() == "":
                                            raise ValueError("Empty integer")
                                        iv = int(str(raw).strip())
                                        if iv <= 0:
                                            raise ValueError("Not positive")
                                        val_to_store = str(iv)
                                    except Exception:
                                        key_for_row = key_for_row or (entries.get("key").get() if entries.get("key") else "(unknown)")
                                        try:
                                            dlg.lift()
                                            dlg.focus_force()
                                        except Exception:
                                            pass
                                        messagebox.showerror("Save", _validation_message(key_for_row, "INTEGER", raw), parent=dlg)
                                        return
                            elif dty == "CHARACTER":
                                widget = entries.get(col)
                                val_to_store = widget.get()[0] if widget is not None and widget.get() else " "
                            else:
                                widget = entries.get(col)
                                val_to_store = widget.get() if widget is not None else None
                            # Special-case: Command Prefix must be a single special character and not '@'
                            try:
                                if key_for_row == "Command Prefix":
                                    vt = "" if val_to_store is None else str(val_to_store)
                                    if len(vt) != 1 or vt == "@" or vt.isalnum():
                                        try:
                                            dlg.lift()
                                            dlg.focus_force()
                                        except Exception:
                                            pass
                                        messagebox.showerror("Save", "Command Prefix must be a single special character (e.g. '!', '&', '?'). The '@' character is not allowed.", parent=dlg)
                                        return
                            except Exception:
                                pass
                            pending_setting_value = val_to_store
                        else:
                            widget = entries.get(col)
                            val_to_store = widget.get() if widget is not None else None
                        set_parts.append(f"{col} = ?")
                        vals.append(val_to_store)
                    vals.append(pk_val)
                    conn.execute(f"UPDATE {table} SET {', '.join(set_parts)} WHERE {pk} = ?", vals)
                conn.commit()
                if table == "settings":
                    self._handle_setting_side_effect(pending_setting_key, pending_setting_value)
                # If the Debug Mode setting exists/was changed, apply it immediately
                if table == "settings":
                    try:
                        try:
                            cur2 = conn.execute("SELECT value FROM settings WHERE key = ?", ("Debug Mode",))
                            fetched = cur2.fetchone()
                        except Exception:
                            fetched = None
                        if fetched:
                            v_debug = fetched[0]
                            debug_bool = True if str(v_debug) in ("1", "True", "true") else False
                            try:
                                # set_debug is async; run it here (quick) or schedule if that fails
                                asyncio.run(set_debug(debug_bool))
                            except Exception:
                                # fallback: run in background thread
                                try:
                                    threading.Thread(target=lambda: asyncio.run(set_debug(debug_bool)), daemon=True).start()
                                except Exception as e:
                                    print(f"Error applying Debug Mode: {e}")
                    except Exception:
                        pass
                dlg.destroy()
                self.refresh_table(table)
                return
            except Exception as e:
                import traceback
                tb = traceback.format_exc()
                print(tb)
                # show a short message and print the full traceback to console
                try:
                    dlg.lift()
                    dlg.focus_force()
                except Exception:
                    pass
                messagebox.showerror("Save", f"Error saving: {e}\nSee console for details.", parent=dlg)
            finally:
                conn.close()

        btn_save = ttk.Button(dlg, text="Save", command=on_save)
        btn_save.grid(row=r, column=0, columnspan=2, pady=6)
        # Center dialog over main window now that widgets are created
        try:
            self.center_window(dlg)
        except Exception:
            pass

    def refresh_settings_inline(self) -> None:
        """Populate the inline settings editor with controls for BOOL and specific combobox keys.

        Saves changes immediately when controls are modified.
        """
        debug_print("GUI", f"Refreshing inline settings editor")
        inline = self.frames.get("settings_inline")
        if inline is None:
            return
        # Clear existing widgets
        try:
            self._hide_settings_tooltip()
        except Exception:
            pass
        for w in inline.winfo_children():
            w.destroy()

        # Load settings from DB
        conn = self.connect()
        try:
            cur = conn.execute("SELECT key, value, data_type FROM settings ORDER BY key")
            rows = cur.fetchall()
        finally:
            conn.close()

        # Define which keys we want as comboboxes and their options
        openai_models = self._get_openai_model_choices()
        combobox_map = {
            "Elevenlabs Synthesizer Model": ELEVEN_LABS_VOICE_MODELS,
            "Azure TTS Backup Voice": AZURE_TTS_VOICES,
            "Audio Output Device": AUDIO_DEVICES,
            "Default OpenAI Model": openai_models,
        }
        combobox_labels = {
            "Default OpenAI Model": "Default GPT Model",
        }
        volume_order = ["Elevenlabs TTS Volume", "Azure TTS Volume", "Sound FX Volume"]
        volume_keys = set(volume_order)

        shared_prefix = "Shared Chat"
        shared_bool_rows: list[sqlite3.Row] = []
        bool_rows: list[sqlite3.Row] = []
        combo_rows: list[sqlite3.Row] = []
        volume_rows: list[sqlite3.Row] = []

        for row in rows:
            key = row["key"]
            dtype = (row["data_type"] or "TEXT").upper()
            if dtype == "BOOL":
                if key.startswith(shared_prefix):
                    shared_bool_rows.append(row)
                else:
                    bool_rows.append(row)
            elif key in combobox_map:
                combo_rows.append(row)
            elif key in volume_keys:
                volume_rows.append(row)

        for col in range(3):
            inline.grid_columnconfigure(col, weight=1)

        slider_jobs: dict[str, str] = {}

        def _format_bool_label(text: str | None) -> str:
            if not text:
                return ""
            cleaned = text.strip()
            if cleaned.lower().endswith(" enabled"):
                cleaned = cleaned[:-len(" enabled")].rstrip()
            return cleaned

        def _schedule_slider_save(setting_key: str, value: int) -> None:
            job_id = slider_jobs.pop(setting_key, None)
            if job_id is not None:
                try:
                    self.after_cancel(job_id)
                except Exception:
                    pass

            def _commit() -> None:
                slider_jobs.pop(setting_key, None)
                try:
                    self.save_setting_inline(setting_key, str(value), "INTEGER")
                except Exception as exc:
                    print(f"Error saving setting {setting_key}: {exc}")

            try:
                slider_jobs[setting_key] = self.after(200, _commit)
            except Exception:
                # Fall back to immediate save if scheduling fails (e.g., window closing)
                _commit()

        def _add_bool_row(container, row_data, grid_row: int, label_override: str | None = None) -> int:
            key = row_data["key"]
            val = row_data["value"]
            label_text = _format_bool_label(label_override or key)
            lbl = ttk.Label(container, text=label_text)
            lbl.grid(row=grid_row, column=0, sticky=tk.W, padx=4, pady=2)
            var = tk.BooleanVar(value=(str(val) in ("1", "True", "true")))
            disable_google_checkbox = (
                key == "Google Sheets Integration Enabled"
                and not getattr(self, "_google_credentials_valid", True)
            )
            if disable_google_checkbox:
                try:
                    var.set(False)
                except Exception:
                    pass
            cb = ttk.Checkbutton(container, variable=var)
            cb.grid(row=grid_row, column=1, sticky=tk.W, padx=4, pady=2)

            if disable_google_checkbox:
                tooltip_msg = (
                    self._google_credentials_error
                    or "Google Sheets credentials.json is missing or invalid. Required keys: type, project_id, private_key_id, private_key."
                )
                try:
                    cb.state(["disabled"])
                except Exception:
                    cb.configure(state=tk.DISABLED)
                try:
                    lbl.configure(foreground="#888888")
                except Exception:
                    pass

                def _show_disabled_tooltip(event, text=tooltip_msg):
                    self._show_settings_tooltip(text, event.x_root, event.y_root)

                def _hide_disabled_tooltip(_event):
                    self._hide_settings_tooltip()

                for widget in (cb, lbl):
                    try:
                        widget.bind("<Enter>", _show_disabled_tooltip)
                        widget.bind("<Leave>", _hide_disabled_tooltip)
                        widget.bind("<FocusOut>", _hide_disabled_tooltip)
                        widget.bind("<Destroy>", _hide_disabled_tooltip)
                    except Exception:
                        pass

            def make_trace(k, v):
                def _trace(*_):
                    try:
                        new_val = "1" if v.get() else "0"
                        self.save_setting_inline(k, new_val, "BOOL")
                    except Exception as e:
                        print(f"Error saving setting {k}: {e}")

                return _trace

            var.trace_add("write", make_trace(key, var))
            return grid_row + 1

        def _add_combobox_row(container, row_data, grid_row: int) -> int:
            key = row_data["key"]
            val = row_data["value"]
            options = list(combobox_map.get(key, []) or [])
            if val not in (None, "") and val not in options:
                options.append(val)
            display_label = combobox_labels.get(key, key)
            lbl = ttk.Label(container, text=display_label)
            lbl.grid(row=grid_row, column=0, sticky=tk.W, padx=4, pady=2)
            cb = ttk.Combobox(container, values=options, state="readonly", width=28)
            try:
                if val is None:
                    cb.set("")
                else:
                    cb.set(val)
            except Exception:
                cb.set("")
            cb.grid(row=grid_row, column=1, sticky=tk.W, padx=4, pady=2)

            def on_sel(event, k=key, widget=cb):
                try:
                    new_val = widget.get()
                    self.save_setting_inline(k, new_val, "TEXT")
                    if k == "Audio Output Device":
                        def _apply_device():
                            try:
                                audio_manager = get_reference("AudioManager")
                                audio_manager.set_output_device(new_val)
                            except Exception as e:
                                try:
                                    messagebox.showerror("Audio Device", f"Failed to set audio output device: {e}", parent=self)
                                except Exception:
                                    print(f"Error setting audio output device: {e}")

                        try:
                            self.after(0, _apply_device)
                        except Exception:
                            try:
                                _apply_device()
                            except Exception as e:
                                print(f"Error applying audio device: {e}")
                except Exception as e:
                    print(f"Error saving combobox setting {k}: {e}")

            cb.bind("<<ComboboxSelected>>", on_sel)
            return grid_row + 1

        def _add_volume_slider(container, row_data, grid_column: int) -> None:
            key = row_data["key"]
            raw_val = row_data["value"]
            try:
                initial = float(raw_val)
            except (TypeError, ValueError):
                initial = 100.0
            initial = max(0.0, min(100.0, initial))
            value_var = tk.StringVar(value=f"{int(round(initial))}%")

            title = ttk.Label(container, text=key, anchor="center", justify="center")
            title.grid(row=0, column=grid_column, padx=6, pady=(0, 2))
            value_lbl = ttk.Label(container, textvariable=value_var, font=(None, 10, "bold"))
            value_lbl.grid(row=1, column=grid_column, padx=6, pady=(0, 6))

            scale_var = tk.DoubleVar(value=initial)
            guard = {"init": True}

            def _on_change(value: str, *, setting_key: str = key, var=value_var, guard_state=guard):
                try:
                    numeric = float(value)
                except (TypeError, ValueError):
                    numeric = 0.0
                numeric = max(0.0, min(100.0, numeric))
                rounded = int(round(numeric))
                var.set(f"{rounded}%")
                if guard_state.get("init"):
                    return
                _schedule_slider_save(setting_key, rounded)

            scale = ttk.Scale(
                container,
                from_=100,
                to=0,
                orient=tk.VERTICAL,
                variable=scale_var,
                length=120,
                command=_on_change,
            )
            scale.grid(row=2, column=grid_column, padx=8, pady=(0, 6), sticky="ns")
            guard["init"] = False

        toggle_frame = None
        if bool_rows:
            toggle_frame = ttk.LabelFrame(inline, text="Settings Toggles")
            toggle_frame.grid(row=0, column=0, sticky="nw", padx=(0, 8), pady=(0, 0))
            toggle_frame.grid_columnconfigure(0, weight=0)
            toggle_frame.grid_columnconfigure(1, weight=0)
            tr = 0
            for row in bool_rows:
                tr = _add_bool_row(toggle_frame, row, tr)

        center_column = None
        if combo_rows or volume_rows:
            center_column = ttk.Frame(inline)
            center_column.grid(row=0, column=1, sticky="nw", padx=(0, 8), pady=(0, 0))
            center_column.grid_columnconfigure(0, weight=1)

        combo_frame = None
        if combo_rows:
            combo_frame = ttk.LabelFrame(center_column, text="Voice, Audio & GPT Options")
            combo_frame.grid(row=0, column=0, sticky="nw")
            combo_frame.grid_columnconfigure(0, weight=0)
            combo_frame.grid_columnconfigure(1, weight=0)
            cr = 0
            for row in combo_rows:
                cr = _add_combobox_row(combo_frame, row, cr)

        if volume_rows:
            volume_rows.sort(key=lambda r: volume_order.index(r["key"]) if r["key"] in volume_order else len(volume_order))
            slider_frame = ttk.LabelFrame(center_column, text="TTS & FX Volume")
            slider_frame.grid(row=1, column=0, sticky="nw", pady=(8, 0))
            for idx, row in enumerate(volume_rows):
                slider_frame.grid_columnconfigure(idx, weight=1)
                _add_volume_slider(slider_frame, row, idx)

        if shared_bool_rows:
            section = ttk.LabelFrame(inline, text="Shared Chat Settings")
            section.grid(row=0, column=2, sticky="nw", padx=(0, 0), pady=(0, 0))
            section.columnconfigure(1, weight=1)
            sr = 0
            for row in shared_bool_rows:
                suffix = row["key"][len(shared_prefix):].lstrip()
                display_label = suffix or row["key"]
                sr = _add_bool_row(section, row, sr, label_override=display_label)

    def _handle_setting_side_effect(self, key: str | None, value: str | None) -> None:
        """Apply runtime side effects for specific settings immediately after save."""
        if not key:
            return
        normalized = str(value).strip().lower() if value is not None else ""
        should_enable = normalized in ("1", "true", "t", "yes", "y", "on")

        if key.startswith("Shared Chat"):
            self._refresh_shared_chat_settings_async()

        if key == "Chat Response Enabled":
            try:
                start_timer_manager_in_background()
            except Exception:
                pass
            try:
                timer = get_reference("ResponseTimer")
            except Exception:
                timer = None
            if timer is None:
                debug_print("GUI", "Chat Response toggled but ResponseTimer is unavailable.")
                return
            loop = None
            try:
                loop = get_database_loop()
                if loop is not None:
                    try:
                        if loop.is_closed() or not loop.is_running():
                            loop = None
                    except Exception:
                        loop = None
            except Exception:
                loop = None
            if loop is None:
                try:
                    import ai_logic
                    loop = getattr(ai_logic, "_timer_loop", None)
                    if loop is not None:
                        try:
                            if loop.is_closed() or not loop.is_running():
                                loop = None
                        except Exception:
                            loop = None
                    if loop is None:
                        loop = ai_logic._ensure_response_timer_loop()
                except Exception:
                    loop = None
            if loop is None:
                debug_print("GUI", "Chat Response toggle ignored because no event loop is available for ResponseTimer.")
                return
            try:
                coro = timer.start_timer() if should_enable else timer.end_timer()
                asyncio.run_coroutine_threadsafe(coro, loop)
                debug_print("GUI", f"Scheduled ResponseTimer {'start' if should_enable else 'stop'} after UI toggle.")
            except Exception as e:
                debug_print("GUI", f"Failed to schedule ResponseTimer update: {e}")
            return

        if key == "Event Queue Enabled":
            try:
                event_manager = get_reference("EventManager")
            except Exception:
                event_manager = None
            if event_manager is None:
                debug_print("GUI", "Event Queue toggled but EventManager reference is unavailable.")
                return
            try:
                coro = (
                    event_manager.stop_event_timer()
                    if should_enable
                    else event_manager.start_event_timer()
                )
            except Exception as exc:
                debug_print("GUI", f"Unable to create EventManager coroutine: {exc}")
                return
            scheduled = self._schedule_async_task(coro, source="GUISettings")
            if not scheduled:
                debug_print("GUI", "Failed to schedule EventManager coroutine after Event Queue toggle.")
            return

        if key == "Seconds Between Events":
            try:
                new_time = int(str(value).strip())
            except (TypeError, ValueError):
                debug_print("GUI", "Seconds Between Events change ignored due to invalid value.")
                return

            queue_enabled = False
            conn = None
            try:
                conn = self.connect()
                cur = conn.execute(
                    "SELECT value FROM settings WHERE key = ?",
                    ("Event Queue Enabled",),
                )
                row = cur.fetchone()
                if row is not None:
                    normalized_flag = str(row["value"]).strip().lower()
                    queue_enabled = normalized_flag in ("1", "true", "t", "yes", "y", "on")
            except Exception as exc:
                debug_print("GUI", f"Failed to read Event Queue Enabled flag: {exc}")
            finally:
                if conn is not None:
                    conn.close()

            if queue_enabled:
                return

            try:
                event_manager = get_reference("EventManager")
            except Exception:
                event_manager = None
            if event_manager is None:
                debug_print("GUI", "Seconds Between Events changed but EventManager is unavailable.")
                return
            try:
                coro = event_manager.update_time_between_events(new_time)
            except Exception as exc:
                debug_print("GUI", f"Unable to create EventManager update coroutine: {exc}")
                return
            scheduled = self._schedule_async_task(coro, source="GUISettings")
            if not scheduled:
                debug_print("GUI", "Failed to schedule EventManager update after Seconds Between Events change.")
            return
        # No additional side effects registered for other keys.
        return

    def _refresh_shared_chat_settings_async(self) -> None:
        """Notify the CommandHandler that shared chat settings changed."""
        try:
            handler = get_reference("CommandHandler")
        except Exception:
            handler = None
        if handler is None:
            debug_print("GUI", "CommandHandler unavailable; cannot refresh shared chat settings.")
            return
        try:
            coro = handler.set_shared_chat_settings()
        except Exception as exc:
            debug_print("GUI", f"Failed to prepare shared chat settings update: {exc}")
            return
        if not self._schedule_async_task(coro, "SharedChatSettings"):
            debug_print("GUI", "Unable to schedule shared chat settings update; bot loop not ready.")

    def _get_openai_model_choices(self) -> list[str]:
        """Return cached OpenAI model ids, fetching from GPTManager if needed."""
        if self._openai_model_choices is not None:
            return self._openai_model_choices
        models: list[str] = []
        try:
            gpt_manager = get_reference("GPTManager")
        except Exception as exc:
            debug_print("GUI", f"Failed to access GPTManager for model list: {exc}")
            gpt_manager = None
        if gpt_manager is not None:
            try:
                fetched = gpt_manager.get_all_models() or []
                models.extend(str(m) for m in fetched if m)
            except Exception as exc:
                debug_print("GUI", f"Error fetching OpenAI models: {exc}")
        if not models:
            models.extend(GPT_MODELS)
        # Remove duplicates while preserving order
        seen: set[str] = set()
        deduped: list[str] = []
        for model in models:
            if model not in seen:
                seen.add(model)
                deduped.append(model)
        self._openai_model_choices = deduped
        return self._openai_model_choices

    def save_setting_inline(self, key: str, value: str, data_type: str = "TEXT") -> None:
        """Persist a single setting change from the inline editor and refresh the display."""
        debug_print("GUI", f"Inline save: key={key}, value={value}, data_type={data_type}")
        conn = self.connect()
        try:
            # store value as string; ensure boolean stored as '1'/'0'
            if data_type.upper() == "BOOL":
                v = "1" if str(value) in ("1", "True", "true") else "0"
            else:
                v = str(value)
            conn.execute("UPDATE settings SET value = ?, data_type = ? WHERE key = ?", (v, data_type.upper(), key))
            conn.commit()
        finally:
            conn.close()
        self._handle_setting_side_effect(key, v)
        # If this was the Debug Mode setting, call set_debug to apply immediately
        try:
            if key == "Debug Mode":
                try:
                    debug_bool = True if str(v) in ("1", "True", "true") else False
                    try:
                        asyncio.run(set_debug(debug_bool))
                    except Exception:
                        # fallback: run in background thread
                        threading.Thread(target=lambda: asyncio.run(set_debug(debug_bool)), daemon=True).start()
                except Exception as e:
                    print(f"Error applying Debug Mode: {e}")
        except Exception:
            pass

        # If this was the audio output device, inform the audio manager asynchronously
        try:
            if key == "Audio Output Device":
                # Apply on the main thread to avoid thread-safety issues in pygame/SDL.
                def _apply():
                    try:
                        audio_manager = get_reference("AudioManager")
                        audio_manager.set_output_device(v)
                    except Exception as e:
                                    try:
                                        messagebox.showerror("Audio Device", f"Failed to set audio output device: {e}", parent=self)
                                    except Exception:
                                        print(f"Error setting audio output device: {e}")
                try:
                    self.after(0, _apply)
                except Exception:
                    try:
                        _apply()
                    except Exception as e:
                        print(f"Error applying audio device: {e}")
        except Exception:
            pass

        # Refresh the settings table and inline widgets to reflect changes
        try:
            self.refresh_table("settings")
        except Exception:
            pass
        # If the assistant manager exists (timer_manager.assistant), update its cached
        # assistant names so the running Assistant picks up any name changes.
        try:
            import ai_logic

            tm = get_reference("ResponseTimer")
            loop = getattr(ai_logic, "_timer_loop", None)
            if tm:
                assistant = get_reference("AssistantManager")
                coro = assistant.set_assistant_names()
                # If the timer manager's loop is available, schedule on that loop
                if loop and loop.is_running():
                    try:
                        asyncio.run_coroutine_threadsafe(coro, loop)
                    except Exception:
                        # Fallback: run in a daemon thread event loop
                        threading.Thread(target=lambda: asyncio.run(coro), daemon=True).start()
                else:
                    # No shared loop detected; run in a background thread.
                    threading.Thread(target=lambda: asyncio.run(coro), daemon=True).start()
        except Exception:
            # Do not allow assistant name refresh failures to affect the settings UI.
            pass

    def start_bot_background(self):
        debug_print("GUI", f"Starting bot in background thread.")
        def run_bot():
            try:
                # Import and run the bot in this thread. twitchbot.main() will block.
                import twitchbot

                print("Starting twitch bot...\n")
                twitchbot.main()
            except Exception as e:
                print(f"Bot thread exception: {e}\n")

        t = threading.Thread(target=run_bot, daemon=True)
        t.start()
        # After starting the bot thread, periodically check for the async DB
        # loop being available and refresh hotkeys once it is. This avoids the
        # common startup race where the GUI queries hotkeys before the async
        # DB pool (created by the bot) exists and ends up showing "null".
        try:
            self.after(2000, lambda: self._refresh_hotkeys_when_db_ready(0))
        except Exception:
            pass

    def _refresh_hotkeys_when_db_ready(self, attempts: int = 0) -> None:
        """Check for the async database loop and refresh hotkeys when ready.

        Retries a few times and then gives up to avoid an endless loop.
        """
        try:
            from db import get_database_loop
            loop = get_database_loop()
            if loop and getattr(loop, "is_running", lambda: False)():
                try:
                    self.refresh_hotkeys()
                    return
                except Exception:
                    pass
        except Exception:
            pass

        # Retry a few times (e.g., ~20 * 500ms = 10s) then stop
        if attempts < 20:
            try:
                self.after(500, lambda: self._refresh_hotkeys_when_db_ready(attempts + 1))
            except Exception:
                pass

    def _on_close(self):
        """Handle GUI shutdown: close async DB pool, then destroy window."""
        try:
            if getattr(self, "_event_tab_refresh_job", None):
                self.after_cancel(self._event_tab_refresh_job)
                self._event_tab_refresh_job = None
        except Exception:
            pass
        try:
            if self._obs_warning_job:
                self.after_cancel(self._obs_warning_job)
                self._obs_warning_job = None
        except Exception:
            pass
        # Fire-and-forget the DB close so the GUI doesn't hang waiting for
        # asynchronous resources to shut down. If the DB loop exists and is
        # running we schedule the close there without waiting; otherwise we
        # schedule the close in a background thread.
        try:
            self.clean_up_temp_files()
            debug_print("GUI", "Scheduling async database pool close (non-blocking).")
            try:
                # prefer scheduling without waiting to avoid GUI freezes
                close_database_sync(wait=False)
            except Exception as e:
                debug_print("GUI", f"Error scheduling DB close: {e}")
        except Exception:
            pass

        # Destroy the main window to exit tkinter mainloop immediately
        try:
            self.destroy()
        except Exception:
            try:
                self.quit()
            except Exception:
                pass

    def clean_up_temp_files(self) -> None:
        """Remove temporary files created during the session."""
        media_dir = path_from_app_root("media")
        memes_dir = media_dir / "memes"
        if memes_dir.exists():
            for file in memes_dir.iterdir():
                if file.name in ["test_meme.png", "test_meme.jpg", "test_meme.jpeg", "test_meme.gif"]:
                    continue
                try:
                    file.unlink()
                except Exception as e:
                    print(f"[ERROR]Error deleting meme file: {e}")
        voice_audio_dir = media_dir / "voice_audio"
        if voice_audio_dir.exists():
            for file in voice_audio_dir.iterdir():
                if file.name == "test_voice.wav":
                    continue
                try:
                    file.unlink()
                except Exception as e:
                    print(f"[ERROR]Error deleting audio file: {e}")
        screenshots_dir = media_dir / "screenshots"
        if screenshots_dir.exists():
            for file in screenshots_dir.iterdir():
                if file.name == "test_screenshot.png":
                    continue
                try:
                    file.unlink()
                except Exception as e:
                    print(f"[ERROR]Error deleting screenshot file: {e}")

    def _scheduler_call_start(self, task_id: int) -> None:
        """Attempt to schedule start_new_message(task_id) on the bot's scheduler.

        Tries several access patterns for robustness: `bot.scheduler`,
        `bot.command_handler.scheduler`, and falls back to running the coroutine
        in a new thread if we can't find the bot loop. This is best-effort so GUI
        doesn't crash when the bot isn't running.
        """
        try:
            bot = get_reference("TwitchBot")
            if not bot:
                debug_print("GUI", "No bot available to start scheduled message")
                return
            # find scheduler object
            scheduler = get_reference("MessageScheduler")

            # Prepare coroutine
            coro = scheduler.start_new_message(int(task_id))

            # Candidate loops: bot loop first, then database pool loop
            candidate_loops = []
            try:
                bot_loop = getattr(bot, "loop", None) or getattr(bot, "_loop", None)
                if bot_loop:
                    candidate_loops.append(bot_loop)
            except Exception:
                pass

            try:
                from db import get_database_loop
                db_loop = get_database_loop()
                if db_loop:
                    candidate_loops.append(db_loop)
            except Exception:
                db_loop = None

            # Try scheduling on any candidate loop via run_coroutine_threadsafe
            for loop in candidate_loops:
                try:
                    asyncio.run_coroutine_threadsafe(coro, loop)
                    return
                except Exception:
                    continue

            # Last resort: run in a new background thread with its own loop
            threading.Thread(target=lambda: asyncio.run(coro), daemon=True).start()
        except Exception as e:
            debug_print("GUI", f"_scheduler_call_start error: {e}")

    def _scheduler_call_end(self, task_id: int) -> None:
        """Attempt to schedule end_task(task_id) on the bot's scheduler.

        See notes in `_scheduler_call_start` about best-effort behavior.
        """
        try:
            bot = get_reference("TwitchBot")
            if not bot:
                debug_print("GUI", "No bot available to end scheduled message")
                return
            scheduler = get_reference("MessageScheduler")
            if not scheduler:
                debug_print("GUI", "Bot has no scheduler attribute; cannot end scheduled message")
                return

            coro = scheduler.end_task(int(task_id))

            candidate_loops = []
            try:
                bot_loop = getattr(bot, "loop", None) or getattr(bot, "_loop", None)
                if bot_loop:
                    candidate_loops.append(bot_loop)
            except Exception:
                pass
            try:
                from db import get_database_loop
                db_loop = get_database_loop()
                if db_loop:
                    candidate_loops.append(db_loop)
            except Exception:
                db_loop = None

            for loop in candidate_loops:
                try:
                    asyncio.run_coroutine_threadsafe(coro, loop)
                    return
                except Exception:
                    continue

            # fallback to background thread with its own loop
            threading.Thread(target=lambda: asyncio.run(coro), daemon=True).start()
        except Exception as e:
            debug_print("GUI", f"_scheduler_call_end error: {e}")

    def start_capture_location(self, object_name: str, is_onscreen: bool) -> None:
        """Run obs_manager.capture_location(is_onscreen) in a background thread and show the result."""
        debug_print("GUI", f"Starting capture location (onscreen={is_onscreen}) in background thread.")
        def worker():
            # New approach: perform capture using OBS client's synchronous methods
            # from this worker thread to avoid running the OBS coroutine on a
            # different event loop. First, fetch the assistant name from the DB
            # loop (if needed), then call the obs client synchronously, then
            # persist the result back on the DB loop.
            result = None
            object_name_local = object_name
            db_loop = None
            try:
                from db import get_database_loop
                db_loop = get_database_loop()
            except Exception:
                db_loop = None

            # Fetch assistant name via DB loop if not provided
            if not object_name_local:
                try:
                    if db_loop and getattr(db_loop, "is_running", lambda: False)():
                        fut = asyncio.run_coroutine_threadsafe(get_setting("OBS Assistant Object Name"), db_loop)
                        try:
                            object_name_local = fut.result(5)
                        except Exception:
                            object_name_local = None
                    else:
                        try:
                            object_name_local = asyncio.run(get_setting("OBS Assistant Object Name"))
                        except Exception:
                            object_name_local = None
                except Exception:
                    object_name_local = None

            # Now call OBS synchronous APIs directly from this thread
            try:
                obs_manager = get_reference("OBSManager")
                current_scene = obs_manager.ws.get_current_program_scene().current_program_scene_name
                scene_items = obs_manager.ws.get_scene_item_list(current_scene)
                scene_item_id = None
                if not object_name_local:
                    result = f"Error capturing location: assistant name not set"
                else:
                    for item in scene_items.scene_items:
                        if item["sourceName"] == object_name_local:
                            scene_item_id = item["sceneItemId"]
                            break

                    if not scene_item_id:
                        result = f"Error: {object_name_local} not found in scene."
                    else:
                        current_transform = obs_manager.ws.get_scene_item_transform(current_scene, scene_item_id)
                        transform = current_transform.scene_item_transform
                        location_data = {
                            "x": transform["positionX"],
                            "y": transform["positionY"],
                            "scaleX": transform["scaleX"],
                            "scaleY": transform["scaleY"],
                        }
                        result = location_data
            except Exception as e:
                result = f"Error capturing location: {e}"

            # Persist capture on DB loop if we have a dict
            if isinstance(result, dict):
                try:
                    if db_loop and getattr(db_loop, "is_running", lambda: False)():
                        futp = asyncio.run_coroutine_threadsafe(save_location_capture(object_name_local or "", int(is_onscreen), result.get("x"), result.get("y"), result.get("scaleX"), result.get("scaleY")), db_loop)
                        try:
                            futp.result(5)
                        except Exception:
                            print("Warning: failed to persist captured location on DB loop")
                    else:
                        try:
                            asyncio.run(save_location_capture(object_name_local or "", int(is_onscreen), result.get("x"), result.get("y"), result.get("scaleX"), result.get("scaleY")))
                        except Exception as e:
                            print(f"Error saving captured location: {e}")
                except Exception as e:
                    print(f"Error saving captured location: {e}")

            def show_result():
                if result:
                    messagebox.showinfo("Capture Location", "Location successfully captured and added to the database.", parent=self)
                else:
                    messagebox.showinfo("Capture Location", "No location returned", parent=self)

            # Schedule UI update on main thread
            try:
                self.after(0, show_result)
            except Exception:
                # If scheduling fails, fallback to printing
                print(result)

        t = threading.Thread(target=worker, daemon=True)
        t.start()

    def refresh_hotkeys(self) -> None:
        """Fetch current hotkeys from DB in a background thread and update UI."""
        debug_print("GUI", f"Refreshing hotkeys in background thread.")
        def worker():
            try:
                # collect current values
                values = {}
                # Prefer scheduling DB coroutines on the DB pool's loop to avoid
                # 'Future attached to a different loop' errors. Fall back to
                # running in a fresh loop if the DB loop isn't available.
                from db import get_database_loop
                db_loop = get_database_loop()
                for action in list(self.hotkey_widgets.keys()):
                    val = "null"
                    try:
                        if db_loop and getattr(db_loop, "is_running", lambda: False)():
                            fut = asyncio.run_coroutine_threadsafe(get_hotkey(action, "null"), db_loop)
                            try:
                                val = fut.result(2)
                            except Exception:
                                val = "null"
                        else:
                            try:
                                val = asyncio.run(get_hotkey(action, "null"))
                            except Exception:
                                val = "null"
                    except Exception:
                        val = "null"
                    values[action] = val
            except Exception as e:
                print(f"Error loading hotkeys: {e}")
                values = {}

            def apply_values():
                for action, val in values.items():
                    var = self.hotkey_widgets.get(action, {}).get("var")
                    if var is not None:
                        var.set(val if val is not None else "null")

            self.after(0, apply_values)

        t = threading.Thread(target=worker, daemon=True)
        t.start()

    def refresh_randomizer_lists(self) -> None:
        """Fetch randomizer main and modifier entries from DB and populate listboxes."""
        debug_print("GUI", "Refreshing randomizer lists.")
        def worker():
            main_rows = []
            mod_rows = []
            try:
                from db import get_database_loop
                db_loop = get_database_loop()
                if db_loop and getattr(db_loop, "is_running", lambda: False)():
                    try:
                        fut_main = asyncio.run_coroutine_threadsafe(get_randomizer_main_entries(), db_loop)
                        fut_mod = asyncio.run_coroutine_threadsafe(get_randomizer_modifier_entries(), db_loop)
                        main_rows = fut_main.result(3)
                        mod_rows = fut_mod.result(3)
                    except Exception:
                        main_rows = []
                        mod_rows = []
                else:
                    try:
                        main_rows = asyncio.run(get_randomizer_main_entries())
                        mod_rows = asyncio.run(get_randomizer_modifier_entries())
                    except Exception:
                        main_rows = []
                        mod_rows = []
            except Exception:
                main_rows = []
                mod_rows = []

            # If async fetch didn't return anything, attempt synchronous DB read
            # directly from the sqlite file so startup populates lists even when
            # the async pool/loop isn't ready yet.
            try:
                if not main_rows and not mod_rows:
                    conn = self.connect()
                    try:
                        cur = conn.execute("SELECT id, text FROM randomizer WHERE is_modifier = 0 ORDER BY id")
                        main_rows = [{"id": r[0], "text": r[1]} for r in cur.fetchall()]
                        cur = conn.execute("SELECT id, text FROM randomizer WHERE is_modifier = 1 ORDER BY id")
                        mod_rows = [{"id": r[0], "text": r[1]} for r in cur.fetchall()]
                    finally:
                        conn.close()
            except Exception:
                # ignore fallback failures
                pass

            def apply():
                try:
                    ml = self.randomizer_widgets.get("main_listbox")
                    mo = self.randomizer_widgets.get("mod_listbox")
                    self.randomizer_widgets["main_rows"] = list(main_rows)
                    self.randomizer_widgets["mod_rows"] = list(mod_rows)
                    # clear or set chosen labels if present
                    mc = self.randomizer_widgets.get("main_choice_var")
                    mmc = self.randomizer_widgets.get("mod_choice_var")
                    combined_var = self.randomizer_widgets.get("combined_choice_var")
                    # Clear stored choice displays on refresh
                    if mc:
                        mc.set("")
                    if mmc:
                        mmc.set("")
                    if combined_var:
                        combined_var.set("")
                    if ml:
                        ml.delete(0, tk.END)
                        for r in main_rows:
                            ml.insert(tk.END, r.get("text") if isinstance(r, dict) else str(r))
                        self._apply_listbox_stripes(ml)
                    if mo:
                        mo.delete(0, tk.END)
                        for r in mod_rows:
                            mo.insert(tk.END, r.get("text") if isinstance(r, dict) else str(r))
                        self._apply_listbox_stripes(mo)
                except Exception as e:
                    debug_print("GUI", f"Failed applying randomizer lists: {e}")

            self.after(0, apply)

        threading.Thread(target=worker, daemon=True).start()

    def _rand_add(self, is_modifier: bool) -> None:
        prompt = "Enter new modifier string:" if is_modifier else "Enter new main string:"
        val = simpledialog.askstring("Add Entry", prompt, parent=self)
        if not val:
            return

        def worker():
            try:
                from db import get_database_loop
                db_loop = get_database_loop()
                if db_loop and getattr(db_loop, "is_running", lambda: False)():
                    fut = asyncio.run_coroutine_threadsafe(add_randomizer_entry(val, is_modifier), db_loop)
                    try:
                        fut.result(3)
                    except Exception:
                        pass
                else:
                    try:
                        asyncio.run(add_randomizer_entry(val, is_modifier))
                    except Exception:
                        pass
            except Exception:
                pass
            self.refresh_randomizer_lists()

        threading.Thread(target=worker, daemon=True).start()

    def _rand_remove(self, is_modifier: bool) -> None:
        lst_name = "mod_rows" if is_modifier else "main_rows"
        lb = self.randomizer_widgets.get("mod_listbox" if is_modifier else "main_listbox")
        if not lb:
            return
        sel = lb.curselection()
        if not sel:
            messagebox.showinfo("Remove Entry", "Please select one or more items to remove.", parent=self)
            return

        rows = self.randomizer_widgets.get(lst_name, [])
        entry_ids = []
        missing_id_indices = []
        for idx in sel:
            try:
                entry = rows[idx]
                entry_id = entry.get("id") if isinstance(entry, dict) else None
            except Exception:
                entry_id = None
            if entry_id is None:
                missing_id_indices.append(idx)
            else:
                entry_ids.append(entry_id)

        if not entry_ids:
            messagebox.showerror("Remove Entry", "Selected entries have no IDs and cannot be removed.", parent=self)
            return

        # Confirm removing N entries
        if not messagebox.askyesno("Remove Entries", f"Remove the {len(entry_ids)} selected entr{'y' if len(entry_ids)==1 else 'ies'}?", parent=self):
            return

        def worker():
            try:
                from db import get_database_loop
                db_loop = get_database_loop()
                for eid in entry_ids:
                    try:
                        if db_loop and getattr(db_loop, "is_running", lambda: False)():
                            fut = asyncio.run_coroutine_threadsafe(remove_randomizer_entry(eid), db_loop)
                            try:
                                fut.result(3)
                            except Exception:
                                pass
                        else:
                            try:
                                asyncio.run(remove_randomizer_entry(eid))
                            except Exception:
                                pass
                    except Exception:
                        # continue removing other entries even if one fails
                        pass
            except Exception:
                pass
            self.refresh_randomizer_lists()

        threading.Thread(target=worker, daemon=True).start()

    def _rand_choose(self, is_modifier: bool) -> None:
        rows = self.randomizer_widgets.get("mod_rows" if is_modifier else "main_rows", [])
        texts = [r.get("text") if isinstance(r, dict) else str(r) for r in rows]
        if not texts:
            messagebox.showinfo("Choose Random", "No entries available to choose from.", parent=self)
            return
        choice = random.choice(texts)
        # store the choice without prefix
        if is_modifier:
            mv = self.randomizer_widgets.get("mod_choice_var")
            if mv:
                mv.set(choice)
        else:
            mv = self.randomizer_widgets.get("main_choice_var")
            if mv:
                mv.set(choice)

        # build combined display from main and modifier (append if both present)
        main_val = self.randomizer_widgets.get("main_choice_var").get() if self.randomizer_widgets.get("main_choice_var") else ""
        mod_val = self.randomizer_widgets.get("mod_choice_var").get() if self.randomizer_widgets.get("mod_choice_var") else ""
        combined = ""
        if main_val and mod_val:
            combined = f"{main_val} {mod_val}"
        elif main_val:
            combined = main_val
        else:
            combined = mod_val

        combined_var = self.randomizer_widgets.get("combined_choice_var")
        if combined_var is not None:
            combined_var.set(combined)

    def _on_tab_changed(self, event) -> None:
        try:
            current = event.widget.select()
        except Exception:
            return
        if self.users_tab_id and current == self.users_tab_id:
            self.refresh_users_tab()

    def _init_obs_warning_banner(self) -> None:
        if self._obs_warning_label is not None:
            return
        # Floating warning label so OBS connection issues are visible on every tab.
        self._obs_warning_label = tk.Label(
            self,
            text="OBS Not Connected",
            bg="#b32626",
            fg="white",
            font=("Segoe UI", 10, "bold"),
            padx=12,
            pady=4,
        )
        self._obs_warning_label.place_forget()
        self._update_obs_warning_banner()

    def _obs_connection_ready(self) -> bool:
        try:
            obs_manager = get_reference("OBSManager")
        except Exception:
            obs_manager = None
        if not obs_manager:
            return False
        connected_flag = getattr(obs_manager, "connected", None)
        if connected_flag is not None:
            try:
                return bool(connected_flag)
            except Exception:
                return False
        return getattr(obs_manager, "ws", None) is not None

    def _update_obs_warning_banner(self) -> None:
        label = self._obs_warning_label
        if label is None:
            return
        if self._obs_connection_ready():
            label.place_forget()
        else:
            label.lift()
            label.place(relx=1.0, rely=0.0, x=-16, y=16, anchor="ne")
        self._obs_warning_job = self.after(3000, self._update_obs_warning_banner)

    def _build_users_tab(self) -> None:
        users_frame = ttk.Frame(self.nb)
        self.nb.add(users_frame, text="Twitch Users")
        self.users_frame = users_frame
        self.users_tab_id = str(users_frame)

        toolbar = ttk.Frame(users_frame)
        toolbar.pack(fill=tk.X, padx=6, pady=6)

        btn_refresh = ttk.Button(toolbar, text="Refresh", command=self.refresh_users_tab)
        btn_refresh.pack(side=tk.LEFT, padx=4)

        self.purge_users_btn = ttk.Button(toolbar, text="Purge Banned/Deleted", command=self.purge_invalid_users)
        self.purge_users_btn.pack(side=tk.LEFT, padx=4)

        ttk.Button(toolbar, text="Remove Selected", command=self._remove_selected_user).pack(side=tk.LEFT, padx=4)

        ttk.Label(toolbar, textvariable=self.users_count_var).pack(side=tk.RIGHT, padx=4)

        columns = (
            "display_name",
            "discord_status",
            "messages",
            "bits",
            "months",
            "gifts",
            "points",
            "tts_voice",
            "date_added",
            "chime",
        )
        column_meta = [
            ("display_name", "Display Name", 160),
            ("discord_status", "Discord", 90),
            ("messages", "Messages", 90),
            ("bits", "Bits Donated", 110),
            ("months", "Months Subscribed", 150),
            ("gifts", "Subs Gifted", 110),
            ("points", "Points Redeemed", 140),
            ("tts_voice", "TTS Voice", 140),
            ("date_added", "Date Added", 120),
            ("chime", "Chime", 140),
        ]

        tree = ttk.Treeview(users_frame, columns=columns, show="headings", selectmode="browse")
        for col_id, heading, width in column_meta:
            tree.heading(col_id, text=heading, anchor=tk.CENTER)
            tree.column(col_id, width=width, anchor=tk.CENTER, stretch=True)

        try:
            tree.tag_configure("odd", background=ROW_STRIPE_LIGHT)
            tree.tag_configure("even", background=ROW_STRIPE_DARK)
        except Exception:
            pass

        tree.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        tree.bind("<Double-1>", self._on_users_tree_double_click)
        tree.bind("<Motion>", self._on_users_tree_motion)
        tree.bind("<Leave>", lambda _evt: self._hide_users_tooltip())
        self.users_tree = tree

        self.refresh_users_tab()

    def refresh_users_tab(self) -> None:
        if self.users_tree is None:
            return

        def worker():
            rows = []
            conn = None
            try:
                conn = self.connect()
                cursor = conn.execute(
                    """
                    SELECT
                        id,
                        username,
                        display_name,
                        discord_username,
                        number_of_messages,
                        bits_donated,
                        months_subscribed,
                        subscriptions_gifted,
                        points_redeemed,
                        tts_voice,
                        date_added,
                        sound_fx
                    FROM users
                    ORDER BY
                        CASE WHEN display_name IS NULL OR display_name = '' THEN username ELSE display_name END COLLATE NOCASE
                    """
                )
                rows = [dict(row) for row in cursor.fetchall()]
            except Exception as e:
                debug_print("GUI", f"Failed to fetch users: {e}")
            finally:
                if conn is not None:
                    conn.close()
            self.after(0, lambda rows=rows: self._apply_users_rows(rows))

        threading.Thread(target=worker, daemon=True).start()

    def _apply_users_rows(self, rows: list[dict]) -> None:
        if self.users_tree is None:
            return
        for child in self.users_tree.get_children():
            self.users_tree.delete(child)
        self.users_row_data = {}
        for idx, row in enumerate(rows):
            user_id = str(row.get("id") or row.get("username") or idx)
            display_name = row.get("display_name") or row.get("username") or "Unknown"
            discord_username = row.get("discord_username") or ""
            discord_status = "Linked" if discord_username and str(discord_username).strip().lower() != "null" else "Unlinked"
            values = (
                display_name,
                discord_status,
                row.get("number_of_messages") or 0,
                row.get("bits_donated") or 0,
                row.get("months_subscribed") or 0,
                row.get("subscriptions_gifted") or 0,
                row.get("points_redeemed") or 0,
                row.get("tts_voice") or "",
                row.get("date_added") or "",
                row.get("sound_fx") or "",
            )
            tag = "even" if (idx % 2 == 0) else "odd"
            try:
                self.users_tree.insert("", tk.END, iid=user_id, values=values, tags=(tag,))
            except Exception:
                self.users_tree.insert("", tk.END, values=values, tags=(tag,))
            self.users_row_data[user_id] = row
        self.users_count_var.set(f"Total Viewers: {len(rows)}")
        self._autosize_users_columns()

    def _on_users_tree_double_click(self, event) -> None:
        if self.users_tree is None:
            return
        if self.users_tree.identify("region", event.x, event.y) != "cell":
            return
        column = self.users_tree.identify_column(event.x)
        column_map = {
            "#3": ("number_of_messages", "Messages Sent"),
            "#4": ("bits_donated", "Bits Donated"),
            "#5": ("months_subscribed", "Months Subscribed"),
            "#6": ("subscriptions_gifted", "Subscriptions Gifted"),
            "#7": ("points_redeemed", "Channel Points Redeemed"),
        }
        if column not in column_map:
            return
        item_id = self.users_tree.identify_row(event.y)
        if not item_id:
            return
        field, label = column_map[column]
        # Treeview columns use the identifiers from self.users_tree["columns"]
        col_name = self.users_tree["columns"][int(column.strip("#")) - 1]
        current_value = self.users_tree.set(item_id, col_name)
        self._prompt_and_update_user_stat(str(item_id), field, label, current_value)

    def _prompt_and_update_user_stat(self, user_id: str, field: str, label: str, current: str) -> None:
        try:
            current_val = int(current)
        except Exception:
            current_val = 0
        new_value = simpledialog.askinteger(
            "Edit Value",
            f"Enter new value for {label}:",
            parent=self,
            minvalue=0,
            initialvalue=current_val,
        )
        if new_value is None:
            return
        self._update_user_stat_value(user_id, field, label, new_value)

    def _update_user_stat_value(self, user_id: str, field: str, label: str, value: int) -> None:
        def worker():
            conn = None
            try:
                conn = self.connect()
                with conn:
                    conn.execute(f"UPDATE users SET {field} = ? WHERE id = ?", (value, user_id))
            except Exception as e:
                debug_print("GUI", f"Failed to update {field} for user {user_id}: {e}")
                self.after(0, lambda: messagebox.showerror("Update Failed", f"Could not update {label}."))
                return
            finally:
                if conn is not None:
                    conn.close()
            self.after(0, self.refresh_users_tab)

        threading.Thread(target=worker, daemon=True).start()

    def _remove_selected_user(self) -> None:
        if self.users_tree is None:
            return
        selection = self.users_tree.selection()
        if not selection:
            messagebox.showinfo("Remove User", "Select a user to remove first.", parent=self)
            return
        user_id = selection[0]
        display_name = self.users_tree.set(user_id, "display_name") or user_id
        if not messagebox.askyesno("Remove User", f"Remove '{display_name}' from the database?", parent=self):
            return

        def worker():
            conn = None
            try:
                conn = self.connect()
                conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
                conn.commit()
            except Exception as e:
                debug_print("GUI", f"Failed to remove user {user_id}: {e}")
                self.after(0, lambda: messagebox.showerror("Remove User", "Could not remove the selected user."))
                return
            finally:
                if conn is not None:
                    conn.close()
            self.after(0, self.refresh_users_tab)

        threading.Thread(target=worker, daemon=True).start()

    def _on_users_tree_motion(self, event) -> None:
        if self.users_tree is None:
            return
        column = self.users_tree.identify_column(event.x)
        if column != "#2":
            self._hide_users_tooltip()
            return
        item_id = self.users_tree.identify_row(event.y)
        if not item_id:
            self._hide_users_tooltip()
            return
        row = self.users_row_data.get(str(item_id))
        if not row:
            self._hide_users_tooltip()
            return
        username = row.get("username") or "Unknown"
        discord_name = row.get("discord_username")
        if discord_name and str(discord_name).strip().lower() != "null":
            tooltip_text = f"Twitch: {username}\nDiscord: {discord_name}"
        else:
            tooltip_text = f"Twitch: {username}\nDiscord: Not linked"
        self._show_users_tooltip(tooltip_text, event.x_root, event.y_root)

    def _show_settings_tooltip(self, text: str, root_x: int, root_y: int) -> None:
        if not text:
            return
        if self._settings_tooltip is None:
            self._settings_tooltip = tk.Toplevel(self)
            self._settings_tooltip.wm_overrideredirect(True)
            try:
                self._settings_tooltip.attributes("-topmost", True)
            except Exception:
                pass
            self._settings_tooltip_label = ttk.Label(
                self._settings_tooltip,
                text=text,
                background="#ffffe0",
                relief=tk.SOLID,
                borderwidth=1,
                padding=4,
                justify=tk.LEFT,
                wraplength=320,
            )
            self._settings_tooltip_label.pack()
        else:
            if self._settings_tooltip_label is not None:
                self._settings_tooltip_label.configure(text=text)
        self._settings_tooltip.wm_geometry(f"+{root_x + 12}+{root_y + 12}")
        self._settings_tooltip.deiconify()

    def _hide_settings_tooltip(self) -> None:
        if self._settings_tooltip is not None:
            try:
                self._settings_tooltip.withdraw()
            except Exception:
                try:
                    self._settings_tooltip.destroy()
                except Exception:
                    pass
                finally:
                    self._settings_tooltip = None
                    self._settings_tooltip_label = None

    def _show_users_tooltip(self, text: str, root_x: int, root_y: int) -> None:
        if not text:
            self._hide_users_tooltip()
            return
        if self._users_tooltip is None:
            self._users_tooltip = tk.Toplevel(self)
            self._users_tooltip.wm_overrideredirect(True)
            self._users_tooltip_label = ttk.Label(
                self._users_tooltip,
                text=text,
                background="#ffffe0",
                relief=tk.SOLID,
                borderwidth=1,
                padding=4,
            )
            self._users_tooltip_label.pack()
        else:
            self._users_tooltip_label.configure(text=text)
        self._users_tooltip.wm_geometry(f"+{root_x + 16}+{root_y + 16}")

    def _hide_users_tooltip(self) -> None:
        if self._users_tooltip is not None:
            try:
                self._users_tooltip.destroy()
            except Exception:
                pass
            finally:
                self._users_tooltip = None
                self._users_tooltip_label = None

    def _autosize_users_columns(self) -> None:
        if self.users_tree is None:
            return
        tree = self.users_tree
        if self._users_font is None:
            try:
                self._users_font = tkfont.nametofont(tree.cget("font"))
            except Exception:
                self._users_font = tkfont.nametofont("TkDefaultFont")
        font = self._users_font
        padding = 24
        value_columns = {
            "display_name",
            "discord_status",
            "tts_voice",
            "date_added",
            "chime",
        }
        header_only_columns = {
            "messages",
            "bits",
            "months",
            "gifts",
            "points",
        }
        for col in tree["columns"]:
            heading = tree.heading(col)
            header_text = heading.get("text", col)
            if col in value_columns:
                max_width = font.measure(header_text)
                for item in tree.get_children():
                    text = tree.set(item, col)
                    if text is None:
                        continue
                    width = font.measure(str(text))
                    if width > max_width:
                        max_width = width
                tree.column(col, width=max_width + padding)
            elif col in header_only_columns:
                tree.column(col, width=font.measure(header_text) + padding)
            else:
                info = tree.column(col)
                current_width = 0
                if isinstance(info, dict):
                    try:
                        current_width = int(info.get("width", 0))
                    except Exception:
                        current_width = 0
                tree.column(col, width=max(font.measure(header_text), current_width) + padding // 2)

    def _apply_listbox_stripes(self, listbox: tk.Listbox | None) -> None:
        """Apply alternating background colors to a tk.Listbox."""
        if listbox is None:
            return
        try:
            size = listbox.size()
        except Exception:
            return
        for idx in range(size):
            color = ROW_STRIPE_DARK if idx % 2 == 0 else ROW_STRIPE_LIGHT
            try:
                listbox.itemconfig(idx, background=color)
            except Exception:
                break

    def purge_invalid_users(self) -> None:
        if self._purge_users_thread and self._purge_users_thread.is_alive():
            messagebox.showinfo("Purge Running", "A purge operation is already in progress.")
            return
        if self.purge_users_btn is not None:
            try:
                self.purge_users_btn.state(["disabled"])
            except Exception:
                pass
        self._purge_users_thread = threading.Thread(target=self._purge_invalid_users_worker, daemon=True)
        self._purge_users_thread.start()

    def _purge_invalid_users_worker(self) -> None:
        conn = None
        rows = []
        try:
            conn = self.connect()
            cursor = conn.execute("SELECT id, username FROM users")
            rows = [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            debug_print("GUI", f"Failed to load users for purge: {e}")
            self.after(0, lambda: (self._enable_purge_button(), messagebox.showerror("Purge Failed", "Could not load users from database.")))
            return
        finally:
            if conn is not None:
                conn.close()

        try:
            bot = get_reference("TwitchBot")
        except Exception:
            bot = None
        if bot is None:
            self.after(0, lambda: (self._enable_purge_button(), messagebox.showerror("Purge Failed", "Twitch bot is not running.")))
            return

        protected_ids: set[str] = set()
        try:
            protected_ids.add(str(getattr(bot, "owner_id", "") or ""))
        except Exception:
            pass
        try:
            protected_ids.add(str(getattr(bot, "bot_id", "") or ""))
        except Exception:
            pass
        protected_ids.discard("")

        user_ids: list[str] = []
        local_delete_ids: list[str] = []
        skipped_protected = 0
        for row in rows:
            raw_id = str(row.get("id") or "").strip()
            if not raw_id:
                continue
            if raw_id in protected_ids:
                skipped_protected += 1
                continue
            if not raw_id.isdigit():
                local_delete_ids.append(raw_id)
                continue
            user_ids.append(raw_id)

        if local_delete_ids:
            debug_print("GUI", f"Queued {len(local_delete_ids)} user records with non-Twitch IDs for removal without Twitch API checks.")
        if skipped_protected:
            debug_print("GUI", f"Protecting {skipped_protected} critical user records (bot/owner) from purge.")

        if not user_ids and not local_delete_ids:
            self.after(0, lambda: (self._enable_purge_button(), messagebox.showinfo("Purge Complete", "No purgeable users were found.")))
            return

        purge_ids: list[str] = []
        if user_ids:
            loop = None
            try:
                loop = get_database_loop()
                if loop is None or not loop.is_running():
                    loop = getattr(bot, "loop", None)
            except Exception:
                loop = None
            if loop is None or not loop.is_running():
                self.after(0, lambda: (self._enable_purge_button(), messagebox.showerror("Purge Failed", "No active event loop available for the bot.")))
                return

            try:
                future = asyncio.run_coroutine_threadsafe(bot.classify_users_for_purge(user_ids), loop)
                status_map = future.result(timeout=180)
            except Exception as e:
                debug_print("GUI", f"Failed to classify users for purge: {e}")
                self.after(0, lambda: (self._enable_purge_button(), messagebox.showerror("Purge Failed", "Unable to classify users. See logs for details.")))
                return

            purge_ids = [uid for uid, status in status_map.items() if status in ("banned", "missing")]

        total_purge_ids = purge_ids + local_delete_ids
        if not total_purge_ids:
            self.after(0, lambda: (self._enable_purge_button(), messagebox.showinfo("Purge Complete", "No banned, deleted, or invalid users found.")))
            return

        try:
            conn = self.connect()
            with conn:
                conn.executemany("DELETE FROM users WHERE id = ?", [(uid,) for uid in total_purge_ids])
        except Exception as e:
            debug_print("GUI", f"Failed to delete users: {e}")
            self.after(0, lambda: (self._enable_purge_button(), messagebox.showerror("Purge Failed", "Database delete failed.")))
            return
        finally:
            if conn is not None:
                conn.close()

        def _show_complete_message():
            parts = [f"Removed {len(total_purge_ids)} users."]
            if purge_ids:
                parts.append(f"{len(purge_ids)} confirmed banned/deleted via Twitch.")
            if local_delete_ids:
                parts.append(f"{len(local_delete_ids)} invalid IDs removed locally.")
            messagebox.showinfo("Purge Complete", "\n".join(parts))

        self.after(0, lambda: (self._enable_purge_button(), self.refresh_users_tab(), _show_complete_message()))

    def _enable_purge_button(self) -> None:
        if self.purge_users_btn is not None:
            try:
                self.purge_users_btn.state(["!disabled"])
            except Exception:
                pass

    def _refresh_elevenlabs_models(self) -> None:
        """Diagnostic: fetch ElevenLabs models on demand and refresh inline UI."""
        debug_print("GUI", f"Manual refresh of ElevenLabs models requested.")

        def worker():
            try:
                print("[GUI] Manual fetch: starting ElevenLabs models fetch...")
                try:
                    try:
                        elevenlabs_manager = get_reference("ElevenLabsManager")
                        models = elevenlabs_manager.get_list_of_models()
                    except TypeError:
                        try:
                            models = elevenlabs_manager.__class__.get_list_of_models()
                        except Exception:
                            models = []
                    except Exception:
                        models = []
                except Exception:
                    models = []

                # normalize returned models into string ids/names
                normalized = []
                for m in (models or []):
                    try:
                        if isinstance(m, dict):
                            if "model_id" in m:
                                normalized.append(str(m["model_id"]))
                            elif "id" in m:
                                normalized.append(str(m["id"]))
                            elif "name" in m:
                                normalized.append(str(m["name"]))
                            else:
                                normalized.append(str(m))
                        else:
                            mid = getattr(m, "model_id", None) or getattr(m, "id", None) or getattr(m, "name", None)
                            if mid:
                                normalized.append(str(mid))
                            else:
                                normalized.append(str(m))
                    except Exception:
                        try:
                            normalized.append(str(m))
                        except Exception:
                            pass

                if normalized:
                    ELEVEN_LABS_VOICE_MODELS.clear()
                    ELEVEN_LABS_VOICE_MODELS.extend(normalized)
                    print(f"[GUI] Manual fetch: found {len(normalized)} models")
                else:
                    print("[GUI] Manual fetch: no models found (empty list)")

            except Exception:
                import traceback
                print("[GUI] Manual fetch: exception during model fetch:")
                print(traceback.format_exc())

            try:
                self.after(0, lambda: self.refresh_settings_inline())
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def normalize_hotkey(self, modifiers: set, key: str) -> str:
        """Return a normalized hotkey string in canonical order: ctrl, shift, alt, meta + main key.

        Examples: ctrl+shift+/, ctrl+a
        """
        debug_print("GUI", f"Normalizing hotkey: modifiers={modifiers}, key='{key}'")
        order = ["ctrl", "shift", "alt", "meta"]
        parts = []
        for o in order:
            if o in modifiers:
                parts.append(o)
        parts.append(key.lower())
        return "+".join(parts)

    def open_hotkey_dialog(self, action: str) -> None:
        """Open a modal dialog that captures a new hotkey from keyboard input."""
        debug_print("GUI", f"Opening hotkey dialog for action '{action}'")
        dlg = tk.Toplevel(self)
        dlg.transient(self)
        dlg.grab_set()
        dlg.title(f"Set Hotkey for: {action}")
        ttk.Label(dlg, text="Press the new hotkey combination now (press Esc to cancel)").pack(padx=12, pady=8)

        captured_var = tk.StringVar(value="(waiting)")
        display_lbl = ttk.Label(dlg, textvariable=captured_var, font=(None, 12, "bold"))
        display_lbl.pack(padx=12, pady=6)

        modifiers_seen = set()

        def on_key(event):
            ks = event.keysym
            # map common modifier keysyms
            mod_map = {
                "Control_L": "ctrl",
                "Control_R": "ctrl",
                "Shift_L": "shift",
                "Shift_R": "shift",
                "Alt_L": "alt",
                "Alt_R": "alt",
                "Meta_L": "meta",
                "Meta_R": "meta",
            }

            if ks in mod_map:
                modifiers_seen.add(mod_map[ks])
                captured_var.set(self.normalize_hotkey(modifiers_seen, ""))
                return

            # If Escape, cancel
            if ks == "Escape":
                _resume_and_destroy()
                return

            # Non-modifier: construct final
            # Also inspect event.state for modifiers if available
            try:
                state = event.state
                if state & 0x0004:  # Control
                    modifiers_seen.add("ctrl")
                if state & 0x0001:  # Shift (platform dependent)
                    modifiers_seen.add("shift")
                if state & 0x20000:  # Alt (may vary)
                    modifiers_seen.add("alt")
            except Exception:
                pass

            main = ks
            # Normalize some common names
            key_name = main.lower()
            if key_name == "slash":
                key_name = "/"
            if key_name == "question":
                key_name = "/"

            combo = self.normalize_hotkey(modifiers_seen, key_name)
            captured_var.set(combo)

        dlg.bind("<Key>", on_key)

        # Pause global hotkey listening so the user doesn't accidentally trigger
        # other hotkeys while programming a new one. We'll resume when the
        # dialog closes (save/cancel/escape).
        try:
            lst = get_global_listener()
            if lst:
                try:
                    lst.pause_listening()
                except Exception as _e:
                    debug_print("GUI", f"Failed to pause hotkey listener: {_e}")
        except Exception:
            pass

        def _resume_and_destroy():
            try:
                lst2 = get_global_listener()
                if lst2:
                    try:
                        lst2.resume_listening()
                    except Exception as _e:
                        debug_print("GUI", f"Failed to resume hotkey listener: {_e}")
            finally:
                try:
                    dlg.destroy()
                except Exception:
                    pass

        def on_save():
            new_value = captured_var.get()
            if not new_value or new_value in ("(waiting)", ""):
                messagebox.showerror("Hotkey", "No hotkey captured.", parent=dlg)
                return

            # Check for conflict with other hotkeys
            for other_action, widgets in self.hotkey_widgets.items():
                if other_action == action:
                    continue
                other_val = widgets["var"].get()
                if other_val == new_value:
                    messagebox.showerror("Hotkey", f"Hotkey '{new_value}' already assigned to '{other_action}'. Choose another.", parent=dlg)
                    return

            # persist
            def worker_save():
                try:
                    # schedule on DB loop if possible to avoid cross-loop errors
                    from db import get_database_loop
                    db_loop = get_database_loop()
                    if db_loop and getattr(db_loop, "is_running", lambda: False)():
                        fut = asyncio.run_coroutine_threadsafe(set_hotkey(action, new_value), db_loop)
                        try:
                            fut.result(2)
                        except Exception as e:
                            raise
                    else:
                        # fallback to running in a fresh loop
                        asyncio.run(set_hotkey(action, new_value))
                except Exception as e:
                    print(f"Error saving hotkey: {e}")
                    # show error parented to the dialog on main thread
                    self.after(0, lambda err=e, d=dlg: messagebox.showerror("Hotkey", f"Error saving hotkey: {err}", parent=d))
                    return
                # update UI and notify hotkey listener so changes take effect immediately
                def _notify_save():
                    try:
                        # update displayed value first
                        self.hotkey_widgets[action]["var"].set(new_value)
                        # resume hotkey listener so the new binding can be applied
                        lst = get_global_listener()
                        if lst:
                            try:
                                lst.resume_listening()
                            except Exception as _e:
                                debug_print("GUI", f"hotkey listener resume failed: {_e}")
                        # now update the OS binding for this action
                        if lst:
                            try:
                                lst.update_hotkey(action, new_value)
                            except Exception as _e:
                                debug_print("GUI", f"hotkey listener update failed: {_e}")
                        # close the dialog
                        try:
                            dlg.destroy()
                        except Exception:
                            pass
                    except Exception as _e:
                        debug_print("GUI", f"notify_save failed: {_e}")

                self.after(0, _notify_save)

            threading.Thread(target=worker_save, daemon=True).start()

        btn_frame = ttk.Frame(dlg)
        btn_frame.pack(pady=8)
        ttk.Button(btn_frame, text="Save", command=on_save).pack(side=tk.LEFT, padx=6)
        ttk.Button(btn_frame, text="Cancel", command=_resume_and_destroy).pack(side=tk.LEFT, padx=6)
        # center the hotkey dialog
        try:
            self.center_window(dlg)
        except Exception:
            pass
        try:
            dlg.protocol("WM_DELETE_WINDOW", _resume_and_destroy)
        except Exception:
            pass
        # Ensure the dialog has keyboard focus so it receives key events immediately.
        try:
            # Lift and focus the dialog and the prominent display label.
            dlg.lift()
            dlg.focus_force()
            display_lbl.focus_set()
            # Some window managers may require a short delay for focus to take.
            dlg.after(50, lambda: (dlg.lift(), dlg.focus_force(), display_lbl.focus_set()))
        except Exception:
            pass

    def clear_hotkey(self, action: str) -> None:
        debug_print("GUI", f"Clearing hotkey for action '{action}'")
        if not messagebox.askyesno("Clear Hotkey", f"Clear hotkey for '{action}'?", parent=self):
            return

        def worker_clear():
            try:
                from db import get_database_loop
                db_loop = get_database_loop()
                if db_loop and getattr(db_loop, "is_running", lambda: False)():
                    fut = asyncio.run_coroutine_threadsafe(set_hotkey(action, "null"), db_loop)
                    try:
                        fut.result(2)
                    except Exception:
                        raise
                else:
                    asyncio.run(set_hotkey(action, "null"))
            except Exception as e:
                print(f"Error clearing hotkey: {e}")
                self.after(0, lambda err=e: messagebox.showerror("Hotkey", f"Error clearing hotkey: {err}", parent=self))
                return
            def _notify_clear():
                try:
                    self.hotkey_widgets[action]["var"].set("null")
                    # notify listener to unregister any OS binding for this action
                    lst = get_global_listener()
                    if lst:
                        try:
                            lst.unregister_action(action)
                        except Exception as _e:
                            debug_print("GUI", f"hotkey listener unregister failed: {_e}")
                except Exception as _e:
                    debug_print("GUI", f"notify_clear failed: {_e}")

            self.after(0, _notify_clear)

        threading.Thread(target=worker_clear, daemon=True).start()


def main():
    app = DBEditor()
    # Start the bot a little after the GUI is shown so DB setup runs in background
    try:
        app.after(1000, app.start_bot_background)
        debug_print("GUI", "DBEditor initialized.")
    except Exception:
        pass
    # Start the ResponseTimer in a background asyncio loop so it runs while the GUI is active.
    try:
        start_timer_manager_in_background()
    except Exception as e:
        print(f"Failed to start ResponseTimer in background: {e}")
    app.mainloop()


if __name__ == "__main__":
    main()
