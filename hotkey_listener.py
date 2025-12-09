"""
Global hotkey listener for MaddiePly.

This module provides `GlobalHotkeyListener` which can:
- load hotkeys from the async DB (via `db.get_hotkey`)
- register global OS-level hotkeys using the `keyboard` package
- allow other parts of the app to register callbacks per-action
"""
from __future__ import annotations
import threading
import traceback
from typing import Callable, Dict, List
import os
import sqlite3

try:
    import keyboard  # type: ignore
except Exception:
    keyboard = None

import db
from db import REQUIRED_HOTKEYS
from tools import debug_print, path_from_app_root

_GLOBAL_LISTENER = None


class GlobalHotkeyListener:
    def __init__(self):
        self._running = False
        # action -> id returned by keyboard.add_hotkey
        self._registered_hotkeys: Dict[str, str] = {}
        # action -> original keybind string (e.g. 'ctrl+shift+a')
        self._hotkey_strings: Dict[str, str] = {}
        self._callbacks: Dict[str, List[Callable[[str], None]]] = {}
        self._lock = threading.Lock()
        self._paused = False
        if keyboard is None:
            debug_print("HotkeyListener", "`keyboard` library not available; global hotkeys disabled. Install with `pip install keyboard`.")
        debug_print("HotkeyListener", "GlobalHotkeyListener initialized.")

    def start(self) -> None:
        """Start the listener (no-op if `keyboard` not available)."""
        if keyboard is None:
            return
        with self._lock:
            if self._running:
                return
            self._running = True
        debug_print("HotkeyListener", "Starting global hotkey listener.")

    def stop(self) -> None:
        """Stop listening and remove registered hotkeys."""
        if keyboard is None:
            return
        with self._lock:
            try:
                keyboard.clear_all_hotkeys()
            except Exception:
                pass
            self._registered_hotkeys.clear()
            self._running = False
        debug_print("HotkeyListener", "Stopped global hotkey listener.")

    def register_callback(self, action: str, func: Callable[[str], None]) -> None:
        """Register a callback that will be called when `action` is triggered.

        The callback will be called in a background thread and will receive the
        `action` string as its single argument.
        """
        with self._lock:
            self._callbacks.setdefault(action, []).append(func)

    def unregister_callback(self, action: str, func: Callable[[str], None]) -> None:
        with self._lock:
            lst = self._callbacks.get(action)
            if not lst:
                return
            try:
                lst.remove(func)
            except ValueError:
                pass

    def _invoke_callbacks(self, action: str) -> None:
        # Run each callback in its own daemon thread so they can't block the
        # keyboard event loop.
        try:
            with self._lock:
                funcs = list(self._callbacks.get(action, []))
            for f in funcs:
                try:
                    threading.Thread(target=f, args=(action,), daemon=True).start()
                except Exception:
                    debug_print("HotkeyListener", f"Failed to start callback thread for {action}: {traceback.format_exc()}")
        except Exception:
            debug_print("HotkeyListener", f"Error invoking callbacks for {action}: {traceback.format_exc()}")

    def _register_keybind(self, action: str, keybind: str) -> None:
        if keyboard is None:
            return
        if not keybind or keybind.lower() == "null":
            return
        if action.lower() == "stop listening":
            return
        try:
            # Remove previous binding for this action if present
            prev = self._registered_hotkeys.get(action)
            if prev:
                try:
                    keyboard.remove_hotkey(prev)
                except Exception:
                    # keyboard.remove_hotkey can accept an id returned by add_hotkey,
                    # but if we passed a string earlier it may not be removable this way.
                    pass

            # Add new hotkey binding
            # keyboard.add_hotkey accepts many string formats e.g. 'ctrl+shift+a' or 'p'
            hotkey_id = keyboard.add_hotkey(keybind, lambda a=action: self._invoke_callbacks(a))
            # Store the identifier so it can be removed later if necessary
            self._registered_hotkeys[action] = hotkey_id
            # Also remember the original keybind string so we can resume
            self._hotkey_strings[action] = keybind
            debug_print("HotkeyListener", f"Registered hotkey for '{action}' -> '{keybind}' (id={hotkey_id})")
        except Exception:
            debug_print("HotkeyListener", f"Failed to register hotkey for '{action}' -> '{keybind}': {traceback.format_exc()}")

    def unregister_action(self, action: str) -> None:
        """Unregister any hotkey bound to `action` and remove it from internal map."""
        if keyboard is None:
            return
        try:
            prev = self._registered_hotkeys.pop(action, None)
            if prev:
                try:
                    # `prev` may be the id returned by add_hotkey
                    keyboard.remove_hotkey(prev)
                except Exception:
                    try:
                        # Fallback: try removing by the hotkey string if stored
                        keyboard.remove_hotkey(str(prev))
                    except Exception:
                        debug_print("HotkeyListener", f"Failed to remove hotkey for action {action}: {traceback.format_exc()}")
            else:
                # nothing registered for this action
                return
            # remove stored string too
            try:
                self._hotkey_strings.pop(action, None)
            except Exception:
                pass
            debug_print("HotkeyListener", f"Unregistered hotkey for action '{action}'")
        except Exception:
            debug_print("HotkeyListener", f"Error unregistering action '{action}': {traceback.format_exc()}")

    def update_hotkey(self, action: str, keybind: str) -> None:
        """Update the hotkey for the given action: unregister previous, register new."""
        if keyboard is None:
            return
        if action.lower() == "stop listening":
            return
        try:
            # Unregister previous binding for this action
            try:
                prev = self._registered_hotkeys.pop(action, None)
                if prev:
                    try:
                        keyboard.remove_hotkey(prev)
                    except Exception:
                        try:
                            keyboard.remove_hotkey(str(prev))
                        except Exception:
                            pass
            except Exception:
                pass

            # Register new if provided and not 'null'
            if keybind and str(keybind).lower() != "null":
                self._register_keybind(action, keybind)
            else:
                # ensure we also clear the stored key string
                try:
                    self._hotkey_strings.pop(action, None)
                except Exception:
                    pass
                debug_print("HotkeyListener", f"Cleared hotkey for action '{action}' (no new keybind provided)")
        except Exception:
            debug_print("HotkeyListener", f"Error updating hotkey for '{action}': {traceback.format_exc()}")

    def load_hotkeys(self, mapping: Dict[str, str]) -> None:
        """Load a mapping of action -> keybind and (re)register them globally.

        This will clear existing registered hotkeys and apply the provided mapping.
        """
        if keyboard is None:
            debug_print("HotkeyListener", "Can't load hotkeys: `keyboard` package not available.")
            return
        try:
            # Clear existing hotkeys
            try:
                keyboard.clear_all_hotkeys()
            except Exception:
                pass
            self._registered_hotkeys.clear()

            for action, keybind in mapping.items():
                if not keybind or str(keybind).lower() == "null":
                    continue
                if action.lower() == "stop listening":
                    continue
                self._register_keybind(action, keybind)
        except Exception:
            debug_print("HotkeyListener", f"Error loading hotkeys: {traceback.format_exc()}")

    def reload_from_db(self, timeout: float = 2.0) -> None:
        """Read hotkeys from the async DB and register them.

        This will attempt to schedule coroutines on the DB event loop (via
        db.get_database_loop()) and fall back to returning early if the DB
        loop is not available.
        """
        loop = db.get_database_loop()
        if loop is None:
            debug_print("HotkeyListener", "DB event loop not available — attempting synchronous DB read fallback.")
            # Fallback: try reading the sqlite DB directly so hotkeys can be
            # applied even when the async pool (created by the bot) isn't running.
            try:
                db_path = path_from_app_root("data", "maddieply.db")
                if os.path.exists(db_path):
                    conn = sqlite3.connect(db_path)
                    conn.row_factory = sqlite3.Row
                    try:
                        cur = conn.execute("SELECT action, keybind FROM hotkeys")
                        rows = cur.fetchall()
                        mapping = {r["action"]: r["keybind"] for r in rows}
                        if mapping:
                            self.load_hotkeys(mapping)
                        else:
                            debug_print("HotkeyListener", "No hotkeys found in DB fallback read.")
                    finally:
                        conn.close()
                else:
                    debug_print("HotkeyListener", f"DB file not found at {db_path}; cannot load hotkeys.")
            except Exception:
                debug_print("HotkeyListener", f"Synchronous hotkey DB read failed: {traceback.format_exc()}")
            return

        mapping = {}
        try:
            # Prefer to fetch all hotkeys in one coroutine call
            try:
                fut = __import__("asyncio").run_coroutine_threadsafe(db.get_all_hotkeys(), loop)
                mapping = fut.result(timeout)
            except Exception:
                # Fallback: try individual gets for required keys only
                debug_print("HotkeyListener", "Bulk fetch failed; falling back to per-key fetch.")
                futures = {}
                for action in REQUIRED_HOTKEYS.keys():
                    fut = None
                    try:
                        fut = __import__("asyncio").run_coroutine_threadsafe(db.get_hotkey(action, "null"), loop)
                    except Exception:
                        fut = None
                    if fut:
                        futures[action] = fut

                for action, fut in futures.items():
                    try:
                        val = fut.result(timeout)
                    except Exception:
                        val = None
                    if val is not None:
                        mapping[action] = val
        except Exception:
            debug_print("HotkeyListener", f"Failed to reload hotkeys from DB: {traceback.format_exc()}")

        # Finally, apply mapping
        if mapping:
            self.load_hotkeys(mapping)

    def pause_listening(self) -> None:
        """Temporarily remove OS bindings but keep the configured key strings so
        they can be restored later with `resume_listening()`.

        Safe to call multiple times.
        """
        if keyboard is None:
            return
        with self._lock:
            if self._paused:
                return
            self._paused = True
            # Remove all active registrations but preserve the _hotkey_strings
            for act, reg in list(self._registered_hotkeys.items()):
                try:
                    if reg:
                        keyboard.remove_hotkey(reg)
                except Exception:
                    try:
                        keyboard.remove_hotkey(str(reg))
                    except Exception:
                        debug_print("HotkeyListener", f"Failed to remove hotkey during pause for {act}: {traceback.format_exc()}")
            self._registered_hotkeys.clear()
        debug_print("HotkeyListener", "Paused global hotkey listening (bindings removed temporarily).")

    def resume_listening(self) -> None:
        """Re-register hotkeys that were previously loaded (using stored key strings).

        This is safe to call even if not paused.
        """
        if keyboard is None:
            return
        with self._lock:
            if not self._paused:
                return
            # Re-register based on stored key strings
            strings = dict(self._hotkey_strings)
            self._paused = False
        for act, kb in strings.items():
            if act.lower() == "stop listening":
                continue
            try:
                if kb and str(kb).lower() != "null":
                    self._register_keybind(act, kb)
            except Exception:
                debug_print("HotkeyListener", f"Failed to re-register hotkey for {act} during resume: {traceback.format_exc()}")
        debug_print("HotkeyListener", "Resumed global hotkey listening (bindings restored).")


def set_global_listener(lst: GlobalHotkeyListener) -> None:
    global _GLOBAL_LISTENER
    _GLOBAL_LISTENER = lst


def get_global_listener() -> GlobalHotkeyListener | None:
    return _GLOBAL_LISTENER


__all__ = ("GlobalHotkeyListener", "set_global_listener", "get_global_listener")
