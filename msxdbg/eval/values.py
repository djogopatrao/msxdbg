"""Value result containers."""

from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class ValueResult:
    """Contains an evaluated value with its location and availability."""
    
    available: bool = False
    
@dataclass(frozen=True)
class LocationResult:
    """Location of a name/variable."""

__all__ = ['ValueResult', 'LocationResult']

