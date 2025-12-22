"""
Codes for building custom channel point redemptions. Each 2-3 letter code is seperated by :: for sequential ordered actions. If two actions should happen simultaneously, 
they can be placed in the same code segment separated by a ++.
AV: Automatic Voiced Response
AI: AI Generated Voiced Response
API: AI Generated Voiced Response w/ Personality
AC: Automatic Chat Response
IC: AI Generated Chat Response
IPA: AI Generated Chat Response w/ Personality
GM: Generate Meme Image
AU: Play Audio File
AN: Animate Onscreen Element
VO: Voiced Message (uses user input as message)
TO: Timeout (waits specified seconds)

Each code can be at max 10 codes long. The code is stored in the database, and there are 10 input columns, one for each possible segment of the code.
For example, a custom channel point redemption that shows a gun firing and a gunshot sound effect, while also generating an AI voiced response with personality, would have the code:
API::AN::AU and would pull data stored in input1, input2, and input3 columns in the database.
"""

"""
All chat responses can use the following codes:
%user% for the username of the redeemer
%reward% for the name of the reward redeemed
%channel% for the channel name
%viewers% for the current viewer count
%followers% for the current follower count
%subscribers% for the current subscriber count
%title% for the current stream title
%game% for the current game being played
%message% for the message content (if applicable)
%rng% for totally random number
%rng:min-max% for random number between min and max (inclusive)

Example: AV::Hello %user%, thanks for redeeming %reward%!
This would generate an automatic voiced response saying "Hello [username], thanks for redeeming [reward name]!"
"""

"""Example Dictionary representation of a redemption action list:
{"1": {"method": method_reference, "input": "input value from db or user or None"}, 
"2": {"method1": method_reference1, "method2": method_reference2, "input1": "input value from db or user or None", "input2": "input value from db or user or None"}, ...}"""
import asyncio
import inspect
import os
import re
import tempfile

from datetime import datetime
from tools import debug_print, get_random_number, get_reference, set_reference, path_from_app_root
from db import get_custom_reward, get_bit_reward, get_setting
from meme_creator import make_meme
from typing import Literal
from PIL import Image, ImageDraw, ImageFont


USER_INPUT_PLACEHOLDER = "<user_input>"


def _compose_timeout_payload(seconds):
    return {
        "seconds": seconds,
        "target": USER_INPUT_PLACEHOLDER,
    }


CODE_BEHAVIOR = {
    "AV": {"db_inputs": 1},  # Automatic voiced response (prompt text)
    "AI": {"db_inputs": 1},  # AI voiced response prompt
    "API": {"db_inputs": 1},  # AI voiced response w/ personality prompt
    "AC": {"db_inputs": 1},  # Automatic chat response text
    "IC": {"db_inputs": 1},  # AI chat response prompt
    "IPA": {"db_inputs": 1},  # AI chat response w/ personality prompt
    "GM": {"db_inputs": 0},  # Generate meme (no input)
    "AU": {"db_inputs": 1},  # Play audio filename
    "AN": {"db_inputs": 1},  # Animate onscreen element filename
    "WT": {"db_inputs": 1},  # Wait duration
    "VO": {"db_inputs": 0, "compose": lambda _val: USER_INPUT_PLACEHOLDER},  # Viewer message only
    "TO": {"db_inputs": 1, "compose": _compose_timeout_payload},  # Timeout requires seconds + viewer message
    "GS": {"db_inputs": 1},  # Change Gacha Set
    "GP": {"db_inputs": 0},  # Gacha Pull
}

GENERATION_TOKENS = {"AV", "AI", "API", "IC", "IPA", "GM", "VO"}
VOICE_TOKENS = {"AV", "AI", "API", "VO"}
CHAT_TOKENS = {"AC", "IC", "IPA"}
DISPLAY_MEDIA_TOKENS = {"GM", "AN"}
AUDIO_TOKENS = {"AU"}
PREEXECUTION_TOKENS = GENERATION_TOKENS | AUDIO_TOKENS
CHAT_MESSAGE_BUFFER_SECONDS = 1.0
SIMULTANEOUS_MEDIA_STAGGER_SECONDS = 0.5
SIMULTANEOUS_VOICE_STAGGER_SECONDS = 0.35


def _extract_user_input(payload, fallback):
    candidate = None
    try:
        if payload is not None:
            candidate = getattr(payload, "user_input", None)
            if candidate in (None, ""):
                reward = getattr(payload, "reward", None)
                candidate = (
                    getattr(reward, "text", None)
                    if reward is not None else None
                ) or (
                    getattr(reward, "prompt", None)
                    if reward is not None else None
                )
            if candidate in (None, ""):
                message = getattr(payload, "message", None)
                if isinstance(message, str):
                    candidate = message
                elif hasattr(message, "text"):
                    candidate = getattr(message, "text", None)
    except Exception:
        candidate = None
    return candidate if candidate not in (None, "") else fallback


def _resolve_user_value(value, payload, fallback):
    """Resolve '<user_input>' placeholders within nested values."""

    def _resolve_str(text: str):
        if USER_INPUT_PLACEHOLDER not in text:
            return text
        replacement = _extract_user_input(payload, fallback)
        if replacement in (None, ""):
            replacement = fallback
        if text.strip() == USER_INPUT_PLACEHOLDER:
            return replacement
        replacement_str = "" if replacement in (None, "") else str(replacement)
        return text.replace(USER_INPUT_PLACEHOLDER, replacement_str)

    if isinstance(value, str):
        return _resolve_str(value)
    if isinstance(value, dict):
        return {k: _resolve_user_value(v, payload, fallback) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_user_value(item, payload, fallback) for item in value]
    if isinstance(value, tuple):
        return tuple(_resolve_user_value(item, payload, fallback) for item in value)
    return value

def _get_payload_user_text(payload):
    """Return actual viewer-supplied text from payload without falling back to prompts."""

    def _coerce_text(value):
        if isinstance(value, str):
            stripped = value.strip()
            return stripped if stripped else None
        return None

    if payload is None:
        return None

    attr_candidates = ("user_input", "userInput", "input")
    for attr in attr_candidates:
        try:
            candidate = getattr(payload, attr)
        except Exception:
            candidate = None
        text = _coerce_text(candidate)
        if text:
            return text

    # Some payloads expose raw data dicts
    data_obj = None
    try:
        data_obj = getattr(payload, "data", None)
    except Exception:
        data_obj = None
    if isinstance(data_obj, dict):
        for key in ("user_input", "userInput", "input"):
            text = _coerce_text(data_obj.get(key))
            if text:
                return text

    # Fall back to payload.message if available
    message_obj = None
    try:
        message_obj = getattr(payload, "message", None)
    except Exception:
        message_obj = None
    text = _coerce_text(message_obj)
    if text:
        return text

    if hasattr(message_obj, "text"):
        try:
            msg = getattr(message_obj, "text", None)
        except Exception:
            msg = None
        text = _coerce_text(msg)
        if text:
            return text

    return None

