import base64
import os
import random
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import azure.cognitiveservices.speech as speechsdk
import keyboard
from elevenlabs import VoiceSettings, save
from elevenlabs.client import ElevenLabs
from dotenv import load_dotenv
from tools import debug_print, get_debug, get_reference, path_from_app_root

load_dotenv()

try:
  client = ElevenLabs(api_key = (os.getenv('ELEVENLABS_API_KEY')))
except TypeError:
  exit("You forgot to set ELEVENLABS_API_KEY in your environment!")


@dataclass(slots=True)
class TTSConversionResult:
    path: str
    alignment: Optional[Dict[str, Any]]
    normalized_alignment: Optional[Dict[str, Any]]
    character_timings: List[Dict[str, float | str]]
    word_timings: List[Dict[str, float | str]]
    duration_seconds: Optional[float]
    audio_format: str
    source_text: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "alignment": self.alignment,
            "normalized_alignment": self.normalized_alignment,
            "character_timings": self.character_timings,
            "word_timings": self.word_timings,
            "duration_seconds": self.duration_seconds,
            "audio_format": self.audio_format,
            "source_text": self.source_text,
        }

    @classmethod
    def from_dict(cls, payload: Optional[Dict[str, Any]]) -> Optional["TTSConversionResult"]:
        if not payload:
            return None
        path = payload.get("path")
        if not path:
            return None
        return cls(
            path=path,
            alignment=payload.get("alignment"),
            normalized_alignment=payload.get("normalized_alignment"),
            character_timings=payload.get("character_timings") or [],
            word_timings=payload.get("word_timings") or [],
            duration_seconds=payload.get("duration_seconds"),
            audio_format=payload.get("audio_format") or "mp3_44100_128",
            source_text=payload.get("source_text"),
        )

