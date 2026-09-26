"""Safety module for special operations."""


from __future__ import annotations  
from dataclasses import dataclass


@dataclass(frozen=True)
class SafetyAction:
    """Special allowed operation. Consumed after first use."""
    
    number: int  # Monotonic identifier
    action: str  # e.g., "write_memory", "set_breakpoint"
    
    __slots__ = ("number", "action")


@dataclass(frozen=True)  
class SafetyState:
    """Safety gate state."""
    
    enabled: bool = True
    queue: tuple[SafetyAction, ...] = ()  # type: ignore[misc]


__all__ = ["SafetyAction", "SafetyState"]
