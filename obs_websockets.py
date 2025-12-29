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