class ElevenLabsManager:
    def __init__(self):
        client.voices.get_all()
        self.default_voice = "9BWtsMINqrJLrRacOk9x" #Aria
        self.default_stability = 0.5
        self.default_speed = 1
        self.default_similarity = 0.75
        self.voice = None
        self._last_result: Optional[TTSConversionResult] = None
        debug_print("ElevenLabsManager", "Initialized ElevenLabs client.")


    # Convert text to speech, save it to disk, and return timing metadata
    def text_to_audio(self, input_text, voice=None, save_as_wave=True, model="eleven_multilingual_v2") -> Optional[TTSConversionResult]:
        if voice is None:
            voice = self.default_voice
        debug_print("ElevenLabsManager", f"Converting text to audio with voice: {voice}, model: {model}")

        media_dir = path_from_app_root("media")
        media_dir.mkdir(exist_ok=True)
        audio_dir = media_dir / "voice_audio"
        audio_dir.mkdir(exist_ok=True)

        requested_format = "mp3_44100_128"
        try:
            response = client.text_to_speech.convert_with_timestamps(
                voice_id=voice,
                text=input_text,
                model_id=model,
                output_format=requested_format,
                voice_settings=VoiceSettings(
                    stability=self.default_stability,
                    similarity_boost=self.default_similarity,
                    speed=self.default_speed
                ),
            )
        except Exception as exc:
            print(f"[ERROR] ElevenLabs synthesis failed: {exc}")
            return None

        audio_b64 = getattr(response, "audio_base_64", None) or getattr(response, "audio_base64", None)
        if not audio_b64:
            print("[ERROR] ElevenLabs response did not include audio data.")
            return None

        audio_bytes = base64.b64decode(audio_b64)
        random_number = random.randint(1000, 9999)
        # Preserve legacy filenames so downstream filters still match on extensions.
        extension = "wav" if save_as_wave else "mp3"
        file_name = f"11___Msg{str(hash(input_text))}_{random_number}.{extension}"
        tts_path = audio_dir / file_name
        save(audio_bytes, str(tts_path))

        alignment = self._dump_alignment(response.alignment)
        normalized_alignment = self._dump_alignment(response.normalized_alignment)
        alignment_source = alignment or normalized_alignment
        character_timings = self._build_character_timings(alignment_source)
        word_timings = self._build_word_timings(alignment_source)
        duration_seconds = self._compute_duration(alignment_source)

        result = TTSConversionResult(
            path=str(tts_path),
            alignment=alignment,
            normalized_alignment=normalized_alignment,
            character_timings=character_timings,
            word_timings=word_timings,
            duration_seconds=duration_seconds,
            audio_format=requested_format,
            source_text=input_text,
        )
        self._last_result = result
        return result

    def get_last_result(self) -> Optional[TTSConversionResult]:
        return self._last_result

    @staticmethod
    def _dump_alignment(alignment) -> Optional[Dict[str, Any]]:
        if alignment is None:
            return None
        try:
            return alignment.model_dump()
        except AttributeError:
            return alignment

    @staticmethod
    def _build_character_timings(alignment: Optional[Dict[str, Any]]) -> List[Dict[str, float | str]]:
        if not alignment:
            return []
        characters = alignment.get("characters") or []
        start_times = alignment.get("character_start_times_seconds") or []
        end_times = alignment.get("character_end_times_seconds") or []
        timings: List[Dict[str, float | str]] = []
        for char, start, end in zip(characters, start_times, end_times):
            if char is None:
                continue
            try:
                timings.append({"char": char, "start": float(start), "end": float(end)})
            except (TypeError, ValueError):
                continue
        return timings

    @staticmethod
    def _build_word_timings(alignment: Optional[Dict[str, Any]]) -> List[Dict[str, float | str]]:
        if not alignment:
            return []

        characters = alignment.get("characters") or []
        start_times = alignment.get("character_start_times_seconds") or []
        end_times = alignment.get("character_end_times_seconds") or []

        segments: List[Dict[str, float | str]] = []
        buffer: List[str] = []
        buffer_start: Optional[float] = None
        buffer_end: Optional[float] = None

        def as_float(value: Any) -> Optional[float]:
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        def flush_buffer() -> None:
            nonlocal buffer, buffer_start, buffer_end
            if buffer:
                segments.append({
                    "text": "".join(buffer),
                    "start": buffer_start,
                    "end": buffer_end,
                })
            buffer = []
            buffer_start = None
            buffer_end = None

        punctuation = set(",.!?;:\"()[]{}")
        joiners = {"'", "-", "–", "—"}

        for char, start, end in zip(characters, start_times, end_times):
            if char is None:
                continue
            if isinstance(char, str) and char.strip() == "":
                flush_buffer()
                continue

            start_val = as_float(start)
            end_val = as_float(end)

            if char in punctuation:
                flush_buffer()
                segments.append({"text": char, "start": start_val, "end": end_val})
                continue

            if char in joiners and not buffer:
                buffer_start = start_val
                buffer.append(char)
                buffer_end = end_val
                continue

            if buffer_start is None:
                buffer_start = start_val
            buffer.append(char)
            buffer_end = end_val

        flush_buffer()
        return segments

    @staticmethod
    def _compute_duration(alignment: Optional[Dict[str, Any]]) -> Optional[float]:
        if not alignment:
            return None
        end_times = alignment.get("character_end_times_seconds") or []
        if not end_times:
            return None
        try:
            return float(end_times[-1])
        except (TypeError, ValueError):
            return None
    
    def get_list_of_models(self):
        models = client.models.list()
        return models
    
