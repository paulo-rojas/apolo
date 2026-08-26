from dataclasses import dataclass
from enum import Enum


class ServiceState(str, Enum):
    CONNECTED = "connected"
    READY = "ready"
    STOPPED = "stopped"
    ERROR = "error"
    DISABLED = "disabled"


@dataclass(frozen=True)
class ServiceStatus:
    name: str
    state: ServiceState
    detail: str = ""

    @property
    def is_online(self) -> bool:
        return self.state in {ServiceState.CONNECTED, ServiceState.READY}
