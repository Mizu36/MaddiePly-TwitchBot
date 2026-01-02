"""Bootstrapper for MaddiePly that performs .env validation before launching the GUI.

This module can be executed directly (``python launcher.py``) and also serves as the
entrypoint when the project is bundled with PyInstaller.  It replaces the old
start_bot.bat logic so we no longer need to provision Python/venv on end-user machines.
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import subprocess
import sys
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from pathlib import Path
from typing import Dict

import asqlite
from dotenv import load_dotenv, set_key
import twitchio

from db import setup_database, close_database
from tools import path_from_app_root

REQUIRED_ENV_KEYS = [
    "TWITCH_CLIENT_ID",
    "TWITCH_APP_SECRET",
    "ELEVENLABS_API_KEY",
    "OPENAI_API_KEY",
    "AZURE_TTS_KEY",
    "AZURE_TTS_REGION",
    "WEBSOCKET_PASSWORD",
]
OPTIONAL_WARN_KEYS = ["DISCORD_TOKEN"]
IDENTITY_KEYS = ["BOT_ID", "OWNER_ID"]
MASK_EXEMPT_KEYS = set(IDENTITY_KEYS)
MASK_CHAR = "."
RUN_MAIN_FLAG = "--run-main"
SKIP_OPTIONAL_ENV = "MP_SKIP_OPTIONAL_WARN"
_NULL_STREAM = None
ENV_TEMPLATE = """TWITCH_CLIENT_ID=
TWITCH_APP_SECRET=
BOT_ID=
OWNER_ID=
ELEVENLABS_API_KEY=
OPENAI_API_KEY=
AZURE_TTS_KEY=
AZURE_TTS_REGION=
DISCORD_TOKEN=
SUPABASE_URL=
SUPABASE_ANON_KEY=
SUPABASE_DIRECT_POSTGRES_URL=
SUPABASE_SECRET_KEY=
WEBSOCKET_PASSWORD=
GOOGLE_API_KEY=
GOOGLE_ENGINE_ID=
"""
MEDIA_SUBFOLDERS = [
    "images_and_gifs",
    "memes",
    "screenshots",
    "soundFX",
    "voice_audio",
    "subtitles",
    "gacha",
    "gacha/gacha_overlay",
    "gacha/gacha_overlay/assets",
    "gacha/sets",
]
ENV_PATH = path_from_app_root(".env")


def _info(message: str) -> None:
    print(f"[INFO] {message}")


def _warn(message: str) -> None:
    print(f"[WARN] {message}")


def _error(message: str) -> None:
    print(f"[ERROR] {message}")


def ensure_directory_structure() -> None:
    """Create data/media folders expected by the rest of the application."""
    root = path_from_app_root()
    data_dir = root / "data"
    media_dir = root / "media"
    data_dir.mkdir(exist_ok=True)
    media_dir.mkdir(exist_ok=True)
    for sub in MEDIA_SUBFOLDERS:
        (media_dir / sub).mkdir(parents=True, exist_ok=True)
    _ensure_subtitle_state_file(media_dir)


def _ensure_subtitle_state_file(media_dir: Path) -> None:
    state_path = media_dir / "subtitles" / "state.json"
    if state_path.exists():
        return
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text("{}", encoding="utf-8")
    except Exception as exc:
        _warn(f"Unable to create subtitle state file at {state_path}: {exc}")


def ensure_env_file() -> None:
    if ENV_PATH.exists():
        return
    ENV_PATH.write_text(ENV_TEMPLATE.strip() + "\n", encoding="utf-8")
    _info(f"Created template .env at {ENV_PATH}. Fill it out before running again.")


def _database_needs_bootstrap(db_path: Path) -> bool:
    if not db_path.exists():
        return True
    try:
        conn = sqlite3.connect(db_path)
        try:
            cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='settings'")
            return cur.fetchone() is None
        finally:
            conn.close()
    except sqlite3.Error:
        return True


def ensure_database_initialized(bot_id: str) -> None:
    db_path = path_from_app_root("data", "maddieply.db")
    if not bot_id:
        _warn("BOT_ID missing; skipping database bootstrap.")
        return
    if not _database_needs_bootstrap(db_path):
        return

    _info(f"Initializing SQLite database at {db_path}...")

    async def _bootstrap() -> None:
        pool = await asqlite.create_pool(str(db_path))
        try:
            await setup_database(pool, bot_id)
        finally:
            try:
                await close_database()
            except Exception:
                pass
            try:
                await pool.close()
            except Exception:
                pass

    try:
        asyncio.run(_bootstrap())
    except Exception as exc:
        _error(f"Failed to initialize database: {exc}")
        raise

def load_environment() -> Dict[str, str]:
    load_dotenv(dotenv_path=ENV_PATH, override=True)
    tracked = REQUIRED_ENV_KEYS + IDENTITY_KEYS + OPTIONAL_WARN_KEYS
    env: Dict[str, str] = {}
    for key in tracked:
        env[key] = (os.getenv(key, "") or "").strip()
    return env

def validate_required(env: Dict[str, str]) -> bool:
    missing = [key for key in REQUIRED_ENV_KEYS if not env.get(key)]
    if not missing:
        return True
    _error("Missing required keys in .env:")
    for key in missing:
        _error(f"  - {key}")
    _info("Update the .env file and relaunch.")
    return False


def warn_optional(env: Dict[str, str]) -> None:
    for key in OPTIONAL_WARN_KEYS:
        if not env.get(key):
            _warn(f"{key} is blank. Associated integrations will remain disabled until it is set.")



def fetch_ids_for_logins(client_id: str, client_secret: str, logins: list[str]) -> Dict[str, str]:
    async def _lookup() -> Dict[str, str]:
        async with twitchio.Client(client_id=client_id, client_secret=client_secret) as client:
            await client.login()
            users = await client.fetch_users(logins=logins)
        return {user.name.lower(): user.id for user in users}

    if not logins:
        return {}
    return asyncio.run(_lookup())


def _modal_error(title: str, message: str) -> None:
    try:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(title, message)
        root.destroy()
    except Exception:
        pass


def _build_main_launch_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, RUN_MAIN_FLAG]
    launcher_script = Path(__file__).resolve()
    python_path = Path(sys.executable)
    executable = python_path
    if os.name == "nt":
        pythonw = python_path.with_name("pythonw.exe")
        if pythonw.exists():
            executable = pythonw
    return [str(executable), str(launcher_script), RUN_MAIN_FLAG]


def spawn_main_process() -> bool:
    cmd = _build_main_launch_command()
    env = os.environ.copy()
    env[SKIP_OPTIONAL_ENV] = "1"
    try:
        subprocess.Popen(cmd, env=env, cwd=str(path_from_app_root()))
        return True
    except Exception as exc:
        _error(f"Failed to spawn MaddiePly GUI: {exc}")
        _modal_error("MaddiePly Launcher", f"Failed to launch GUI: {exc}")
        return False


def maybe_hide_console() -> None:
    """Detach the Windows console so only the Tkinter window is visible."""
    global _NULL_STREAM
    if os.name != "nt" or os.environ.get("MP_KEEP_CONSOLE"):
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        user32 = ctypes.windll.user32
        hwnd = kernel32.GetConsoleWindow()
        if hwnd:
            user32.ShowWindow(hwnd, 0)
            kernel32.FreeConsole()
            if _NULL_STREAM is None:
                _NULL_STREAM = open(os.devnull, "w", buffering=1)
            sys.stdout = _NULL_STREAM
            sys.stderr = _NULL_STREAM
            try:
                sys.stdin = open(os.devnull, "r")
            except Exception:
                pass
    except Exception:
        pass
def launch_gui() -> None:
    from gui_main import main as gui_main

    _info("Starting MaddiePly GUI...")
    gui_main()


def _launch_primary_gui() -> None:
    env = load_environment()
    if os.environ.get(SKIP_OPTIONAL_ENV) != "1":
        warn_optional(env)
    try:
        launch_gui()
    except KeyboardInterrupt:
        _warn("Launcher interrupted by user.")
    except Exception as exc:
        _error(f"Fatal error while launching GUI: {exc}")
        _modal_error("MaddiePly Launcher", f"Failed to launch GUI: {exc}")
        raise


class PreflightWindow(tk.Tk):
    FIELD_SECTIONS = [
        ("Required Secrets", REQUIRED_ENV_KEYS),
        ("Identity IDs", IDENTITY_KEYS),
        ("Optional Settings", OPTIONAL_WARN_KEYS),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.title("MaddiePly Preflight Checks")
        self.resizable(False, False)
        self.field_keys = [key for _, keys in self.FIELD_SECTIONS for key in keys]
        self.entry_vars: dict[str, tk.StringVar] = {}
        self.entry_widgets: dict[str, ttk.Entry] = {}
        self.actual_values: dict[str, str] = {}
        self.masked_keys = {key for key in self.field_keys if key not in MASK_EXEMPT_KEYS}
        self.status_var = tk.StringVar(value="Ready")
        self.launch_ready = False
        self.auto_launch_attempted = False
        self.validated_env: Dict[str, str] = {}
        ensure_directory_structure()
        ensure_env_file()
        self._build_ui()
        self._load_entries_from_disk()
        self.protocol("WM_DELETE_WINDOW", self._handle_close)

    def _build_ui(self) -> None:
        container = ttk.Frame(self, padding=16)
        container.pack(fill=tk.BOTH, expand=True)

        for section_title, keys in self.FIELD_SECTIONS:
            frame = ttk.LabelFrame(container, text=section_title)
            frame.pack(fill=tk.X, expand=True, pady=(0, 8))
            for idx, key in enumerate(keys):
                ttk.Label(frame, text=key).grid(row=idx, column=0, sticky=tk.W, padx=(8, 4), pady=2)
                var = tk.StringVar()
                entry = ttk.Entry(frame, textvariable=var, width=40)
                entry.grid(row=idx, column=1, sticky=tk.EW, padx=(0, 8), pady=2)
                entry.bind("<FocusIn>", lambda event, key=key: self._handle_focus_in(key))
                entry.bind("<FocusOut>", lambda event, key=key: self._handle_focus_out(key))
                frame.grid_columnconfigure(1, weight=1)
                self.entry_vars[key] = var
                self.entry_widgets[key] = entry
                if key in IDENTITY_KEYS:
                    ttk.Button(
                        frame,
                        text="Fetch",
                        width=8,
                        command=lambda key=key: self._prompt_lookup_id(key),
                    ).grid(row=idx, column=2, padx=(0, 8), pady=2)
            if section_title.startswith("Identity"):
                frame.grid_columnconfigure(2, weight=0)

        button_row = ttk.Frame(container)
        button_row.pack(fill=tk.X, expand=True)
        ttk.Button(button_row, text="Save Changes", command=self._save_entries).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(button_row, text="Launch MaddiePly", command=self._run_checks_and_launch).pack(side=tk.RIGHT)

        self.status_label = tk.Label(container, textvariable=self.status_var, fg="#0A7B34", anchor="w")
        self.status_label.pack(fill=tk.X, pady=(12, 0))

    def _mask_value(self, value: str) -> str:
        if not value:
            return ""
        clean = value.strip()
        if len(clean) <= 2:
            return clean
        if len(clean) == 3:
            return f"{clean[:2]}{MASK_CHAR}{clean[-1]}"
        if len(clean) == 4:
            return f"{clean[:2]}{clean[-2:]}"
        middle_len = len(clean) - 4
        return f"{clean[:2]}{MASK_CHAR * middle_len}{clean[-2:]}"

    def _apply_mask(self, key: str) -> None:
        entry = self.entry_widgets.get(key)
        var = self.entry_vars.get(key)
        if not entry or not var:
            return
        value = self.actual_values.get(key, "")
        masked = self._mask_value(value)
        entry.configure(state="normal")
        var.set(masked)
        entry.configure(state="readonly")

    def _handle_focus_in(self, key: str) -> None:
        if key not in self.masked_keys:
            return
        entry = self.entry_widgets.get(key)
        var = self.entry_vars.get(key)
        if not entry or not var:
            return
        entry.configure(state="normal")
        var.set(self.actual_values.get(key, ""))
        entry.icursor(tk.END)

    def _handle_focus_out(self, key: str) -> None:
        if key not in self.masked_keys:
            return
        var = self.entry_vars.get(key)
        if not var:
            return
        self.actual_values[key] = var.get().strip()
        self._apply_mask(key)

    def _refresh_masked_entries(self) -> None:
        for key in self.masked_keys:
            self._apply_mask(key)

    def _current_value_for(self, key: str) -> str:
        entry = self.entry_widgets.get(key)
        var = self.entry_vars.get(key)
        if not entry or not var:
            return ""
        if key in self.masked_keys:
            state = str(entry.cget("state"))
            if state == "readonly":
                value = self.actual_values.get(key, "")
            else:
                value = var.get()
        else:
            value = var.get()
        value = value.strip()
        self.actual_values[key] = value
        return value

    def _gather_current_values(self) -> Dict[str, str]:
        return {key: self._current_value_for(key) for key in self.entry_vars}

    def _all_fields_filled(self) -> bool:
        for key in self.entry_vars:
            if not self.actual_values.get(key, ""):
                return False
        return True

    def _auto_launch_if_ready(self) -> None:
        if self.auto_launch_attempted:
            return
        if self._all_fields_filled():
            self.auto_launch_attempted = True
            self._set_status("All settings detected. Launching...")
            self.after(50, self._run_checks_and_launch)

    def _set_status(self, message: str, *, error: bool = False) -> None:
        self.status_var.set(message)
        color = "#B00020" if error else "#0A7B34"
        if hasattr(self, "status_label"):
            self.status_label.configure(fg=color)

    def _load_entries_from_disk(self) -> None:
        env = load_environment()
        for key in self.entry_vars:
            value = (env.get(key, "") or "").strip()
            self.actual_values[key] = value
            if key in self.masked_keys:
                self._apply_mask(key)
            else:
                entry = self.entry_widgets.get(key)
                if entry:
                    entry.configure(state="normal")
                self.entry_vars[key].set(value)
        self.after(150, self._maybe_prompt_missing_ids)

    def _prompt_lookup_id(self, field: str) -> None:
        prompt = "Enter the Twitch login for the broadcaster:" if field == "OWNER_ID" else "Enter the Twitch login for the bot account:"
        login = simpledialog.askstring(
            "Fetch Twitch ID",
            prompt,
            parent=self,
        )
        if not login:
            return
        login = login.strip()
        if not login:
            return
        self._lookup_and_apply_ids({field: login})

    def _lookup_and_apply_ids(self, login_map: Dict[str, str]) -> None:
        if not login_map:
            return
        client_id = self._current_value_for("TWITCH_CLIENT_ID").strip()
        client_secret = self._current_value_for("TWITCH_APP_SECRET").strip()
        if not client_id or not client_secret:
            messagebox.showerror("Fetch IDs", "Client ID and Secret are required before fetching IDs.")
            return
        try:
            results = fetch_ids_for_logins(client_id, client_secret, list(login_map.values()))
        except Exception as exc:
            messagebox.showerror("Fetch IDs", f"Unable to reach Twitch: {exc}")
            return

        updated = []
        for field, login in login_map.items():
            user_id = results.get(login.lower())
            if not user_id:
                messagebox.showwarning("Fetch IDs", f"Twitch did not return an ID for {login}.")
                continue
            self.actual_values[field] = user_id
            entry = self.entry_widgets.get(field)
            if entry:
                entry.configure(state="normal")
            self.entry_vars[field].set(user_id)
            set_key(str(ENV_PATH), field, user_id)
            updated.append(field)
        if updated:
            self._set_status(f"Updated {' & '.join(updated)} from Twitch.")
            self._refresh_masked_entries()
            self.after(50, self._auto_launch_if_ready)

    def _maybe_prompt_missing_ids(self) -> None:
        missing = [key for key in IDENTITY_KEYS if not self.actual_values.get(key)]
        if not missing:
            self._auto_launch_if_ready()
            return
        messagebox.showinfo(
            "Fetch Twitch IDs",
            "BOT_ID or OWNER_ID is blank. We'll fetch them from Twitch usernames.",
        )
        login_map: Dict[str, str] = {}
        for field in missing:
            prompt = "Enter the Twitch login for the broadcaster:" if field == "OWNER_ID" else "Enter the Twitch login for the bot account:"
            login = simpledialog.askstring("Fetch Twitch ID", prompt, parent=self)
            if login:
                login_map[field] = login.strip()
        if login_map:
            self._lookup_and_apply_ids(login_map)
        self.after(150, self._auto_launch_if_ready)
        self.after(300, self._auto_launch_if_ready)

    def _save_entries(self) -> None:
        values = self._gather_current_values()
        for key, value in values.items():
            set_key(str(ENV_PATH), key, value)
        self._refresh_masked_entries()
        self._set_status("Saved .env values.")

    def _run_checks_and_launch(self) -> None:
        self.auto_launch_attempted = True
        self._save_entries()
        env = load_environment()
        missing = [key for key in REQUIRED_ENV_KEYS if not env.get(key)]
        if missing:
            messagebox.showerror("Launch", f"Missing required settings: {', '.join(missing)}")
            return
        if not env.get("BOT_ID") or not env.get("OWNER_ID"):
            messagebox.showerror("Launch", "BOT_ID and OWNER_ID are required. Populate them in .env before launching.")
            return
        try:
            ensure_database_initialized(env.get("BOT_ID", ""))
        except Exception as exc:
            messagebox.showerror("Launch", f"Database initialization failed: {exc}")
            return
        optional_missing = [key for key in OPTIONAL_WARN_KEYS if not env.get(key)]
        if optional_missing:
            messagebox.showwarning("Optional Settings", f"The following optional settings are blank: {', '.join(optional_missing)}")
        self.validated_env = env
        self.launch_ready = True
        self._set_status("Launching MaddiePly...")
        self.destroy()

    def _handle_close(self) -> None:
        self.launch_ready = False
        self.destroy()


def main() -> None:
    maybe_hide_console()

    if RUN_MAIN_FLAG in sys.argv:
        _launch_primary_gui()
        return

    try:
        app = PreflightWindow()
    except Exception as exc:
        _error(f"Failed to start preflight UI: {exc}")
        sys.exit(1)

    app.mainloop()

    if not app.launch_ready:
        _warn("Preflight checks cancelled. Exiting without launching MaddiePly.")
        return

    env = app.validated_env or load_environment()
    warn_optional(env)
    if spawn_main_process():
        _info("Preflight complete. MaddiePly GUI launching in a new window.")
    else:
        _warn("Preflight checks passed but MaddiePly could not be launched.")


if __name__ == "__main__":
    main()
