from pathlib import Path
import time
import os
import sys
import asyncio
import threading
import obsws_python as obs
from obsws_python.error import OBSSDKRequestError
from PIL import Image, ImageFont
from contextlib import contextmanager
from audio_player import AudioManager
from subtitle_overlay import SubtitleOverlayServer
from tools import debug_print, path_from_app_root, get_debug
from db import get_setting, get_location_capture
from dotenv import load_dotenv
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

if TYPE_CHECKING:  # pragma: no cover - used for type hints only
    from tts import TTSConversionResult

##########################################################
##########################################################

load_dotenv()

WEBSOCKET_HOST = "localhost"
WEBSOCKET_PORT = 4455
WEBSOCKET_PASSWORD = os.getenv("WEBSOCKET_PASSWORD")

# Subtitle overlay configuration
SUBTITLE_UPDATE_MODE = "word"
if SUBTITLE_UPDATE_MODE not in {"word", "character"}:
    SUBTITLE_UPDATE_MODE = "word"
SUBTITLE_BOX_WIDTH = 1280
SUBTITLE_BOX_HEIGHT = 720
SUBTITLE_MARGIN_BOTTOM = 0
SUBTITLE_MAX_FONT_SIZE = 64
SUBTITLE_MIN_FONT_SIZE = 28
SUBTITLE_FONT_FACE = "Segoe UI"
SUBTITLE_FONT_STYLE = "Bold"
SUBTITLE_AUTO_SHRINK_THRESHOLD = 110
SUBTITLE_NO_SPACE_BEFORE = set(",.!?;:\"”’)]}")
SUBTITLE_OPENING_QUOTES = {"\"", "“", "„", "«"}
SUBTITLE_LINE_FONT_STEP = 3
SUBTITLE_LINE_SHRINK_DELAY = 3
SUBTITLE_PYRAMID_START_RATIO = 0.95
SUBTITLE_PYRAMID_RATIO_STEP = 0.03
SUBTITLE_CHAR_WIDTH_RATIO = 0.42
TEXTBOX_POST_ROLL_SECONDS = 1.0
TEXTBOX_FADE_OUT_SECONDS = 0.35
SUBTITLE_LINE_HEIGHT_RATIO = 1.25
SUBTITLE_WRAP_SLACK = 48
SUBTITLE_VERTICAL_SAFE_RATIO = 0.9
SUBTITLE_CHAR_EQUIVALENTS = {
    "“": "\"",
    "”": "\"",
    "„": "\"",
    "«": "\"",
    "»": "\"",
    "‘": "'",
    "’": "'",
    "‚": "'",
    "—": "-",
    "–": "-",
}
SUBTITLE_FONT_CANDIDATES = (
    os.getenv("SUBTITLE_FONT_FILE"),
    str(path_from_app_root("media", "fonts", "subtitle.ttf")),
    os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts", "segoeui.ttf"),
    os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts", "arial.ttf"),
    "/System/Library/Fonts/SFNSDisplay.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)
SUBTITLE_OVERLAY_PORT = int(os.getenv("SUBTITLE_OVERLAY_PORT", "4816"))
SUBTITLE_BASE_CHAR_TARGET = 28
SUBTITLE_BASE_CHAR_MAX = 33
SUBTITLE_CHAR_GROWTH_LINE_START = 3
SUBTITLE_CHAR_GROWTH_PER_LINE = 3


@contextmanager
def suppress_stderr():
    """Temporarily suppress stderr output."""
    with open(os.devnull, "w") as devnull:
        old_stderr = sys.stderr
        sys.stderr = devnull
        try:
            yield
        finally:
            sys.stderr = old_stderr


class OBSWebsocketsManager:
    ws = None
    FADE_STEPS = 25
    FADE_STEP_INTERVAL = 0.02
    
    def __init__(self):
        self.connected = False
        self._reconnect_lock = threading.Lock()
        self._connect_thread: Optional[threading.Thread] = None
        self._connect_with_retry()
        self.onscreen_location = None
        self.offscreen_location = None
        self.display_fade_in_seconds = self.FADE_STEPS * self.FADE_STEP_INTERVAL
        self.video_width, self.video_height = self._load_video_settings()
        self._subtitle_mode = SUBTITLE_UPDATE_MODE
        self.subtitle_overlay = SubtitleOverlayServer(port=SUBTITLE_OVERLAY_PORT)
        self._subtitle_font_path = self._resolve_subtitle_font_path()
        self._subtitle_font_cache: Dict[int, ImageFont.FreeTypeFont] = {}
        self._subtitle_lines: List[str] = []
        self._subtitle_line_chars: List[int] = []
        self._subtitle_pending_new_line: bool = False
        self._subtitle_block_font_size: int = SUBTITLE_MAX_FONT_SIZE
        self._subtitle_last_line_count: int = 0
        self._pending_quote_prefix: str = ""
        debug_print("OBSWebsocketsManager", "OBSWebsocketsManager initialized.")

    def _connect_with_retry(self) -> None:
        while True:
            try:
                with suppress_stderr():
                    self.ws = obs.ReqClient(
                        host=WEBSOCKET_HOST,
                        port=WEBSOCKET_PORT,
                        password=WEBSOCKET_PASSWORD,
                        json_response=False,
                    )
                self.connected = True
                return
            except Exception as exc:
                self.connected = False
                print(f"\n[ERROR]Could not connect to OBS websockets ({exc}). Retrying in 10 seconds...")
                time.sleep(10)

    def _perform_reconnect(self) -> None:
        self.disconnect()
        self._connect_with_retry()
        self.video_width, self.video_height = self._load_video_settings()

    def _async_reconnect(self) -> None:
        with self._reconnect_lock:
            try:
                self._perform_reconnect()
            except Exception as exc:
                print(f"[ERROR]OBS reconnection attempt failed: {exc}")
                raise

    def refresh_connection(self, *, blocking: bool = False) -> bool:
        if blocking:
            with self._reconnect_lock:
                self._perform_reconnect()
            return True
        if self._reconnect_lock.locked():
            return False
        thread = threading.Thread(target=self._async_reconnect, name="OBSReconnect", daemon=True)
        self._connect_thread = thread
        thread.start()
        return True

    def is_reconnecting(self) -> bool:
        return self._reconnect_lock.locked()

    def get_display_fade_in_delay(self) -> float:
        """Return the configured fade-in duration for meme/gif sources."""
        try:
            return float(self.display_fade_in_seconds)
        except Exception:
            return self.FADE_STEPS * self.FADE_STEP_INTERVAL
    
    def _load_video_settings(self) -> tuple[int, int]:
        """Best effort fetch of the base canvas dimensions for subtitle placement."""
        try:
            resp = self.ws.send("GetVideoSettings", {})
            width = getattr(resp, "baseWidth", None) or getattr(resp, "base_width", None)
            height = getattr(resp, "baseHeight", None) or getattr(resp, "base_height", None)
            if isinstance(resp, dict):
                width = width or resp.get("baseWidth") or resp.get("base_width")
                height = height or resp.get("baseHeight") or resp.get("base_height")
        except Exception:
            width = None
            height = None
        if not width or not height:
            width, height = 1920, 1080
        return int(width), int(height)

    def _resolve_subtitle_font_path(self) -> Optional[str]:
        for candidate in SUBTITLE_FONT_CANDIDATES:
            if not candidate:
                continue
            try:
                path_obj = Path(candidate)
            except Exception:
                continue
            if path_obj.exists():
                return str(path_obj)
        return None

    def _get_subtitle_font(self, font_size: int):
        size = max(1, int(font_size))
        cached = self._subtitle_font_cache.get(size)
        if cached is not None:
            return cached
        font_path = self._subtitle_font_path
        font = None
        if font_path:
            try:
                font = ImageFont.truetype(font_path, size=size)
            except Exception:
                font = None
                self._subtitle_font_path = None
        if font is None:
            try:
                font = ImageFont.load_default()
            except Exception:
                font = None
        self._subtitle_font_cache[size] = font
        return font
        
    async def set_assistant_locations(self) -> bool:
        """Sets the onscreen and offscreen locations of the assistant object"""
        debug_print("OBSWebsocketsManager", "Setting local variables for onscreen and offscreen locations.")
        assistant_name = await get_setting("OBS Assistant Object Name")
        if not assistant_name:
            print("[ERROR]Assistant name not set in settings.")
            return False
        onscreen_location_dict = await get_location_capture(assistant_name, True)
        if not onscreen_location_dict:
            print("[ERROR]Onscreen location not set in database.")
            return
        self.onscreen_location = {
            "x": float(onscreen_location_dict.get("x_position")),
            "y": float(onscreen_location_dict.get("y_position")),
            "scaleX": float(onscreen_location_dict.get("scale_x")),
            "scaleY": float(onscreen_location_dict.get("scale_y"))
        }

        offscreen_location_dict = await get_location_capture(assistant_name, False)
        if not offscreen_location_dict:
            print("[ERROR]Offscreen location not set in database.")
            return False
        self.offscreen_location = {
            "x": float(offscreen_location_dict.get("x_position")),
            "y": float(offscreen_location_dict.get("y_position")),
            "scaleX": float(offscreen_location_dict.get("scale_x")),
            "scaleY": float(offscreen_location_dict.get("scale_y"))
        }
        return True

    async def capture_location(self, is_onscreen: bool) -> dict:
        """Captures location of the assistant object for customizability"""
        debug_print("OBSWebsocketsManager", f"Capturing {'onscreen' if is_onscreen else 'offscreen'} location of assistant object.")
        assistant_name = await get_setting("OBS Assistant Object Name")
        current_scene = self.ws.get_current_program_scene().current_program_scene_name
        scene_items = self.ws.get_scene_item_list(current_scene)
        scene_item_id = None
        if not assistant_name:
            print("[ERROR]Assistant name not set in settings.")
            return

        for item in scene_items.scene_items:
            if item["sourceName"] == assistant_name:
                scene_item_id = item["sceneItemId"]
                break

        if not scene_item_id:
            print(f"[ERROR] {assistant_name} not found in scene.")
            return

        try:
            current_transform = self.ws.get_scene_item_transform(current_scene, scene_item_id)
            transform = current_transform.scene_item_transform
            location_data = {
                "x": transform["positionX"],
                "y": transform["positionY"],
                "scaleX": transform["scaleX"],
                "scaleY": transform["scaleY"]
            }

            if is_onscreen:
                self.onscreen_location = location_data
            else:
                self.offscreen_location = location_data

            debug_print("OBSWebsocketsManager", f"Captured location data: {location_data}")
            return location_data

        except Exception as e:
            print(f"[ERROR] Failed to get transform for {assistant_name}: {e}")
            return None

    async def activate_assistant(self, assistant_name: str, stationary_assistant_name: str):
        """Moves the assistant on-screen if not already on"""
        debug_print("OBSWebsocketsManager", f"Activating assistant: {assistant_name}")
        current_scene = self.ws.get_current_program_scene().current_program_scene_name
        scene_items = self.ws.get_scene_item_list(current_scene)
        scene_item_id = None
        stationary = False

        for item in scene_items.scene_items:
            if item["sourceName"] == assistant_name:
                scene_item_id = item["sceneItemId"]
                break
            elif item["sourceName"] == stationary_assistant_name:
                scene_item_id = item["sceneItemId"]
                stationary = True
                break

        if not scene_item_id:
            print(f"[ERROR]{assistant_name} or {stationary_assistant_name} not found in scene.")
            return

        if stationary:
            return self.ws.get_scene_item_transform(current_scene, scene_item_id).scene_item_transform

        if (not self.onscreen_location or not self.offscreen_location):
            if not await self.set_assistant_locations():
                print("[ERROR]Set onscreen and offscreen locations for the non-stationary assistant. Use the tools tab of the GUI.")
                return

        self.ws.set_scene_item_transform(
            current_scene,
            scene_item_id,
            {
                "positionX": self.offscreen_location["x"],
                "positionY": self.offscreen_location["y"],
                "scaleX": self.offscreen_location["scaleX"],
                "scaleY": self.offscreen_location["scaleY"]
            }
        )
        self.ws.set_scene_item_enabled(current_scene, scene_item_id, True)

        steps = 30
        for i in range(1, steps + 1):
            t = i / steps
            x = self.offscreen_location["x"] + (self.onscreen_location["x"] - self.offscreen_location["x"]) * t
            y = self.offscreen_location["y"] + (self.onscreen_location["y"] - self.offscreen_location["y"]) * t
            self.ws.set_scene_item_transform(
                current_scene,
                scene_item_id,
                {
                    "positionX": x,
                    "positionY": y,
                    "scaleX": self.onscreen_location["scaleX"],
                    "scaleY": self.onscreen_location["scaleY"]
                }
            )
            time.sleep(0.01)

        self.ws.set_scene_item_transform(
            current_scene,
            scene_item_id,
            {
                "positionX": self.onscreen_location["x"],
                "positionY": self.onscreen_location["y"],
                "scaleX": self.onscreen_location["scaleX"],
                "scaleY": self.onscreen_location["scaleY"]
            }
        )

    async def deactivate_assistant(self, assistant_name: str, is_stationary: bool = False, original_transform=None):
        """Moves the assistant object off screen"""
        debug_print("OBSWebsocketsManager", f"Deactivating assistant: {assistant_name}")
        if not self.offscreen_location:
            if not await self.set_assistant_locations():
                if not is_stationary:
                    return
        current_scene = self.ws.get_current_program_scene().current_program_scene_name
        scene_items = self.ws.get_scene_item_list(current_scene)
        scene_item_id = None

        for item in scene_items.scene_items:
            if item["sourceName"] == assistant_name:
                scene_item_id = item["sceneItemId"]
                break

        if not scene_item_id:
            print(f"[ERROR]{assistant_name} not found in scene.")
            return

        try:
            transform_data = self.ws.get_scene_item_transform(current_scene, scene_item_id)
            transform = transform_data.scene_item_transform
            current_x = transform["positionX"]
            current_y = transform["positionY"]
        except Exception as e:
            print(f"[ERROR]Failed to get current transform: {e}")
            return

        if is_stationary and original_transform:
            try:
                target_x = original_transform["positionX"]
                target_y = original_transform["positionY"]
                steps = 30
                for i in range(1, steps + 1):
                    t = i / steps
                    x = current_x + (target_x - current_x) * t
                    y = current_y + (target_y - current_y) * t
                    self.ws.set_scene_item_transform(
                        current_scene,
                        scene_item_id,
                        {
                            "positionX": x,
                            "positionY": y,
                            "scaleX": original_transform["scaleX"],
                            "scaleY": original_transform["scaleY"]
                        }
                    )
                    time.sleep(0.01)

                self.ws.set_scene_item_transform(
                    current_scene,
                    scene_item_id,
                    {
                        "positionX": target_x,
                        "positionY": target_y,
                        "scaleX": original_transform["scaleX"],
                        "scaleY": original_transform["scaleY"]
                    }
                )
            except Exception as e:
                print(f"[ERROR]Returning stationary assistant to rest: {e}")
            return

        if not self.offscreen_location:
            if not await self.set_assistant_locations():
                print("[ERROR]Offscreen location not set. Use the GUI tools to define it.")
                return

        try:
            target_x = self.offscreen_location["x"]
            target_y = self.offscreen_location["y"]
            steps = 30
            for i in range(1, steps + 1):
                t = i / steps
                x = current_x + (target_x - current_x) * t
                y = current_y + (target_y - current_y) * t
                self.ws.set_scene_item_transform(
                    current_scene,
                    scene_item_id,
                    {
                        "positionX": x,
                        "positionY": y,
                        "scaleX": self.offscreen_location["scaleX"],
                        "scaleY": self.offscreen_location["scaleY"]
                    }
                )
                time.sleep(0.01)

            self.ws.set_scene_item_transform(
                current_scene,
                scene_item_id,
                {
                    "positionX": target_x,
                    "positionY": target_y,
                    "scaleX": self.offscreen_location["scaleX"],
                    "scaleY": self.offscreen_location["scaleY"]
                }
            )
        except Exception as e:
            print(f"[ERROR]Deactivating assistant: {e}")

        self.ws.set_scene_item_enabled(current_scene, scene_item_id, False)

    async def bounce_while_talking(self, audio_manager: AudioManager, volumes, min_vol, max_vol, total_duration_ms, assistant_name, stationary_assistant_name, scene_name=None, original_transform=None):
        """Bounces the assistant object in OBS while the voiced response plays"""
        debug_print("OBSWebsocketsManager", f"Bouncing assistant: {assistant_name} while talking.")
        try:
            if not scene_name:
                scene_name = self.ws.get_current_program_scene().current_program_scene_name
            scene_items = self.ws.get_scene_item_list(scene_name)            

            scene_item_id = None

            for item in scene_items.scene_items:
                if item["sourceName"] in [assistant_name, stationary_assistant_name]:
                    scene_item_id = item["sceneItemId"]
                    break

            if not scene_item_id:
                debug_print("OBSWebsocketsManager", f"{assistant_name} not found in scene.")
                return
            
            # Override base X/Y from original transform if available
            if original_transform is not None:
                actual_base_y = original_transform["positionY"]
                actual_base_x = original_transform["positionX"]
                scale_x = original_transform["scaleX"]
                scale_y = original_transform["scaleY"]
            else:
                actual_base_y = self.onscreen_location["y"]
                actual_base_x = self.onscreen_location["x"]
                scale_x = self.onscreen_location["scaleX"]
                scale_y = self.onscreen_location["scaleY"]

            frame_ms = 50
            num_frames = len(volumes)
            start_time = time.perf_counter()
            total_duration_s = total_duration_ms / 1000

            while True:
                elapsed = time.perf_counter() - start_time
                if elapsed >= total_duration_s:
                    break

                frame_index = int(elapsed * 1000 // frame_ms) % num_frames
                vol = volumes[frame_index]
                y = await audio_manager.map_volume_to_y(vol, min_vol, max_vol, actual_base_y)

                await asyncio.to_thread(self.ws.set_scene_item_transform,
                    scene_name,
                    scene_item_id,
                    {
                        "positionX": actual_base_x,
                        "positionY": y,
                        "scaleX": scale_x,
                        "scaleY": scale_y
                    }
                )
                await asyncio.sleep(frame_ms / 2000)

            # Reset to original transform
            await asyncio.to_thread(self.ws.set_scene_item_transform,
                scene_name,
                scene_item_id,
                {
                    "positionX": actual_base_x,
                    "positionY": actual_base_y,
                    "scaleX": scale_x,
                    "scaleY": scale_y
                }
            )

        except asyncio.CancelledError:
            await asyncio.to_thread(self.ws.set_scene_item_transform,
                scene_name,
                scene_item_id,
                {
                    "positionX": actual_base_x,
                    "positionY": actual_base_y,
                    "scaleX": scale_x,
                    "scaleY": scale_y
                }
            )
            
    async def run_subtitle_track(
        self,
        tts_result: "TTSConversionResult",
        update_mode: Optional[str] = None,
        style: Optional[str] = None,
    ) -> None:
        """Render timed subtitles using ElevenLabs timestamp metadata."""
        if not tts_result:
            await self.clear_subtitles()
            return
        if not self.subtitle_overlay:
            return
        style_key = self._normalize_subtitle_style(style)
        if style_key == "text_box":
            payload = self._build_textbox_payload(tts_result)
            try:
                await asyncio.to_thread(self.subtitle_overlay.update_state, payload)
                duration = self._resolve_subtitle_duration(tts_result, payload)
                await asyncio.sleep(max(0.0, duration + TEXTBOX_POST_ROLL_SECONDS))
                await asyncio.to_thread(self.subtitle_overlay.update_state, self._build_textbox_hide_payload())
                await asyncio.sleep(TEXTBOX_FADE_OUT_SECONDS)
            except asyncio.CancelledError:
                await asyncio.to_thread(self.subtitle_overlay.update_state, self._build_textbox_clear_payload())
                raise
            except Exception as exc:
                print(f"[ERROR]Subtitle rendering failed: {exc}")
            finally:
                await asyncio.to_thread(self.subtitle_overlay.update_state, self._build_textbox_clear_payload())
            return
        update_mode = (update_mode or self._subtitle_mode or "word").lower()
        if update_mode not in {"word", "character"}:
            update_mode = "word"
        tokens = self._build_caption_schedule(tts_result, update_mode)
        if not tokens:
            await self.clear_subtitles()
            return
        start_time = time.perf_counter()
        self._subtitle_block_font_size = SUBTITLE_MAX_FONT_SIZE
        self._subtitle_last_line_count = 0
        self._subtitle_lines = []
        self._subtitle_line_chars = []
        self._subtitle_pending_new_line = False
        self._pending_quote_prefix = ""
        current_text = ""
        try:
            for token in tokens:
                delay = token["start"] - (time.perf_counter() - start_time)
                if delay > 0:
                    await asyncio.sleep(delay)
                self._append_caption_token(token["value"], mode=update_mode, space_before=token.get("space_before"))
                current_text = "\n".join(self._subtitle_lines)
                payload = self._build_overlay_payload(current_text, style_label="Inverted Pyramid")
                await asyncio.to_thread(self.subtitle_overlay.update_state, payload)
            total_duration = (tts_result.duration_seconds or (tokens[-1]["start"] + 0.75)) + 2.0
            remaining = total_duration - (time.perf_counter() - start_time)
            if remaining > 0:
                await asyncio.sleep(remaining)
        except asyncio.CancelledError:
            await asyncio.to_thread(self.subtitle_overlay.clear_state)
            raise
        except Exception as exc:
            print(f"[ERROR]Subtitle rendering failed: {exc}")
        finally:
            await asyncio.to_thread(self.subtitle_overlay.clear_state)

    async def clear_subtitles(self) -> None:
        """Ensure the subtitle overlay is cleared."""
        if self.subtitle_overlay:
            await asyncio.to_thread(self.subtitle_overlay.clear_state)

    async def refresh_browser_sources(self, scene_name: Optional[str] = None) -> int:
        """Refresh all browser sources in the target scene."""
        if not self.ws:
            return 0
        try:
            if not scene_name:
                scene_name = self.ws.get_current_program_scene().current_program_scene_name
            scene_items = self.ws.get_scene_item_list(scene_name)
            input_list = await asyncio.to_thread(self.ws.send, "GetInputList", {})
        except Exception as exc:
            debug_print("OBSWebsocketsManager", f"Failed to load OBS inputs for refresh: {exc}")
            return 0

        input_map: Dict[str, str] = {}
        try:
            inputs = None
            if hasattr(input_list, "inputs"):
                inputs = input_list.inputs
            elif isinstance(input_list, dict):
                inputs = input_list.get("inputs")
            if inputs:
                for entry in inputs:
                    if isinstance(entry, dict):
                        name = entry.get("inputName") or entry.get("input_name")
                        kind = entry.get("inputKind") or entry.get("input_kind") or ""
                    else:
                        name = getattr(entry, "inputName", None) or getattr(entry, "input_name", None)
                        kind = getattr(entry, "inputKind", None) or getattr(entry, "input_kind", None) or ""
                    if name:
                        input_map[str(name)] = str(kind)
        except Exception:
            input_map = {}

        refreshed = 0
        items = getattr(scene_items, "scene_items", None) or getattr(scene_items, "sceneItems", None) or []
        for item in items:
            if isinstance(item, dict):
                source_name = item.get("sourceName")
            else:
                source_name = getattr(item, "sourceName", None) or getattr(item, "source_name", None)
            if not source_name:
                continue
            kind = input_map.get(source_name, "")
            if "browser" not in str(kind).lower():
                continue
            try:
                await asyncio.to_thread(
                    self.ws.send,
                    "PressInputPropertiesButton",
                    {"inputName": source_name, "propertyName": "refreshnocache"},
                )
                refreshed += 1
            except Exception:
                try:
                    await asyncio.to_thread(
                        self.ws.send,
                        "PressInputPropertiesButton",
                        {"inputName": source_name, "propertyName": "refresh"},
                    )
                    refreshed += 1
                except Exception as exc:
                    debug_print("OBSWebsocketsManager", f"Failed to refresh browser source '{source_name}': {exc}")
        return refreshed

    def _build_overlay_payload(self, text: str, *, style_label: str = "Inverted Pyramid") -> Dict[str, Any]:
        lines: List[Dict[str, Any]] = []
        if text:
            clean_lines = [raw_line.strip() for raw_line in text.split("\n") if raw_line.strip()]
            block_size = self._resolve_block_font_size(clean_lines)
            for clean in clean_lines:
                lines.append({
                    "text": clean,
                    "fontSize": block_size,
                })
        constrained = self._apply_vertical_constraints(lines)
        return {
            "style": style_label,
            "lines": constrained,
            "width": SUBTITLE_BOX_WIDTH,
            "height": SUBTITLE_BOX_HEIGHT,
        }

    @staticmethod
    def _normalize_subtitle_style(style: Optional[str]) -> str:
        normalized = (style or "").strip().lower()
        if "text box" in normalized:
            return "text_box"
        return "inverted_pyramid"

    def _build_textbox_payload(self, tts_result: "TTSConversionResult") -> Dict[str, Any]:
        if isinstance(tts_result, dict):
            text = tts_result.get("source_text") or ""
            timings = tts_result.get("character_timings") or []
            duration = tts_result.get("duration_seconds")
        else:
            text = getattr(tts_result, "source_text", None) or ""
            timings = getattr(tts_result, "character_timings", []) or []
            duration = getattr(tts_result, "duration_seconds", None)

        if not text:
            words = getattr(tts_result, "word_timings", []) if not isinstance(tts_result, dict) else tts_result.get("word_timings")
            if words:
                text = " ".join(str(item.get("text", "")) for item in words if item.get("text"))

        return {
            "style": "Text Box",
            "mode": "text_box",
            "text": text or "",
            "character_timings": timings,
            "duration_seconds": duration,
            "visible": True,
            "reset": True,
            "lines": [],
        }

    @staticmethod
    def _build_textbox_hide_payload() -> Dict[str, Any]:
        return {
            "style": "Text Box",
            "mode": "text_box",
            "visible": False,
            "clear": True,
        }

    @staticmethod
    def _build_textbox_clear_payload() -> Dict[str, Any]:
        return {
            "style": "Text Box",
            "mode": "text_box",
            "visible": False,
            "reset": True,
            "lines": [],
        }

    @staticmethod
    def _resolve_subtitle_duration(tts_result: "TTSConversionResult", payload: Dict[str, Any]) -> float:
        if payload.get("duration_seconds"):
            try:
                return float(payload["duration_seconds"])
            except (TypeError, ValueError):
                pass
        timings = payload.get("character_timings") or []
        if timings:
            last = timings[-1]
            try:
                return float(last.get("end") or last.get("start") or 0.0)
            except (TypeError, ValueError):
                return 0.0
        if isinstance(tts_result, dict):
            try:
                return float(tts_result.get("duration_seconds") or 0.0)
            except (TypeError, ValueError):
                return 0.0
        try:
            return float(getattr(tts_result, "duration_seconds", 0.0) or 0.0)
        except (TypeError, ValueError):
            duration = 0.0
        text = payload.get("text") if isinstance(payload, dict) else ""
        if not duration and text:
            return max(1.0, len(str(text)) * 0.04)
        return duration

    def _build_caption_schedule(self, tts_result: "TTSConversionResult", mode: str) -> List[Dict[str, Any]]:
        tokens: List[Dict[str, Any]] = []
        character_entries = getattr(tts_result, "character_timings", []) or []
        source_text = getattr(tts_result, "source_text", None)
        if source_text is None and isinstance(tts_result, dict):
            source_text = tts_result.get("source_text")

        if mode != "character" and source_text and character_entries:
            tokens = self._build_tokens_from_source_text(source_text, character_entries)
        if not tokens:
            if mode == "character" and character_entries:
                for item in character_entries:
                    char = item.get("char")
                    if not char:
                        continue
                    start = float(item.get("start") or item.get("start_time") or item.get("startTime") or 0.0)
                    tokens.append({"value": char, "start": max(0.0, start)})
            elif character_entries:
                tokens = self._build_tokens_from_characters(character_entries)
            else:
                words = getattr(tts_result, "word_timings", []) or []
                if not words and character_entries:
                    words = [{"text": entry.get("char"), "start": entry.get("start")} for entry in character_entries]
                for item in words:
                    word = item.get("text")
                    if word is None:
                        continue
                    start = float(item.get("start") or 0.0)
                    tokens.append({"value": word, "start": max(0.0, start)})
        tokens.sort(key=lambda entry: entry["start"])
        return tokens

    def _build_tokens_from_source_text(self, source_text: str, character_entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        segments = self._split_source_segments(source_text)
        if not segments:
            return []
        entries: List[Tuple[str, str, float]] = []
        for entry in character_entries:
            raw_char = entry.get("char")
            if raw_char is None:
                continue
            char_str = str(raw_char)
            if not char_str:
                continue
            start = float(entry.get("start") or entry.get("start_time") or entry.get("startTime") or 0.0)
            entries.append((char_str, self._normalize_char_for_match(char_str), max(0.0, start)))
        if not entries:
            return []
        entry_index = 0
        entry_count = len(entries)
        tokens: List[Dict[str, Any]] = []
        for segment_text, space_before in segments:
            targets: List[Tuple[str, bool]] = []
            for ch in segment_text:
                if ch.isspace():
                    continue
                normalized = self._normalize_char_for_match(ch)
                requires_match = self._requires_char_alignment(ch)
                targets.append((normalized, requires_match))
            if not targets:
                continue
            start_time: Optional[float] = None
            probe_index = entry_index
            matched = True
            for seg_char, requires_match in targets:
                found_index, char_start = self._find_next_char_match(entries, probe_index, seg_char)
                if found_index is None:
                    if requires_match:
                        matched = False
                        break
                    continue
                if start_time is None:
                    start_time = char_start
                probe_index = found_index
            if not matched:
                return []
            if start_time is None:
                if entry_count:
                    reference_index = min(max(probe_index - 1, 0), entry_count - 1)
                    start_time = entries[reference_index][2]
                else:
                    start_time = 0.0
            entry_index = probe_index
            tokens.append({
                "value": segment_text,
                "start": max(0.0, start_time),
                "space_before": space_before,
            })
        return tokens

    @staticmethod
    def _split_source_segments(text: str) -> List[Tuple[str, bool]]:
        segments: List[Tuple[str, bool]] = []
        current: List[str] = []
        space_pending = False
        space_flag = False
        for char in text:
            if char.isspace():
                if current:
                    segments.append(("".join(current), space_flag))
                    current = []
                space_pending = True
                continue
            if not current:
                space_flag = space_pending
                space_pending = False
            current.append(char)
        if current:
            segments.append(("".join(current), space_flag))
        return segments

    @staticmethod
    def _normalize_char_for_match(char: str) -> str:
        if not char:
            return ""
        mapped = SUBTITLE_CHAR_EQUIVALENTS.get(char, char)
        if mapped.isalpha():
            return mapped.casefold()
        return mapped

    @staticmethod
    def _requires_char_alignment(char: str) -> bool:
        return char.isalnum()

    @staticmethod
    def _find_next_char_match(entries: List[Tuple[str, str, float]], start_index: int, target: str) -> Tuple[Optional[int], Optional[float]]:
        probe = start_index
        count = len(entries)
        while probe < count:
            raw_char, normalized_char, char_start = entries[probe]
            probe += 1
            if raw_char.isspace():
                continue
            if normalized_char == target:
                return probe, char_start
        return None, None

    def _build_tokens_from_characters(self, character_entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        tokens: List[Dict[str, Any]] = []
        chunk_chars: List[str] = []
        chunk_start: Optional[float] = None
        chunk_space_before = False
        pending_space = False

        def flush_chunk() -> None:
            nonlocal chunk_chars, chunk_start, chunk_space_before
            if not chunk_chars:
                return
            tokens.append({
                "value": "".join(chunk_chars),
                "start": max(0.0, chunk_start or 0.0),
                "space_before": chunk_space_before,
            })
            chunk_chars = []
            chunk_start = None
            chunk_space_before = False

        for entry in character_entries:
            char = entry.get("char")
            if char is None:
                continue
            char_str = str(char)
            if not char_str:
                continue
            if char_str.isspace():
                flush_chunk()
                pending_space = True
                continue
            if not chunk_chars:
                chunk_start = float(entry.get("start") or entry.get("start_time") or entry.get("startTime") or 0.0)
                chunk_space_before = pending_space
                pending_space = False
            chunk_chars.append(char_str)

        flush_chunk()
        return tokens


    def _append_caption_token(self, token: str, *, mode: str, space_before: Optional[bool] = None) -> None:
        normalized = self._sanitize_token(token, mode)
        if not normalized:
            return
        if normalized in SUBTITLE_OPENING_QUOTES and self._is_opening_quote_context():
            self._pending_quote_prefix = f"{self._pending_quote_prefix}{normalized}"
            return
        if self._pending_quote_prefix:
            normalized = f"{self._pending_quote_prefix}{normalized}"
            self._pending_quote_prefix = ""
        self._append_token_to_current_line(normalized, space_before)

    def _sanitize_token(self, token: str, mode: str) -> str:
        if token is None:
            return ""
        if mode == "character":
            return token.replace("\r", "").replace("\n", "")
        cleaned = token.replace("\r", " ").replace("\n", " ")
        return " ".join(cleaned.split())
    def _append_token_to_current_line(self, token: str, space_before: Optional[bool] = None) -> None:
        if not self._subtitle_lines or self._subtitle_pending_new_line:
            self._start_new_line()
            self._subtitle_pending_new_line = False
        line_index = len(self._subtitle_lines) - 1
        base_text = self._subtitle_lines[line_index]
        if not base_text:
            spacer = ""
        elif space_before is True:
            spacer = " "
        elif space_before is False:
            spacer = ""
        else:
            spacer = "" if token in SUBTITLE_NO_SPACE_BEFORE else " "
        candidate_text = (f"{base_text}{spacer}{token}" if base_text else token).strip()
        target, max_chars = self._line_char_limits(line_index)
        candidate_chars = self._subtitle_line_chars[line_index] + self._token_char_length(token, spacer)
        if self._subtitle_line_chars[line_index] > 0 and candidate_chars > max_chars:
            self._start_new_line()
            line_index += 1
            base_text = ""
            spacer = ""
            candidate_text = token
            target, max_chars = self._line_char_limits(line_index)
            candidate_chars = self._token_char_length(token)
        self._subtitle_lines[line_index] = candidate_text
        self._subtitle_line_chars[line_index] = candidate_chars
        self._subtitle_pending_new_line = candidate_chars > target

    def _start_new_line(self) -> None:
        self._subtitle_lines.append("")
        self._subtitle_line_chars.append(0)

    def _line_char_limits(self, line_index: int) -> Tuple[int, int]:
        growth_anchor = max(0, SUBTITLE_CHAR_GROWTH_LINE_START - 1)
        extra_lines = max(0, line_index - growth_anchor)
        extra_chars = extra_lines * SUBTITLE_CHAR_GROWTH_PER_LINE
        target = SUBTITLE_BASE_CHAR_TARGET + extra_chars
        max_chars = SUBTITLE_BASE_CHAR_MAX + extra_chars
        return max(1, target), max(target, max_chars)

    @staticmethod
    def _token_char_length(token: str, spacer: str = "") -> int:
        spacer_len = 1 if spacer == " " else 0
        return spacer_len + len(token.replace(" ", ""))

    def _is_opening_quote_context(self) -> bool:
        if not self._subtitle_lines:
            return True
        last_line = self._subtitle_lines[-1] if self._subtitle_lines else ""
        if not last_line:
            return True
        last_char = last_line[-1]
        if last_char in {" ", "\t", "\n"}:
            return True
        return last_char in {"(", "[", "{", "-", "—", "\u2013"}

    def _estimate_line_width(self, text: str, font_size: int) -> float:
        if not text:
            return 0.0
        size = max(SUBTITLE_MIN_FONT_SIZE, min(SUBTITLE_MAX_FONT_SIZE, font_size))
        font = self._get_subtitle_font(size)
        if font is not None:
            try:
                if hasattr(font, "getlength"):
                    return float(font.getlength(text))
                bbox = font.getbbox(text)
                if bbox:
                    return float(bbox[2] - bbox[0])
            except Exception:
                pass
        return float(len(text) * size * SUBTITLE_CHAR_WIDTH_RATIO)

    def _line_width_limit(self, line_index: int) -> float:
        base_ratio = SUBTITLE_PYRAMID_START_RATIO + max(0, line_index) * SUBTITLE_PYRAMID_RATIO_STEP
        ratio = min(1.0, max(0.25, base_ratio))
        return SUBTITLE_BOX_WIDTH * ratio

    def _determine_block_font_size(self, lines: List[str]) -> int:
        if not lines:
            return SUBTITLE_MAX_FONT_SIZE
        available_height = SUBTITLE_BOX_HEIGHT * SUBTITLE_VERTICAL_SAFE_RATIO
        count = len(lines)
        baseline = SUBTITLE_MAX_FONT_SIZE - max(0, count - 1) * SUBTITLE_LINE_FONT_STEP
        font_size = max(SUBTITLE_MIN_FONT_SIZE, baseline)
        while font_size > SUBTITLE_MIN_FONT_SIZE:
            if self._block_fits_canvas(lines, font_size, available_height):
                return font_size
            font_size = max(SUBTITLE_MIN_FONT_SIZE, font_size - SUBTITLE_LINE_FONT_STEP)
            if font_size == SUBTITLE_MIN_FONT_SIZE:
                break
        return font_size

    def _resolve_block_font_size(self, lines: List[str]) -> int:
        line_count = len(lines)
        if line_count == 0:
            self._subtitle_last_line_count = 0
            self._subtitle_block_font_size = SUBTITLE_MAX_FONT_SIZE
            return self._subtitle_block_font_size
        needs_recalc = (
            line_count != self._subtitle_last_line_count
            or self._subtitle_block_font_size <= 0
        )
        if needs_recalc:
            self._subtitle_block_font_size = self._determine_block_font_size(lines)
            self._subtitle_last_line_count = line_count
        return self._subtitle_block_font_size

    def _block_fits_canvas(self, lines: List[str], font_size: int, available_height: float) -> bool:
        total_height = len(lines) * font_size * SUBTITLE_LINE_HEIGHT_RATIO
        if total_height > available_height:
            return False
        for idx, line in enumerate(lines):
            width_limit = self._line_width_limit(idx)
            width = self._estimate_line_width(line, font_size)
            if width > (width_limit + SUBTITLE_WRAP_SLACK):
                return False
        return True

    def _apply_vertical_constraints(self, lines: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not lines:
            return []

        available = SUBTITLE_BOX_HEIGHT * SUBTITLE_VERTICAL_SAFE_RATIO
        multiplier = SUBTITLE_LINE_HEIGHT_RATIO

        def total_height() -> float:
            return sum(max(SUBTITLE_MIN_FONT_SIZE, entry.get("fontSize", SUBTITLE_MIN_FONT_SIZE)) * multiplier for entry in lines)

        current_height = total_height()
        if current_height > available:
            scale = max(0.2, available / current_height)
            for entry in lines:
                entry["fontSize"] = max(SUBTITLE_MIN_FONT_SIZE, int(entry.get("fontSize", SUBTITLE_MIN_FONT_SIZE) * scale))

        # If still too tall due to hitting the min size, gradually trim further.
        for _ in range(25):
            current_height = total_height()
            if current_height <= available:
                break
            reduced = False
            for entry in lines:
                if entry.get("fontSize", SUBTITLE_MIN_FONT_SIZE) > SUBTITLE_MIN_FONT_SIZE:
                    entry["fontSize"] -= 1
                    reduced = True
            if not reduced:
                break

        return lines

    def _compute_caption_font_size(self, text: str) -> int:
        if not text:
            return SUBTITLE_MAX_FONT_SIZE
        base_size = SUBTITLE_MAX_FONT_SIZE
        line_count = max(1, text.count("\n") + 1)
        line_penalty = (line_count - 1) * SUBTITLE_LINE_FONT_STEP
        adjusted = max(SUBTITLE_MIN_FONT_SIZE, int(base_size - line_penalty))
        return adjusted

    async def display_meme(self, path: str, is_meme: bool = True, duration: float = None, ready_event=None, ready_opacity: float | None = None, object_name_override: str | None = None):
        current_scene = self.ws.get_current_program_scene().current_program_scene_name
        scene_items = self.ws.get_scene_item_list(current_scene)
        scene_item_id = None
        if object_name_override:
            object_name = object_name_override
            fade_out_delay = duration if duration is not None else 5.0
        elif is_meme:
            object_name = await get_setting("OBS Meme Object Name", "MemeDisplay")
            fade_out_delay = duration if duration is not None else 10.0
        else:
            object_name = await get_setting("OBS GIF Placeholder Object Name", "GIFDisplay")
            fade_out_delay = 5.0

        if not object_name:
            print("[ERROR]No OBS source configured for display_meme.")
            return

        for item in scene_items.scene_items:
            if item["sourceName"] == object_name:
                scene_item_id = item["sceneItemId"]
                break

        if not scene_item_id:
            print(f"[ERROR]{object_name} source not found in scene.")
            return
        
        # Set the meme image path. Use absolute path and ensure file exists.
        abs_path = os.path.abspath(path)
        if object_name_override:
            asset_label = "overlay"
        elif is_meme:
            asset_label = "Meme image"
        else:
            asset_label = "GIF"

        if not os.path.exists(abs_path):
            print(f"[ERROR] {asset_label} not found: {abs_path}")
            return
        
        used_input_api = True
        try:
            get_resp = await asyncio.to_thread(
                self.ws.send, "GetInputSettings", {"inputName": object_name}
            )
        except Exception as e:
            # Fallback to older/newer source-based API
            try:
                get_resp = await asyncio.to_thread(
                    self.ws.send, "GetSourceSettings", {"sourceName": object_name}
                )
                used_input_api = False
            except Exception as e2:
                print(f"[DEBUG] Could not fetch settings for '{object_name}': {e} / {e2}")
                get_resp = None

        # Normalize to a dict of current settings where possible
        source_settings = {}
        try:
            if get_resp is None:
                source_settings = {}
            elif hasattr(get_resp, "inputSettings"):
                source_settings = get_resp.inputSettings or {}
            elif hasattr(get_resp, "sourceSettings"):
                source_settings = get_resp.sourceSettings or {}
            elif isinstance(get_resp, dict):
                source_settings = get_resp.get("inputSettings") or get_resp.get("sourceSettings") or get_resp
            else:
                source_settings = dict(get_resp)
        except Exception:
            source_settings = {}

        # Choose the best key to set based on existing settings keys
        preferred_keys = ["file", "local_file", "localFile", "path"]
        key_to_set = None
        if isinstance(source_settings, dict):
            for k in preferred_keys:
                if k in source_settings:
                    key_to_set = k
                    break

        if key_to_set is None:
            # Default to 'file' which is commonly used for image_source
            key_to_set = "file"

        # Build the correct payload depending on the API the server accepts
        if used_input_api:
            payload = {"inputName": object_name, "inputSettings": {key_to_set: abs_path}, "overlay": False}
            request_name = "SetInputSettings"
        else:
            payload = {"sourceName": object_name, "sourceSettings": {key_to_set: abs_path}}
            request_name = "SetSourceSettings"

        try:
            await asyncio.to_thread(self.ws.send, request_name, payload)
        except Exception as e:
            print(f"[ERROR] Failed to set source/input settings for '{object_name}' using {request_name}: {e}")
            # For debugging, attempt to fetch and print whatever settings we can
            try:
                if used_input_api:
                    current = await asyncio.to_thread(self.ws.send, "GetInputSettings", {"inputName": object_name})
                else:
                    current = await asyncio.to_thread(self.ws.send, "GetSourceSettings", {"sourceName": object_name})
                print(f"[DEBUG] Current settings for '{object_name}': {current}")
            except Exception as e2:
                print(f"[DEBUG] Could not fetch settings for '{object_name}': {e2}")
            return

        # Force filter opacity to 0.0 before fade in (filter expects 0.0-1.0)
        self.ws.set_source_filter_settings(
            object_name,
            "Color Correction",
            {
                "opacity": 0.0
            }
        )

        #Enable the source if disabled
        self.ws.set_scene_item_enabled(current_scene, scene_item_id, True)

        # Fade in the meme (use 0.0..1.0 range for filter opacity)
        steps = self.FADE_STEPS
        step_sleep = self.FADE_STEP_INTERVAL
        ready_set = False
        target_opacity = None
        if ready_event is not None:
            try:
                if ready_opacity is None:
                    target_opacity = 1.0
                else:
                    target_opacity = max(0.0, min(1.0, float(ready_opacity)))
            except Exception:
                target_opacity = 1.0
        for i in range(1, steps + 1):
            t = i / steps
            self.ws.set_source_filter_settings(
                object_name,
                "Color Correction",
                {
                    "opacity": float(t)
                }
            )
            if ready_event is not None and not ready_set and target_opacity is not None and t >= target_opacity:
                ready_event.set()
                ready_set = True
            await asyncio.sleep(step_sleep)

        # Force opacity to full (1.0)
        self.ws.set_source_filter_settings(
            object_name,
            "Color Correction",
            {
                "opacity": 1.0
            }
        )
        if ready_event is not None and not ready_set:
            ready_event.set()

        # Wait 10 seconds, then fade out the meme
        await asyncio.sleep(fade_out_delay)
        for i in range(1, steps + 1):
            t = i / steps
            self.ws.set_source_filter_settings(
                object_name,
                "Color Correction",
                {
                    "opacity": float(1.0 - t)
                }
            )
            await asyncio.sleep(step_sleep)

        # Ensure opacity is fully off
        self.ws.set_source_filter_settings(
            object_name,
            "Color Correction",
            {
                "opacity": 0.0
            }
        )

        media_root = path_from_app_root("media")
        if object_name_override:
            default_path = media_root / "images_and_gifs" / "test_tts.png"
        elif is_meme:
            default_path = media_root / "memes" / "test_meme.png"
        else:
            default_path = media_root / "images_and_gifs" / "test_anime.gif"

        default_abs_path = str(default_path)
        if default_path.exists():
            restore_payload = (
                {
                    "inputName": object_name,
                    "inputSettings": {key_to_set: default_abs_path},
                    "overlay": False,
                }
                if used_input_api
                else {
                    "sourceName": object_name,
                    "sourceSettings": {key_to_set: default_abs_path},
                }
            )
            restore_request = "SetInputSettings" if used_input_api else "SetSourceSettings"
            try:
                await asyncio.to_thread(self.ws.send, restore_request, restore_payload)
            except Exception as exc:
                print(f"Failed to restore placeholder for '{object_name}': {exc}")
        else:
            print(f"Placeholder file missing at {default_abs_path}; leaving current media in place.",)

        #Disable the source after fade out
        self.ws.set_scene_item_enabled(current_scene, scene_item_id, False)

    def get_obs_screenshot(self, output_path: str) -> str:
        '''Takes a screenshot of the OBS output using obs-websockets and saves it to a temporary file. Returns the file path.'''
        output_path = os.path.abspath(output_path)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        current_scene = self.ws.get_current_program_scene().current_program_scene_name
        source_name = current_scene  # Full output
        output_path = output_path
        self.ws.save_source_screenshot(
            name=source_name,
            img_format="png",
            file_path=output_path,
            width=None,
            height=None,
            quality=-1
        )

        return output_path

    def disconnect(self):
        try:
            if self.ws:
                self.ws.disconnect()
        finally:
            self.connected = False
            self.ws = None

async def tests():
    await meme_creation_workflow()

async def meme_creation_workflow():
    manager = OBSWebsocketsManager()
    media_dir = path_from_app_root("media")
    media_dir.mkdir(exist_ok=True)
    screenshots_dir = media_dir / "screenshots"
    screenshots_dir.mkdir(exist_ok=True)
    manager.get_obs_screenshot(screenshots_dir / "test_screenshot.png")
    from meme_creator import make_meme
    from openai_chat import OpenAiManager
    ai = OpenAiManager()
    screenshot_path = screenshots_dir / "test_screenshot.png"
    response = ai.analyze_image(image_path=screenshot_path, is_meme=True)
    import re
    caption_match = re.search(r'!caption\s*(.*?)\s*(?=!font|$)', response, re.DOTALL | re.IGNORECASE)
    font_match = re.search(r'!font\s*(.*?)\s*(?=!caption|$)', response, re.DOTALL | re.IGNORECASE)
    if caption_match:
        parsed_caption = caption_match.group(1).strip()
        print(f"Parsed Caption: {parsed_caption}")
    if font_match:
        parsed_font = font_match.group(1).strip()
        print(f"Parsed Font: {parsed_font}")
    output_path = make_meme(screenshot_path, parsed_caption, parsed_font)
    await manager.display_meme(output_path)
    manager.disconnect()

#############################################

if __name__ == "__main__":
    asyncio.run(tests())
