"""Fake target implementation."""

from __future__ import annotations


class FakeTarget:
    """No-op target implementation for development."""
    
    def send(self, op: str) -> None:
        pass
    
    def recv(self) -> None:
        return None

