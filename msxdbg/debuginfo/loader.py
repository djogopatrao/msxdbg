"""Project loader stub."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ImageSpec:
    id: str
    output_dir: str
    
@dataclass(frozen=True)
class ProjectLoader:
    def load(self, *args):
        pass

__all__ = ['ProjectLoader', 'ImageSpec']