class CustomPointRedemptionBuilder():
    _AUDIO_FILE_EXTENSIONS = (".mp3", ".wav", ".ogg", ".flac")
    def __init__(self):
        self.code_behavior = CODE_BEHAVIOR
        self.response_manager = get_reference("ResponseTimer")
        self.event_manager = get_reference("EventManager")
        self.twitch_bot = get_reference("TwitchBot")
        self.elevenlabs_manager = get_reference("ElevenLabsManager")
        self.azure_manager = get_reference("SpeechToTextManager")
        self.assistant = get_reference("AssistantManager")
        self.chatGPT = get_reference("GPTManager")
        self.obs_manager = get_reference("OBSManager")
        self.audio_manager = get_reference("AudioManager")
        self.gacha_handler = get_reference("GachaHandler")
        self.online_database = get_reference("OnlineDatabase")
        self.discord_bot = None
        self.media_dir = path_from_app_root("media")
        self.media_dir.mkdir(exist_ok=True)
        self.images_and_gifs_dir = self.media_dir / "images_and_gifs"
        self.memes_dir = self.media_dir / "memes"
        self.screenshots_dir = self.media_dir / "screenshots"
        self.sounds_dir = self.media_dir / "soundFX"
        self.voice_audio_dir = self.media_dir / "voice_audio"
        self.voice_audio_dir.mkdir(parents=True, exist_ok=True)
        self.voice_overlay_template = self.images_and_gifs_dir / "speaker.png"
        self._overlay_font_dir = path_from_app_root("media", "fonts")
        self.code_decryption_map = {"AV": self.automatic_voiced_response,
                                    "AI": self.ai_generated_voiced_response,
                                    "API": self.ai_generated_voiced_response_personality,
                                    "AC": self.automatic_chat_response,
                                    "IC": self.ai_generated_chat_response,
                                    "IPA": self.ai_generated_chat_response_personality,
                                    "GM": self.generate_meme_image,
                                    "AU": self.play_audio_file,
                                    "AN": self.animate_onscreen_element,
                                    "WT": self.wait_for_seconds,
                                    "VO": self.voiced_message,
                                    "TO": self.timeout
                                    }
        debug_print("CustomBuilder", "CustomPointRedemptionBuilder initialized.")

    def _prepare_input_for_token(self, token: str, inputs: list | None, input_ptr: int) -> tuple:
        behavior = self.code_behavior.get(token.upper(), {})
        needs_db_value = int(behavior.get("db_inputs", 0) or 0)
        value = None
        if needs_db_value > 0:
            if inputs is not None and input_ptr < len(inputs):
                value = inputs[input_ptr]
            input_ptr += 1
        composer = behavior.get("compose")
        if callable(composer):
            try:
                value = composer(value)
            except Exception:
                pass
        return value, input_ptr

    async def build_actions(self, custom_reward: dict | None = None, code: str | None = None, inputs: list | None = None) -> list:
        """Parse a redemption `code` (or a `custom_reward` DB row) into a list of step dictionaries.

        Each returned item represents either a single sequential step:
            {"step": method_ref, "input": inputs[index]}
        or a simultaneous group with multiple numbered entries:
            {"step1": method_ref1, "input1": inputs[i], "step2": method_ref2, "input2": inputs[i+1], ...}

        If `custom_reward` is provided it will be used to extract `code` and `input1..input10`.
        """
        # Normalize inputs and code from provided custom_reward or args
        if custom_reward is not None:
            # support multiple naming variants just in case
            code = custom_reward.get("code") or custom_reward.get("redemption_code") or custom_reward.get("reward_code")
            # gather inputs 1..10
            inputs = [custom_reward.get(f"input{i}") for i in range(1, 11)]

        if code is None:
            return []

        # split into groups separated by '::' — each group can contain one or more codes separated by '++'
        groups = [g.strip() for g in code.split("::") if g is not None and g.strip() != ""]

        steps = []
        input_ptr = 0
        step_counter = 0
        for grp in groups:
            subcodes = [c.strip() for c in grp.split("++") if c is not None and c.strip() != ""]
            if len(subcodes) == 0:
                continue

            if len(subcodes) == 1:
                token = subcodes[0].upper()
                method = self.code_decryption_map.get(token)
                inp, input_ptr = self._prepare_input_for_token(token, inputs, input_ptr)
                step_counter += 1
                steps.append(
                    {
                        "step": method,
                        "input": inp,
                        "token": token,
                        "cache_key": f"step_{step_counter}",
                    }
                )
            else:
                # simultaneous group — create numbered keys step1,input1, step2,input2, ...
                group_entry = {}
                for i, token in enumerate(subcodes, start=1):
                    tok = token.upper()
                    method = self.code_decryption_map.get(tok)
                    inp, input_ptr = self._prepare_input_for_token(tok, inputs, input_ptr)
                    step_counter += 1
                    group_entry[f"step{i}"] = method
                    group_entry[f"input{i}"] = inp
                    group_entry[f"token{i}"] = tok
                    group_entry[f"cache_key{i}"] = f"step_{step_counter}"
                steps.append(group_entry)

        return steps

    def _method_accepts_kwarg(self, method_ref, kw_name: str) -> bool:
        try:
            sig = inspect.signature(method_ref)
        except (TypeError, ValueError):
            return True
        for param in sig.parameters.values():
            if param.kind == inspect.Parameter.VAR_KEYWORD:
                return True
        return kw_name in sig.parameters

    def _token_needs_generation(self, token: str | None) -> bool:
        return bool(token and token.upper() in PREEXECUTION_TOKENS)

    def _get_cached_asset(self, event: dict | None, cache_key: str | None):
        if not event or not cache_key:
            return None
        bucket = event.get("_generated_assets")
        if not isinstance(bucket, dict):
            return None
        return bucket.get(cache_key)

    def _store_cached_asset(self, event: dict | None, cache_key: str | None, data):
        if not event or not cache_key or data is None:
            return
        bucket = event.setdefault("_generated_assets", {})
        bucket[cache_key] = data

    def _entry_contains_chat_token(self, entry: dict | None) -> bool:
        if not isinstance(entry, dict):
            return False
        token = entry.get("token")
        if isinstance(token, str) and token.upper() in CHAT_TOKENS:
            return True
        for key, value in entry.items():
            if key.startswith("token") and isinstance(value, str) and value.upper() in CHAT_TOKENS:
                return True
        return False

    def _normalize_audio_fx_name(self, file_name: str | None) -> str:
        """Strip known audio extensions so AudioManager can locate the asset."""
        if not isinstance(file_name, str):
            return ""
        candidate = file_name.strip()
        if not candidate:
            return ""
        lowered = candidate.lower()
        for ext in self._AUDIO_FILE_EXTENSIONS:
            if lowered.endswith(ext):
                candidate = candidate[: -len(ext)].strip()
                break
        return candidate

    def _voice_duration_for_cache(self, event: dict | None, cache_key: str | None) -> float | None:
        if not event or not cache_key:
            return None
        asset = self._get_cached_asset(event, cache_key)
        if not isinstance(asset, dict):
            return None
        duration_ms = None
        audio_meta = asset.get("audio_meta")
        if isinstance(audio_meta, dict):
            duration_ms = audio_meta.get("duration_ms")
        if duration_ms is None:
            duration_ms = asset.get("duration_ms")
        if duration_ms is None and isinstance(asset.get("duration"), (int, float)):
            duration_ms = float(asset.get("duration")) * 1000.0
        if duration_ms is None:
            return None
        try:
            duration_sec = max(0.0, float(duration_ms) / 1000.0)
        except Exception:
            return None
        return duration_sec

    def _display_name_from_payload(self, payload) -> str:
        username = "Viewer"
        if not payload:
            return username
        try:
            user = payload.user
        except Exception:
            user = None
        if user is not None:
            username = user.display_name
        return str(username)

    def _estimate_voice_overlay_duration(self, audio_path: str | None, message: str | None) -> float:
        duration = None
        if self.audio_manager and audio_path:
            try:
                duration = self.audio_manager._compute_audio_duration(audio_path)
            except Exception:
                duration = None
        if duration is None:
            text = (message or "").strip()
            approx_words = max(1, len(text.split()))
            duration = max(4.0, min(30.0, approx_words * 0.6))
        return float(duration + 0.75)

    async def _start_voiced_overlay(self, payload, message: str, audio_path: str | None):
        manager = self.obs_manager or get_reference("OBSManager")
        if manager is None or not audio_path:
            return None
        self.obs_manager = manager
        username = self._display_name_from_payload(payload)
        overlay_path = await self._render_voice_overlay_image(username, message, payload)
        if not overlay_path:
            return None
        duration = self._estimate_voice_overlay_duration(audio_path, message)
        ready_event = asyncio.Event()
        overlay_task = asyncio.create_task(
            self._run_voice_overlay_task(overlay_path, duration, ready_event)
        )
        return ready_event, overlay_task

    async def _run_voice_overlay_task(self, overlay_path: str, duration: float, ready_event: asyncio.Event | None):
        manager = self.obs_manager or get_reference("OBSManager")
        if manager is None:
            try:
                os.remove(overlay_path)
            except Exception:
                pass
            return
        self.obs_manager = manager
        try:
            object_name = await get_setting("OBS TTS Display Object Name", "TTSDisplay")
        except Exception:
            object_name = "TTSDisplay"
        if not object_name:
            object_name = "TTSDisplay"
        try:
            await manager.display_meme(
                overlay_path,
                is_meme=False,
                duration=duration,
                ready_event=ready_event,
                ready_opacity=0.92,
                object_name_override=object_name,
            )
        finally:
            try:
                os.remove(overlay_path)
            except Exception:
                pass

    async def _render_voice_overlay_image(self, username: str, message: str, payload) -> str | None:
        overlay_text = (message or "").strip()
        payload_text = None
        if payload is not None:
            try:
                payload_text = getattr(payload, "user_input", None)
            except Exception:
                payload_text = None
            if not payload_text:
                try:
                    payload_text = getattr(payload, "message", None)
                except Exception:
                    payload_text = None
        if isinstance(payload_text, str) and payload_text.strip():
            overlay_text = payload_text.strip()

        bits_amount = None
        if payload is not None:
            try:
                bits_amount = getattr(payload, "bits", None)
            except Exception:
                bits_amount = None
            if not bits_amount:
                try:
                    message_obj = getattr(payload, "message", None)
                    bits_amount = getattr(message_obj, "bits", None)
                except Exception:
                    bits_amount = None
        header_text = f"{username or 'Viewer'} says:"
        if bits_amount not in (None, 0):
            try:
                bits_display = int(bits_amount)
            except Exception:
                bits_display = bits_amount
            header_text = f"{username or 'Viewer'} donated {bits_display} bits:"
            overlay_text = re.sub(r"(?i)\\bcheer\\d+\\b", "", overlay_text).strip()

        try:
            return await asyncio.to_thread(
                self._compose_voice_overlay_image,
                username,
                overlay_text,
                header_text,
            )
        except Exception as exc:
            print(f"Failed to compose voice overlay image: {exc}")
            return None

    def _compose_voice_overlay_image(self, username: str, message: str, header_text: str) -> str:
        canvas = None
        width, height = 960, 420
        canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(canvas, "RGBA")
        padding = max(32, canvas.width // 30)

        speaker_path = self.images_and_gifs_dir / "speaker.png"
        icon_bottom = padding
        if speaker_path.exists():
            try:
                with Image.open(speaker_path) as icon_img_src:
                    icon_img = icon_img_src.convert("RGBA")
                max_icon_width = int(canvas.width * 0.4)
                max_icon_height = int(canvas.height * 0.35)
                scale_w = max_icon_width / icon_img.width if icon_img.width else 1.0
                scale_h = max_icon_height / icon_img.height if icon_img.height else 1.0
                scale = min(scale_w, scale_h, 1.0)
                new_w = max(1, int(icon_img.width * scale))
                new_h = max(1, int(icon_img.height * scale))
                resample_attr = getattr(Image, "Resampling", None)
                resample_filter = resample_attr.LANCZOS if resample_attr else getattr(Image, "LANCZOS", Image.BICUBIC)
                icon_resized = icon_img.resize((new_w, new_h), resample=resample_filter)
                icon_x = (canvas.width - new_w) // 2
                icon_y = padding
                shadow_offset = max(2, new_w // 60)
                try:
                    icon_alpha = icon_resized.split()[3]
                except Exception:
                    icon_alpha = None
                if icon_alpha is not None:
                    shadow_image = Image.new("RGBA", icon_resized.size, (255, 255, 255, 160))
                    canvas.paste(shadow_image, (icon_x + shadow_offset, icon_y + shadow_offset), icon_alpha)
                canvas.paste(icon_resized, (icon_x, icon_y), icon_resized)
                icon_bottom = icon_y + new_h
            except Exception:
                icon_bottom = padding

        header_line = header_text or f"{username or 'Viewer'} says:"
        parts = header_line.split(" ", 1)
        username_only = parts[0]
        remainder = f" {parts[1]}" if len(parts) > 1 else ""
        header_len = len(header_line)
        if header_len <= 24:
            header_target = max(36, canvas.width // 22)
        elif header_len <= 48:
            header_target = max(30, canvas.width // 26)
        else:
            header_target = max(26, canvas.width // 30)
        header_font = self._load_overlay_font(header_target, bold=True)
        header_size = getattr(header_font, "size", header_target)
        header_y = icon_bottom + max(12, padding // 3)
        header_width = self._measure_text(draw, header_line, header_font)
        header_x = max(padding, (canvas.width - header_width) / 2)
        shadow_color = (0, 0, 0, 200)
        shadow_offset = max(2, header_target // 18)
        draw.text((header_x + shadow_offset, header_y + shadow_offset), header_line, font=header_font, fill=shadow_color)
        username_width = self._measure_text(draw, username_only, header_font)
        username_color = (70, 125, 255, 255)
        draw.text((header_x, header_y), username_only, font=header_font, fill=username_color)
        draw.text((header_x + username_width, header_y), remainder, font=header_font, fill=(255, 255, 255, 255))

        message_text = (message or "").strip() or "(No message provided)"
        char_count = len(message_text.replace("\n", ""))
        if char_count <= 45:
            body_target = max(34, canvas.width // 24)
            words_per_line = 4
        elif char_count <= 120:
            body_target = max(28, canvas.width // 30)
            words_per_line = 7
        else:
            body_target = max(22, canvas.width // 34)
            words_per_line = 10
        body_font = self._load_overlay_font(body_target)
        body_size = getattr(body_font, "size", body_target)
        available_width = int(canvas.width * 0.88)
        text_y = header_y + header_size + max(14, header_size // 4)
        bottom_padding = padding
        remaining_height = canvas.height - text_y - bottom_padding
        approx_line_height = body_size + max(8, int(body_size * 0.25))
        max_lines = max(2, int(remaining_height // approx_line_height))
        wrapped_lines = self._wrap_overlay_lines(
            message_text,
            body_font,
            available_width,
            draw,
            max_lines,
            max_words_per_line=words_per_line,
        )
        line_spacing = max(8, int(body_size * 0.25))
        for line in wrapped_lines:
            line_width = self._measure_text(draw, line, body_font)
            line_x = max(padding, (canvas.width - line_width) / 2)
            draw.text((line_x + shadow_offset, text_y + shadow_offset), line, font=body_font, fill=shadow_color)
            draw.text((line_x, text_y), line, font=body_font, fill=(255, 255, 255, 255))
            text_y += body_size + line_spacing

        output_file = tempfile.NamedTemporaryFile(delete=False, suffix=".png", dir=self.voice_audio_dir)
        temp_path = output_file.name
        output_file.close()
        canvas.save(temp_path)
        return temp_path

    def _load_overlay_font(self, size: int, bold: bool = False):
        candidates: list[str] = []
        if bold:
            candidates.extend(["Montserrat-SemiBold.ttf", "SegoeUI-Semibold.ttf", "arialbd.ttf"])
        else:
            candidates.extend(["Montserrat-Regular.ttf", "SegoeUI.ttf", "arial.ttf"])
        if self._overlay_font_dir and self._overlay_font_dir.exists():
            for name in list(candidates):
                path = self._overlay_font_dir / name
                if path.exists():
                    try:
                        return ImageFont.truetype(str(path), size=size)
                    except Exception:
                        continue
        for name in candidates:
            try:
                return ImageFont.truetype(name, size=size)
            except Exception:
                continue
        return ImageFont.load_default()

    def _wrap_overlay_lines(
        self,
        message: str | None,
        font,
        max_width: int,
        draw: ImageDraw.ImageDraw,
        max_lines: int,
        *,
        max_words_per_line: int | None = None,
    ) -> list[str]:
        text = (message or "").strip() or "(No message provided)"
        paragraphs = text.splitlines() or [text]
        lines: list[str] = []
        truncated = False
        for paragraph in paragraphs:
            words = paragraph.split()
            if not words:
                if len(lines) < max_lines:
                    lines.append("")
                else:
                    truncated = True
                continue
            current_words: list[str] = []
            for word in words:
                candidate_words = current_words + [word]
                candidate_text = " ".join(candidate_words)
                exceeds_word_limit = (
                    max_words_per_line is not None
                    and current_words
                    and len(candidate_words) > max_words_per_line
                )
                exceeds_width = (
                    current_words
                    and self._measure_text(draw, candidate_text, font) > max_width
                )
                if exceeds_word_limit or exceeds_width:
                    lines.append(" ".join(current_words))
                    current_words = [word]
                    if len(lines) >= max_lines:
                        truncated = True
                        break
                else:
                    current_words = candidate_words
            if len(lines) >= max_lines:
                truncated = True
                break
            if current_words:
                lines.append(" ".join(current_words))
                if len(lines) >= max_lines and len(words) > len(current_words):
                    truncated = True
                    break
        if not lines:
            lines = [text]
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            truncated = True
        if truncated and lines:
            last = lines[-1]
            ellipsis = "…"
            while self._measure_text(draw, last + ellipsis, font) > max_width and last:
                last = last[:-1]
            lines[-1] = (last.rstrip() + ellipsis) if last else ellipsis
        return lines

    def _measure_text(self, draw: ImageDraw.ImageDraw, text: str, font) -> int:
        try:
            bbox = draw.textbbox((0, 0), text, font=font)
            return bbox[2] - bbox[0]
        except Exception:
            try:
                if hasattr(font, "getlength"):
                    return int(font.getlength(text))
            except Exception:
                pass
            try:
                size = font.getsize(text)
                return size[0]
            except Exception:
                return len(text) * max(1, getattr(font, "size", 12))

    def _display_fade_in_delay(self) -> float:
        """Retrieve the OBS fade-in delay so audio can align with media visibility."""
        manager = self.obs_manager
        if not manager:
            manager = get_reference("OBSManager")
            self.obs_manager = manager
        if manager:
            getter = getattr(manager, "get_display_fade_in_delay", None)
            if callable(getter):
                try:
                    value = getter()
                    if isinstance(value, (int, float)):
                        return max(0.0, float(value))
                except Exception:
                    pass
            attr_val = getattr(manager, "display_fade_in_seconds", None)
            if isinstance(attr_val, (int, float)):
                return max(0.0, float(attr_val))
        return 0.5
    
    def _ensure_assistant(self):
        if not self.assistant:
            self.assistant = get_reference("AssistantManager")
        return self.assistant

    async def _build_voice_asset(
        self,
        audio_path: str,
        *,
        event: dict | None = None,
        cache_key: str | None = None,
        extra: dict | None = None,
    ):
        assistant = self._ensure_assistant()
        audio_meta = None
        if assistant:
            try:
                audio_meta = await assistant._build_audio_metadata(audio_path)
            except Exception:
                audio_meta = None
        if not audio_meta:
            audio_meta = {
                "path": audio_path,
                "volumes": [],
                "min_volume": 0,
                "max_volume": 0,
                "duration_ms": 0,
            }
        cache_payload = {"kind": "audio", "audio": audio_path, "audio_meta": audio_meta}
        if extra:
            cache_payload.update(extra)
        self._store_cached_asset(event, cache_key, cache_payload)
        return cache_payload

    async def _play_voice_asset(self, asset: dict | None):
        if not asset:
            return
        assistant = self._ensure_assistant()
        if not assistant:
            return
        audio_meta = asset.get("audio_meta")
        if audio_meta:
            await assistant.assistant_responds(audio_meta)
        else:
            await assistant.assistant_responds(asset.get("audio"))

    async def _invoke_method(
        self,
        method_ref,
        arg,
        payload,
        *,
        event: dict | None = None,
        execute: bool = True,
        cache_key: str | None = None,
        token: str | None = None,
    ):
        """Call a method reference with optional arg; await if it is a coroutine/function that returns coroutine."""
        if method_ref is None:
            return None
        accepts_payload_kw = self._method_accepts_kwarg(method_ref, "payload")
        accepts_event_kw = self._method_accepts_kwarg(method_ref, "event")
        accepts_execute_kw = self._method_accepts_kwarg(method_ref, "execute")
        accepts_cache_kw = self._method_accepts_kwarg(method_ref, "cache_key")
        accepts_token_kw = self._method_accepts_kwarg(method_ref, "token")

        def _build_kwargs():
            kwargs = {}
            if accepts_payload_kw:
                kwargs["payload"] = payload
            if accepts_event_kw:
                kwargs["event"] = event
            if accepts_execute_kw:
                kwargs["execute"] = execute
            if accepts_cache_kw:
                kwargs["cache_key"] = cache_key
            if accepts_token_kw:
                kwargs["token"] = token
            return kwargs

        try:
            # If method is coroutine function, call with arg or no-arg accordingly
            if inspect.iscoroutinefunction(method_ref):
                kwargs = _build_kwargs()
                if arg is None:
                    return await method_ref(**kwargs)
                return await method_ref(arg, **kwargs)
            else:
                # call synchronously; if it returns coroutine, await it
                kwargs = _build_kwargs()
                if arg is None:
                    res = method_ref(**kwargs)
                else:
                    res = method_ref(arg, **kwargs)
                if inspect.isawaitable(res):
                    return await res
                return res
        except TypeError:
            # fallback: try calling with no args
            try:
                res = method_ref()
                if inspect.isawaitable(res):
                    return await res
                return res
            except Exception:
                return None

    async def channel_points_redemption_handler(self, payload, type: Literal["custom", "auto"]) -> None:
        # Determine redemption name depending on payload type, determined by if reward has title attribute or type attribute
        if type == "auto":
            redemption_name = payload.reward.type
            points = payload.reward.channel_points
        elif type == "custom":
            redemption_name = payload.reward.title
            points = payload.reward.cost

        change_set_name = await get_setting("Gacha Change Set Redemption Name", "Change Gacha Set")
        gacha_pull_name = await get_setting("Gacha Pull Redemption Name", "Gacha Pull")
        gacha_enabled = await get_setting("Gacha System Enabled", False)
        if not gacha_enabled and redemption_name in [change_set_name, gacha_pull_name]:
            debug_print("CustomBuilder", f"Gacha system is disabled; ignoring redemption: {redemption_name}")
            try:
                payload.refund(token_for=self.bot.owner_id)
            except Exception as e:
                print(f"Failed to refund redemption for disabled gacha system: {e}")
            return
        user_id = payload.user.id

        if not self.online_database:
            self.online_database = get_reference("OnlineDatabase")
        if not self.event_manager:
            self.event_manager = get_reference("EventManager")
        if not self.gacha_handler:
            self.gacha_handler = get_reference("GachaHandler")

        if not await self.online_database.user_exists(user_id):
            debug_print("CustomBuilder", f"User ID: {user_id} does not exist in the database. Creating user entry.")
            data = {"twitch_username": payload.user.name, "twitch_display_name": payload.user.display_name, "active_gacha_set": "humble beginnings"}
            await self.online_database.create_user(user_id, data)

        await self.online_database.increment_column(table="users", column_filter="twitch_id", value=user_id, column_to_increment="channel_points_redeemed", increment_by=points)
        if not self.gacha_handler:
            debug_print("CustomBuilder", "GachaHandler reference missing or is disabled.")
        else:
            if redemption_name == change_set_name:
                if self.gacha_handler:
                    await self.gacha_handler.handle_gacha_set_change(payload)
                return
            elif redemption_name == gacha_pull_name:
                if not self.gacha_handler:
                    self.gacha_handler = get_reference("GachaHandler")
                if self.gacha_handler:
                    event = await self.gacha_handler.roll_for_gacha(twitch_user_id=user_id, num_pulls=1)
                    self.event_manager.add_event(event)
                return
        
        custom_reward = await get_custom_reward(redemption_name, "channel_points")
        if not custom_reward:
            return
        # Build parsed methods and delegate execution to run_custom_redemption
        try:
            parsed = await self.build_actions(custom_reward=custom_reward)
            raw_user_input = _get_payload_user_text(payload)
            user_input_value = raw_user_input if raw_user_input is not None else _extract_user_input(payload, None)
            event = {
                "type": "channel_points",
                "id": custom_reward.get("id") if isinstance(custom_reward, dict) else None,
                "code": custom_reward.get("code") if isinstance(custom_reward, dict) else None,
                "parsed_methods": parsed,
                "payload": payload,
                "user_input": user_input_value,
                "user_input_raw": raw_user_input,
                "event_type": f"channel point redemption of {redemption_name} by {payload.user.display_name}"
            }
            try:
                debug_print("CustomBuilder", f"Pre-generating assets for redemption event code: {event['code']}")
                await self.run_custom_redemption(event, execute=False)
            except Exception as precache_err:
                print(f"Pre-generation failed: {precache_err}")
            self.event_manager.add_event(event)
        except Exception as e:
            print(f"channel_points_redemption_handler error: {e}")
        return
    
    async def handle_cheer(self, payload):
        bits = payload.bits
        user_id = payload.user.id
        gacha_task = None
        if not self.online_database:
            self.online_database = get_reference("OnlineDatabase")
        await self.online_database.increment_column(table="users", column_filter="twitch_id", value=payload.user.id, column_to_increment="bits_donated", increment_by=bits)
        if bits >= 500:
            number_of_rolls = bits // 500
        if not self.gacha_handler:
            self.gacha_handler = get_reference("GachaHandler")

        if not await self.online_database.user_exists(user_id):
            debug_print("CustomBuilder", f"User ID: {user_id} does not exist in the database. Creating user entry.")
            data = {"twitch_username": payload.user.name, "twitch_display_name": payload.user.display_name, "active_gacha_set": "humble beginnings"}
            await self.online_database.create_user(user_id, data)
        if self.gacha_handler and await get_setting("Gacha System Enabled", False):
            gacha_task = asyncio.create_task(self.gacha_handler.roll_for_gacha(payload.user.id, number_of_rolls, bits_toward_next_pull=bits % 500))
        if not self.online_database:
            self.online_database = get_reference("OnlineDatabase")
        user_data = await self.online_database.get_specific_user_data(twitch_user_id=user_id, field="bits_donated")
        override = False
        if user_data in [0, None]:
            if not self.twitch_bot:
                self.twitch_bot = get_reference("TwitchBot")
            temp_bits = await self.twitch_bot.get_total_bits_donated(user_id=user_id)
            if temp_bits and temp_bits > 0 and temp_bits > bits:
                bits = temp_bits
                override = True
        if override:
            await self.online_database.create_user(user_id, {"bits_donated": bits})
        else:
            await self.online_database.increment_column(table="users", column_filter="twitch_id", value=user_id, column_to_increment="bits_donated", increment_by=bits)
        custom_reward = await get_bit_reward(bits)
        if not custom_reward:
            #Fallback: Uses default customizable cheer response
            event = {"type": "cheer", "user": payload.user.display_name, "event": payload}
            if not self.assistant:
                self.assistant = get_reference("AssistantManager")
            asyncio.create_task(self.assistant.generate_voiced_response(event))
            if gacha_task:
                if isinstance(gacha_task, asyncio.Task):
                    gacha_event = await gacha_task
                else:
                    gacha_event = gacha_task
                self.event_manager.add_event(gacha_event)
            return
        # Build parsed methods and delegate execution to run_custom_redemption
        try:
            parsed = await self.build_actions(custom_reward=custom_reward)
            raw_user_input = _get_payload_user_text(payload)
            user_input_value = raw_user_input if raw_user_input is not None else _extract_user_input(payload, None)
            event = {
                "type": "bits",
                "id": custom_reward.get("id") if isinstance(custom_reward, dict) else None,
                "code": custom_reward.get("code") if isinstance(custom_reward, dict) else None,
                "parsed_methods": parsed,
                "payload": payload,
                "user_input": user_input_value,
                "user_input_raw": raw_user_input,
                "event_type": f"cheer of {bits} bits from {payload.user.display_name}"
            }
            if not self.event_manager:
                self.event_manager = get_reference("EventManager")
            try:
                await self.run_custom_redemption(event, execute=False)
            except Exception as precache_err:
                print(f"Pre-generation failed: {precache_err}")
            self.event_manager.add_event(event)
            if gacha_task:
                if isinstance(gacha_task, asyncio.Task):
                    gacha_event = await gacha_task
                else:
                    gacha_event = gacha_task
                self.event_manager.add_event(gacha_event)
        except Exception as e:
            print(f"handle_cheer error: {e}")
        return
    
    async def run_custom_redemption(self, event: dict, execute: bool = True):
        """Execute a custom redemption using a pre-parsed list of methods.

        Expected `event` structure:
          - 'type': 'bits' or 'point_redemption' (optional)
          - 'id': database id (optional)
          - 'code': original code string (optional)
          - 'parsed_methods': list returned from `build_actions` (required)
          - 'payload': optional payload object (used for '<user_input>' resolution)
          - 'user_input': optional fallback string for '<user_input>'

        Each item in 'parsed_methods' is expected to be either:
          - {'step': method_ref, 'input': value}
        or a parallel group with numbered keys:
          - {'step1': method_ref1, 'input1': v1, 'step2': method_ref2, 'input2': v2, ...}

        This function will run sequential steps in-order and run numbered groups
        concurrently.
        """
        builder = self
        prepare_only = not execute
        try:
            if not isinstance(event, dict):
                return
            parsed = event.get("parsed_methods") or event.get("parsed") or []
            payload = event.get("payload")
            fallback_user_input = event.get("user_input_raw")
            if not fallback_user_input:
                fallback_user_input = event.get("user_input")

            if not parsed:
                return

            chat_buffer_seconds = CHAT_MESSAGE_BUFFER_SECONDS if execute else 0.0
            last_step_was_chat = False

            for entry in parsed:
                if not entry:
                    continue
                contains_chat = self._entry_contains_chat_token(entry)
                if execute and contains_chat and last_step_was_chat and chat_buffer_seconds > 0:
                    await asyncio.sleep(chat_buffer_seconds)
                # detect numbered (parallel) group keys
                numbered = [k for k in entry.keys() if k.startswith("step")]
                if len(numbered) <= 1:
                    method = entry.get("step")
                    inp = entry.get("input")
                    if isinstance(inp, str) and "%" in inp:
                        inp = await builder.string_builder(payload, inp)
                    token = entry.get("token")
                    cache_key = entry.get("cache_key")
                    if prepare_only and not self._token_needs_generation(token):
                        continue
                    final_inp = _resolve_user_value(inp, payload, fallback_user_input)

                    try:
                        await builder._invoke_method(
                            method,
                            final_inp,
                            payload,
                            event=event,
                            execute=execute,
                            cache_key=cache_key,
                            token=token,
                        )
                    except Exception:
                        pass
                else:
                    # run numbered steps concurrently
                    count = max((int(k.replace("step", "")) for k in numbered), default=0)
                    tasks = []
                    gm_cache_keys: list[str] = []
                    voice_durations: list[float] = []
                    audio_cache_keys: list[str] = []
                    display_cache_keys: list[str] = []
                    entry_specs: list[dict] = []

                    for i in range(1, count + 1):
                        method = entry.get(f"step{i}")
                        a = entry.get(f"input{i}")
                        token = entry.get(f"token{i}")
                        cache_key = entry.get(f"cache_key{i}")
                        if prepare_only and not self._token_needs_generation(token):
                            continue

                        if isinstance(token, str):
                            upper_tok = token.upper()
                            if upper_tok in DISPLAY_MEDIA_TOKENS and cache_key:
                                display_cache_keys.append(cache_key)
                            if upper_tok == "GM" and cache_key:
                                gm_cache_keys.append(cache_key)
                            if upper_tok in VOICE_TOKENS:
                                duration_val = self._voice_duration_for_cache(event, cache_key)
                                if duration_val:
                                    voice_durations.append(duration_val)
                            if upper_tok in AUDIO_TOKENS and cache_key:
                                audio_cache_keys.append(cache_key)

                        entry_specs.append(
                            {
                                "method": method,
                                "input": a,
                                "token": token,
                                "cache_key": cache_key,
                            }
                        )

                    def _parallel_priority(spec: dict) -> int:
                        tok = spec.get("token")
                        if isinstance(tok, str):
                            upper_tok = tok.upper()
                            if upper_tok in AUDIO_TOKENS:
                                return 0
                            if upper_tok in DISPLAY_MEDIA_TOKENS:
                                return 1
                        return 2

                    entry_specs.sort(key=_parallel_priority)

                    ready_event = None
                    display_ready_map = None
                    audio_wait_map = None
                    if (
                        event
                        and display_cache_keys
                        and audio_cache_keys
                    ):
                        ready_event = asyncio.Event()
                        display_ready_map = event.setdefault("_display_ready_events", {})
                        audio_wait_map = event.setdefault("_audio_wait_events", {})
                        for ck in display_cache_keys:
                            display_ready_map[ck] = ready_event
                        for ck in audio_cache_keys:
                            audio_wait_map[ck] = ready_event

                    audio_specs: list[dict] = []
                    voice_specs: list[dict] = []
                    display_specs: list[dict] = []
                    other_specs: list[dict] = []

                    for spec in entry_specs:
                        tok_upper = spec.get("token")
                        if isinstance(tok_upper, str):
                            tok_upper = tok_upper.upper()
                        if tok_upper in AUDIO_TOKENS:
                            audio_specs.append(spec)
                        elif tok_upper in VOICE_TOKENS:
                            voice_specs.append(spec)
                        elif tok_upper in DISPLAY_MEDIA_TOKENS:
                            display_specs.append(spec)
                        else:
                            other_specs.append(spec)

                    async def _invoke_spec(spec: dict):
                        m = spec.get("method")
                        a = spec.get("input")
                        tok = spec.get("token")
                        ck = spec.get("cache_key")
                        final = _resolve_user_value(a, payload, fallback_user_input)
                        try:
                            return await builder._invoke_method(
                                m,
                                final,
                                payload,
                                event=event,
                                execute=execute,
                                cache_key=ck,
                                token=tok,
                            )
                        except Exception:
                            return None

                    async def _run_specs_serial(specs: list[dict]):
                        for spec in specs:
                            await _invoke_spec(spec)

                    async def _run_specs_parallel(specs: list[dict]):
                        tasks = [asyncio.create_task(_invoke_spec(spec)) for spec in specs]
                        if tasks:
                            await asyncio.gather(*tasks, return_exceptions=True)

                    if event and voice_durations and gm_cache_keys:
                        duration_hint = max(voice_durations)
                        duration_map = event.setdefault("_meme_duration_hints", {})
                        for ck in gm_cache_keys:
                            if ck:
                                duration_map[ck] = duration_hint

                    if event and display_cache_keys and audio_cache_keys:
                        fade_delay = self._display_fade_in_delay()
                        if fade_delay and fade_delay > 0:
                            half_delay = max(0.0, fade_delay * 0.5)
                            delay_map = event.setdefault("_audio_delay_hints", {})
                            for ck in audio_cache_keys:
                                if not ck:
                                    continue
                                delay_map[ck] = half_delay

                    if (
                        not audio_specs
                        and voice_specs
                        and display_specs
                    ):
                        combined_specs = voice_specs + display_specs
                        await _run_specs_parallel(combined_specs)
                        voice_specs = []
                        display_specs = []

                    if audio_specs:
                        await _run_specs_serial(audio_specs)

                    if (
                        audio_specs
                        and voice_specs
                        and execute
                        and SIMULTANEOUS_VOICE_STAGGER_SECONDS > 0
                    ):
                        debug_print(
                            "CustomBuilder",
                            "Staggering voice start by "
                            f"{SIMULTANEOUS_VOICE_STAGGER_SECONDS:.2f}s after audio",
                        )
                        await asyncio.sleep(SIMULTANEOUS_VOICE_STAGGER_SECONDS)

                    if voice_specs:
                        if audio_specs:
                            await _run_specs_serial(voice_specs)
                        else:
                            await _run_specs_parallel(voice_specs)

                    if (
                        audio_specs
                        and display_specs
                        and execute
                        and SIMULTANEOUS_MEDIA_STAGGER_SECONDS > 0
                    ):
                        debug_print(
                            "CustomBuilder",
                            "Staggering display start by "
                            f"{SIMULTANEOUS_MEDIA_STAGGER_SECONDS:.2f}s after audio",
                        )
                        await asyncio.sleep(SIMULTANEOUS_MEDIA_STAGGER_SECONDS)

                    if display_specs:
                        await _run_specs_serial(display_specs)

                    if other_specs:
                        await _run_specs_parallel(other_specs)

                if execute:
                    last_step_was_chat = contains_chat

            return
        except Exception as e:
            print(f"run_custom_redemption error: {e}")
            return
    
    async def string_builder(self, payload, text: str) -> str:
        # %bot% - bot's display name
        # %user% - user's display name
        # %channel% - channel name
        # %reward% for the name of the reward redeemed
        # %viewers% for the current viewer count
        # %followers% for the current follower count
        # %subscribers% for the current subscriber count
        # %title% for the current stream title
        # %game% for the current game being played
        # %bits% for the number of bits cheered
        # %message% for the user's input message
        # %rng% for totally random number
        # %rng:min-max% for random number between min and max (inclusive)
        debug_print("CommandHandler", f"Building text for: {text}")
        updated_text = text
        if "%" in updated_text:
            if "%bot%" in updated_text:
                try:
                    if not self.twitch_bot:
                        self.twitch_bot = get_reference("TwitchBot")
                    updated_text = updated_text.replace("%bot%", self.twitch_bot.user.name.capitalize())
                except Exception:
                    pass
            if "%user%" in updated_text:
                try:
                    updated_text = updated_text.replace("%user%", payload.user.display_name.capitalize())
                except Exception:
                    pass
            if "%channel%" in updated_text:
                try:
                    updated_text = updated_text.replace("%channel%", payload.broadcaster.display_name.capitalize())
                except Exception:
                    pass
            if "%reward%" in updated_text:
                try:
                    updated_text = updated_text.replace("%reward%", payload.reward.title)
                except Exception:
                    pass
            if "%viewers%" in updated_text:
                try:
                    if not self.twitch_bot:
                        self.twitch_bot = get_reference("TwitchBot")
                    viewers = await self.twitch_bot.fetch_viewer_count()
                    updated_text = updated_text.replace("%viewers%", str(viewers))
                except Exception:
                    pass
            if "%followers%" in updated_text:
                try:
                    if not self.twitch_bot:
                        self.twitch_bot = get_reference("TwitchBot")
                    followers = await self.twitch_bot.fetch_follower_count()
                    updated_text = updated_text.replace("%followers%", str(followers))
                except Exception:
                    pass
            if "%subscribers%" in updated_text:
                try:
                    if not self.twitch_bot:
                        self.twitch_bot = get_reference("TwitchBot")
                    subscribers = await self.twitch_bot.fetch_subscriber_count()
                    updated_text = updated_text.replace("%subscribers%", str(subscribers))
                except Exception:
                    pass
            if "%title%" in updated_text:
                try:
                    if not self.twitch_bot:
                        self.twitch_bot = get_reference("TwitchBot")
                    title = await self.twitch_bot.fetch_title()
                    updated_text = updated_text.replace("%title%", title)
                except Exception:
                    pass
            if "%game%" in updated_text:
                try:
                    if not self.twitch_bot:
                        self.twitch_bot = get_reference("TwitchBot")
                    game = await self.twitch_bot.get_current_game()
                    updated_text = updated_text.replace("%game%", game)
                except Exception:
                    pass
            if "%message%" in updated_text:
                try:
                    message = payload.user_input
                    updated_text = updated_text.replace("%message%", message)
                except Exception:
                    pass
            if "%bits%" in updated_text:
                try:
                    bits = str(payload.bits)
                    updated_text = updated_text.replace("%bits%", bits)
                except Exception:
                    pass
            if "%rng%" in updated_text:
                try:
                    while "%rng%" in updated_text:
                        rand_num = get_random_number(0, 100)
                        updated_text = updated_text.replace("%rng%", str(rand_num), 1)
                except Exception:
                    pass
            if "%rng:" in updated_text:
                try:
                    import re
                    pattern = r"%rng:(-?\d+)-(-?\d+)%"
                    matches = re.findall(pattern, updated_text)
                    for match in matches:
                        min_val = int(match[0])
                        max_val = int(match[1])
                        if min_val > max_val:
                            min_val, max_val = max_val, min_val
                        rand_num = get_random_number(min_val, max_val)
                        updated_text = re.sub(r"%rng:{}-{}%".format(match[0], match[1]), str(rand_num), updated_text, count=1)
                except Exception:
                    pass

        return updated_text

    async def get_action_method(self, method_code: str, index: int):
        """Maps method codes to actual functions."""
        return self.code_decryption_map.get(method_code)
    
    async def tts(self, text: str, use: Literal["assistant", "azure", "viewer"], user_id = None) -> str | None:
        if use == "assistant":
            voice = await get_setting("Elevenlabs Voice ID", None)
            if not self.elevenlabs_manager:
                self.elevenlabs_manager = get_reference("ElevenLabsManager")
            output = self.elevenlabs_manager.text_to_audio(input_text=text, voice=voice)
            if not output:
                if not self.azure_manager:
                    self.azure_manager = get_reference("SpeechToTextManager")
                voice = await get_setting("Azure TTS Backup Voice", None)
                output = self.azure_manager.text_to_speech(text=text, voice=voice)
            if not output:
                return None
            return output
        else:
            if not self.azure_manager:
                self.azure_manager = get_reference("SpeechToTextManager")
            if use == "viewer" and user_id:
                if not self.online_database:
                    self.online_database = get_reference("OnlineDatabase")
                voice = await self.online_database.get_specific_user_data(twitch_user_id=user_id, field="tts_voice")
            else:
                voice = None
            if not voice:
                voice = await get_setting("Azure TTS Backup Voice", None)
            output = self.azure_manager.text_to_speech(text=text, voice=voice)
            if not output:
                return None
            return output

    async def automatic_voiced_response(
        self,
        message: str,
        *,
        payload=None,
        event: dict | None = None,
        execute: bool = True,
        cache_key: str | None = None,
    ):
        debug_print("CustomBuilder", f"Generating automatic voiced response for: {message}")
        if not message:
            return None
        cache = self._get_cached_asset(event, cache_key)
        if cache is None:
            output = await self.tts(message, use="assistant")
            if not output:
                return None
            cache = await self._build_voice_asset(output, event=event, cache_key=cache_key)
        if execute or event is None:
            await self._play_voice_asset(cache)
        return cache

    async def ai_generated_voiced_response(
        self,
        prompt: str,
        *,
        payload=None,
        event: dict | None = None,
        execute: bool = True,
        cache_key: str | None = None,
    ):
        debug_print("CustomBuilder", "Generating AI voiced response...")
        cache = self._get_cached_asset(event, cache_key)
        if cache is None:
            if not self.chatGPT:
                self.chatGPT = get_reference("GPTManager")
            chatGPT = asyncio.to_thread(self.chatGPT.chat, [{"role": "user", "content": prompt}])
            response = await chatGPT
            if not response:
                print("Failed to generate text response.")
                return None
            output = await self.tts(response, use="assistant")
            if not output:
                return None
            cache = await self._build_voice_asset(
                output,
                event=event,
                cache_key=cache_key,
                extra={"text": response},
            )
        if execute or event is None:
            await self._play_voice_asset(cache)
        return cache

    async def ai_generated_voiced_response_personality(
        self,
        prompt: str,
        *,
        payload=None,
        event: dict | None = None,
        execute: bool = True,
        cache_key: str | None = None,
    ):
        debug_print("CustomBuilder", "Generating AI voiced response with personality...")
        cache = self._get_cached_asset(event, cache_key)
        if cache is None:
            full_prompt = [{"role": "user", "content": prompt}]
            if not self.chatGPT:
                self.chatGPT = get_reference("GPTManager")
            chatGPT = asyncio.to_thread(self.chatGPT.chat, full_prompt)
            response = await chatGPT
            if not response:
                print("Failed to generate text response.")
                return None
            output = await self.tts(response, use="assistant")
            if not output:
                return None
            cache = await self._build_voice_asset(
                output,
                event=event,
                cache_key=cache_key,
                extra={"text": response, "personality": True},
            )
        if execute or event is None:
            await self._play_voice_asset(cache)
        return cache

    async def automatic_chat_response(self, message: str):
        debug_print("CustomBuilder", f"Sending automatic chat response: {message}")
        if not self.twitch_bot:
            self.twitch_bot = get_reference("TwitchBot")
        await self.twitch_bot.send_chat(message)

    async def ai_generated_chat_response(
        self,
        prompt: str,
        *,
        payload=None,
        event: dict | None = None,
        execute: bool = True,
        cache_key: str | None = None,
    ):
        debug_print("CustomBuilder", f"Generating AI chat response for: {prompt}")
        cache = self._get_cached_asset(event, cache_key)
        if cache is None:
            if not self.chatGPT:
                self.chatGPT = get_reference("GPTManager")
            chatGPT = asyncio.to_thread(self.chatGPT.chat, [{"role": "user", "content": prompt}])
            response = await chatGPT
            if not response:
                return None
            cache = {"kind": "chat", "message": response}
            self._store_cached_asset(event, cache_key, cache)
        if execute or event is None:
            if not self.twitch_bot:
                self.twitch_bot = get_reference("TwitchBot")
            await self.twitch_bot.send_chat(cache.get("message"))
        return cache

    async def ai_generated_chat_response_personality(
        self,
        prompt: str,
        *,
        payload=None,
        event: dict | None = None,
        execute: bool = True,
        cache_key: str | None = None,
    ):
        debug_print("CustomBuilder", f"Generating AI chat response with personality for: {prompt}")
        cache = self._get_cached_asset(event, cache_key)
        if cache is None:
            full_prompt = [{"role": "user", "content": prompt}]
            if not self.chatGPT:
                self.chatGPT = get_reference("GPTManager")
            chatGPT = asyncio.to_thread(self.chatGPT.chat, full_prompt, use_twitch_emotes=True)
            response = await chatGPT
            if not response:
                return None
            cache = {"kind": "chat", "message": response, "personality": True}
            self._store_cached_asset(event, cache_key, cache)
        if execute or event is None:
            if not self.twitch_bot:
                self.twitch_bot = get_reference("TwitchBot")
            await self.twitch_bot.send_chat(cache.get("message"))
        return cache

    async def generate_meme_image(
        self,
        *,
        payload=None,
        event: dict | None = None,
        execute: bool = True,
        cache_key: str | None = None,
    ):
        """Generates (or reuses) a meme image and displays it when executing."""
        debug_print("CustomBuilder", "Generating meme image...")
        if not self.obs_manager:
            self.obs_manager = get_reference("OBSManager")
        duration_hint = None
        ready_event = None
        ready_opacity = None
        if event and cache_key:
            duration_map = event.get("_meme_duration_hints") or {}
            if isinstance(duration_map, dict):
                duration_hint = duration_map.get(cache_key)
            ready_map = event.get("_display_ready_events") or {}
            if isinstance(ready_map, dict):
                ready_event = ready_map.get(cache_key)
                if ready_event:
                    ready_opacity = 0.5
        cache = self._get_cached_asset(event, cache_key)
        if cache is None:
            self.memes_dir.mkdir(exist_ok=True)
            self.screenshots_dir.mkdir(exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = self.screenshots_dir / f"meme_screenshot_{timestamp}.png"
            output_path = self.obs_manager.get_obs_screenshot(output_path)
            if not self.chatGPT:
                self.chatGPT = get_reference("GPTManager")
            chatGPT = asyncio.to_thread(self.chatGPT.analyze_image, image_path=output_path, is_meme=True)
            response = await chatGPT
            caption_match = re.search(r'!caption\s*(.*?)\s*(?=!font|$)', response, re.DOTALL | re.IGNORECASE)
            font_match = re.search(r'!font\s*(.*?)\s*(?=!caption|$)', response, re.DOTALL | re.IGNORECASE)
            parsed_caption = caption_match.group(1).strip() if caption_match else ""
            parsed_font = font_match.group(1).strip() if font_match else None
            output_path = make_meme(output_path, parsed_caption, parsed_font)
            cache = {"kind": "meme", "path": output_path, "discord_sent": False}
            self._store_cached_asset(event, cache_key, cache)
        if execute or event is None:
            await self.obs_manager.display_meme(
                cache.get("path"),
                is_meme=True,
                duration=duration_hint,
                ready_event=ready_event,
                ready_opacity=ready_opacity,
            )
            discord_integration = await get_setting("Discord Integration Enabled", False)
            if discord_integration and not cache.get("discord_sent"):
                self.discord_bot = get_reference("DiscordBot")
                if self.discord_bot:
                    channel_id = await get_setting("Discord Meme Channel ID", None)
                    asyncio.create_task(self.discord_bot.send_image(channel_id, cache.get("path")))
                    cache["discord_sent"] = True
        return cache

    async def play_audio_file(
        self,
        file_name: str,
        *,
        payload=None,
        event: dict | None = None,
        execute: bool = True,
        cache_key: str | None = None,
    ):
        """Plays an audio file from media/soundFX directory, honoring any requested delay."""
        sound_name = self._normalize_audio_fx_name(file_name)
        if not sound_name:
            debug_print("CustomBuilder", f"play_audio_file received invalid filename '{file_name}'.")
            return None
        debug_print("CustomBuilder", f"Playing audio file request: {file_name} -> {sound_name}")
        if not self.audio_manager:
            self.audio_manager = get_reference("AudioManager")
        if not self.audio_manager:
            debug_print("CustomBuilder", "AudioManager unavailable; cannot play audio.")
            return None

        prepared_map = None
        prepared_asset = None
        if event and cache_key:
            prepared_map = event.setdefault("_prepared_audio_assets", {})
            prepared_asset = prepared_map.get(cache_key)

        def _remember_prepared(asset):
            if prepared_map is not None and cache_key and asset:
                prepared_map[cache_key] = asset

        if prepared_asset is None and self.audio_manager:
            cached = self.audio_manager.get_prepared_sound_fx(sound_name)
            if cached:
                prepared_asset = cached
                debug_print("CustomBuilder", f"Using global audio cache for '{sound_name}'.")

        if not execute:
            if prepared_asset is None:
                prepared_asset = await self.audio_manager.prepare_sound_fx(sound_name)
                _remember_prepared(prepared_asset)
            return prepared_asset

        prepare_task = None
        if prepared_asset is None:
            prepare_task = asyncio.create_task(self.audio_manager.prepare_sound_fx(sound_name))
            debug_print("CustomBuilder", f"No cached audio for '{sound_name}', preparing asynchronously.")
        else:
            debug_print("CustomBuilder", f"Using cached audio asset for '{sound_name}'.")

        try:
            sync_audio_to_ready = await get_setting("Sync Audio To Display Ready", False)
        except Exception:
            sync_audio_to_ready = False

        delay_seconds = 0.0
        wait_event = None
        if sync_audio_to_ready and event and cache_key:
            delay_map = event.get("_audio_delay_hints") or {}
            delay_val = delay_map.get(cache_key)
            if isinstance(delay_val, (int, float)):
                delay_seconds = max(0.0, float(delay_val))
            wait_map = event.get("_audio_wait_events") or {}
            if isinstance(wait_map, dict):
                wait_event = wait_map.get(cache_key)

        if sync_audio_to_ready:
            if wait_event and delay_seconds > 0:
                wait_tasks = [
                    asyncio.create_task(wait_event.wait()),
                    asyncio.create_task(asyncio.sleep(delay_seconds)),
                ]
                done, pending = await asyncio.wait(wait_tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in pending:
                    task.cancel()
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)
            elif wait_event:
                try:
                    await asyncio.wait_for(wait_event.wait(), timeout=3.0)
                except asyncio.TimeoutError:
                    pass
            elif delay_seconds > 0:
                await asyncio.sleep(delay_seconds)
        else:
            debug_print("CustomBuilder", "Audio sync waiting disabled; playing immediately.")

        if prepared_asset is None and prepare_task is not None:
            try:
                prepared_asset = await prepare_task
            except Exception:
                prepared_asset = None
            _remember_prepared(prepared_asset)

        await self.audio_manager.play_sound_fx_by_name(
            sound_name,
            prepared_asset=prepared_asset,
        )
        if prepared_map is not None and cache_key:
            prepared_map.pop(cache_key, None)
        return None

    async def animate_onscreen_element(
        self,
        file_name: str,
        *,
        payload=None,
        event: dict | None = None,
        execute: bool = True,
        cache_key: str | None = None,
    ):
        """Animates an onscreen element in OBS."""
        debug_print("CustomBuilder", f"Animating onscreen element: {file_name}")
        if not execute:
            return None
        self.images_and_gifs_dir.mkdir(exist_ok=True)
        file_path = self.images_and_gifs_dir / file_name
        if not self.obs_manager:
            self.obs_manager = get_reference("OBSManager")

        ready_event = None
        ready_opacity = None
        if event and cache_key:
            ready_map = event.get("_display_ready_events") or {}
            if isinstance(ready_map, dict):
                ready_event = ready_map.get(cache_key)
                if ready_event:
                    ready_opacity = 0.5

        await self.obs_manager.display_meme(
            file_path,
            is_meme=False,
            ready_event=ready_event,
            ready_opacity=ready_opacity,
        )
        return None

    async def wait_for_seconds(self, seconds: int | float | str | None):
        """Pause execution for the requested duration, accepting string/int inputs from the DB."""
        try:
            secs = float(seconds)
        except (TypeError, ValueError):
            secs = 0.0
        if secs <= 0:
            debug_print("CustomBuilder", f"wait_for_seconds received non-positive value '{seconds}', skipping pause.")
            return
        debug_print("CustomBuilder", f"Waiting for {secs} seconds...")
        await asyncio.sleep(secs)

    async def voiced_message(
        self,
        message: str,
        payload=None,
        *,
        event: dict | None = None,
        execute: bool = True,
        cache_key: str | None = None,
    ):
        """Uses Azure TTS to read out loud a message and display a chat-style overlay."""
        debug_print("CustomBuilder", f"Generating voiced message for: {message}.")
        cache = self._get_cached_asset(event, cache_key)
        if cache is None:
            if not self.azure_manager:
                self.azure_manager = get_reference("SpeechToTextManager")
            voice = None
            try:
                user_id = payload.user.id if payload else None
            except Exception:
                user_id = None
            output = await self.tts(message, use="viewer", user_id=user_id)
            if not output:
                print("Failed to generate voiced message.")
                return None
            cache = {"kind": "voice_message", "audio": output, "voice": voice}
            self._store_cached_asset(event, cache_key, cache)

        if execute or event is None:
            if not self.audio_manager:
                self.audio_manager = get_reference("AudioManager")

            overlay_ready = None
            overlay_task = None
            audio_path = cache.get("audio") if isinstance(cache, dict) else None
            if audio_path and self.audio_manager:
                overlay_result = await self._start_voiced_overlay(payload, message, audio_path)
                if overlay_result:
                    overlay_ready, overlay_task = overlay_result

            if overlay_ready is not None:
                wait_timeout = 3.0
                if self.obs_manager:
                    try:
                        wait_timeout = max(0.5, float(self.obs_manager.get_display_fade_in_delay()) + 0.75)
                    except Exception:
                        wait_timeout = 3.0
                try:
                    await asyncio.wait_for(overlay_ready.wait(), timeout=wait_timeout)
                except asyncio.TimeoutError:
                    pass

            delete_after = event is None
            volume = await get_setting("Azure TTS Volume", 100)
            if self.audio_manager:
                self.audio_manager.play_audio(
                    audio_path,
                    delete_file=delete_after,
                    volume=volume,
                    play_using_music=False,
                )
            else:
                print("[WARN] AudioManager not available; cannot play voiced message.")

            if overlay_task:
                def _overlay_done(task: asyncio.Task):
                    try:
                        task.result()
                    except Exception as exc:
                        print(f"Voice overlay task encountered an error: {exc}")

                overlay_task.add_done_callback(_overlay_done)

        return cache

    async def timeout(self, data, *, payload=None, event=None):
        """Timeout a user specified in the redemption message for the configured seconds."""
        debug_print("CustomBuilder", f"Timeout redemption invoked with data: {data}")

        seconds = None
        target_text = None
        if isinstance(data, dict):
            seconds = data.get("seconds")
            target_text = data.get("target") or data.get("user_input")
        elif isinstance(data, (list, tuple)):
            if len(data) >= 1:
                seconds = data[0]
            if len(data) >= 2:
                target_text = data[1]
        elif isinstance(data, (int, float)):
            seconds = data
        elif isinstance(data, str):
            target_text = data

        try:
            seconds = int(float(seconds))
        except (TypeError, ValueError):
            seconds = None
        if not seconds or seconds < 1:
            seconds = 1

        target_text = "" if target_text is None else str(target_text).strip()

        payload_text = _get_payload_user_text(payload)
        if isinstance(payload_text, str) and payload_text.strip():
            target_text = payload_text.strip()
        elif isinstance(event, dict):
            event_text = event.get("user_input_raw") or event.get("user_input")
            if isinstance(event_text, str) and event_text.strip():
                target_text = event_text.strip()

        if not target_text:
            debug_print("CustomBuilder", "Timeout redemption missing viewer message; cannot determine target user.")
            return

        parts = target_text.split()
        username = parts[0].lstrip("@#").strip()
        if not username:
            debug_print("CustomBuilder", "Timeout redemption could not parse a username from viewer message.")
            return
        reason_text = " ".join(parts[1:]).strip()
        if not reason_text:
            reason_text = "Timed out via custom redemption"
        reason_text = reason_text.replace("\n", " ").strip()
        if len(reason_text) > 200:
            reason_text = reason_text[:200]

        if not self.twitch_bot:
            self.twitch_bot = get_reference("TwitchBot")
        if not self.twitch_bot:
            debug_print("CustomBuilder", "TwitchBot reference unavailable; cannot issue timeout command.")
            return

        await self.twitch_bot.timeout(username, seconds, reason_text)

async def parse_redemption_code(redemption_code: str):
    """Parse the redemption code into a list of methods."""
    builder = CustomPointRedemptionBuilder(None)
    set_reference("PointBuilder", builder)
    return await builder.build_actions(code=redemption_code)

if __name__ == "__main__":
    import asyncio
    async def main():
        builder = CustomPointRedemptionBuilder(None)
        set_reference("PointBuilder", builder)
    asyncio.run(main())