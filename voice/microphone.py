import wave
from pathlib import Path

from .vad import EnergyVad, VadConfig


class MicrophoneNotAvailable(RuntimeError):
    pass


def record_utterance_to_wav(
    path: str,
    sample_rate: int = 16000,
    vad_config: VadConfig = None,
) -> str:
    """Record one utterance to WAV using a small energy-based VAD.

    This MVP imports sounddevice lazily so tests and server startup do not require audio
    dependencies or a microphone.
    """
    try:
        import numpy as np
        import sounddevice as sd
    except Exception as e:
        raise MicrophoneNotAvailable("install sounddevice and numpy to use microphone capture") from e

    config = vad_config or VadConfig(sample_rate=sample_rate)
    vad = EnergyVad(config)
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    block_ms = 100
    block_size = int(sample_rate * block_ms / 1000)
    silence_blocks_needed = max(1, config.silence_ms // block_ms)
    max_blocks = max(1, config.max_utterance_ms // block_ms)

    frames = []
    recording = False
    silence_blocks = 0

    with sd.InputStream(samplerate=sample_rate, channels=1, dtype="int16", blocksize=block_size) as stream:
        for _ in range(max_blocks):
            block, _ = stream.read(block_size)
            rms = float(np.sqrt(np.mean((block.astype("float32") / 32768.0) ** 2)))
            if vad.is_voice_frame(rms):
                recording = True
                silence_blocks = 0
            elif recording:
                silence_blocks += 1

            if recording:
                frames.append(block.copy())
                if silence_blocks >= silence_blocks_needed:
                    break

    if not frames:
        raise MicrophoneNotAvailable("no voice detected")

    audio = np.concatenate(frames, axis=0)
    with wave.open(str(output), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(audio.tobytes())
    return str(output)
