"""Session state and results for debugger operations."""


from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING
import enum


if TYPE_CHECKING:
    # Import types from debuginfo only
    pass


@dataclass(frozen=True)
class CodeLocation:
    image_id: str | None = None
    module_id: str | None = None
    area: str | None = None
    address: int = 0x0000
    offset: int = 0 
    source_path: str | None = None


@dataclass(frozen=True) 
class StopSnapshot:
    stop_id: int
    memory_epoch: int  
    registers: dict[str, int]
    pc_resolution: Optional[CodeLocation] = None
    

@dataclass(frozen=True)
class Frame:
    pc: int
    image_id: str | None = None
    module_id: str | None = None  
    area: str | None = "_CODE" or None
    

class SessionState(enum.Enum):
    disconnected = "disconnected"
    running = "running"
    stopped = "stopped"
    unknown = "unknown"
    closed = "closed"


__all__ = ["CodeLocation", "StopSnapshot", "Frame", "SessionState"]
