# eve-hub — Remote Skill Proxy via MCP

Exposes Eve's custom skills (findata-analyst, company-wiki, market-digest, etc.) as an MCP Server over SSE/HTTP. Any OpenClaw instance on the same Tailscale tailnet can register and use these skills as native tools.

## Architecture

```
┌─────────────────────┐     Tailscale      ┌─────────────────────────┐
│ Richard's OpenClaw   │ ◄──── SSE/MCP ───► │ Eve's Mac mini          │
│                     │                     │                         │
│ openclaw mcp set    │                     │ eve-hub MCP Server      │
│ eve-hub → url:...   │                     │ :18800                  │
│                     │                     │                         │
│ Agent sees tools:   │                     │ Skills:                 │
│ • eve_findata_analyst│                    │ • findata-analyst/      │
│ • eve_company_wiki  │                     │ • company-wiki/         │
│ • eve_market_digest │                     │ • market-digest/        │
│ • ...43 total       │                     │ • ...43 total           │
└─────────────────────┘                     └─────────────────────────┘
```

## Setup on Eve's machine (server)

### 1. Bootstrap the venv
```bash
cd ~/.openclaw/workspace
bash skills/eve-hub/run.sh --help  # triggers venv creation + pip install
```

### 2. Install as service (auto-start)
```bash
bash skills/eve-hub/scripts/install_service.sh
```

### 3. Verify
```bash
curl http://127.0.0.1:18800/health
# → {"ok":true,"service":"eve-hub-mcp","skills":43,"executable":35,"reference":8}
```

## Setup on other team members' machines (client)

### 1. Register the MCP server
```bash
openclaw mcp set eve-hub '{"url":"http://100.78.235.49:18800/sse"}'
```
Replace `100.78.235.49` with Eve's Tailscale IP.

### 2. That's it
The agent will automatically see all of Eve's skills as available tools.
Tool names follow the pattern `eve_<skill_name>` (hyphens become underscores).

## Skill types

- **Executable** (`[exec]`): Has `run.sh` → registered as a callable MCP tool with `args` parameter
- **Reference** (`[ref]`): SKILL.md only → returns instructions for the agent to follow using its own tools

## Available commands

### List skills (local inspection)
```bash
cd ~/.openclaw/workspace
skills/eve-hub/venv/bin/python skills/eve-hub/scripts/eve_hub_mcp_server.py --list
```

### Manual start (foreground)
```bash
skills/eve-hub/venv/bin/python skills/eve-hub/scripts/eve_hub_mcp_server.py --port 18800 --verbose
```

## Security

- MCP server listens on 0.0.0.0:18800 — accessible from Tailscale tailnet only (no public internet exposure)
- No authentication required (Tailscale mesh provides the trust boundary)
- All skill execution happens under Eve's user account on Eve's machine
- Consider adding auth if tailnet includes untrusted devices

## Notes

- Skills are discovered in real-time on each `tools/list` call — new skills appear immediately
- System/bundled OpenClaw skills are excluded to avoid conflicts with local skills
- Default execution timeout is 600s (10 minutes) for long-running skills
- Logs: `~/.openclaw/logs/eve-hub-mcp.log`
