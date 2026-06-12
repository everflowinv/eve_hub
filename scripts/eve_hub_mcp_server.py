#!/usr/bin/env python3
"""
eve-hub MCP Server — Exposes Eve's custom skills as MCP tools over SSE/HTTP.

Run: python scripts/eve_hub_mcp_server.py [--port 18800] [--host 0.0.0.0]

Other OpenClaw instances register this server:
  openclaw mcp set eve-hub '{"url":"http://<tailscale-ip>:18800/sse"}'
"""

import argparse
import asyncio
import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Load environment from .env files (API keys etc.)
# ---------------------------------------------------------------------------

def _load_env_files():
    """Load .env files so skills get their API keys."""
    env_files = [
        Path.home() / ".openclaw" / "workspace" / ".env",
        Path.home() / ".openclaw" / ".env",
    ]
    # Also load per-skill .env files
    for skill_dir in [
        Path.home() / ".openclaw" / "workspace" / "skills",
        Path.home() / ".openclaw" / "skills",
    ]:
        if skill_dir.is_dir():
            for entry in skill_dir.iterdir():
                env_path = entry / ".env"
                if env_path.is_file():
                    env_files.append(env_path)
                # Also check scripts/.env
                scripts_env = entry / "scripts" / ".env"
                if scripts_env.is_file():
                    env_files.append(scripts_env)

    for env_file in env_files:
        if not env_file.is_file():
            continue
        try:
            with open(env_file) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        key, _, value = line.partition("=")
                        key = key.strip()
                        value = value.strip().strip('"').strip("'")
                        if key and key not in os.environ:
                            os.environ[key] = value
        except Exception:
            pass

_load_env_files()

from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import Tool, TextContent
from starlette.applications import Starlette
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route
import uvicorn

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SKILL_DIRS = [
    Path.home() / ".openclaw" / "workspace" / "skills",
    Path.home() / ".openclaw" / "skills",
]

# System/bundled skills to exclude (these exist on every OpenClaw install)
SYSTEM_SKILLS = {
    "coding-agent", "discord", "gh-issues", "github", "healthcheck",
    "mcporter", "node-connect", "skill-creator", "video-frames", "weather",
    "skill-blueprint", "find-skills", "eve-hub",
}

# Skills that are SKILL.md-only (no run.sh) — exposed as read-only reference
# These provide instructions for the agent, not executable tools
MD_ONLY_SKILL_PREFIX = "ref"

DEFAULT_TIMEOUT = 600  # 10 min

logger = logging.getLogger("eve-hub-mcp")

# ---------------------------------------------------------------------------
# Skill discovery
# ---------------------------------------------------------------------------

def discover_skills() -> dict:
    """
    Scan skill directories and return a dict of:
    {name: {"path": Path, "description": str, "has_run_sh": bool, "skill_md": str}}
    """
    skills = {}
    for skill_dir in SKILL_DIRS:
        if not skill_dir.is_dir():
            continue
        for entry in sorted(skill_dir.iterdir()):
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            name = entry.name
            if name in SYSTEM_SKILLS or name in skills:
                continue

            skill_md_path = entry / "SKILL.md"
            if not skill_md_path.exists():
                continue

            # Read SKILL.md
            try:
                content = skill_md_path.read_text(encoding="utf-8")
            except Exception:
                continue

            # Parse description from YAML frontmatter
            desc = ""
            m = re.search(
                r'^description:\s*["\']?(.+?)["\']?\s*$',
                content, re.MULTILINE,
            )
            if m:
                desc = m.group(1).strip().strip('"').strip("'")

            has_run_sh = (entry / "run.sh").exists()

            skills[name] = {
                "path": entry,
                "description": desc or f"Skill: {name}",
                "has_run_sh": has_run_sh,
                "skill_md": content,
            }

    return skills


