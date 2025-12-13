from db import DATABASE, get_setting, get_prompt, get_hotkey, get_specific_user_data, increment_user_stat, user_exists, set_user_data
from audio_player import AudioManager
from message_scheduler import MessageScheduler
from tts import ElevenLabsManager, SpeechToTextManager
from obs_websockets import OBSWebsocketsManager
from openai_chat import OpenAiManager
from tools import get_reference, set_reference, debug_print, path_from_app_root
import random
import asyncio
import time
import threading
from pathlib import Path

class AssistantManager():
    def __init__(self):
        self.assistant_name = None
        self.stationary_assistant_name = None
        self.recent_subscriptions = []
        self.recent_gifted_subscriptions = []
        self.chatGPT: OpenAiManager = gpt_manager
        self.obs: OBSWebsocketsManager = obs_manager
        self.audio_manager: AudioManager = audio_manager
        self.elevenlabs: ElevenLabsManager = elevenlabs_manager
        self.azure: SpeechToTextManager = azure_manager
        self.event_manager: EventManager = event_manager
        self.twitch_bot = get_reference("TwitchBot")
        self.handler = get_reference("CommandHandler")
        self._ensure_models_loaded()
        debug_print("Assistant", "AssistantManager initialized.")

    def _ensure_models_loaded(self) -> None:
        """Load OpenAI model settings without requiring an active event loop."""
        async def _load():
            try:
                await self.chatGPT.set_models()
            except Exception as exc:
                debug_print("Assistant", f"Failed to set OpenAI models: {exc}")

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_load())
        except RuntimeError:
            threading.Thread(target=lambda: asyncio.run(_load()), daemon=True).start()

    async def generate_chat_response(self, messages: list) -> None:
        """Gathers messages and context and generates a response from chatgpt"""
        debug_print("Assistant", f"Generating chat response with messages: {messages}")
        screenshot_result = None
        if not self.obs:
            self.obs = get_reference("OBSManager")
        if await get_setting("Include Screenshot Context", False):
            random_number = random.randint(1, 100)
            if random_number <= await get_setting("Screenshot Chance Percentage", 0):
                media_dir = path_from_app_root("media")
                media_dir.mkdir(exist_ok=True)
                screenshot_dir = media_dir / "screenshots"
                screenshot_dir.mkdir(exist_ok=True)
                output_path = screenshot_dir / f"screenshot_{int(time.time())}.png"
                output_path = self.obs.get_obs_screenshot(output_path)
                analysis_fn = self.chatGPT.analyze_image
                if asyncio.iscoroutinefunction(analysis_fn):
                    screenshot_result = asyncio.create_task(analysis_fn(output_path))
                else:
                    screenshot_result = asyncio.create_task(asyncio.to_thread(analysis_fn, output_path))
        messages_str = "\n".join(messages)
        dictated_context = None
        if await get_setting("Include STT Context", False):
            try:
                seconds = await get_setting("Seconds of STT", 10)
                dictated_context = azure_manager.timed_speechtotext_from_mic(seconds)
            except Exception as e:
                print(f"[ERROR]Error during speech-to-text: {e}")
                dictated_context = None
        if not gpt_manager.twitch_chat_history:
            prompt_text = await get_prompt("Message Response Prompt", False)
            gpt_manager.twitch_chat_history = [{"role": "system", "content": prompt_text}]
        if await get_setting("Include Screenshot Context", False):
            if isinstance(screenshot_result, asyncio.Task): #Waits for screenshot task to finish if it hasn't already
                screenshot_result = await screenshot_result
        current_time_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        if not self.twitch_bot:
            self.twitch_bot = get_reference("TwitchBot")
        game = await self.twitch_bot.get_current_game()
        speech_part = f"ModdiPly's last ten seconds of speech: {dictated_context}. " if dictated_context else ""
        screenshot_part = f"Description of whats currently on stream (single-frame): {screenshot_result}" if screenshot_result else ""
        prompt = (
            f"Date/Time: {current_time_str}\nTwitch Chat Messages: {messages_str}\n"
            f"Twitch Stream Context: The game currently being played is {game}. {speech_part}{screenshot_part}. "
            "You may choose to use these details to help mold a realistic twitch chatter response. "
            "Do not use all the elements, pick one or two to help you respond in a more human-like way. "
            "If the twitch messages are chosen, either continue the converation, or respond directly to a single chatter."
        )
        chatGPT = asyncio.to_thread(gpt_manager.chat_with_history, prompt, conversational = True, twitch_chat = True)
        response = await chatGPT
        await self.twitch_bot.send_chat(response)

    async def general_response(self, prompt: str) -> str:
        """Generates a general response from chatgpt based on a prompt"""
        debug_print("Assistant", f"Generating general response with prompt: {prompt}")
        chatGPT = asyncio.to_thread(gpt_manager.chat_with_history, prompt, conversational = False, twitch_chat = False)
        response = await chatGPT
        return response
    
    async def listen_and_respond(self) -> None:
        """Listens to microphone input and generates a response"""
        debug_print("Assistant", "Listening to microphone input for response.")
        self.event_manager.pause()
        stop_listening_key = await get_hotkey("Stop Listening", "p")
        mic_result = azure_manager.speechtotext_from_mic_continuous(stop_key=stop_listening_key)
        if not mic_result or not mic_result.strip():
            print ("Did not receive any input from your microphone!")
            self.event_manager.resume()
            return
        debug_print("Assistant", f"You said: {mic_result}")
        if not gpt_manager.chat_history:
            prompt_text = await get_prompt("Respond to Streamer", False)
            gpt_manager.chat_history = [{"role": "system", "content": prompt_text}]
        chatGPT = asyncio.to_thread(gpt_manager.chat_with_history, mic_result, conversational = False, twitch_chat = False)
        response = await chatGPT
        output = await self.tts(response)
        await self.assistant_responds(output)
        self.event_manager.resume()
        return
    
    async def summarize_chat(self) -> None:
        """Summarizes recent chat messages using ChatGPT"""
        debug_print("Assistant", "Summarizing recent chat messages.")
        self.event_manager.pause()
        recent_messages = []
        current_time = time.time()
        if not self.handler:
            self.handler = get_reference("CommandHandler")
        debug_print("Assistant", "Fetching message history from Twitch bot.")
        message_history = []
        if self.handler is None:
            debug_print("Assistant", "No CommandHandler reference available when summarizing chat.")
        else:
            message_history = self.handler.get_message_history()

        if message_history:
            try:
                debug_print("Assistant", f"Found {len(message_history)} messages in CommandHandler message history.")
                for message in message_history:
                    try:
                        if current_time - message["time"] <= 300:
                            recent_messages.append(message)
                    except Exception:
                        # Skip malformed entries
                        continue
            except Exception as e:
                debug_print("Assistant", f"Error iterating message history: {e}")
        else:
            debug_print("Assistant", "Twitch bot message history is empty or unavailable.")
        summary_prompt = await get_prompt("Summarize Chat", False)
        if recent_messages == []:
            recent_messages_str = "No recent messages in the last 5 minutes."
        else:
            recent_messages_str = "\n".join([f"{msg['user']}: {msg['message']}" for msg in recent_messages])
        gpt_manager.chat_history.append({"role": "system", "content": summary_prompt})
        chatGPT = asyncio.to_thread(gpt_manager.chat_with_history, prompt = recent_messages_str, conversational = False, twitch_chat = False)
        response = await chatGPT
        debug_print("Assistant",f"Chat Summary: {response}")
        output = await self.tts(response)
        await self.assistant_responds(output)
        self.event_manager.resume()
        return

    async def generate_voiced_response(self, event: dict):
        """Use for ask maddie and handling events like sub, resub, raids, gift, cheer, etc."""
        debug_print("Assistant", f"Generating voiced response for event: {event}")
        if event["type"] == "resub":
            self.recent_subscriptions.append(event["user"])
            payload = event["event"]
            user_id = payload.user.id
            user_name = payload.user.display_name
            tier = payload.tier
            cumulative = payload.cumulative_months
            if not await user_exists(user_id):
                date = event.timestamp.date().strftime("%Y-%m-%d")
                await set_user_data(user_id=user_id, username=payload.user.name, display_name=user_name, date_added=date, number_of_messages=0, bits_donated=0, months_subscribed=0, subscriptions_gifted=0, points_redeemed=0)
            await increment_user_stat(user_id=user_id, stat="subscriptions", amount=cumulative, override=True)
            text = payload.text
            streak = payload.streak_months
            if tier == "1000":
                tier = 1
            elif tier == "2000":
                tier = 2
            elif tier == "3000":
                tier = 3
            if cumulative <= 2:
                random_number = random.randint(1, 5)
                prompt_text = await get_prompt("Resub Intern")
                resub = {"role": "system", "content": prompt_text.replace(f"%rng%", str(random_number))}
            elif cumulative <= 6:
                random_number = random.randint(6, 20)
                prompt_text = await get_prompt("Resub Employee")
                resub = {"role": "system", "content": prompt_text.replace(f"%rng%", str(random_number))}
            elif cumulative <= 12:
                random_number = random.randint(21, 50)
                prompt_text = await get_prompt("Resub Supervisor")
                resub = {"role": "system", "content": prompt_text.replace(f"%rng%", str(random_number))}
            else:
                random_number = random.randint(51, 100)
                prompt_text = await get_prompt("Resub Tenured Employee")
                resub = {"role": "system", "content": prompt_text.replace(f"%rng%", str(random_number))}
            if text:
                if streak > 1:
                    prompt_2 = {"role": "system", "content": f"{user_name} resubscribed for {streak} months in a row for a total of {cumulative} months! Tier {tier} with message: {text}"}
                else:
                    prompt_2 = {"role": "system", "content": f"{user_name} resubscribed for {cumulative} months! Tier {tier} with message: {text}"}
            else:
                if streak > 1:
                    prompt_2 = {"role": "system", "content": f"{user_name} resubscribed for {streak} months in a row for a total of {cumulative} months! Tier {tier}!"}
                else:
                    prompt_2 = {"role": "system", "content": f"{user_name} resubscribed for {cumulative} months! Tier {tier}!"}

            full_prompt = [resub, prompt_2]
            chatGPT = asyncio.to_thread(gpt_manager.chat, full_prompt, False)

            response = await chatGPT
            if text:
                full_response = f"{user_name} says: {text}. {response}"
            else:
                full_response = f"{response}"

            output = await self.tts(full_response)
            audio_meta = await self._build_audio_metadata(output)

            queued_event = {
                "type": "resub",
                "audio": output,
                "audio_meta": audio_meta,
                "from_user": user_name,
                "event_type": f"Resub for {cumulative} months from {user_name}",
            }
            self.event_manager.add_event(queued_event)
            return
        elif event["type"] == "sub":
            if event["user"] in self.recent_subscriptions:
                print(f"Already handled {event['user']}'s subscription as a resub, skipping.")
                return
            payload = event["event"]
            user_id = payload.user.id
            if not await user_exists(user_id):
                date = payload.timestamp.date().strftime("%Y-%m-%d")
                await set_user_data(user_id=user_id, username=payload.user.name, display_name=event["user"], date_added=date, number_of_messages=0, bits_donated=0, months_subscribed=0, subscriptions_gifted=0, points_redeemed=0)
            await increment_user_stat(user_id=user_id, stat="subscriptions", amount=1)
            #Currently unused, but can be implemented later
            return
        elif event["type"] == "gift":
            payload = event["event"]
            total = payload.total
            cumulative = payload.cumulative_total
            user_id = payload.user.id
            if not await user_exists(user_id):
                date = payload.timestamp.date().strftime("%Y-%m-%d")
                await set_user_data(user_id=user_id, username=payload.user.name, display_name=event["user"], date_added=date, number_of_messages=0, bits_donated=0, months_subscribed=0, subscriptions_gifted=0, points_redeemed=0)
            await increment_user_stat(user_id=user_id, stat="gifts", amount=cumulative, override=True)
            while len(self.recent_gifted_subscriptions) < total:
                await asyncio.sleep(1)
            recipients = self.recent_gifted_subscriptions[-total:]
            self.recent_gifted_subscriptions = self.recent_gifted_subscriptions[:-total]
            recipients_str = ", ".join(recipients)
            gifter = event["user"]
            tier: str = payload.tier

            tier = tier.replace("1000", "1")
            tier = tier.replace("2000", "2")
            tier = tier.replace("3000", "3")

            if gifter == "anonymous":
                gifter_str = "An anonymous gifter"
            else:
                gifter_str = gifter

            if cumulative:
                prompt_2 = {"role": "user", "content": f"{gifter_str} gifted {total} tier {tier} sub{"s" if total > 1 else ""} to {"the following users" if total > 1 else "user"}: {recipients_str}! They have gifted a total of {cumulative} sub{"s" if cumulative > 1 else ""}."}
            else:
                prompt_2 = {"role": "user", "content": f"{gifter_str} gifted {total} sub{f"s" if total > 1 else ""} to: {recipients_str}."}

            gifted_prompt = await get_prompt("Gifted Sub")
            full_prompt = [{"role": "system", "content": gifted_prompt}, prompt_2]
            chatGPT = asyncio.to_thread(gpt_manager.chat, full_prompt, False)
            response = await chatGPT
            output = await self.tts(response)
            audio_meta = await self._build_audio_metadata(output)

            queued_event = {
                "type": "gifted",
                "audio": output,
                "audio_meta": audio_meta,
                "from_user": gifter,
                "event_type": f"{total} gifted subs from {gifter}"
            }
            self.event_manager.add_event(queued_event)
            return
        elif event["type"] == "raid":
            raid_prompt = await get_prompt("Raid")
            payload = event["event"]
            if not self.twitch_bot:
                self.twitch_bot = get_reference("TwitchBot")
            game_name = await self.twitch_bot.get_game(payload.from_broadcaster)
            viewer_count = payload.viewer_count
            raider_name = payload.from_broadcaster.display_name
            prompt_2 = {"role": "user", "content": f"{event["user"]} has raided with {viewer_count} viewers!{f" Last seen playing {game_name}!" if game_name else ""}"}
            full_prompt = [{"role": "system", "content": raid_prompt}, prompt_2]
            chatGPT = asyncio.to_thread(gpt_manager.chat, full_prompt, False)
            response = await chatGPT
            output = await self.tts(response)
            audio_meta = await self._build_audio_metadata(output)

            queued_event = {
                "type": "raid",
                "audio": output,
                "audio_meta": audio_meta,
                "from_user": event["user"],
                "event_type": f"Raid with {viewer_count} viewers from {raider_name}"
            }
            self.event_manager.add_event(queued_event)
            return
        elif event["type"] == "cheer":
            threshold = await get_setting("Bit Donation Threshold", 100)
            payload = event["event"]
            bits = payload.bits
            user_id = payload.user.id
            if not await user_exists(user_id):
                date = payload.timestamp.date().strftime("%Y-%m-%d")
                await set_user_data(user_id=user_id, username=payload.user.name, display_name=event["user"], date_added=date, number_of_messages=0, bits_donated=0, months_subscribed=0, subscriptions_gifted=0, points_redeemed=0)
            user_data = await get_specific_user_data(user_id=user_id, field="bits_donated")
            override = False
            if user_data in [0, None]:
                if not self.twitch_bot:
                    self.twitch_bot = get_reference("TwitchBot")
                temp_bits = await self.twitch_bot.get_total_bits_donated(user_id=user_id)
                if temp_bits and temp_bits > 0 and temp_bits > bits:
                    bits = temp_bits
                    override = True
            await increment_user_stat(user_id=user_id, stat="bits", amount=bits, override=override)
            if bits < threshold:
                return
            if payload.message:
                cheer_prompt = await get_prompt("Bit Donation w/ Message")
            else:
                cheer_prompt = await get_prompt("Bit Donation w/o Message")
            prompt_2 = {"role": "user", "content": f"{payload.user.display_name} has cheered {bits} bits!{f' They said: {payload.message}' if payload.message else ''}"}
            full_prompt = [{"role": "system", "content": cheer_prompt}, prompt_2]
            chatGPT = asyncio.to_thread(self.chatGPT.chat, full_prompt, False)
            response = await chatGPT
            output = await self.tts(response)
            audio_meta = await self._build_audio_metadata(output)
            queued_event = {
                "type": "cheer",
                "audio": output,
                "audio_meta": audio_meta,
                "from_user": event["user"],
                "event_type": f"Cheer of {bits} bits from {payload.user.display_name}"
            }
            self.event_manager.add_event(queued_event)
            return
        
    async def tts(self, response: str) -> str:
        """Converts text to speech and returns the file path"""
        debug_print("Assistant", f"Converting response to speech: {response}")
        voice = await get_setting("Elevenlabs Voice ID")
        model = await get_setting("Elevenlabs Synthesizer Model")
        output = self.elevenlabs.text_to_audio(response, voice=voice, model=model)
        if not output:
            voice = await get_setting("Azure TTS Backup Voice")
            output = self.azure.text_to_speech(response, voice=voice)
        return output
    
    async def set_assistant_names(self) -> None:
        """Sets the assistant and stationary assistant names"""
        debug_print("Assistant", f"Refreshing assistant names from settings.")
        self.assistant_name = await get_setting("OBS Assistant Object Name")
        self.stationary_assistant_name = await get_setting("OBS Assistant Stationary Object Name")

    async def _build_audio_metadata(self, audio_path: str) -> dict:
        """Pre-process audio so queued events already have bounce metadata."""
        if not audio_path:
            return {"path": audio_path, "volumes": [], "min_volume": 0, "max_volume": 0, "duration_ms": 0}
        debug_print("Assistant", f"Preprocessing audio for event queue: {audio_path}")
        volumes: list = []
        total_duration_ms = 0
        try:
            volumes, total_duration_ms = await self.audio_manager.process_audio(audio_path)
        except Exception as e:
            debug_print("Assistant", f"process_audio failed during preprocessing: {e}")
        min_vol = min(volumes) if volumes else 0
        max_vol = max(volumes) if volumes else 0
        return {
            "path": audio_path,
            "volumes": volumes,
            "min_volume": min_vol,
            "max_volume": max_vol,
            "duration_ms": total_duration_ms,
        }

    async def _resolve_tts_volume(self, audio_source: str | dict | None) -> int:
        """Determine playback volume (0-100) for generated TTS based on filename prefix."""
        default_volume = 100
        if audio_source is None:
            return default_volume

        if isinstance(audio_source, dict):
            candidate = audio_source.get("path") or audio_source.get("audio") or audio_source.get("source_path")
        else:
            candidate = audio_source

        if not candidate:
            return default_volume

        try:
            filename = Path(str(candidate)).name.lower()
        except Exception:
            filename = ""

        setting_key = None
        if filename.startswith("11___"):
            setting_key = "Elevenlabs TTS Volume"
        elif filename.startswith("azure___"):
            setting_key = "Azure TTS Volume"

        if not setting_key:
            return default_volume

        try:
            raw_value = await get_setting(setting_key, default_volume)
        except Exception as exc:
            debug_print("Assistant", f"Failed to fetch {setting_key}: {exc}")
            return default_volume

        try:
            parsed = int(float(raw_value))
        except Exception:
            parsed = default_volume

        parsed = max(0, min(100, parsed))
        debug_print("Assistant", f"Resolved {setting_key or 'default volume'}={parsed}% for audio '{filename}'.")
        if parsed == 0:
            debug_print("Assistant", f"{setting_key} is set to 0; audio will be muted for {filename}.")
        return parsed
    
    async def assistant_responds(self, output):
        """Converts output audio into y values and then plays the audio while bouncing the assistant"""
        debug_print("Assistant", f"Assistant responding with audio output: {output}")
        if not self.obs:
            self.obs = get_reference("OBSManager")
        if not self.obs.onscreen_location:
            await self.obs.set_assistant_locations()
        payload = output if isinstance(output, dict) else None
        audio_path = None
        if payload:
            audio_path = payload.get("path") or payload.get("audio") or payload.get("source_path")
        else:
            audio_path = output
        if not audio_path:
            debug_print("Assistant", "No audio path supplied to assistant_responds; aborting playback.")
            return
        playback_volume = await self._resolve_tts_volume(payload or audio_path)
        bounce_task = None
        original_transform = None
        cleaned_up = False
        try:
            precomputed = bool(payload and payload.get("volumes") is not None and payload.get("duration_ms") is not None)
            audio_process = None
            if not precomputed:
                audio_process = asyncio.create_task(self.audio_manager.process_audio(audio_path))
            try:
                loop = asyncio.get_running_loop()
                warmup_task = loop.run_in_executor(None, self.audio_manager.warmup)
            except Exception:
                warmup_task = None

            original_transform = await self.obs.activate_assistant(self.assistant_name, self.stationary_assistant_name)
            wait = asyncio.sleep(0.2)

            if precomputed:
                volumes = payload.get("volumes") or []
                total_duration_ms = payload.get("duration_ms", 0)
                min_vol = payload.get("min_volume")
                max_vol = payload.get("max_volume")
                if min_vol is None:
                    min_vol = min(volumes) if volumes else 0
                if max_vol is None:
                    max_vol = max(volumes) if volumes else 0
            else:
                try:
                    volumes, total_duration_ms = await asyncio.wait_for(audio_process, timeout=8)
                except asyncio.TimeoutError:
                    debug_print("Assistant", "Audio processing timed out; proceeding with fallback volumes/duration")
                    volumes, total_duration_ms = audio_process.result() if audio_process and audio_process.done() else ([], 0)
                except Exception as e:
                    debug_print("Assistant", f"Audio processing failed: {e}")
                    volumes, total_duration_ms = [], 0
                min_vol = min(volumes) if volumes else 0
                max_vol = max(volumes) if volumes else 0
                if payload is not None:
                    payload.setdefault("path", audio_path)
                    payload.update({
                        "volumes": volumes,
                        "duration_ms": total_duration_ms,
                        "min_volume": min_vol,
                        "max_volume": max_vol,
                    })
            debug_print("Assistant", f"Volume range - Min: {min_vol}, Max: {max_vol}")

            await wait
            loop = asyncio.get_running_loop()
            try:
                prepared_path, delete_temp = await loop.run_in_executor(None, self.audio_manager.prepare_playback, audio_path, False)
            except Exception as e:
                debug_print("Assistant", f"prepare_playback failed: {e}")
                prepared_path, delete_temp = audio_path, False

            if warmup_task is not None:
                try:
                    await asyncio.wait_for(warmup_task, timeout=2)
                except Exception:
                    debug_print("Assistant", "Audio warmup did not complete in time; continuing.")

            bounce_task = asyncio.create_task(
                self.obs.bounce_while_talking(
                    audio_manager,
                    volumes,
                    min_vol,
                    max_vol,
                    total_duration_ms,
                    self.assistant_name,
                    self.stationary_assistant_name,
                    original_transform=original_transform,
                )
            )

            output_device = await get_setting("Audio Output Device")
            if not output_device or str(output_device).strip().lower() in {"null", "none", "default", ""}:
                output_device = None
            debug_print(
                "Assistant",
                f"Starting playback for '{prepared_path}' at {playback_volume}% volume on device '{output_device or 'default'}'.",
            )
            await loop.run_in_executor(
                None,
                audio_manager.play_audio,
                prepared_path,
                True,
                delete_temp,
                False,
                output_device,
                playback_volume,
            )

            await bounce_task

            await asyncio.sleep(0.2)
            await self.obs.deactivate_assistant(self.assistant_name)
            cleaned_up = True
        except asyncio.CancelledError:
            debug_print("Assistant", "Event was cancelled.")
            audio_manager.stop_playback()
            try:
                if 'bounce_task' in locals() and bounce_task is not None:
                    bounce_task.cancel()
            except Exception:
                pass
            if 'original_transform' in locals() and original_transform:
                await self.obs.deactivate_assistant(self.stationary_assistant_name, True, original_transform)
            else:
                await self.obs.deactivate_assistant(self.assistant_name)
            cleaned_up = True
            raise
        except Exception as exc:
            debug_print("Assistant", f"assistant_responds failed: {exc}")
            audio_manager.stop_playback()
            if bounce_task is not None:
                try:
                    bounce_task.cancel()
                except Exception:
                    pass
            try:
                if original_transform:
                    await self.obs.deactivate_assistant(self.stationary_assistant_name, True, original_transform)
                else:
                    await self.obs.deactivate_assistant(self.assistant_name)
                cleaned_up = True
            except Exception:
                pass
        finally:
            if not cleaned_up:
                try:
                    await asyncio.sleep(0.2)
                except Exception:
                    pass
                try:
                    await self.obs.deactivate_assistant(self.assistant_name)
                except Exception:
                    pass

