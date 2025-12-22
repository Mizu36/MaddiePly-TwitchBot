from pathlib import Path
import time
import os
import sys
import asyncio
import typing
import obsws_python as obs
from PIL import Image, ImageFont
from contextlib import contextmanager
from audio_player import AudioManager
from tools import debug_print, path_from_app_root
from db import get_setting, get_location_capture
from dotenv import load_dotenv

##########################################################
##########################################################

load_dotenv()

WEBSOCKET_HOST = "localhost"
WEBSOCKET_PORT = 4455
WEBSOCKET_PASSWORD = os.getenv("WEBSOCKET_PASSWORD")

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
    GACHA_ANCHOR_NAME = "GachaAnchor"
    GACHA_HORIZONTAL_SPACING = 220.0
    GACHA_START_DROP = 240.0
    GACHA_CARD_TARGET_SIZE = 200.0
    GACHA_CARD_MIN_SCALE = 0.02
    GACHA_CARD_MAX_SCALE = 0.85
    GACHA_CARD_START_SCALE_RATIO = 0.005
    GACHA_CARD_MULTI_START_RATIO = 0.005
    GACHA_CARD_MIN_START_SCALE = 0.0001
    GACHA_CARD_RISE_STEPS = 28
    GACHA_CARD_FRAME_DELAY = 0.02
    GACHA_CARD_STAGGER = 0.12
    GACHA_CARD_ALIGNMENT = 4
    GACHA_ANCHOR_GAP = 40.0
    GACHA_ANCHOR_BUFFER = 60.0
    GACHA_SILHOUETTE_COLOR_BLACK = 0xFF000000
    GACHA_SILHOUETTE_COLOR_WHITE = 0xFFFFFFFF
    GACHA_NAME_ABOVE_GAP = 0.0
    GACHA_NAME_SCALE = 0.35
    GACHA_NAME_ALIGNMENT = 24
    GACHA_LEVEL_SCALE = 0.45
    GACHA_LEVEL_FINAL_SCALE = 0.75
    GACHA_LEVEL_POP_SCALE = 2.0
    GACHA_LEVEL_FRAME_DELAY = 0.02
    GACHA_LEVEL_PREFIX_ALIGNMENT = 6
    GACHA_LEVEL_NUMBER_ALIGNMENT = 5
    GACHA_LEVEL_NUMBER_OFFSET_X = 0.0
    GACHA_LEVEL_VERTICAL_OFFSET = 0.0
    GACHA_LEVEL_FONT_FACE = "Segoe UI"
    GACHA_LEVEL_FONT_STYLE = "Bold"
    GACHA_LEVEL_FONT_SIZE = 64
    GACHA_LEVEL_INITIAL_HOLD = 0.5
    GACHA_LEVEL_COLOR_RED = 0xFF0000FF
    GACHA_LEVEL_COLOR_GREEN = 0xFF00FF00
    GACHA_BATCH_HOLD_SECONDS = 3.0
    GACHA_FADE_STEPS = 20
    GACHA_SINGLE_SILHOUETTE_DELAY = 0.50
    
    def __init__(self):
        # Connect to websockets
        self.connected = False
        while True:
            try:
                with suppress_stderr():
                    self.ws = obs.ReqClient(host = WEBSOCKET_HOST, port = WEBSOCKET_PORT, password = WEBSOCKET_PASSWORD, json_response = False)
                self.connected = True
                break
            except Exception:
                self.connected = False
                print("\n[ERROR]Could not connect to OBS websockets. Retrying in 10 seconds...")
                time.sleep(10)
        self.onscreen_location = None
        self.offscreen_location = None
        self.display_fade_in_seconds = self.FADE_STEPS * self.FADE_STEP_INTERVAL
        self._font_cache: dict[tuple[str, str, int], ImageFont.FreeTypeFont] = {}
        self._text_bounds_cache: dict[tuple[str, str, str, int], tuple[float, float]] = {}
        debug_print("OBSWebsocketsManager", "OBSWebsocketsManager initialized.")

    def get_display_fade_in_delay(self) -> float:
        """Return the configured fade-in duration for meme/gif sources."""
        try:
            return float(self.display_fade_in_seconds)
        except Exception:
            return self.FADE_STEPS * self.FADE_STEP_INTERVAL
        
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

    async def animate_gacha_pulls(self, twitch_user_id: str, number_of_pulls: int, pulled_gachas: list[dict]) -> None:
        """Animate a batch of up to five gacha pulls using in-scene image/text inputs."""
        if not pulled_gachas:
            return
        try:
            scene_name = self.ws.get_current_program_scene().current_program_scene_name
            scene_items = self.ws.get_scene_item_list(scene_name)
            anchor_item = None
            for item in scene_items.scene_items:
                if item["sourceName"] == self.GACHA_ANCHOR_NAME:
                    anchor_item = item
                    break
            if not anchor_item:
                raise RuntimeError("GachaAnchor source not found in the current scene.")
            anchor_transform = self.ws.get_scene_item_transform(scene_name, anchor_item["sceneItemId"]).scene_item_transform
            slots = self._compute_gacha_slots(anchor_transform, min(len(pulled_gachas), 5))
            timestamp = int(time.time() * 1000)
            slot_pairs = list(zip(slots, pulled_gachas))
            batch_size = len(slot_pairs)
            prepared_entries: list[dict[str, typing.Any]] = []
            for idx, (slot, gacha) in enumerate(slot_pairs):
                try:
                    entry = await self._prepare_gacha_entry(scene_name, slot, gacha, idx, timestamp, batch_size)
                except Exception as entry_exc:
                    print(f"Failed to stage gacha pull {idx + 1}: {entry_exc}")
                    continue
                try:
                    entry["name_entry"] = await self._spawn_name_label(scene_name, entry)
                except Exception as name_exc:
                    print(f"Unable to spawn gacha name label: {name_exc}")
                try:
                    entry["level_entry"] = await self._spawn_level_label(scene_name, entry)
                except Exception as level_exc:
                    print(f"Unable to spawn gacha level label: {level_exc}")
                try:
                    await self._update_label_positions(scene_name, entry, entry["start_transform"])
                except Exception as label_position_exc:
                    print(f"Unable to align gacha labels: {label_position_exc}")
                prepared_entries.append(entry)
            if not prepared_entries:
                raise RuntimeError("No gacha entries could be prepared for animation.")
            ordered_entries = sorted(prepared_entries, key=lambda entry: entry["slot"]["order"])
            tasks = []
            for order_idx, entry in enumerate(ordered_entries):
                delay = order_idx * self.GACHA_CARD_STAGGER
                tasks.append(asyncio.create_task(self._animate_single_gacha(scene_name, entry, delay)))
            if tasks:
                await asyncio.gather(*tasks)
            await asyncio.sleep(self.GACHA_BATCH_HOLD_SECONDS)
            await self._fade_and_cleanup(scene_name, prepared_entries)
        except Exception as exc:
            print(f"Gacha animation failed ({exc}). Falling back to legacy logging output.")
            self.animate_gacha_pulls_old(twitch_user_id, number_of_pulls, pulled_gachas)

    async def _animate_single_gacha(
        self,
        scene_name: str,
        entry: dict[str, typing.Any],
        start_delay: float,
    ) -> None:
        await asyncio.sleep(max(0.0, start_delay))
        start = entry["start_transform"]
        target = entry["target_transform"]
        steps = max(1, self.GACHA_CARD_RISE_STEPS)
        silhouette_filter = entry.get("silhouette_filter")
        if silhouette_filter:
            await self._update_silhouette_filter(entry["image_input"], silhouette_filter, 1.0)
        if not entry.get("is_multi") and self.GACHA_SINGLE_SILHOUETTE_DELAY > 0:
            await asyncio.sleep(self.GACHA_SINGLE_SILHOUETTE_DELAY)
        for step in range(steps):
            ratio = (step + 1) / steps
            eased = self._ease_out_back(ratio)
            current_y = start["positionY"] + (target["positionY"] - start["positionY"]) * eased
            current_scale = start["scaleX"] + (target["scaleX"] - start["scaleX"]) * eased
            transform = {
                "positionX": target["positionX"],
                "positionY": current_y,
                "scaleX": current_scale,
                "scaleY": current_scale,
                "rotation": 0.0,
            }
            await self._set_scene_item_transform(scene_name, entry["image_item_id"], transform)
            if silhouette_filter:
                silhouette_strength = max(0.0, 1.0 - eased)
                await self._update_silhouette_filter(entry["image_input"], silhouette_filter, silhouette_strength)
            if entry.get("name_entry") or entry.get("level_entry"):
                await self._update_label_positions(scene_name, entry, transform)
            await asyncio.sleep(self.GACHA_CARD_FRAME_DELAY)
        await self._set_scene_item_transform(scene_name, entry["image_item_id"], target)
        if silhouette_filter:
            await self._update_silhouette_filter(entry["image_input"], silhouette_filter, 0.0)
        if entry.get("name_entry") or entry.get("level_entry"):
            await self._update_label_positions(scene_name, entry, target, persist=True)
        entry["current_transform"] = target
        if entry.get("level_entry"):
            await self._animate_level_badge(scene_name, entry)

    def _compute_gacha_slots(
        self,
        anchor_transform: dict[str, typing.Any],
        count: int,
    ) -> list[dict[str, float]]:
        count = max(1, min(5, count))
        metrics = self._extract_anchor_metrics(anchor_transform)
        base_x = metrics["center_x"]
        debug_print(
            "OBSWebsocketsManager",
            (
                "Gacha anchor metrics -> center_x={:.2f}, center_y={:.2f}, width={:.2f}, height={:.2f}, alignment={}"
            ).format(
                metrics["center_x"],
                metrics["center_y"],
                metrics["width"],
                metrics["height"],
                metrics.get("alignment"),
            ),
        )
        s = self.GACHA_HORIZONTAL_SPACING
        layouts = {
            1: [0.0],
            2: [-0.8 * s, 0.8 * s],
            3: [-s, 0.0, s],
            4: [-1.5 * s, -0.5 * s, 0.5 * s, 1.5 * s],
            5: [-2.0 * s, -s, 0.0, s, 2.0 * s],
        }
        offsets = layouts.get(count, layouts[5])[:count]
        slots: list[dict[str, float]] = []
        for order, offset in enumerate(offsets):
            center_x = base_x + offset
            slots.append(
                {
                    "order": order,
                    "center_x": center_x,
                    "anchor_center_y": metrics["center_y"],
                    "anchor_half_height": metrics["height"] / 2.0,
                }
            )
            debug_print(
                "OBSWebsocketsManager",
                f"Slot {order}: center_x={center_x:.2f} anchor_center_y={metrics['center_y']:.2f} half_height={metrics['height']/2.0:.2f}",
            )
        return slots

    async def _prepare_gacha_entry(
        self,
        scene_name: str,
        slot: dict[str, float],
        gacha: dict,
        index: int,
        timestamp: int,
        batch_size: int,
    ) -> dict[str, typing.Any]:
        image_path = gacha.get("image_path")
        if not image_path:
            raise ValueError("Missing image_path for gacha pull.")
        abs_path = os.path.abspath(image_path)
        if not os.path.exists(abs_path):
            raise FileNotFoundError(f"Gacha image not found at {abs_path}.")
        input_name = f"GachaPull_{timestamp}_{index}"
        scene_item_id = await self._create_input(
            scene_name,
            input_name,
            "image_source",
            {"file": abs_path},
            enabled=False,
        )
        image_width, image_height = self._get_image_dimensions(abs_path)
        target_scale = self._resolve_card_scale(image_width, image_height)
        multi_spawn = batch_size > 1
        start_ratio = self.GACHA_CARD_MULTI_START_RATIO if multi_spawn else self.GACHA_CARD_START_SCALE_RATIO
        ratio = max(0.0, float(start_ratio))
        start_scale = max(target_scale * ratio, self.GACHA_CARD_MIN_START_SCALE)
        final_dimensions = {
            "width": image_width * target_scale,
            "height": image_height * target_scale,
        }
        card_center_x = slot["center_x"]
        card_height = final_dimensions["height"]
        anchor_center_y = slot["anchor_center_y"]
        anchor_half = slot["anchor_half_height"] or (self.GACHA_CARD_TARGET_SIZE / 2)
        offset = anchor_half + (card_height / 2) + self.GACHA_ANCHOR_GAP + self.GACHA_ANCHOR_BUFFER
        target_center_y = anchor_center_y - offset
        # Spawn cards at the anchor's Y level before animating upward to their final slot.
        start_center_y = anchor_center_y
        start_height = image_height * start_scale
        start_position_y = start_center_y - (start_height / 2.0)
        start_transform = self._build_transform(
            card_center_x,
            start_position_y,
            start_scale,
            alignment=self.GACHA_CARD_ALIGNMENT,
        )
        target_transform = self._build_transform(
            card_center_x,
            target_center_y,
            target_scale,
            alignment=self.GACHA_CARD_ALIGNMENT,
        )
        anchor_top = anchor_center_y - anchor_half
        card_bottom = target_center_y + (card_height / 2)
        debug_print(
            "OBSWebsocketsManager",
            (
                "Card clearance -> anchor_top={:.1f}, card_bottom={:.1f}, gap={:.1f}"
            ).format(anchor_top, card_bottom, max(0.0, anchor_top - card_bottom)),
        )
        debug_print(
            "OBSWebsocketsManager",
            f"Prepared gacha entry (w={final_dimensions['width']:.1f}, h={final_dimensions['height']:.1f}) targeting center=({card_center_x:.1f},{target_center_y:.1f})",
        )
        await self._set_scene_item_transform(scene_name, scene_item_id, start_transform)
        await self._set_scene_item_enabled(scene_name, scene_item_id, True)
        silhouette_filter = await self._ensure_silhouette_filter(input_name)
        if silhouette_filter:
            await self._update_silhouette_filter(input_name, silhouette_filter, 1.0)
        return {
            "gacha": gacha,
            "slot": slot,
            "image_input": input_name,
            "image_item_id": scene_item_id,
            "start_transform": start_transform,
            "target_transform": target_transform,
            "final_dimensions": final_dimensions,
            "target_scale": target_scale,
            "silhouette_filter": silhouette_filter,
            "name_entry": None,
            "level_entry": None,
            "is_multi": multi_spawn,
        }

    async def _create_input(
        self,
        scene_name: str,
        input_name: str,
        input_kind: str,
        input_settings: dict,
        *,
        enabled: bool = True,
    ) -> int:
        payload = {
            "sceneName": scene_name,
            "inputName": input_name,
            "inputKind": input_kind,
            "inputSettings": input_settings,
            "sceneItemEnabled": enabled,
        }
        response = await self._obs_request("CreateInput", payload, raw=True)
        scene_item_id = None
        if response:
            if isinstance(response, dict):
                scene_item_id = response.get("sceneItemId") or response.get("sceneItemId")
            else:
                scene_item_id = getattr(response, "sceneItemId", None)
        if scene_item_id is None:
            try:
                scene_items = await asyncio.to_thread(self.ws.get_scene_item_list, scene_name)
                for item in scene_items.scene_items:
                    if item.get("sourceName") == input_name:
                        scene_item_id = item.get("sceneItemId")
                        break
            except Exception as lookup_exc:
                print(f"CreateInput fallback lookup failed for {input_name}: {lookup_exc}")
        if scene_item_id is None:
            raise RuntimeError(f"OBS did not return a sceneItemId for '{input_name}'.")
        return scene_item_id

    async def _set_scene_item_transform(self, scene_name: str, scene_item_id: int, transform: dict) -> None:
        payload = {
            "sceneName": scene_name,
            "sceneItemId": scene_item_id,
            "sceneItemTransform": transform,
        }
        await self._obs_request("SetSceneItemTransform", payload)

    async def _set_scene_item_enabled(self, scene_name: str, scene_item_id: int, enabled: bool) -> None:
        payload = {
            "sceneName": scene_name,
            "sceneItemId": scene_item_id,
            "sceneItemEnabled": enabled,
        }
        await self._obs_request("SetSceneItemEnabled", payload)

    async def _set_input_settings(self, input_name: str, settings: dict) -> None:
        payload = {
            "inputName": input_name,
            "inputSettings": settings,
            "overlay": False,
        }
        await self._obs_request("SetInputSettings", payload)

    async def _remove_input(self, input_name: str) -> None:
        await self._obs_request("RemoveInput", {"inputName": input_name})

    async def _ensure_silhouette_filter(self, source_name: str) -> typing.Optional[str]:
        filter_name = f"{source_name}_Silhouette"
        settings = {
            "multiply_enabled": True,
            "color_multiply": int(self.GACHA_SILHOUETTE_COLOR_BLACK),
        }
        payload = {
            "sourceName": source_name,
            "filterName": filter_name,
            "filterKind": "color_filter_v2",
            "filterSettings": settings,
            "filterEnabled": True,
        }
        try:
            await self._obs_request("CreateSourceFilter", payload, raw=True)
        except Exception as exc:
            if "already exists" not in str(exc):
                print(f"Unable to add silhouette filter to {source_name}: {exc}")
                return None
        return filter_name

    async def _update_silhouette_filter(self, source_name: str, filter_name: str, strength: float) -> None:
        if not filter_name:
            return
        settings = {
            "multiply_enabled": True,
            "color_multiply": int(self._build_silhouette_color_value(strength)),
        }
        await self._set_filter_settings(source_name, filter_name, settings)

    async def _set_filter_settings(self, source_name: str, filter_name: str, settings: dict) -> None:
        payload = {
            "sourceName": source_name,
            "filterName": filter_name,
            "filterSettings": settings,
        }
        await self._obs_request("SetSourceFilterSettings", payload)

    async def _spawn_name_label(self, scene_name: str, entry: dict[str, typing.Any]) -> typing.Optional[dict[str, typing.Any]]:
        formatted_name = self._format_gacha_name(entry["gacha"].get("name"))
        input_name = f"{entry['image_input']}_Name"
        settings = {
            "text": formatted_name,
            "font": {"face": "Segoe UI", "style": "Bold", "size": 72},
            "color1": 0xFFFFFFFF,
            "outline": True,
        }
        scene_item_id = await self._create_input(scene_name, input_name, "text_ft2_source_v2", settings, enabled=False)
        transform = self._compute_name_transform(entry)
        await self._set_scene_item_transform(scene_name, scene_item_id, transform)
        await self._set_scene_item_enabled(scene_name, scene_item_id, True)
        return {"input_name": input_name, "scene_item_id": scene_item_id, "transform": transform}

    async def _spawn_level_label(self, scene_name: str, entry: dict[str, typing.Any]) -> typing.Optional[dict[str, typing.Any]]:
        start_level_raw = int(entry["gacha"].get("level") or 0)
        start_level_display = min(99, max(0, start_level_raw))
        entry["gacha"]["display_level"] = start_level_display
        prefix_name = f"{entry['image_input']}_LevelPrefix"
        number_name = f"{entry['image_input']}_LevelValue"
        created_inputs: list[str] = []
        try:
            prefix_settings = {
                "text": "Lvl.",
                "font": {
                    "face": self.GACHA_LEVEL_FONT_FACE,
                    "style": self.GACHA_LEVEL_FONT_STYLE,
                    "size": self.GACHA_LEVEL_FONT_SIZE,
                },
                "color1": self.GACHA_LEVEL_COLOR_RED,
                "outline": True,
            }
            prefix_id = await self._create_input(scene_name, prefix_name, "text_ft2_source_v2", prefix_settings, enabled=False)
            created_inputs.append(prefix_name)

            number_settings = {
                "text": str(start_level_display),
                "font": {
                    "face": self.GACHA_LEVEL_FONT_FACE,
                    "style": self.GACHA_LEVEL_FONT_STYLE,
                    "size": self.GACHA_LEVEL_FONT_SIZE,
                },
                "color1": self.GACHA_LEVEL_COLOR_RED,
                "outline": True,
            }
            number_id = await self._create_input(scene_name, number_name, "text_ft2_source_v2", number_settings, enabled=False)
            created_inputs.append(number_name)
        except Exception as creation_exc:
            for input_name in created_inputs:
                try:
                    await self._remove_input(input_name)
                except Exception:
                    pass
            raise
        prefix_transform, number_transform = self._compute_level_transforms(entry)

        await self._set_scene_item_transform(scene_name, prefix_id, prefix_transform)
        await self._set_scene_item_transform(scene_name, number_id, number_transform)
        await self._set_scene_item_enabled(scene_name, prefix_id, True)
        await self._set_scene_item_enabled(scene_name, number_id, True)

        return {
            "prefix": {
                "input_name": prefix_name,
                "scene_item_id": prefix_id,
                "transform": prefix_transform,
                "text": prefix_settings["text"],
                "font_face": prefix_settings["font"]["face"],
                "font_style": prefix_settings["font"]["style"],
                "font_size": int(prefix_settings["font"]["size"]),
            },
            "number": {
                "input_name": number_name,
                "scene_item_id": number_id,
                "transform": number_transform,
                "text": number_settings["text"],
                "font_face": number_settings["font"]["face"],
                "font_style": number_settings["font"]["style"],
                "font_size": int(number_settings["font"]["size"]),
            },
        }

    async def _update_label_positions(
        self,
        scene_name: str,
        entry: dict[str, typing.Any],
        card_transform: dict[str, typing.Any] | None,
        *,
        persist: bool = False,
    ) -> None:
        if not card_transform:
            card_transform = entry.get("target_transform")
        if not card_transform:
            return
        name_entry = entry.get("name_entry")
        level_entry = entry.get("level_entry")
        if name_entry:
            name_transform = self._compute_name_transform(entry, card_transform)
            await self._set_scene_item_transform(scene_name, name_entry["scene_item_id"], name_transform)
            if persist:
                name_entry["transform"] = dict(name_transform)
        if level_entry:
            prefix_entry = level_entry.get("prefix")
            number_entry = level_entry.get("number")
            prefix_override = prefix_entry.get("scale_override") if prefix_entry else None
            number_override = number_entry.get("scale_override") if number_entry else None
            layout = self._build_level_layout(
                entry,
                card_transform,
                prefix_scale_override=prefix_override,
                number_scale_override=number_override,
                level_entry=level_entry,
            )
            prefix_transform = layout["prefix_transform"]
            number_transform = layout["number_transform"]
            number_metrics = layout.get("number_metrics") or {}
            anchor_left_mid = layout.get("number_anchor")
            if prefix_entry:
                await self._set_scene_item_transform(scene_name, prefix_entry["scene_item_id"], prefix_transform)
                if persist:
                    prefix_entry["transform"] = dict(prefix_transform)
            if number_entry:
                await self._set_scene_item_transform(scene_name, number_entry["scene_item_id"], number_transform)
                if persist:
                    number_entry["transform"] = dict(number_transform)
                    width_rest = number_metrics.get("width") if number_metrics else None
                    height_rest = number_metrics.get("height") if number_metrics else None
                    if width_rest is not None:
                        number_entry["rest_width"] = width_rest
                    if height_rest is not None:
                        number_entry["rest_height"] = height_rest
                effective_anchor = anchor_left_mid
                if not effective_anchor:
                    height_for_anchor = (number_metrics or {}).get("height")
                    if height_for_anchor is None:
                        height_for_anchor = number_entry.get("rest_height")
                    if height_for_anchor is None:
                        height_for_anchor = self._fallback_label_dimension(
                            "y",
                            False,
                            target_scale=number_transform["scaleY"],
                            text=self._resolve_number_text(entry, number_entry),
                        )
                    effective_anchor = {
                        "x": number_transform["positionX"],
                        "y": number_transform["positionY"] + (height_for_anchor / 2.0),
                    }
                number_entry["anchor_left_mid"] = dict(effective_anchor)

    async def _animate_level_badge(
        self,
        scene_name: str,
        entry: dict[str, typing.Any],
    ) -> None:
        level_entry = entry.get("level_entry")
        if not level_entry:
            return
        number_entry = level_entry.get("number")
        if not number_entry:
            return
        gacha = entry.get("gacha") or {}
        raw_level = int(gacha.get("level") or 0)
        start_display = gacha.get("display_level")
        if start_display is None:
            start_display = min(99, max(0, raw_level))
        start_display = int(start_display)
        final_display_str: str
        if start_display >= 99:
            final_display_str = "MAX"
        else:
            final_display_str = str(min(99, start_display + 1))
        steps_up = 10
        steps_down = 10
        card_transform = entry.get("current_transform") or entry.get("target_transform")
        number_entry["scale_override"] = self.GACHA_LEVEL_FINAL_SCALE
        _, computed_number_transform = self._compute_level_transforms(
            entry,
            card_transform,
            number_scale_override=number_entry["scale_override"],
            level_entry=level_entry,
        )
        rest_transform = dict(computed_number_transform)
        if self.GACHA_LEVEL_INITIAL_HOLD > 0:
            await asyncio.sleep(self.GACHA_LEVEL_INITIAL_HOLD)
        await self._set_input_settings(
            number_entry["input_name"],
            {
                "text": final_display_str,
                "color1": self.GACHA_LEVEL_COLOR_GREEN,
                "font": {
                    "face": self.GACHA_LEVEL_FONT_FACE,
                    "style": self.GACHA_LEVEL_FONT_STYLE,
                    "size": self.GACHA_LEVEL_FONT_SIZE,
                },
            },
        )
        await self._set_scene_item_transform(scene_name, number_entry["scene_item_id"], rest_transform)
        number_entry["transform"] = dict(rest_transform)
        number_entry["text"] = final_display_str
        width_rest = number_entry.get("rest_width")
        height_rest = number_entry.get("rest_height")
        if width_rest is None:
            base_width = float(number_entry.get("width") or 0.0)
            width_rest = base_width if base_width > 0.0 else self._fallback_label_dimension(
                "x",
                False,
                target_scale=rest_transform["scaleX"],
                text=final_display_str,
            )
        if height_rest is None:
            base_height = float(number_entry.get("height") or 0.0)
            height_rest = base_height if base_height > 0.0 else self._fallback_label_dimension(
                "y",
                False,
                target_scale=rest_transform["scaleY"],
                text=final_display_str,
            )
        anchor = number_entry.get("anchor_left_mid") or {}
        anchor_x = anchor.get("x")
        anchor_y = anchor.get("y")
        if anchor_x is None:
            anchor_x = rest_transform["positionX"]
        if anchor_y is None:
            anchor_y = rest_transform["positionY"] + (height_rest / 2.0)
        number_entry["rest_width"] = width_rest
        number_entry["rest_height"] = height_rest
        number_entry["anchor_left_mid"] = {"x": anchor_x, "y": anchor_y}
        peak = max(1.0, self.GACHA_LEVEL_POP_SCALE)
        base_transform = dict(rest_transform)
        for step in range(steps_up):
            progress = (step + 1) / steps_up
            multiplier = 1.0 + (peak - 1.0) * progress
            await self._apply_left_mid_scaled_transform(
                scene_name,
                number_entry["scene_item_id"],
                base_transform,
                multiplier,
                anchor_x=anchor_x,
                anchor_y=anchor_y,
                base_width=width_rest,
                base_height=height_rest,
            )
            await asyncio.sleep(self.GACHA_LEVEL_FRAME_DELAY)
        for step in range(steps_down):
            progress = (step + 1) / steps_down
            multiplier = peak - (peak - 1.0) * progress
            await self._apply_left_mid_scaled_transform(
                scene_name,
                number_entry["scene_item_id"],
                base_transform,
                multiplier,
                anchor_x=anchor_x,
                anchor_y=anchor_y,
                base_width=width_rest,
                base_height=height_rest,
            )
            await asyncio.sleep(self.GACHA_LEVEL_FRAME_DELAY)
        await self._set_scene_item_transform(scene_name, number_entry["scene_item_id"], rest_transform)

    async def _apply_scaled_transform(
        self,
        scene_name: str,
        scene_item_id: int,
        base_transform: dict,
        multiplier: float,
    ) -> None:
        multiplier = max(0.0, multiplier)
        transform = dict(base_transform)
        transform["scaleX"] = base_transform["scaleX"] * multiplier
        transform["scaleY"] = base_transform["scaleY"] * multiplier
        await self._set_scene_item_transform(scene_name, scene_item_id, transform)

    async def _apply_center_scaled_transform(
        self,
        scene_name: str,
        scene_item_id: int,
        base_transform: dict,
        multiplier: float,
        *,
        center_x: float | None,
        center_y: float | None,
        base_width: float | None,
        base_height: float | None,
    ) -> None:
        measurements_available = (
            center_x is not None
            and center_y is not None
            and base_width is not None
            and base_height is not None
            and base_width > 0.0
            and base_height > 0.0
        )
        if not measurements_available:
            await self._apply_scaled_transform(scene_name, scene_item_id, base_transform, multiplier)
            return
        constrained_multiplier = max(0.0, multiplier)
        new_width = base_width * constrained_multiplier
        new_height = base_height * constrained_multiplier
        transform = dict(base_transform)
        transform["scaleX"] = base_transform["scaleX"] * constrained_multiplier
        transform["scaleY"] = base_transform["scaleY"] * constrained_multiplier
        transform["positionX"] = center_x - (new_width / 2.0)
        transform["positionY"] = center_y - (new_height / 2.0)
        await self._set_scene_item_transform(scene_name, scene_item_id, transform)

    async def _apply_left_mid_scaled_transform(
        self,
        scene_name: str,
        scene_item_id: int,
        base_transform: dict,
        multiplier: float,
        *,
        anchor_x: float | None,
        anchor_y: float | None,
        base_width: float | None,
        base_height: float | None,
    ) -> None:
        measurements_available = (
            anchor_x is not None
            and anchor_y is not None
            and base_width is not None
            and base_height is not None
            and base_width > 0.0
            and base_height > 0.0
        )
        if not measurements_available:
            await self._apply_center_scaled_transform(scene_name, scene_item_id, base_transform, multiplier)
            return
        constrained_multiplier = max(0.0, multiplier)
        new_width = base_width * constrained_multiplier
        new_height = base_height * constrained_multiplier
        transform = dict(base_transform)
        transform["scaleX"] = base_transform["scaleX"] * constrained_multiplier
        transform["scaleY"] = base_transform["scaleY"] * constrained_multiplier
        transform["positionX"] = anchor_x
        transform["positionY"] = anchor_y - (new_height / 2.0)
        await self._set_scene_item_transform(scene_name, scene_item_id, transform)

    async def _fade_and_cleanup(self, scene_name: str, entries: list[dict[str, typing.Any]]) -> None:
        if not entries:
            return
        steps = max(1, self.GACHA_FADE_STEPS)
        for step in range(steps):
            factor = max(0.0, 1.0 - (step + 1) / steps)
            for entry in entries:
                await self._apply_scaled_transform(scene_name, entry["image_item_id"], entry["target_transform"], factor)
                if entry.get("name_entry"):
                    await self._apply_scaled_transform(scene_name, entry["name_entry"]["scene_item_id"], entry["name_entry"]["transform"], factor)
                level_entry = entry.get("level_entry")
                if level_entry:
                    for label in level_entry.values():
                        await self._apply_scaled_transform(scene_name, label["scene_item_id"], label["transform"], factor)
            await asyncio.sleep(self.GACHA_CARD_FRAME_DELAY)
        cleanup_tasks = []
        for entry in entries:
            cleanup_tasks.append(self._remove_input(entry["image_input"]))
            if entry.get("name_entry"):
                cleanup_tasks.append(self._remove_input(entry["name_entry"]["input_name"]))
            level_entry = entry.get("level_entry")
            if level_entry:
                for label in level_entry.values():
                    cleanup_tasks.append(self._remove_input(label["input_name"]))
        if cleanup_tasks:
            await asyncio.gather(*cleanup_tasks, return_exceptions=True)

    @staticmethod
    def _format_gacha_name(raw: typing.Any) -> str:
        if not raw:
            return "Unknown"
        return str(raw).replace("_", " ").title()

    @staticmethod
    def _ease_out_back(value: float) -> float:
        c1 = 1.70158
        c3 = c1 + 1
        t = value - 1
        return 1 + c3 * (t ** 3) + c1 * (t ** 2)

    def _build_silhouette_color_value(self, strength: float) -> int:
        clamped = max(0.0, min(1.0, strength))
        channel = int(255 * (1.0 - clamped))
        channel = max(0, min(255, channel))
        alpha = 0xFF
        return (alpha << 24) | (channel << 16) | (channel << 8) | channel

    def _compute_name_transform(
        self,
        entry: dict[str, typing.Any],
        transform_override: dict[str, typing.Any] | None = None,
    ) -> dict[str, float]:
        extents = self._resolve_card_extents(entry, transform_override)
        scale_ratio = self._resolve_scale_ratio(entry, transform_override)
        gap = self.GACHA_NAME_ABOVE_GAP * scale_ratio
        name_y = extents["top"] - gap
        scale = self.GACHA_NAME_SCALE * scale_ratio
        return self._build_transform(
            extents["center_x"],
            name_y,
            scale,
            alignment=self.GACHA_NAME_ALIGNMENT,
        )

    def _compute_level_transforms(
        self,
        entry: dict[str, typing.Any],
        transform_override: dict[str, typing.Any] | None = None,
        *,
        prefix_scale_override: float | None = None,
        number_scale_override: float | None = None,
        level_entry: dict[str, typing.Any] | None = None,
    ) -> tuple[dict[str, float], dict[str, float]]:
        layout = self._build_level_layout(
            entry,
            transform_override,
            prefix_scale_override=prefix_scale_override,
            number_scale_override=number_scale_override,
            level_entry=level_entry,
        )
        return layout["prefix_transform"], layout["number_transform"]

    def _build_level_layout(
        self,
        entry: dict[str, typing.Any],
        transform_override: dict[str, typing.Any] | None = None,
        *,
        prefix_scale_override: float | None = None,
        number_scale_override: float | None = None,
        level_entry: dict[str, typing.Any] | None = None,
    ) -> dict[str, typing.Any]:
        extents = self._resolve_card_extents(entry, transform_override)
        scale_ratio = self._resolve_scale_ratio(entry, transform_override)
        base_scale = self.GACHA_LEVEL_SCALE * scale_ratio
        prefix_scale = base_scale if prefix_scale_override is None else prefix_scale_override * scale_ratio
        number_scale = base_scale if number_scale_override is None else number_scale_override * scale_ratio
        top_right_x = extents["right"]
        anchor_offset = self.GACHA_LEVEL_NUMBER_OFFSET_X * scale_ratio
        number_left_x = top_right_x + anchor_offset
        prefix_entry = level_entry.get("prefix") if level_entry else None
        number_entry = level_entry.get("number") if level_entry else None
        prefix_text = self._resolve_label_text(prefix_entry, default_text="Lvl.")
        number_text = self._resolve_number_text(entry, number_entry)
        prefix_height = self._estimate_label_dimension(
            prefix_entry,
            "y",
            prefix_scale,
            text=prefix_text,
            is_prefix=True,
        )
        number_height = self._estimate_label_dimension(
            number_entry,
            "y",
            number_scale,
            text=number_text,
            is_prefix=False,
        )
        prefix_center_y = extents["top"] - (self.GACHA_LEVEL_VERTICAL_OFFSET * scale_ratio) + (prefix_height / 2.0)
        prefix_top_y = prefix_center_y - (prefix_height / 2.0)
        number_top_y = prefix_center_y - (number_height / 2.0)
        prefix_transform = self._build_transform(
            top_right_x,
            prefix_top_y,
            prefix_scale,
            alignment=self.GACHA_LEVEL_PREFIX_ALIGNMENT,
        )
        number_transform = self._build_transform(
            number_left_x,
            number_top_y,
            number_scale,
            alignment=self.GACHA_LEVEL_NUMBER_ALIGNMENT,
        )
        number_width = self._estimate_label_dimension(
            number_entry,
            "x",
            number_scale,
            text=number_text,
            is_prefix=False,
        )
        number_anchor = {
            "x": number_left_x,
            "y": prefix_center_y,
        }
        return {
            "prefix_transform": prefix_transform,
            "number_transform": number_transform,
            "number_anchor": number_anchor,
            "number_metrics": {
                "width": number_width,
                "height": number_height,
            },
        }

    def _estimate_label_dimension(
        self,
        label_entry: dict[str, typing.Any] | None,
        axis: str,
        target_scale: float,
        *,
        text: str,
        is_prefix: bool,
    ) -> float:
        axis = axis.lower()
        dim_key = "width" if axis == "x" else "height"
        base_scale_key = "base_scaleX" if axis == "x" else "base_scaleY"
        base_dim = 0.0
        base_scale_value = 0.0
        if label_entry:
            base_dim = float(label_entry.get(dim_key) or 0.0)
            base_scale_value = float(label_entry.get(base_scale_key) or 0.0)
        if base_dim > 0.0 and base_scale_value > 0.0 and target_scale > 0.0:
            return base_dim * (target_scale / base_scale_value)
        face, style, size = self._resolve_label_font(label_entry, is_prefix=is_prefix)
        width, height = self._measure_text_bounds(text or "", face, style, size)
        base_value = width if axis == "x" else height
        return base_value * target_scale

    def _resolve_label_font(
        self,
        label_entry: dict[str, typing.Any] | None,
        *,
        is_prefix: bool,
    ) -> tuple[str, str, int]:
        face = (label_entry or {}).get("font_face") or self.GACHA_LEVEL_FONT_FACE
        style = (label_entry or {}).get("font_style") or self.GACHA_LEVEL_FONT_STYLE
        size = int((label_entry or {}).get("font_size") or self.GACHA_LEVEL_FONT_SIZE)
        return face, style, size

    def _resolve_label_text(self, label_entry: dict[str, typing.Any] | None, default_text: str) -> str:
        if label_entry:
            text = label_entry.get("text")
            if text is not None:
                return str(text)
        return default_text

    def _resolve_number_text(self, entry: dict[str, typing.Any], number_entry: dict[str, typing.Any] | None = None) -> str:
        if number_entry and number_entry.get("text"):
            return str(number_entry["text"])
        gacha = entry.get("gacha") or {}
        display_level = gacha.get("display_level")
        if display_level is None:
            display_level = gacha.get("level")
        try:
            display_level_int = int(display_level)
        except Exception:
            display_level_int = 0
        if display_level_int >= 99:
            return "MAX"
        return str(max(0, min(999, display_level_int)))

    def _measure_text_bounds(
        self,
        text: str,
        font_face: str,
        font_style: str,
        font_size: int,
    ) -> tuple[float, float]:
        cache_key = (text, font_face, font_style, int(font_size))
        if cache_key in self._text_bounds_cache:
            return self._text_bounds_cache[cache_key]
        font = self._load_font(font_face, font_style, font_size)
        if font is None:
            font = ImageFont.load_default()
        bounds = font.getbbox(text or " ")
        width = max(1.0, float(bounds[2] - bounds[0]))
        height = max(1.0, float(bounds[3] - bounds[1]))
        self._text_bounds_cache[cache_key] = (width, height)
        return width, height

    def _load_font(self, font_face: str, font_style: str, font_size: int) -> ImageFont.FreeTypeFont | None:
        cache_key = (font_face.lower(), font_style.lower(), int(font_size))
        cached = self._font_cache.get(cache_key)
        if cached is not None:
            return cached
        candidates = self._resolve_font_candidates(font_face, font_style)
        for candidate in candidates:
            try:
                font = ImageFont.truetype(candidate, int(font_size))
                self._font_cache[cache_key] = font
                return font
            except Exception:
                continue
        try:
            font = ImageFont.truetype(font_face, int(font_size))
            self._font_cache[cache_key] = font
            return font
        except Exception:
            return None

    def _resolve_font_candidates(self, font_face: str, font_style: str) -> list[str]:
        font_dir = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        normalized_face = (font_face or "").lower().replace(" ", "")
        normalized_style = (font_style or "").lower()
        candidates: list[str] = []
        if "segoe" in normalized_face:
            if "bold" in normalized_style:
                for name in ("segoeuib.ttf", "seguibl.ttf", "seguibd.ttf"):
                    candidates.append(str(font_dir / name))
            else:
                candidates.append(str(font_dir / "segoeui.ttf"))
        default_name = normalized_face or "segoeui"
        if "bold" in normalized_style and not default_name.endswith("b"):
            default_name = f"{default_name}b"
        candidates.append(str(font_dir / f"{default_name}.ttf"))
        return candidates

    def _fallback_label_dimension(
        self,
        axis: str,
        is_prefix: bool,
        *,
        target_scale: float,
        text: str,
    ) -> float:
        face = self.GACHA_LEVEL_FONT_FACE
        style = self.GACHA_LEVEL_FONT_STYLE
        size = self.GACHA_LEVEL_FONT_SIZE
        width, height = self._measure_text_bounds(text or ("Lvl." if is_prefix else "0"), face, style, size)
        base_value = width if axis.lower() == "x" else height
        return base_value * max(0.0, float(target_scale))

    def _resolve_scale_ratio(
        self,
        entry: dict[str, typing.Any],
        transform_override: dict[str, typing.Any] | None = None,
    ) -> float:
        target_scale = float(entry.get("target_scale") or 1.0)
        if target_scale == 0:
            return 1.0
        reference = transform_override or entry.get("current_transform") or entry.get("target_transform") or {}
        scale_x = float(reference.get("scaleX") or target_scale)
        return max(0.001, scale_x / target_scale)

    def _resolve_card_extents(
        self,
        entry: dict[str, typing.Any],
        transform_override: dict[str, typing.Any] | None = None,
    ) -> dict[str, float]:
        transform = transform_override or entry.get("current_transform") or entry.get("target_transform") or {}
        dims = entry.get("final_dimensions") or {}
        width = float(dims.get("width") or self.GACHA_CARD_TARGET_SIZE)
        height = float(dims.get("height") or self.GACHA_CARD_TARGET_SIZE)
        scale_ratio = self._resolve_scale_ratio(entry, transform_override)
        width *= scale_ratio
        height *= scale_ratio
        alignment = int(transform.get("alignment") or (entry.get("target_transform") or {}).get("alignment") or 0)
        pos_x = float(transform.get("positionX") or 0.0)
        pos_y = float(transform.get("positionY") or 0.0)

        if alignment & 0x1 and not alignment & 0x2:
            left = pos_x
        elif alignment & 0x2 and not alignment & 0x1:
            left = pos_x - width
        else:
            left = pos_x - (width / 2.0)
        right = left + width

        if alignment & 0x4 and not alignment & 0x8:
            top = pos_y
        elif alignment & 0x8 and not alignment & 0x4:
            top = pos_y - height
        else:
            top = pos_y - (height / 2.0)
        bottom = top + height

        center_x = (left + right) / 2.0
        center_y = (top + bottom) / 2.0
        return {
            "left": left,
            "right": right,
            "top": top,
            "bottom": bottom,
            "center_x": center_x,
            "center_y": center_y,
        }


    def _build_transform(
        self,
        position_x: float,
        position_y: float,
        scale: float,
        *,
        rotation: float = 0.0,
        alignment: int | None = None,
    ) -> dict[str, float]:
        transform: dict[str, float] = {
            "positionX": float(position_x),
            "positionY": float(position_y),
            "scaleX": float(scale),
            "scaleY": float(scale),
            "rotation": float(rotation),
        }
        if alignment is not None:
            transform["alignment"] = alignment
        return transform

    def _extract_anchor_metrics(self, transform: dict[str, typing.Any]) -> dict[str, float]:
        pos_x = float(transform.get("positionX", 0.0))
        pos_y = float(transform.get("positionY", 0.0))
        alignment = int(transform.get("alignment") or 0)
        width = self._resolve_dimension(transform, axis="x")
        height = self._resolve_dimension(transform, axis="y")
        half_w = width / 2.0
        half_h = height / 2.0

        # OBS alignment is a bitmask where 1=left, 2=right, 4=top, 8=bottom, 16=center
        align_left = bool(alignment & 0x1)
        align_right = bool(alignment & 0x2)
        align_top = bool(alignment & 0x4)
        align_bottom = bool(alignment & 0x8)
        align_center = bool(alignment & 0x10)

        # Horizontal center
        if align_left and not align_right:
            center_x = pos_x + half_w
        elif align_right and not align_left:
            center_x = pos_x - half_w
        elif align_center:
            center_x = pos_x
        else:
            center_x = pos_x

        # Vertical center
        if align_top and not align_bottom:
            center_y = pos_y + half_h
        elif align_bottom and not align_top:
            center_y = pos_y - half_h
        elif align_center:
            center_y = pos_y
        else:
            center_y = pos_y

        return {
            "center_x": center_x,
            "center_y": center_y,
            "top_y": center_y - half_h,
            "bottom_y": center_y + half_h,
            "width": width,
            "height": height,
            "alignment": alignment,
        }

    def _resolve_dimension(self, transform: dict[str, typing.Any], axis: str) -> float:
        axis = axis.lower()
        if axis not in {"x", "y"}:
            axis = "y"
        dim_key = "height" if axis == "y" else "width"
        source_key = "sourceHeight" if axis == "y" else "sourceWidth"
        bounds_key = "boundsHeight" if axis == "y" else "boundsWidth"
        scale_key = "scaleY" if axis == "y" else "scaleX"
        value = self._dict_get(transform, dim_key)
        if value:
            return float(value)
        source = float(self._dict_get(transform, source_key) or 0.0)
        scale = float(self._dict_get(transform, scale_key) or 1.0)
        if source > 0:
            return source * scale
        bounds = float(self._dict_get(transform, bounds_key) or 0.0)
        if bounds > 0:
            return bounds
        return self.GACHA_CARD_TARGET_SIZE

    @staticmethod
    def _dict_get(source: typing.Any, key: str, default: typing.Any = None):
        if hasattr(source, "get"):
            return source.get(key, default)
        return getattr(source, key, default)

    @staticmethod
    def _get_image_dimensions(path: str) -> tuple[float, float]:
        try:
            with Image.open(path) as img:
                return float(img.width), float(img.height)
        except Exception:
            return 1000.0, 1000.0

    def _resolve_card_scale(self, width: float, height: float) -> float:
        base = max(1.0, width, height)
        desired_scale = self.GACHA_CARD_TARGET_SIZE / base
        return max(self.GACHA_CARD_MIN_SCALE, min(self.GACHA_CARD_MAX_SCALE, desired_scale))

    async def _obs_request(self, request_type: str, payload: dict | None = None, raw: bool = False):
        return await asyncio.to_thread(self.ws.send, request_type, payload, raw)
    
    def animate_gacha_pulls_old(self, twitch_user_id: str, number_of_pulls: int, pulled_gachas: list[dict]) -> None:
        """
        Animates the gacha rolls using OBS and displays results. Will animate a max of five rolls simultaneously. 
        If passed more than five rolls, will queue them up in groups of five.
        """
        debug_print("OBSWebsocketsManager", f"Animation not currently implemented.")
        #debug_print("OBSWebsocketsManager", f"Animating {number_of_pulls} gacha pulls for user {twitch_user_id}.")
        if number_of_pulls > 5:
            batches = [pulled_gachas[i:i + 5] for i in range(0, number_of_pulls, 5)]
            for batch in batches:
                #Placeholder code, to animate each batch, instead just print each gacha name, their level, and rarity
                pulls_string = f"Gacha Pulls for user {twitch_user_id}:\n"
                for gacha in batch:
                    name = gacha.get("name", "Unknown")
                    rarity = gacha.get("rarity", "Unknown")
                    level = gacha.get("level", "Unknown")
                    image_path = gacha.get("image_path", "Unknown")
                    pulls_string += f"{name} {rarity}, Lvl: {level})\n"
                print(pulls_string.strip())
                time.sleep(2)  #Wait 2 seconds between batches
        else:
            #Placeholder code, to animate each roll, instead just print each gacha name, their level, and rarity
            for gacha in pulled_gachas:
                name: str = gacha.get("name", "Unknown")
                rarity: str = gacha.get("rarity", "Unknown")
                level_value = gacha.get("level", "Unknown")
                display_level = "MAX" if level_value == 99 else level_value + 1 if isinstance(level_value, int) else level_value
                image_path: str = gacha.get("image_path", "Unknown")
                print(f"Gacha Pull for user {twitch_user_id}:\n{name.title()} {rarity}, lvl: {display_level})")
                time.sleep(2)

    def disconnect(self):
        try:
            if self.ws:
                self.ws.disconnect()
        finally:
            self.connected = False

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
