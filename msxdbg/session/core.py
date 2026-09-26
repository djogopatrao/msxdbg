"""Session core functionality."""


from __future__ import annotations  
from typing import Protocol


# Base classes for session operations  


class SessionAPI(Protocol):  # type: ignore[misc]
    
    def get_snapshot(self) -> StopSnapshot: ...  
    def add_breakpoint(self, address: int) -> None: ...
    

__all__ = ["SessionAPI"]
