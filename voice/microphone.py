import wave
from collections import deque
from pathlib import Path

from .vad import EnergyVad, VadConfig
from .audio_devices import selected_device


class MicrophoneNotAvailable(RuntimeError):
    pass


def record_utterance_to_wav(
    path: str,
    sample_rate: int = 16000,
    vad_config: VadConfig = None,
    stop_when=None,
    start_immediately: bool = False,
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
    block_ms = max(10, config.block_ms)
    block_size = int(sample_rate * block_ms / 1000)
    silence_blocks_needed = max(1, config.silence_ms // block_ms)
    max_blocks = max(1, config.max_utterance_ms // block_ms)
    pre_roll_blocks = max(0, config.pre_roll_ms // block_ms)

    frames = []
    pre_roll = deque(maxlen=pre_roll_blocks)
    recording = start_immediately
    silence_blocks = 0

    with sd.InputStream(
        samplerate=sample_rate,
        channels=1,
        dtype="int16",
        blocksize=block_size,
        device=selected_device("input"),
    ) as stream:
        for _ in range(max_blocks):
            if stop_when is not None and not stop_when():
                break
            block, _ = stream.read(block_size)
            rms = float(np.sqrt(np.mean((block.astype("float32") / 32768.0) ** 2)))
            if vad.is_voice_frame(rms):
                if not recording and pre_roll:
                    frames.extend(frame.copy() for frame in pre_roll)
                recording = True
                silence_blocks = 0
            elif recording:
                silence_blocks += 1

            if recording:
                frames.append(block.copy())
                if silence_blocks >= silence_blocks_needed:
                    break
            elif pre_roll_blocks:
                pre_roll.append(block.copy())

    if not frames:
        raise MicrophoneNotAvailable("no voice detected")

    audio = np.concatenate(frames, axis=0)
    with wave.open(str(output), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(audio.tobytes())
    return str(output)