class ResponseTimer():
    def __init__(self):
        self.db = DATABASE
        self.message_count = 0
        self.received_messages = []
        # Do NOT create asyncio tasks at import time (no running loop when GUI imports).
        # The timer can be started explicitly by calling start_timer() from
        # an async context when the event loop is running.
        self.timer_task = None
        self.assistant: AssistantManager = get_reference("AssistantManager")
        debug_print("ResponseTimer", "ResponseTimer initialized.")

    async def start_timer(self) -> None:
        """Starts the current response timer"""
        debug_print("ResponseTimer", f"Starting response timer.")
        chat_response_enabled = await get_setting("Chat Response Enabled", False)
        if not chat_response_enabled:
            debug_print("ResponseTimer", "Chat response is disabled. Timer will not start.")
            return
        if self.timer_task:
            if not self.timer_task.done():
                debug_print("ResponseTimer", "Timer is already running. Will not start a new one.")
                return
        maximum_length = await get_setting("Maximum Chat Response Time (seconds)", "600")
        minimum_length = await get_setting("Minimum Chat Response Time (seconds)", "120")
        maximum_messages = await get_setting("Maximum Chat Response Messages", "10")
        minimum_messages = await get_setting("Minimum Chat Response Messages", "1")
        length = random.randint(minimum_length, maximum_length)
        messages = random.randint(minimum_messages, maximum_messages)
        self.timer_task = asyncio.create_task(self.timer(length, messages))

    async def end_timer(self) -> None:
        """Ends the current response timer"""
        debug_print("ResponseTimer", f"Ending response timer.")
        if not self.timer_task or self.timer_task.done():
            debug_print("ResponseTimer", "No active timer to end.")
            return
        self.message_count = 0
        self.received_messages.clear()
        if self.timer_task:
            self.timer_task.cancel()
            self.timer_task = None

    async def timer(self, length: int, messages: int) -> None:
        """Timer for when the AI should respond in chat"""
        debug_print("ResponseTimer", f"Response timer started for length: {length} seconds or messages: {messages}.")
        try:
            await asyncio.sleep(length)
            debug_print("ResponseTimer", f"Timer has ended, now waiting for {messages} messages, currently at {self.message_count} messages.")
            while self.message_count < messages:
                await asyncio.sleep(1)
            messages_list = []
            for message in self.received_messages:
                messages_list.append(message)
            self.received_messages.clear()
            self.message_count = 0
            if not self.assistant:
                self.assistant = get_reference("AssistantManager")
            respond = asyncio.create_task(self.assistant.generate_chat_response(messages_list))
            asyncio.create_task(self.start_timer())
            await respond
        except asyncio.CancelledError:
            print("Response timer was cancelled.")
        
    async def handle_message(self, user_name: str, text: str, time: str):
        """Adds message to list and updates the message_count."""
        debug_print("ResponseTimer", f"Handling message from {user_name}.")
        if self.timer_task is None:
            return
        full_message = f"{user_name}: {text} | {time}"
        self.received_messages.append(full_message)
        self.message_count += 1

