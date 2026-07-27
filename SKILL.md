---
name: "eve-hub"
description: "通过私有 MCP 向受信任的远程 OpenClaw 实例暴露 Eve 的自定义技能。"
metadata: {"openclaw":{"requires":{"env":["EVE_HUB_URL","EVE_HUB_TOKEN"]},"primaryEnv":"EVE_HUB_TOKEN"}}
---

# eve-hub — Remote Skill Proxy via MCP

Exposes Eve's custom skills as MCP tools. Other OpenClaw instances register the server and gain access to all of Eve's skills as native tools.

## For Eve's machine (server side)

### Start the MCP server
```bash
# Bootstrap venv
bash {baseDir}/run.sh --help

# Install as auto-start service
bash {baseDir}/scripts/install_service.sh

# Or run manually
{baseDir}/venv/bin/python {baseDir}/scripts/eve_hub_mcp_server.py --port 18800
```

### Verify
```bash
curl http://127.0.0.1:18800/health
```

## For other team members (client side)

### Register the MCP server
```bash
openclaw mcp set eve-hub '{"url":"http://<eve-tailscale-ip>:18800/sse"}'
```

That's it. Your agent will see all of Eve's skills as available tools.

## How it works

- **Executable skills** (with `run.sh`): Registered as MCP tools. Call with `args` parameter.
- **Reference skills** (SKILL.md only): Returns instructions for your agent to follow using its own tools.
- Skills are discovered in real-time — when Eve installs a new skill, it appears immediately.
- System/bundled OpenClaw skills are excluded to avoid conflicts with your local skills.

## CLI tools

```bash
# List available skills (local inspection, no server needed)
bash {baseDir}/run.sh list

# Show skill details
bash {baseDir}/run.sh describe <skill-name>

# Execute a skill (via CLI, not MCP)
bash {baseDir}/run.sh exec <skill-name> <args...>

# Connectivity test
bash {baseDir}/run.sh self-test
```

## Notes

- Requires Tailscale connectivity (private network)
- MCP Server listens on port 18800 by default
- Execution timeout: 600s (10 min) for long-running skills
- Logs: `~/.openclaw/logs/eve-hub-mcp.log`
