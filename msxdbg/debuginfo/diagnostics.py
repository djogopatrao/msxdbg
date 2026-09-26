"""Diagnostic types for parsing errors."""


from __future__ import annotations
from typing import Optional, Tuple
from pathlib import Path
from dataclasses import dataclass

@dataclass(frozen=True)
class Origin:
    """Origin of a diagnostic."""
    
    path: Path
    line: Optional[int] = None
    record_kind: str = "unknown"


__all__ = ['Origin']
