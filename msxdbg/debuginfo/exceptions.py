"""Base exceptions for msxdbg."""


from __future__ import annotations

class MsxdbgError(Exception):
    """Base debugging error."""
    pass

class ParseError(MsxdbgError):
    """Error parsing debug info files."""
    pass

__all__ = ['MsxdbgError', 'ParseError']