def build_tools(skills: dict) -> list[Tool]:
    """Build MCP Tool definitions from discovered skills."""
    tools = []

    for name, info in sorted(skills.items()):
        if info["has_run_sh"]:
            # Executable skill → tool with args parameter
            tools.append(Tool(
                name=f"eve_{name.replace('-', '_')}",
                description=info["description"],
                inputSchema={
                    "type": "object",
                    "properties": {
                        "args": {
                            "type": "string",
                            "description": f"Command-line arguments to pass to {name}/run.sh. "
                                           f"Run with '--help' to see available commands.",
                        },
                    },
                    "required": [],
                },
            ))
        else:
            # SKILL.md-only → read-only reference tool
            tools.append(Tool(
                name=f"eve_{MD_ONLY_SKILL_PREFIX}_{name.replace('-', '_')}",
                description=f"[Reference] {info['description']} — Returns the skill instructions (SKILL.md). This skill has no executable script; use the instructions to guide your actions.",
                inputSchema={
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            ))

    return tools


# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------

async def execute_skill(name: str, args: str, timeout: int = DEFAULT_TIMEOUT) -> str:
    """Execute a skill's run.sh and return output."""
    skills = discover_skills()
    if name not in skills:
        return json.dumps({"ok": False, "error": "not_found",
                           "hint": f"Skill '{name}' not found on Eve hub."})

    info = skills[name]

    if not info["has_run_sh"]:
        # Return SKILL.md content for reference-only skills
        return info["skill_md"]

    run_sh = info["path"] / "run.sh"
    cmd = f'bash "{run_sh}" {args}'

    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(Path.home() / ".openclaw" / "workspace"),
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout,
        )
    except asyncio.TimeoutError:
        return json.dumps({"ok": False, "error": "timeout",
                           "hint": f"Skill execution timed out after {timeout}s."})
    except Exception as e:
        return json.dumps({"ok": False, "error": "exec_failed",
                           "hint": str(e)})

    output = stdout.decode("utf-8", errors="replace")
    err_output = stderr.decode("utf-8", errors="replace")

    if proc.returncode != 0 and not output.strip():
        output = err_output or f"Process exited with code {proc.returncode}"

    return output


# ---------------------------------------------------------------------------
# MCP Server setup
# ---------------------------------------------------------------------------

def create_server() -> Server:
    server = Server("eve-hub")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        skills = discover_skills()
        return build_tools(skills)

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        # Resolve tool name back to skill name
        # eve_skill_name → skill-name (executable)
        # eve_ref_skill_name → skill-name (reference)
        skill_name = name

        if skill_name.startswith(f"eve_{MD_ONLY_SKILL_PREFIX}_"):
            # Reference skill
            raw = skill_name[len(f"eve_{MD_ONLY_SKILL_PREFIX}_"):]
            skill_name = raw.replace("_", "-")
            result = await execute_skill(skill_name, "", timeout=10)
        elif skill_name.startswith("eve_"):
            raw = skill_name[4:]  # strip "eve_"
            skill_name = raw.replace("_", "-")
            args_str = arguments.get("args", "")
            result = await execute_skill(skill_name, args_str)
        else:
            result = json.dumps({"ok": False, "error": "unknown_tool",
                                 "hint": f"Tool '{name}' not recognized."})

        return [TextContent(type="text", text=result)]

    return server


# ---------------------------------------------------------------------------
# HTTP app (SSE transport)
# ---------------------------------------------------------------------------

def create_app(server: Server) -> Starlette:
    sse = SseServerTransport("/messages/")

    async def handle_sse(request):
        async with sse.connect_sse(
            request.scope, request.receive, request._send,
        ) as streams:
            await server.run(
                streams[0], streams[1], server.create_initialization_options(),
            )
        return Response()


    async def health(request):
        skills = discover_skills()
        return JSONResponse({
            "ok": True,
            "service": "eve-hub-mcp",
            "skills": len(skills),
            "executable": sum(1 for s in skills.values() if s["has_run_sh"]),
            "reference": sum(1 for s in skills.values() if not s["has_run_sh"]),
        })

    return Starlette(
        debug=False,
        routes=[
            Route("/health", health),
            Route("/sse", handle_sse),
            # handle_post_message is a raw ASGI app that sends its own response;
            # wrapping it in a Route makes Starlette await a None return value.
            Mount("/messages/", app=sse.handle_post_message),
        ],
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        prog="eve-hub-mcp-server",
        description="MCP Server exposing Eve's custom skills",
    )
    parser.add_argument("--port", type=int, default=18800, help="Port (default: 18800)")
    parser.add_argument("--host", default="0.0.0.0", help="Bind address (default: 0.0.0.0)")
    parser.add_argument("--list", action="store_true", help="List discovered skills and exit")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    if args.list:
        skills = discover_skills()
        print(f"Discovered {len(skills)} custom skills:\n")
        for name, info in sorted(skills.items()):
            mode = "exec" if info["has_run_sh"] else "ref"
            desc = info["description"][:100]
            print(f"  [{mode}] {name}: {desc}")
        return

    server = create_server()
    app = create_app(server)

    skills = discover_skills()
    exec_count = sum(1 for s in skills.values() if s["has_run_sh"])
    ref_count = sum(1 for s in skills.values() if not s["has_run_sh"])
    logger.info(f"Starting eve-hub MCP server on {args.host}:{args.port}")
    logger.info(f"Discovered {len(skills)} skills ({exec_count} executable, {ref_count} reference)")
    logger.info(f"Register on remote OpenClaw: openclaw mcp set eve-hub '{{\"url\":\"http://<tailscale-ip>:{args.port}/sse\"}}'")

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
