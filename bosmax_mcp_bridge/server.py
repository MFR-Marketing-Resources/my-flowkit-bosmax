"""stdio entrypoint for the local BOSMAX MCP bridge."""

from __future__ import annotations

import asyncio
import json
import sys
from typing import TextIO

from .bridge import BosmaxMcpBridge


async def serve_stdio(
    bridge: BosmaxMcpBridge,
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
) -> None:
    source = stdin or sys.stdin
    sink = stdout or sys.stdout
    for line in source:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Parse error"},
            }
        else:
            response = await bridge.handle_jsonrpc(message)
        if response is not None:
            sink.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
            sink.flush()


async def main() -> None:
    bridge = BosmaxMcpBridge.from_env()
    try:
        await serve_stdio(bridge)
    finally:
        await bridge.close()
