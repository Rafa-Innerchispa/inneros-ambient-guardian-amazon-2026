"""Compatibility entry point.

The canonical ASGI application now lives in ``official_server`` so the web demo and MCP
endpoint share the same official MCP Python SDK v2 runtime and state.
"""

from .official_server import REASONER, STATE, app, main

__all__ = ["app", "main", "STATE", "REASONER"]


if __name__ == "__main__":
    main()
