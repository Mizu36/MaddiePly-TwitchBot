import subprocess
import sys
import os
from pathlib import Path
from tools import path_from_app_root

REQ_FILE = "requirements.txt"

# Detect installed packages using standard library
try:
    from importlib.metadata import distributions
except ImportError:
    # Python <3.8 fallback
    print("Python 3.8+ is required for this script.")
    sys.exit(1)

installed = {d.metadata["Name"].lower() for d in distributions()}

# Read requirements
missing = []
with open(REQ_FILE, encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        # Extract package name (before any version specifiers)
        pkg = line.split(";", 1)[0].split("==", 1)[0].split(">=", 1)[0].split("<=", 1)[0].split(">", 1)[0].split("<", 1)[0].split("~=", 1)[0].strip().lower()
        if pkg and pkg not in installed:
            missing.append(line)

if not missing:
    print("✅ All packages are already installed.")
else:
    print("📦 Installing missing packages:")
    for pkg in missing:
        print("   →", pkg)
        subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])
    print("✅ Done installing missing packages.")

for folder in ["data", "media"]:
    if not os.path.exists(folder):
        os.makedirs(folder)
        print(f"Created missing folder: {folder}")
        if folder == "media":
            subfolders = ["images_and_gifs", "memes", "screenshots", "soundFX", "voice_audio"]
            for subfolder in subfolders:
                subfolder_path = os.path.join(folder, subfolder)
                if not os.path.exists(subfolder_path):
                    os.makedirs(subfolder_path)
                    print(f"Created missing subfolder: {subfolder_path}")

def ensure_local_ffmpeg() -> None:
    """Install bundled FFmpeg binaries via local-ffmpeg so GUI runs under pythonw."""
    try:
        from local_ffmpeg import install, is_installed
    except ImportError:
        print("[WARN] local-ffmpeg package missing; skipping FFmpeg binary setup.")
        return

    target = path_from_app_root("ffmpeg_bin")
    target.mkdir(exist_ok=True)
    if is_installed(str(target)):
        print(f"✅ Local FFmpeg already present at {target}")
        return

    print("[INFO] Local FFmpeg binaries missing; downloading now (one-time).")
    ok, msg = install(str(target))
    if ok:
        print(f"✅ FFmpeg binaries installed to {target}")
    else:
        raise SystemExit(f"FFmpeg install failed: {msg}")

ensure_local_ffmpeg()