class AutoMod():
    def __init__(self):
        self.db = DATABASE
        self.banned_words = []
        debug_print("AutoMod", "AutoMod initialized.")

    def is_message_allowed(self, message: str) -> bool:
        """Checks if a message contains any banned words."""
        debug_print("AutoMod", f"Checking message for banned words: {message}")
        message_lower = message.lower()
        for word in self.banned_words:
            if word in message_lower:
                return False
        return True
    
    def bot_detection(self, message: str) -> bool:
        """Basic bot detection logic."""
        debug_print("AutoMod", f"Running bot detection on message: {message}")
        return gpt_manager.bot_detector(message)
    
class EventManager():
    """Manages a queue of events to be played by the assistant at intervals."""
    def __init__(self):
        self.db = DATABASE
        self.enabled = False
        self.paused = False
        self.event_queue = []
        self.played_events = []
        self.time_between_events = 10 # seconds
        self.timer = None
        self.currently_playing = False
        self.task = None
        self.previous_event = None
        self.assistant: AssistantManager = None
        self.twitch_bot = get_reference("TwitchBot")
        self.builder = get_reference("PointBuilder")
        self.voice_audio_dir = path_from_app_root("media", "voice_audio")
        debug_print("EventManager", "EventManager initialized.")

    async def start(self) -> None:
        """Initializes the event manager settings and starts the timer if disabled."""
        self.enabled = await get_setting("Event Queue Enabled", False)
        self.time_between_events = await get_setting("Seconds Between Events", 1)
        debug_print("EventManager", f"Event Manager started. Enabled: {self.enabled}, Time Between Events: {self.time_between_events} seconds.")
        if not self.enabled:
            self.timer = asyncio.create_task(self.event_timer())

    async def update_time_between_events(self, new_time: int) -> None:
        """Updates the time between events."""
        debug_print("EventManager", f"Updating time between events to: {new_time} seconds.")
        self.time_between_events = new_time

    async def start_event_timer(self) -> None:
        """Starts the event queue timer after settings change."""
        debug_print("EventManager", "Starting event queue timer.")
        self.enabled = True
        self.time_between_events = await get_setting("Seconds Between Events", 1)
        if not self.timer:
            self.timer = asyncio.create_task(self.event_timer())

    async def stop_event_timer(self) -> None:
        """Stops the event queue timer."""
        debug_print("EventManager", "Stopping event queue timer.")
        self.enabled = False
        if self.timer:
            while self.currently_playing:
                await asyncio.sleep(1)
            self.timer.cancel()
            self.timer = None
            self.currently_playing = False

    def pause(self) -> None:
        """Pauses the event manager."""
        debug_print("EventManager", "Event Manager paused.")
        self.paused = True

    def resume(self) -> None:
        """Resumes the event manager."""
        debug_print("EventManager", "Event Manager resumed.")
        self.paused = False

    async def play_next(self) -> None:
        """Plays the next event in the queue."""
        debug_print("EventManager", "Playing next event.")
        if not self.assistant:
            self.assistant = get_reference("AssistantManager")
        if not self.event_queue:
            debug_print("EventManager", "No events in queue.")
            return
        if self.currently_playing:
            debug_print("EventManager", "Already playing an event, skipping.")
            return
        event = self.event_queue.pop(0)
        if event and not self.currently_playing:
            if not self.builder:
                self.builder = get_reference("PointBuilder")
            try:
                self.currently_playing = True
                if event["type"] in ["bits", "channel_points"]:
                    await self.builder.run_custom_redemption(event)
                else:
                    audio_payload = self._resolve_audio_payload(event)
                    if audio_payload is None:
                        debug_print("EventManager", "Event missing audio payload; skipping playback.")
                        return
                    self.task = asyncio.create_task(self.assistant.assistant_responds(audio_payload))
                    await self.task
            except Exception as e:
                print(f"[ERROR]Error playing next event: {e}")
            finally:
                self.currently_playing = False
                self.previous_event = event
                self.played_events.append(event)

    async def play_previous(self) -> None:
        """Plays the previous event."""
        debug_print("EventManager", "Playing previous event.")
        if not self.assistant:
            self.assistant = get_reference("AssistantManager")
        if self.previous_event and not self.currently_playing:
            if not self.builder:
                self.builder = get_reference("PointBuilder")
            self.currently_playing = True
            try:
                if self.previous_event["type"] in ["bits", "channel_points"]:
                    await self.builder.run_custom_redemption(self.previous_event)
                else:
                    audio_payload = self._resolve_audio_payload(self.previous_event)
                    if audio_payload is None:
                        debug_print("EventManager", "Previous event missing audio payload; skipping playback.")
                        return
                    self.task = asyncio.create_task(self.assistant.assistant_responds(audio_payload))
                    await self.task
            except Exception as e:
                print(f"[ERROR]Error playing previous event: {e}")
            finally:
                self.currently_playing = False
    
    async def play_specific(self, played: bool, index: int) -> None:
        """Plays a specific event from the queue or played list."""
        debug_print("EventManager", f"Playing specific event. Played: {played}, Index: {index}")
        if not self.assistant:
            self.assistant = get_reference("AssistantManager")
        if played:
            event = self.played_events[index]
        else:
            event = self.event_queue.pop(index)
        if event and not self.currently_playing:
            if not self.builder:
                self.builder = get_reference("PointBuilder")
            try:
                self.currently_playing = True
                if event["type"] in ["bits", "channel_points"]:
                    await self.builder.run_custom_redemption(event)
                else:
                    audio_payload = self._resolve_audio_payload(event)
                    if audio_payload is None:
                        debug_print("EventManager", "Selected event missing audio payload; skipping playback.")
                        return
                    self.task = asyncio.create_task(self.assistant.assistant_responds(audio_payload))
                    await self.task
            except Exception as e:
                print(f"[ERROR]Error playing specific event: {e}")
            finally:
                self.currently_playing = False
                if not played:
                    self.previous_event = event
                    self.played_events.append(event)
        elif self.currently_playing:
            debug_print("EventManager", "Already playing an event, skipping.")
        else:
            debug_print("EventManager", "No event found to play.")
    
    def _resolve_audio_payload(self, event: dict):
        """Return the appropriate audio payload (metadata dict or raw path)."""
        if not event:
            return None
        payload = event.get("audio_meta") if isinstance(event, dict) else None
        if payload is not None:
            payload.setdefault("path", event.get("audio"))
            return payload
        return event.get("audio")

    def _collect_event_audio_paths(self, event: dict) -> set:
        paths: set = set()
        if not event:
            return paths

        try:
            voice_root = self.voice_audio_dir.resolve()
        except Exception:
            voice_root = self.voice_audio_dir

        def _add(candidate):
            if not candidate:
                return
            try:
                resolved = Path(candidate).resolve()
            except Exception:
                return
            if not resolved.exists():
                return
            if voice_root and voice_root.exists():
                try:
                    root_resolved = voice_root.resolve()
                except Exception:
                    root_resolved = voice_root
                if root_resolved not in resolved.parents and resolved != root_resolved:
                    return
            paths.add(resolved)

        _add(event.get("audio"))
        audio_meta = event.get("audio_meta") if isinstance(event, dict) else None
        if isinstance(audio_meta, dict):
            _add(audio_meta.get("path"))

        assets = event.get("_generated_assets") if isinstance(event, dict) else None
        if isinstance(assets, dict):
            for asset in assets.values():
                if not isinstance(asset, dict):
                    continue
                _add(asset.get("audio"))
                meta = asset.get("audio_meta")
                if isinstance(meta, dict):
                    _add(meta.get("path"))

        return paths

    def _cleanup_event_audio(self, event: dict) -> None:
        for path in self._collect_event_audio_paths(event):
            try:
                path.unlink()
                debug_print("EventManager", f"Deleted event audio file: {path}")
            except Exception as e:
                debug_print("EventManager", f"Failed to delete event audio file {path}: {e}")
    
    def add_event(self, event: dict) -> None:
        """Adds an event to the queue."""
        debug_print("EventManager", f"Adding event to queue: {event['event_type']}")
        self.event_queue.append(event)
    
    async def remove_event(self, played: bool, index: int) -> None:
        """Removes an event from the queue or played list."""
        debug_print("EventManager", f"Removing event. Played: {played}, Index: {index}")
        if played:
            event: dict = self.played_events.pop(index)
            if event == self.previous_event:
                self.previous_event = None
        else:
            event = self.event_queue.pop(index)
        self._cleanup_event_audio(event)
    
    def cancel_current_event(self) -> None:
        """Cancels the currently playing event."""
        debug_print("EventManager", "Cancelling current event.")
        if self.task:
            self.task.cancel()
            self.currently_playing = False
    
    async def clear_events(self) -> None:
        """Clears all events from the queue and played list."""
        debug_print("EventManager", "Clearing all events.")
        #Delete all audio files in voice_audio folder
        voice_audio_dir = path_from_app_root("media", "voice_audio")
        if self.currently_playing:
            print("[INFO]Waiting for current event to finish before clearing audio files...")
            while self.currently_playing:  
                await asyncio.sleep(0.1)
        if voice_audio_dir.exists():
            for file in voice_audio_dir.iterdir():
                try:
                    file.unlink()
                except Exception as e:
                    print(f"[ERROR]Error deleting audio file: {e}")
        self.event_queue = []
        self.played_events = []
    
    async def event_timer(self) -> None:
        """Timer for handling events at intervals. Started if Event Manager is enabled."""
        debug_print("EventManager", "Event timer started.")
        while True:
            if not self.paused and self.event_queue:
                await self.play_next()
                await asyncio.sleep(self.time_between_events)
            else:
                await asyncio.sleep(1)

