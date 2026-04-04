#!/usr/bin/env python3
"""
eve-hub SSE→stdio MCP Proxy

Bridges an SSE-based MCP server (eve-hub) to a stdio-based MCP client.
This is needed for MCP hosts that only support stdio transport (e.g., Antigravity,
Cursor, Windsurf, Claude Desktop).

Usage:
    python eve_hub_proxy.py <SSE_URL>
    python eve_hub_proxy.py http://100.78.235.49:18800/sse

The proxy:
1. Connects to the remote eve-hub MCP server via SSE
2. Exposes a local stdio MCP interface
3. Forwards messages bidirectionally between the two

Requirements:
    pip install mcp anyio httpx httpx-sse
"""

import anyio
import sys
import os
import logging
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Logging — writes to a file next to this script for debugging
# ---------------------------------------------------------------------------

LOG_FILE = Path(__file__).parent / "proxy.log"


def log(msg: str):
    """Append a timestamped line to the proxy log file."""
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().isoformat()}] {msg}\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Message forwarding
# ---------------------------------------------------------------------------

async def forward(receive_stream, send_stream, direction: str):
    """Forward messages from one stream to another."""
    try:
        async for msg in receive_stream:
            log(f"[{direction}] {str(msg)[:300]}")
            await send_stream.send(msg)
    except Exception as e:
        log(f"[{direction}] Stream ended: {e}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    from mcp.client.sse import sse_client
    from mcp.server.stdio import stdio_server

    # Default URL — override via CLI argument
    url = "http://100.78.235.49:18800/sse"
    if len(sys.argv) > 1:
        url = sys.argv[1]

    log(f"Proxy starting — target: {url}")

    try:
        async with sse_client(url) as (sse_read, sse_write):
            log("SSE connected successfully")
            async with stdio_server() as (stdio_read, stdio_write):
                log("stdio server initialized — forwarding messages")
                async with anyio.create_task_group() as tg:
                    tg.start_soon(forward, stdio_read, sse_write, "client→eve")
                    tg.start_soon(forward, sse_read, stdio_write, "eve→client")
    except Exception as e:
        log(f"Fatal error: {e}")
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    anyio.run(main)
