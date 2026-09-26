"""Typed openMSX target adapter stub."""

from __future__ import annotations

from .api import TargetCapabilities, _UnimplementedTarget
from .transport import OpenMSXTransport


class OpenMSXTarget(_UnimplementedTarget):
    """Adapter that will translate typed operations to openMSX Tcl."""

    def __init__(
        self,
        transport: OpenMSXTransport,
        capabilities: TargetCapabilities,
    ) -> None:
        self._transport = transport
        self._capabilities = capabilities


__all__ = ["OpenMSXTarget"]