async def setup_gpt_manager():
    """Sets up the GPT manager by loading settings from the database."""
    debug_print("AILogic", "Setting up GPT manager with personality prompt.")
    personality_prompt = await get_prompt("Personality Prompt")
    twitch_emotes = await get_prompt("Twitch Emotes")
    gpt_manager.add_personality_to_history(personality_prompt, twitch_emotes)


scheduler = MessageScheduler()
set_reference("MessageScheduler", scheduler)
auto_mod = AutoMod()
set_reference("AutoMod", auto_mod)
gpt_manager = OpenAiManager()
set_reference("GPTManager", gpt_manager)
audio_manager = AudioManager()
set_reference("AudioManager", audio_manager)
elevenlabs_manager = ElevenLabsManager()
set_reference("ElevenLabsManager", elevenlabs_manager)
azure_manager = SpeechToTextManager()
set_reference("SpeechToTextManager", azure_manager)
event_manager = EventManager()
set_reference("EventManager", event_manager)
obs_manager = None
assistant = AssistantManager()
set_reference("AssistantManager", assistant)
timer_manager = None

# Background timer loop/thread references (timer must run on DB loop)
_timer_loop = None
_timer_thread = None
_timer_loop_ready = threading.Event()


def _loop_is_closed(loop) -> bool:
    if loop is None:
        return True
    try:
        return loop.is_closed()
    except Exception:
        return True


