#!/usr/bin/env python3
"""
eve-hub CLI — Remote skill proxy to Eve's central OpenClaw hub.

Discovers and executes Eve's workspace skills by routing requests to
Eve's Gateway via `openclaw agent` (WebSocket, full operator access).
"""

import argparse
import json
import os
import subprocess
import sys
import re

__version__ = "1.0.0"

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

EVE_HUB_URL = os.environ.get("EVE_HUB_URL", "").rstrip("/")
EVE_HUB_TOKEN = os.environ.get("EVE_HUB_TOKEN", "")

# Timeout for remote agent calls (seconds)
REQUEST_TIMEOUT = int(os.environ.get("EVE_HUB_TIMEOUT", "600"))

# Directories on Eve to scan for custom skills
SKILL_DIRS = [
    "~/.openclaw/workspace/skills",
    "~/.openclaw/skills",
]

# Bundled/system skill names to EXCLUDE (these exist on every OpenClaw install)
SYSTEM_SKILLS = {
    "coding-agent", "discord", "gh-issues", "github", "healthcheck",
    "mcporter", "node-connect", "skill-creator", "video-frames", "weather",
    "skill-blueprint", "find-skills",
}


# ---------------------------------------------------------------------------
# Core: remote agent call via openclaw agent CLI
# ---------------------------------------------------------------------------

def _remote_agent(prompt: str, timeout: int = REQUEST_TIMEOUT) -> dict:
    """
    Send a prompt to Eve's Gateway agent via `openclaw agent` CLI.
    This uses WebSocket transport with full operator access.
    """
    cmd = [
        "openclaw", "agent",
        "--agent", "main",
        "--json",
        "-m", prompt,
    ]

    env = os.environ.copy()
    # Point to Eve's gateway
    if EVE_HUB_URL:
        # Convert https:// URL to wss:// WebSocket URL
        ws_url = EVE_HUB_URL
        if ws_url.startswith("https://"):
            ws_url = "wss://" + ws_url[8:]
        elif ws_url.startswith("http://"):
            ws_url = "ws://" + ws_url[7:]
        # Add port if not present
        if ":" not in ws_url.split("//")[1].split("/")[0].split("@")[-1]:
            ws_url = ws_url.rstrip("/")  # default port handled by openclaw
        env["OPENCLAW_GATEWAY_URL"] = ws_url

    if EVE_HUB_TOKEN:
        env["OPENCLAW_GATEWAY_TOKEN"] = EVE_HUB_TOKEN

    env["OPENCLAW_HIDE_BANNER"] = "1"
    env["OPENCLAW_SUPPRESS_NOTES"] = "1"

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=timeout, env=env,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout",
                "hint": f"Remote agent call timed out after {timeout}s."}
    except FileNotFoundError:
        return {"ok": False, "error": "openclaw_not_found",
                "hint": "openclaw CLI not found. Install OpenClaw first."}

    if result.returncode != 0:
        stderr = result.stderr.strip()
        if "Unauthorized" in stderr or "unauthorized" in stderr:
            return {"ok": False, "error": "auth_failed",
                    "hint": "EVE_HUB_TOKEN is invalid. Check your token."}
        return {"ok": False, "error": "agent_failed",
                "hint": f"openclaw agent returned exit code {result.returncode}: {stderr[:500]}"}

    stdout = result.stdout.strip()
    if not stdout:
        return {"ok": False, "error": "empty_response",
                "hint": "No output from remote agent."}

    # Parse JSON response
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        # Maybe the output has non-JSON prefix lines
        for line in stdout.split("\n"):
            line = line.strip()
            if line.startswith("{"):
                try:
                    data = json.loads(line)
                    break
                except json.JSONDecodeError:
                    continue
        else:
            return {"ok": True, "content": stdout}

    # Extract text from the agent response
    text = _extract_agent_text(data)
    if text:
        return {"ok": True, "content": text}

    return {"ok": True, "content": stdout, "raw": data}


