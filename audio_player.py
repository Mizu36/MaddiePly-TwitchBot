import pygame
import pygame._sdl2.audio as sdl2_audio
import time
import os
import asyncio
import tempfile
import traceback
import threading
import subprocess
import soundfile as sf
from mutagen.mp3 import MP3
from pathlib import Path
from tools import debug_print, get_debug
from db import get_setting

if os.name == "nt":
    _ORIG_POPEN = subprocess.Popen
    _CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

    def _hidden_popen(*args, **kwargs):
        startupinfo = kwargs.get("startupinfo")
        if startupinfo is None:
            startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        kwargs["startupinfo"] = startupinfo
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | _CREATE_NO_WINDOW
        return _ORIG_POPEN(*args, **kwargs)

    subprocess.Popen = _hidden_popen

from local_ffmpeg import install, is_installed
from pydub import AudioSegment, utils

AUDIO_DEVICES = []
FFMPEG_DIR = Path(__file__).with_name("ffmpeg_bin")
if not is_installed(str(FFMPEG_DIR)):
    ok, msg = install(str(FFMPEG_DIR))
    if not ok:
        raise RuntimeError(f"FFmpeg install failed: {msg}")

bin_dir = str(FFMPEG_DIR)
os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
os.environ["FFMPEG_BINARY"] = bin_dir + os.sep + ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
os.environ["FFPROBE_BINARY"] = bin_dir + os.sep + ("ffprobe.exe" if os.name == "nt" else "ffprobe")