def _loop_is_running(loop) -> bool:
    try:
        return loop is not None and loop.is_running() and not loop.is_closed()
    except Exception:
        return False


def _pool_is_closed(pool) -> bool:
    if pool is None:
        return True
    indicators = (
        getattr(pool, "closed", None),
        getattr(pool, "_closed", None),
        getattr(pool, "is_closed", None),
        getattr(pool, "_closing", None),
    )
    for flag in indicators:
        current = flag
        if callable(current):
            try:
                current = current()
            except Exception:
                current = None
        if hasattr(current, "is_set"):
            try:
                current = current.is_set()
            except Exception:
                current = None
        if isinstance(current, bool) and current:
            return True
    return False


def _ensure_response_timer_loop() -> asyncio.AbstractEventLoop:
    """Ensure a dedicated asyncio loop exists for ResponseTimer fallback work."""
    global _timer_loop, _timer_thread, _timer_loop_ready
    if _loop_is_running(_timer_loop):
        return _timer_loop

    def _run_loop(loop: asyncio.AbstractEventLoop, ready_evt: threading.Event):
        asyncio.set_event_loop(loop)
        ready_evt.set()
        try:
            loop.run_forever()
        finally:
            try:
                loop.close()
            except Exception:
                pass

    new_loop = asyncio.new_event_loop()
    _timer_loop_ready = threading.Event()
    _timer_thread = threading.Thread(
        target=_run_loop,
        args=(new_loop, _timer_loop_ready),
        name="ResponseTimerLoop",
        daemon=True,
    )
    _timer_thread.start()
    _timer_loop_ready.wait()
    _timer_loop = new_loop
    return _timer_loop