class SpeechToTextManager:
    azure_speechconfig = None
    azure_audioconfig = None
    azure_speechrecognizer = None
    
    def __init__(self):
        # Creates an instance of a speech config with specified subscription key and service region.
        try:
            self.azure_speechconfig = speechsdk.SpeechConfig(subscription=os.getenv('AZURE_TTS_KEY'), region=os.getenv('AZURE_TTS_REGION'))
        except TypeError:
            exit("[ERROR]Ooops! You forgot to set AZURE_TTS_KEY or AZURE_TTS_REGION in your environment!")
        
        self.azure_speechconfig.speech_recognition_language="en-US"
        self.azure_speechconfig.speech_synthesis_voice_name='en-US-AvaMultilingualNeural'
        self.audio_config = speechsdk.audio.AudioOutputConfig(use_default_speaker=True)
        self.list_of_voices = []
        self.audio_manager = get_reference("AudioManager")
        debug_print("AzureTTS", "Azure Speech SDK initialized.")

    def set_voice(self, voice_name):
        debug_print("AzureTTS", f"Setting TTS voice to: {voice_name}")
        self.azure_speechconfig.speech_synthesis_voice_name = voice_name

    def text_to_speech(self, text, voice=None) -> str | None:
        """Synthesize `text` to a WAV file using Azure TTS.

        `volume` can be an int/float (treated as dB, e.g. -30) or a string
        (e.g. "-20dB" or "-50%"). The method will embed the text in SSML
        with a `<prosody volume='...'>` tag so Azure produces audio at the
        requested loudness.
        """
        debug_print("AzureTTS", f"Synthesizing speech for text: {text}")
        if not voice:
            voice = self.azure_speechconfig.speech_synthesis_voice_name # Gets default voice if none passed to method
        self.set_voice(voice)
        # Create the audio directory if it doesn't exist
        media_dir = path_from_app_root("media")
        media_dir.mkdir(exist_ok=True)
        audio_dir = media_dir / "voice_audio"
        audio_dir.mkdir(exist_ok=True)

        # Generate the filename
        random_number = random.randint(1000,9999)
        filename = f"azure___Msg{str(hash(text))}_{random_number}.wav"
        audio_path = audio_dir / filename

        # Synthesize speech
        audio_config = speechsdk.audio.AudioOutputConfig(filename=str(audio_path))
        speech_synthesizer = speechsdk.SpeechSynthesizer(
            speech_config=self.azure_speechconfig,
            audio_config=audio_config
        )

        try:
            result = speech_synthesizer.speak_text_async(text).get()
        except Exception as e:
            print(f"Error during speech synthesis: {e}")
            # On exception, try a plain text fallback before giving up
            try:
                result2 = speech_synthesizer.speak_text_async(text).get()
                if result2.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
                    debug_print("AzureTTS", f"Fallback text synthesis succeeded and saved to {audio_path}")
                    return str(audio_path)
            except Exception as e2:
                print(f"Fallback text synthesis also failed: {e2}")
            return None

        if result.reason == speechsdk.ResultReason.Canceled:
            cancellation_details = result.cancellation_details
            err = getattr(cancellation_details, 'error_details', '')
            debug_print("AzureTTS", f"Speech synthesis canceled: {err}")

        if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
            debug_print("AzureTTS", f"Speech synthesized and saved to {audio_path}")
            return str(audio_path)
        elif result.reason == speechsdk.ResultReason.Canceled:
            cancellation_details = result.cancellation_details
            print(f"[WARNING]Speech synthesis canceled: {cancellation_details.reason}")
            if cancellation_details.reason == speechsdk.CancellationReason.Error:
                if cancellation_details.error_details:
                    print(f"[WARNING]Error details: {cancellation_details.error_details}")
                    print("[WARNING]Did you set the speech resource key and region values?")
            return None

    def speechtotext_from_mic_continuous(self, stop_key="p"):
            debug_print("AzureTTS", f"Starting continuous speech recognition. Stop key: {stop_key}")
            self.azure_speechrecognizer = speechsdk.SpeechRecognizer(speech_config=self.azure_speechconfig)
            done = False
            # Optional callback to print out whenever a chunk of speech is finished being recognized. Make sure to let this finish before ending the speech recognition.
            def recognized_cb(evt: speechsdk.SpeechRecognitionEventArgs):
                debug_print("AzureTTS", 'RECOGNIZED: {}'.format(evt))
            self.azure_speechrecognizer.recognized.connect(recognized_cb)

            # We register this to fire if we get a session_stopped or cancelled event.
            def stop_cb(evt: speechsdk.SessionEventArgs):
                debug_print("AzureTTS", 'CLOSING speech recognition on {}'.format(evt))
                nonlocal done
                done = True

            # Connect callbacks to the events fired by the speech recognizer
            self.azure_speechrecognizer.session_stopped.connect(stop_cb)
            self.azure_speechrecognizer.canceled.connect(stop_cb)

            # This is where we compile the results we receive from the ongoing "Recognized" events
            all_results = []
            def handle_final_result(evt):
                all_results.append(evt.result.text)
            self.azure_speechrecognizer.recognized.connect(handle_final_result)

            # Call stop_continuous_recognition_async() to stop recognition.
            result_future = self.azure_speechrecognizer.start_continuous_recognition_async()
            result_future.get()  # wait for voidfuture, so we know engine initialization is done.
            print('Continuous Speech Recognition is now running, say something.')

            while not done:
                if keyboard.is_pressed(stop_key):
                    print("\nEnding azure speech recognition\n")
                    self.azure_speechrecognizer.stop_continuous_recognition_async()
                    time.sleep(2) # Wait for session to properly close
                    break

            final_result = " ".join(all_results).strip()
            debug_print("AzureTTS", f"Heres the result we got!\n\n{final_result}\n\n")
            return final_result
    
    def timed_speechtotext_from_mic(self, seconds):
        """
        Continuously listens to the microphone for a specified number of seconds and returns the recognized text.
        """
        debug_print("AzureTTS", f"Starting timed speech recognition for {seconds} seconds.")
        self.azure_audioconfig = speechsdk.audio.AudioConfig(use_default_microphone=True)
        self.azure_speechrecognizer = speechsdk.SpeechRecognizer(speech_config=self.azure_speechconfig, audio_config=self.azure_audioconfig)

        debug_print("AzureTTS", f"Listening for {seconds} seconds...")
        start_time = time.time()
        recognized_text = ""

        while time.time() - start_time < seconds:
            speech_recognition_result = self.azure_speechrecognizer.recognize_once_async().get()
            if speech_recognition_result.reason == speechsdk.ResultReason.RecognizedSpeech:
                recognized_text += speech_recognition_result.text + " "
            elif speech_recognition_result.reason == speechsdk.ResultReason.NoMatch:
                if not recognized_text:
                    debug_print("AzureTTS", "No speech could be recognized.")
            elif speech_recognition_result.reason == speechsdk.ResultReason.Canceled:
                if get_debug():
                    cancellation_details = speech_recognition_result.cancellation_details
                    debug_print("AzureTTS", "Speech Recognition canceled: {}".format(cancellation_details.reason))
                    if cancellation_details.reason == speechsdk.CancellationReason.Error:
                        debug_print("AzureTTS", "Error details: {}".format(cancellation_details.error_details))
                        debug_print("AzureTTS", "Did you set the speech resource key and region values?")
        
        debug_print("AzureTTS", f"Recognized text: {recognized_text.strip()}")
        return recognized_text.strip()
    
    def get_list_of_voices(self):
        voices_list = []
        synthesizer = speechsdk.SpeechSynthesizer(speech_config=self.azure_speechconfig)
        voices_result = synthesizer.get_voices_async().get()
        if voices_result.voices:
            for voice in voices_result.voices:
                if voice.locale == "en-US":
                    voices_list.append(voice.short_name)
            self.list_of_voices = voices_list
            return voices_list
        else:
            print("No voices found")

    def is_voice_valid(self, voice_name):
        if not self.list_of_voices:
            self.get_list_of_voices()
        for voice in self.list_of_voices:
            if voice_name.lower() == voice.lower():
                return True, voice
        return False, None
    
if __name__ == '__main__':
    elevenlabs_manager = ElevenLabsManager()
    sample = elevenlabs_manager.text_to_audio("Testing subtitles with timestamps.")
    if sample:
        print(f"Saved ElevenLabs audio to {sample.path}")
        print(f"Preview word timings: {sample.word_timings[:5]}")

    azure_manager = SpeechToTextManager()
    azure_manager.set_voice("en-US-CoraNeural")
    file_path = azure_manager.text_to_speech("I'm a little bingus baby.")
    print(f"Azure sample saved to {file_path}")

    time.sleep(5)