class AudioManager:
    def __init__(self):
        self.output_device = None
        self.cached_output_device = None
        self._should_stop = False
        self._is_playing = False
        self.device_object = None
        self.list_of_sound_fx = []
        self.prepared_sound_cache: dict[str, dict] = {}
        self.init_mixer()
        debug_print("AudioManager", "AudioManager initialized.")

    def _delete_file_with_retry(self, path: str | None, attempts: int = 5, delay: float = 0.15) -> bool:
        """Attempt to delete `path`, retrying when the OS still locks the file."""
        if not path:
            return False
        last_err = None
        for attempt in range(1, max(1, attempts) + 1):
            try:
                if os.path.exists(path):
                    os.remove(path)
                    debug_print("AudioManager", f"Deleted file: {path}")
                return True
            except Exception as exc:
                last_err = exc
                time.sleep(max(0.0, delay))
        if last_err is not None:
            debug_print(
                "AudioManager",
                f"Failed to delete {path} after {attempts} attempts: {last_err}",
            )
        return False

    def _schedule_delayed_cleanup(self, paths: list[str], wait_seconds: float) -> None:
        if not paths:
            return

        def _cleanup_worker():
            time.sleep(max(0.0, wait_seconds))
            for target in paths:
                self._delete_file_with_retry(target)

        threading.Thread(target=_cleanup_worker, daemon=True).start()

    def _compute_audio_duration(self, path: str | None) -> float | None:
        if not path:
            return None
        try:
            _, ext = os.path.splitext(path)
            ext = ext.lower()
            if ext == ".wav":
                with sf.SoundFile(path) as wav_file:
                    return wav_file.frames / wav_file.samplerate
            if ext == ".mp3":
                mp3_file = MP3(path)
                return mp3_file.info.length
        except Exception as exc:
            debug_print("AudioManager", f"Failed to determine duration for {path}: {exc}")
        return None

    def _wait_for_playback(self, duration: float | None) -> None:
        if duration is None or duration <= 0:
            return
        elapsed = 0.0
        interval = 0.1
        limit = max(0.0, duration)
        while elapsed < limit:
            if self._should_stop:
                debug_print("AudioManager", "Playback flagged to stop early.")
                self._should_stop = False
                break
            time.sleep(interval)
            elapsed += interval

    def init_mixer(self):
        # Initialize mixer with or without a specific device
        if pygame.mixer.get_init():
            pygame.mixer.quit()
        if self.output_device is not None:
            pygame.mixer.init(devicename=self.output_device, frequency=48000, buffer=1024)
        else:
            pygame.mixer.init(frequency=48000, buffer=1024)
        debug_print("AudioManager", f"Pygame mixer initialized with device: {self.output_device}")

    @staticmethod
    def list_output_devices():
        devices = sdl2_audio.get_audio_device_names(iscapture=False)
        for idx, name in enumerate(devices):
            AUDIO_DEVICES.append(name)
        if get_debug():
            print("[DEBUG][AudioManager] Available output devices:")
            for idx, name in enumerate(devices):
                print(f"  [{idx}] {name}")
        return devices

    def set_output_device(self, device_name_or_index):
        debug_print("AudioManager", f"Setting output device to: {device_name_or_index}")
        self.cached_output_device = device_name_or_index
        devices = self.list_output_devices()
        if isinstance(device_name_or_index, int):
            if 0 <= device_name_or_index < len(devices):
                self.output_device = devices[device_name_or_index]
            else:
                print(f"[ERROR][AudioManager] Invalid device index: {device_name_or_index}")
                return
        elif isinstance(device_name_or_index, str):
            if device_name_or_index in devices:
                self.output_device = device_name_or_index
            else:
                print(f"[ERROR][AudioManager] Device '{device_name_or_index}' not found.")
                return
        else:
            print("[ERROR][AudioManager] Invalid device identifier.")
            return
        self.init_mixer()
    
    def warmup(self, duration_ms: int = 50) -> None:
        """Quickly warm up the audio system by playing a tiny silent buffer.

        This is intended to be run in a thread executor so it doesn't block
        the main asyncio loop. It creates a short silent WAV, plays it with
        `play_audio(..., sleep_during_playback=False)`, and removes the file.
        """
        debug_print("AudioManager", "Warming up audio device.")
        try:
            if not pygame.mixer.get_init():
                self.init_mixer()
            # Create a tiny silent buffer and write to a temp WAV
            samples = max(1, int(48000 * (duration_ms / 1000.0)))
            try:
                import numpy as _np
                arr = _np.zeros((samples, 2), dtype=_np.int16)
            except Exception:
                # Fall back to simple Python list if numpy isn't available
                arr = [[0, 0] for _ in range(samples)]
            tmpf = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
            tmpname = tmpf.name
            tmpf.close()
            try:
                sf.write(tmpname, arr, 48000, format='WAV', subtype='PCM_16')
                try:
                    # Play but don't block for the duration
                    self.play_audio(tmpname, sleep_during_playback=False, delete_file=True, play_using_music=False, volume=0)
                except Exception as e:
                    debug_print("AudioManager", f"Warmup playback error: {e}")
            finally:
                self._delete_file_with_retry(tmpname)
        except Exception as e:
            debug_print("AudioManager", f"Warmup failed: {e}")

    def stop_playback(self):
        debug_print("AudioManager", "Stopping playback.")
        self._should_stop = True
        self._is_playing = False
        try:
            pygame.mixer.music.stop()
            pygame.mixer.stop()
        except Exception as e:
            print(f"[ERROR]{e} - Could not stop playback.")

    def is_playing(self):
        debug_print("AudioManager", f"is_playing queried: {self._is_playing}")
        return self._is_playing

    def play_audio(self, file_path, sleep_during_playback=True, delete_file=False, play_using_music=True, output_device = None, volume: int = 100):
        debug_print("AudioManager", f"Playing audio: {file_path} on device: {output_device if output_device else self.cached_output_device} at volume: {volume}%")
        converted_tmp = None
        active_path = file_path
        sound_obj = None
        music_loaded = False
        playback_duration = None
        volume = max(0, min(100, volume)) / 100.0  # Normalize volume to 0.0 - 1.0
        try:
            if output_device and output_device != self.cached_output_device:
                self.set_output_device(output_device)
            self._should_stop = False
            self._is_playing = True
            if not pygame.mixer.get_init():
                self.init_mixer()

            def _load_and_play(path):
                nonlocal sound_obj, music_loaded
                if play_using_music:
                    pygame.mixer.music.load(path)
                    pygame.mixer.music.set_volume(volume)
                    music_loaded = True
                    pygame.mixer.music.play()
                else:
                    sound_obj = pygame.mixer.Sound(path)
                    sound_obj.set_volume(volume)
                    sound_obj.play()

            try:
                _load_and_play(active_path)
            except Exception as e:
                debug_print("AudioManager", f"Initial load failed, attempting conversion: {e}")
                try:
                    audio = AudioSegment.from_file(active_path)
                    audio = audio.set_frame_rate(48000).set_channels(2).set_sample_width(2)
                    tmpf = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
                    converted_tmp = tmpf.name
                    tmpf.close()
                    audio.export(converted_tmp, format="wav")
                    active_path = converted_tmp
                    _load_and_play(active_path)
                except Exception as e2:
                    debug_print("AudioManager", f"Conversion/playback failed: {e2}")
                    raise

            playback_duration = self._compute_audio_duration(active_path)

            if sleep_during_playback and playback_duration:
                self._wait_for_playback(playback_duration)
            elif sleep_during_playback:
                debug_print("AudioManager", f"Skipping playback wait; duration unavailable for {active_path}.")
        except Exception as e:
            print(f"[ERROR][AudioManager] Error playing audio: {e}\n{traceback.format_exc()}")
        finally:
            if play_using_music:
                try:
                    pygame.mixer.music.stop()
                except Exception:
                    pass
                if music_loaded:
                    try:
                        pygame.mixer.music.unload()
                    except Exception:
                        pass
            if sound_obj is not None:
                try:
                    sound_obj.stop()
                except Exception:
                    pass
                sound_obj = None

            self._is_playing = False
            self._should_stop = False

            paths_to_delete = set()
            if delete_file:
                paths_to_delete.add(file_path)
                paths_to_delete.add(active_path)
            if converted_tmp and converted_tmp not in paths_to_delete:
                paths_to_delete.add(converted_tmp)

            cleanup_targets = [target for target in paths_to_delete if target]
            if not cleanup_targets:
                return

            if delete_file and not sleep_during_playback:
                wait_time = 0.25
                if playback_duration and playback_duration > 0:
                    wait_time += playback_duration
                self._schedule_delayed_cleanup(cleanup_targets, wait_time)
            else:
                for target in cleanup_targets:
                    self._delete_file_with_retry(target)

    def prepare_playback(self, file_path, play_using_music=True):
        """Preload or convert the audio so playback start latency is minimized.

        Returns a tuple `(effective_path, delete_temp)` where `effective_path` is
        the path that should be passed to `play_audio` and `delete_temp` is a
        boolean that indicates whether the returned path is a temporary file
        that should be deleted after use.
        """
        debug_print("AudioManager", f"Preparing playback for: {file_path}")
        try:
            if not pygame.mixer.get_init():
                self.init_mixer()
            converted_tmp = None
            try:
                if play_using_music:
                    # Try loading into music channel (does not start playback)
                    pygame.mixer.music.load(file_path)
                else:
                    # Try loading as a Sound
                    _ = pygame.mixer.Sound(file_path)
                return file_path, False
            except Exception:
                # Need to convert to a PCM WAV that pygame will accept
                try:
                    audio = AudioSegment.from_file(file_path)
                    audio = audio.set_frame_rate(48000).set_channels(2).set_sample_width(2)
                    tmpf = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
                    converted_tmp = tmpf.name
                    tmpf.close()
                    audio.export(converted_tmp, format="wav")
                    # attempt to load converted file to ensure it's valid
                    if play_using_music:
                        pygame.mixer.music.load(converted_tmp)
                    else:
                        _ = pygame.mixer.Sound(converted_tmp)
                    return converted_tmp, True
                except Exception as e:
                    debug_print("AudioManager", f"prepare_playback conversion failed: {e}")
                    # Give up — return original and let play_audio attempt conversion/on-the-fly
                    return file_path, False
        except Exception as e:
            debug_print("AudioManager", f"prepare_playback unexpected error: {e}")
            return file_path, False

    async def play_audio_async(self, file_path, volume: int = 100):
        debug_print("AudioManager", f"Asynchronously playing audio: {file_path}")
        if not pygame.mixer.get_init():
            self.init_mixer()
        pygame_sound = pygame.mixer.Sound(file_path)
        pygame_sound.set_volume(max(0, min(100, volume)) / 100.0)
        pygame_sound.play()
        _, ext = os.path.splitext(file_path)
        if ext.lower() == '.wav':
            wav_file = sf.SoundFile(file_path)
            file_length = wav_file.frames / wav_file.samplerate
            wav_file.close()
        elif ext.lower() == '.mp3':
            mp3_file = MP3(file_path)
            file_length = mp3_file.info.length
        else:
            print("[WARNING]Cannot play audio, unknown file type")
            return
        await asyncio.sleep(file_length)

    async def process_audio(self, audio_file):
        debug_print("AudioManager", f"Processing audio for volume mapping: {audio_file}")
        if not os.path.exists(audio_file):
            debug_print("AudioManager", f"Audio file does not exist: {audio_file}")
            return [], 0
        size = os.path.getsize(audio_file)
        debug_print("AudioManager", f"Audio file size: {size} bytes")

        # Try to sniff the file header to pick a sensible loader/format for pydub
        fmt = None
        try:
            with open(audio_file, "rb") as fh:
                header = fh.read(64)
            if header.startswith(b"RIFF"):
                fmt = "wav"
            elif header.startswith(b"ID3") or header[0:1] == b"\xff":
                fmt = "mp3"
            elif header.startswith(b"OggS"):
                fmt = "ogg"
            elif header.startswith(b"fLaC"):
                fmt = "flac"
            else:
                fmt = None
            debug_print("AudioManager", f"Detected audio format from header: {fmt}")
        except Exception as e:
            debug_print("AudioManager", f"Failed to read header for format detection: {e}")
            fmt = None

        # Attempt primary load using pydub (ffmpeg). If that fails, fallback to soundfile
        try:
            if fmt == "wav":
                debug_print("AudioManager", "Loading WAV via AudioSegment.from_wav")
                audio = AudioSegment.from_wav(audio_file)
            elif fmt is not None:
                debug_print("AudioManager", f"Loading via AudioSegment.from_file with format={fmt}")
                audio = AudioSegment.from_file(audio_file, format=fmt)
            else:
                debug_print("AudioManager", "Loading via AudioSegment.from_file with no explicit format")
                audio = AudioSegment.from_file(audio_file)

            frame_ms = 50
            frames = [audio[i:i+frame_ms] for i in range(0, len(audio), frame_ms)]
            volumes = [frame.rms for frame in frames]
            debug_print("AudioManager", f"Processed audio frames: {len(frames)}, sample duration(ms): {len(audio)}")
            return volumes, len(audio)
        except Exception as e:
            debug_print("AudioManager", f"Error processing audio with pydub/ffmpeg: {e}")
            debug_print("AudioManager", "Falling back to soundfile-based processing (no ffmpeg required)")
            try:
                # Use soundfile to read waveform data in blocks and compute RMS per block
                with sf.SoundFile(audio_file) as f:
                    sr = f.samplerate
                    total_frames = f.frames
                    duration_ms = int((total_frames / sr) * 1000)
                    block_ms = 50
                    block_frames = max(1, int(sr * (block_ms / 1000.0)))
                    volumes = []
                    f.seek(0)
                    while True:
                        data = f.read(block_frames, dtype="int16")
                        if data is None or len(data) == 0:
                            break
                        # data may be mono or stereo
                        try:
                            # compute RMS across all channels
                            import numpy as _np
                            arr = _np.array(data)
                            if arr.size == 0:
                                break
                            # if multi-dimensional, flatten channels
                            if arr.ndim > 1:
                                arr = arr.mean(axis=1)
                            rms = int((_np.sqrt((_np.square(arr.astype(_np.float64))).mean())))
                        except Exception:
                            # Last-resort simple heuristic
                            rms = 0
                        volumes.append(rms)
                    debug_print("AudioManager", f"SoundFile processed blocks: {len(volumes)}, duration_ms: {duration_ms}")
                    if not volumes:
                        volumes = [0]
                    return volumes, duration_ms
            except Exception as e2:
                debug_print("AudioManager", f"Fallback processing also failed: {e2}")
                return [], 0

    async def map_volume_to_y(self, vol, min_vol, max_vol, base_y = 800, max_bounce = 25):
        if max_vol - min_vol == 0:
            return base_y
        normalized = (vol - min_vol) / (max_vol - min_vol)
        bounce = normalized * max_bounce
        return base_y - bounce
    
    async def get_list_of_sound_fx(self):
        if not self.list_of_sound_fx:
            await self.populate_sound_fx_list()
        return self.list_of_sound_fx
    
    async def populate_sound_fx_list(self):
        # Scan the 'media/sound_fx' directory for audio files
        sound_fx_dir = os.path.join(os.path.dirname(__file__), "media", "soundFX")
        sound_fx_list = []
        if not os.path.exists(sound_fx_dir):
            debug_print("AudioManager", f"Sound effects directory does not exist: {sound_fx_dir}")
            self.list_of_sound_fx = sound_fx_list
            return
        for filename in os.listdir(sound_fx_dir):
            if filename.lower().endswith(('.mp3', '.wav', '.ogg', '.flac')):
                if filename == "test_sound.mp3":
                    continue  # Skip test sound
                filename = filename.strip(".mp3").strip(".wav").strip(".ogg").strip(".flac")
                sound_fx_list.append(filename)
        self.list_of_sound_fx = sound_fx_list
        debug_print("AudioManager", f"Populated sound effects list with {len(self.list_of_sound_fx)} items.")

    def _sound_fx_directory(self) -> str:
        return os.path.join(os.path.dirname(__file__), "media", "soundFX")

    def _find_sound_fx_file(self, sound_fx_name: str) -> str | None:
        sound_fx_dir = self._sound_fx_directory()
        for ext in ['.mp3', '.wav', '.ogg', '.flac']:
            potential_path = os.path.join(sound_fx_dir, sound_fx_name + ext)
            if os.path.exists(potential_path):
                return potential_path
        return None

    def get_prepared_sound_fx(self, sound_fx_name: str):
        if not sound_fx_name:
            return None
        return self.prepared_sound_cache.get(sound_fx_name.lower())

    def _store_prepared_sound_fx(self, sound_fx_name: str, asset: dict | None):
        if not sound_fx_name or not asset:
            return
        self.prepared_sound_cache[sound_fx_name.lower()] = asset

    async def check_sound_fx_exists(self, sound_fx_name: str) -> bool:
        debug_print("AudioManager", f"Checking existence of sound effect: {sound_fx_name}")
        if not self.list_of_sound_fx:
            await self.populate_sound_fx_list()
        for file in self.list_of_sound_fx:
            if file.lower() == sound_fx_name.lower():
                debug_print("AudioManager", f"Sound effect '{sound_fx_name}' found in list.")
                return True
            
    async def play_sound_fx_by_name(
        self,
        sound_fx_name: str,
        *,
        prepared_asset: dict | None = None,
    ):
        debug_print("AudioManager", f"Playing sound effect by name: {sound_fx_name}")
        asset = prepared_asset
        if asset is None:
            asset = await self.prepare_sound_fx(sound_fx_name)
            if asset is None:
                return
        else:
            debug_print("AudioManager", f"Using preloaded sound for '{sound_fx_name}'.")

        volume = await get_setting("Sound FX Volume", 100)
        await asyncio.to_thread(self._play_prepared_sound, asset, volume)

    async def prepare_sound_fx(self, sound_fx_name: str):
        debug_print("AudioManager", f"Preparing sound effect: {sound_fx_name}")
        cached = self.get_prepared_sound_fx(sound_fx_name)
        if cached and cached.get("sound"):
            debug_print("AudioManager", f"Using cached prepared sound for '{sound_fx_name}'.")
            return cached
        if not await self.check_sound_fx_exists(sound_fx_name):
            debug_print("AudioManager", f"Cannot prepare '{sound_fx_name}' because it does not exist.")
            return None
        file_path = self._find_sound_fx_file(sound_fx_name)
        if not file_path:
            debug_print("AudioManager", f"No playable file located for '{sound_fx_name}'.")
            return None

        asset = await asyncio.to_thread(self._prepare_sound_asset, file_path)
        if asset is None:
            return None
        asset["name"] = sound_fx_name
        self._store_prepared_sound_fx(sound_fx_name, asset)
        return asset

    async def play_random_sound_fx(self):
        debug_print("AudioManager", "Playing random sound effect.")
        import random
        if not self.list_of_sound_fx:
            await self.populate_sound_fx_list()
        if not self.list_of_sound_fx:
            debug_print("AudioManager", "No sound effects available to play.")
            return
        chosen_sound = random.choice(self.list_of_sound_fx)
        await self.play_sound_fx_by_name(chosen_sound)

    def _prepare_sound_asset(self, file_path: str):
        converted_tmp = None
        try:
            if not pygame.mixer.get_init():
                self.init_mixer()
            try:
                sound_obj = pygame.mixer.Sound(file_path)
                duration = sound_obj.get_length()
                return {
                    "sound": sound_obj,
                    "duration": duration,
                    "source_path": file_path,
                }
            except Exception as primary_err:
                debug_print("AudioManager", f"Direct load failed for '{file_path}': {primary_err}")
                audio = AudioSegment.from_file(file_path)
                audio = audio.set_frame_rate(48000).set_channels(2).set_sample_width(2)
                tmpf = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
                converted_tmp = tmpf.name
                tmpf.close()
                audio.export(converted_tmp, format="wav")
                sound_obj = pygame.mixer.Sound(converted_tmp)
                duration = sound_obj.get_length()
                self._delete_file_with_retry(converted_tmp)
                converted_tmp = None
                return {
                    "sound": sound_obj,
                    "duration": duration,
                    "source_path": file_path,
                }
        except Exception as e:
            debug_print("AudioManager", f"_prepare_sound_asset error for '{file_path}': {e}")
        finally:
            if converted_tmp:
                self._delete_file_with_retry(converted_tmp)
        return None

    def _play_prepared_sound(self, asset: dict, volume_percent: int) -> float:
        sound_obj = asset.get("sound")
        if not sound_obj:
            return 0.0
        clamped = max(0, min(100, volume_percent)) / 100.0
        sound_obj.set_volume(clamped)
        sound_obj.play()
        duration = asset.get("duration")
        if not duration:
            try:
                duration = sound_obj.get_length()
            except Exception:
                duration = 0.0
        return max(0.0, float(duration))
        
if __name__ == '__main__':
    audio_manager = AudioManager()
    devices = audio_manager.list_output_devices()
    if devices:
        # Set to the first available device for demo
        audio_manager.set_output_device(0)
    MP3_FILEPATH = "TestAudio_MP3.mp3"
    WAV_FILEPATH = "TestAudio_WAV.wav"
    if os.path.exists(MP3_FILEPATH):
        audio_manager.play_audio(MP3_FILEPATH)
    if os.path.exists(WAV_FILEPATH):
        audio_manager.play_audio(WAV_FILEPATH)