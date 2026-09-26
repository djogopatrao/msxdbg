"""Protocol and DTOs for OpenMSX target operations."""

from __future__ import annotations
from typing import Protocol, Optional


class OpenMSXTarget:
    """Read/write/open interface to openMSX emulator. Stubbed."""
    
    def send(self, operation: str) -> str:
        pass
    
    def recv(self) -> Optional[str]:
        return None

