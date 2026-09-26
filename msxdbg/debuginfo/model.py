"""Core data models for program information."""


from __future__ import annotations
from typing import Optional, Tuple, Union
from dataclasses import dataclass

@dataclass(frozen=True)
class AddressRange:
    """Range of addresses [start, end_exclusive)."""
    
    start: int
    end_exclusive: int
    
    def contains(self, address: int) -> bool:
        return self.start <= address < self.end_exclusive


__all__ = ['AddressRange']
