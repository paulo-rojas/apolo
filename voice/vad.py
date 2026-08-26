from dataclasses import dataclass


@dataclass
class VadConfig:
    sample_rate: int = 16000
    threshold: float = 0.015
    block_ms: int = 40
    silence_ms: int = 700
    max_utterance_ms: int = 8000
    pre_roll_ms: int = 240


class EnergyVad:
    def __init__(self, config: VadConfig = None):
        self.config = config or VadConfig()

    def is_voice_frame(self, rms: float) -> bool:
        return rms >= self.config.threshold