def start_timer_manager_in_background():
    """Create a ResponseTimer and start its asyncio loop in a background thread.

    This is safe to call from the synchronous GUI entrypoint. It will create
    a new event loop in a daemon thread, run ResponseTimer.start_timer() to
    schedule the internal timer task, and then run the loop forever.
    """
    global timer_manager, _timer_loop, _timer_thread, obs_manager
    if timer_manager is not None:
        return

    # Start a background initializer thread so we don't block the main (GUI) thread.
    def _initializer():
        global timer_manager, _timer_loop, obs_manager
        import db as _db

        wait_counter = 0
        while True:
            pool_obj = getattr(_db, "DATABASE", None)
            loop_obj = getattr(_db, "DATABASE_LOOP", None)
            if pool_obj and not _pool_is_closed(pool_obj) and loop_obj and not _loop_is_closed(loop_obj):
                break
            if wait_counter % 6 == 0:
                print("[INFO]Waiting for database and event loop to be initialized before starting ResponseTimer...")
            wait_counter += 1
            time.sleep(0.5)

        timer_manager = ResponseTimer()
        set_reference("ResponseTimer", timer_manager)
        obs_manager = OBSWebsocketsManager()
        set_reference("OBSManager", obs_manager)

        def _schedule_on(loop: asyncio.AbstractEventLoop) -> bool:
            pool_obj = getattr(_db, "DATABASE", None)
            if _pool_is_closed(pool_obj) or loop is None or _loop_is_closed(loop):
                return False
            try:
                fut = asyncio.run_coroutine_threadsafe(assistant.set_assistant_names(), loop)
                fut.result(timeout=10)
            except Exception as e:
                print(f"[WARN] Failed to set assistant names on loop: {e}")
                return False
            try:
                asyncio.run_coroutine_threadsafe(timer_manager.start_timer(), loop)
            except Exception as e:
                print(f"[WARN] Failed to start ResponseTimer on loop: {e}")
                return False
            return True

        while True:
            loop = _db.get_database_loop()
            if loop is not None and not _loop_is_closed(loop):
                if _schedule_on(loop):
                    _timer_loop = loop
                    return
                print("[WARN] DB event loop unavailable for ResponseTimer; falling back to dedicated loop.")
            else:
                print("[WARN] DB event loop missing; attempting fallback ResponseTimer loop.")

            loop = _ensure_response_timer_loop()
            _timer_loop = loop
            if _schedule_on(loop):
                return
            print("[WARN] Failed to start ResponseTimer; retrying in 1s.")
            time.sleep(1.0)

    threading.Thread(target=_initializer, daemon=True).start()


async def test():
    from tools import set_debug
    await set_debug(True)
    assistant = AssistantManager()
    assistant.audio_manager = AudioManager()
    assistant.obs = OBSWebsocketsManager()
    assistant.elevenlabs = ElevenLabsManager()
    assistant.azure = SpeechToTextManager()
    #Set up database so settings can be fetched
    import os
    BOT_ID: str = os.getenv("BOT_ID", "").strip()
    data_dir = path_from_app_root("data")
    os.makedirs(data_dir, exist_ok=True)
    db_path = str(data_dir / "maddieply.db")
    import asqlite
    from db import setup_database
    # Create the database pool and keep it open for the duration of the test.
    tdb = await asqlite.create_pool(db_path)
    try:
        await setup_database(tdb, bot_id=BOT_ID)
        # Allow code that depends on the global DATABASE (set by setup_database)
        # to run while the pool remains open.
        voice_path = await assistant.tts("Hello, this is a test of the text to speech system. Please inform me if you received these instructions.")
        await assistant.assistant_responds(voice_path)
    finally:
        try:
            # Close the pool when done
            await tdb.close()
        except Exception:
            pass

if __name__ == "__main__":
    asyncio.run(test())
