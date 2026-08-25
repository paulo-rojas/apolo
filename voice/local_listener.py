import argparse
import json
import sys
import tempfile
import urllib.request
from pathlib import Path

from core.config import get_int, get_str
from .microphone import record_utterance_to_wav
from .whisper_cpp import WhisperCppTranscriber


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="Record one voice command and send it to Apolo.")
    parser.add_argument("--server", default="http://127.0.0.1:8000")
    parser.add_argument("--language", default=get_str("whisper.language", "es"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    wav_path = Path(tempfile.gettempdir()) / "apolo_voice_command.wav"
    record_utterance_to_wav(str(wav_path), sample_rate=get_int("voice.vad.sample_rate", 16000))
    transcript = WhisperCppTranscriber().transcribe_file(str(wav_path), language=args.language)
    payload = json.dumps({"text": transcript, "dry_run": args.dry_run}).encode("utf-8")
    request = urllib.request.Request(
        f"{args.server.rstrip('/')}/voice-command",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        print(response.read().decode("utf-8"))


if __name__ == "__main__":
    main()