def _extract_agent_text(data: dict) -> str:
    """Extract the reply text from openclaw agent --json output."""
    # Direct text field
    if isinstance(data.get("text"), str) and data["text"]:
        return data["text"]
    # Nested in reply
    reply = data.get("reply", {})
    if isinstance(reply, dict) and isinstance(reply.get("text"), str):
        return reply["text"]
    # Search recursively for text content
    def find_text(obj, depth=0):
        if depth > 4:
            return None
        if isinstance(obj, dict):
            if "text" in obj and isinstance(obj["text"], str) and obj["text"]:
                return obj["text"]
            for v in obj.values():
                r = find_text(v, depth + 1)
                if r:
                    return r
        elif isinstance(obj, list):
            for item in obj:
                r = find_text(item, depth + 1)
                if r:
                    return r
        return None
    return find_text(data) or ""


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_list(args):
    """List all available custom skills on Eve's hub."""
    prompt = f"""You are being called programmatically by eve-hub (a remote skill proxy).
Do NOT read any workspace files (SOUL.md, USER.md, MEMORY.md, etc). Skip all startup routines.

Execute this task and return ONLY a JSON object, nothing else:

1. Run: ls -d ~/.openclaw/workspace/skills/*/SKILL.md ~/.openclaw/skills/*/SKILL.md 2>/dev/null
2. For each SKILL.md found, extract the skill name (parent directory name) and the description from YAML frontmatter
3. EXCLUDE these system/bundled skills: {', '.join(sorted(SYSTEM_SKILLS))}
4. Return JSON: {{"skills": [{{"name": "x", "description": "y"}}], "count": N}}

Output ONLY the JSON. No markdown code blocks. No explanation."""

    result = _remote_agent(prompt, timeout=60)
    if not result.get("ok"):
        _print_result(result, args)
        return 1

    content = result["content"].strip()
    data = _extract_json(content)
    if data and "skills" in data:
        data["ok"] = True
        _print_result(data, args)
    else:
        if getattr(args, "json", False):
            _print_result({"ok": True, "raw": content}, args)
        else:
            print(content)
    return 0


def cmd_describe(args):
    """Show the full SKILL.md for a specific skill."""
    name = args.skill_name

    prompt = f"""You are being called programmatically by eve-hub (a remote skill proxy).
Do NOT read any workspace files (SOUL.md, USER.md, MEMORY.md, etc). Skip all startup routines.

Read and output the FULL content of the SKILL.md file for skill "{name}".
Look in: ~/.openclaw/workspace/skills/{name}/SKILL.md and ~/.openclaw/skills/{name}/SKILL.md

Output ONLY the file content. No extra text."""

    result = _remote_agent(prompt, timeout=30)
    if not result.get("ok"):
        _print_result(result, args)
        return 1

    content = result["content"]
    if getattr(args, "json", False):
        _print_result({"ok": True, "skill": name, "content": content}, args)
    else:
        print(content)
    return 0


def cmd_exec(args):
    """Execute a remote skill on Eve's hub."""
    name = args.skill_name
    skill_args = " ".join(args.skill_args) if args.skill_args else ""

    prompt = f"""You are being called programmatically by eve-hub (a remote skill proxy).
Do NOT read any workspace files (SOUL.md, USER.md, MEMORY.md, etc). Skip all startup routines.

Execute this command and return ONLY the raw output:

bash skills/{name}/run.sh {skill_args}

If the skill is not in ~/.openclaw/workspace/skills/, also check ~/.openclaw/skills/{name}/run.sh

Return the command output exactly as-is. No extra commentary."""

    result = _remote_agent(prompt, timeout=REQUEST_TIMEOUT)
    if not result.get("ok"):
        _print_result(result, args)
        return 1

    content = result["content"].strip()

    # Try to parse as JSON
    data = _extract_json(content)
    if data:
        if getattr(args, "json", False):
            print(json.dumps(data, ensure_ascii=False))
        else:
            if data.get("ok") is False:
                print(f"ERROR: {data.get('error', 'unknown')}", file=sys.stderr)
                if data.get("hint"):
                    print(f"Hint: {data['hint']}", file=sys.stderr)
            else:
                print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        if getattr(args, "json", False):
            _print_result({"ok": True, "output": content}, args)
        else:
            print(content)

    return 0


def cmd_self_test(args):
    """Verify connectivity to Eve's hub."""
    errors = []

    if not EVE_HUB_URL:
        errors.append("EVE_HUB_URL is not set")
    if not EVE_HUB_TOKEN:
        errors.append("EVE_HUB_TOKEN is not set")

    if errors:
        _print_result({
            "ok": False,
            "error": "config_missing",
            "hint": f"Missing: {'; '.join(errors)}. "
                    "Set in skills.entries.eve-hub.env in openclaw.json.",
        }, args)
        return 1

    # Test: simple agent call
    result = _remote_agent(
        "Reply with exactly: EVE_HUB_OK. Nothing else.",
        timeout=30,
    )
    if not result.get("ok"):
        _print_result(result, args)
        return 1

    content = result.get("content", "")
    if "EVE_HUB_OK" in content:
        _print_result({
            "ok": True,
            "message": "Connected to Eve hub successfully.",
            "hub_url": EVE_HUB_URL,
            "transport": "openclaw-agent-ws",
        }, args)
        return 0
    else:
        _print_result({
            "ok": False,
            "error": "unexpected_response",
            "hint": f"Expected EVE_HUB_OK, got: {content[:200]}",
        }, args)
        return 1


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_json(text: str):
    """Try to extract a JSON object from text that may contain markdown."""
    text = text.strip()
    # Strip markdown code blocks
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()

    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to find JSON object in text
    match = re.search(r'\{[\s\S]*\}', text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    return None


def _print_result(data: dict, args):
    if getattr(args, "json", False):
        print(json.dumps(data, ensure_ascii=False))
    else:
        if data.get("ok"):
            if "skills" in data:
                skills = data["skills"]
                print(f"Available skills on Eve hub ({data.get('count', len(skills))}):\n")
                for s in skills:
                    desc = s.get("description", "(no description)")
                    if len(desc) > 120:
                        desc = desc[:117] + "..."
                    print(f"  • {s['name']}: {desc}")
            elif "content" in data:
                print(data["content"])
            elif "output" in data:
                print(data["output"])
            elif "message" in data:
                print(data["message"])
                for k, v in data.items():
                    if k not in ("ok", "message"):
                        print(f"  {k}: {v}")
            else:
                print(json.dumps(data, ensure_ascii=False, indent=2))
        else:
            print(f"ERROR: {data.get('error', 'unknown')}", file=sys.stderr)
            if data.get("hint"):
                print(f"Hint: {data['hint']}", file=sys.stderr)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        prog="eve-hub",
        description="Remote skill proxy to Eve's central OpenClaw hub",
    )
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--quiet", "-q", action="store_true", help="Quiet mode")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    sub = parser.add_subparsers(dest="command", help="Command")

    # list
    sub.add_parser("list", help="List available skills on Eve hub")

    # describe
    p_desc = sub.add_parser("describe", help="Show skill details")
    p_desc.add_argument("skill_name", help="Skill name")

    # exec
    p_exec = sub.add_parser("exec", help="Execute a remote skill")
    p_exec.add_argument("skill_name", help="Skill name")
    p_exec.add_argument("skill_args", nargs=argparse.REMAINDER, help="Arguments to pass")

    # self-test
    sub.add_parser("self-test", help="Verify connectivity")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    handlers = {
        "list": cmd_list,
        "describe": cmd_describe,
        "exec": cmd_exec,
        "self-test": cmd_self_test,
    }

    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main() or 0)
