# eve-hub — Remote Skill Proxy via MCP

Exposes Eve's custom skills (findata-analyst, company-wiki, market-digest, etc.) as an MCP Server over SSE/HTTP. Any OpenClaw instance on the same Tailscale tailnet can call these skills as if they were local tools.

## Architecture

```
┌─────────────────────┐     Tailscale      ┌─────────────────────────┐
│ Your OpenClaw        │ ◄──── SSE/MCP ───► │ Eve's Mac mini          │
│                     │                     │                         │
│ mcporter config add │                     │ eve-hub MCP Server      │
│ eve-hub → url:...   │                     │ :18800                  │
│                     │                     │                         │
│ Agent calls:        │                     │ Skills:                 │
│ mcporter call       │                     │ • findata-analyst       │
│ eve-hub.eve_company │                     │ • company-wiki          │
│ _wiki args="..."    │                     │ • market-digest         │
│                     │                     │ • ...43 total           │
└─────────────────────┘                     └─────────────────────────┘
```

## Client Setup (for team members)

### Prerequisites
- Your machine is on the same **Tailscale tailnet** as Eve's Mac mini
- **OpenClaw** installed and running
- **mcporter** installed (`npm i -g mcporter`)

### Step 1: Register Eve's MCP server
```bash
mcporter config add eve-hub --url http://100.78.235.49:18800/sse
```
(Replace `100.78.235.49` with Eve's current Tailscale IP if changed.)

### Step 2: Verify connection
```bash
# List all available skills
mcporter list eve-hub

# Test a call
mcporter call eve-hub.eve_findata_analyst args="--help"
```

### Step 3: That's it
Your OpenClaw agent uses the **mcporter** skill (bundled with OpenClaw) to discover and call tools from Eve's MCP server. When you ask the agent something like "查一下 FUTU 的净现金", the agent will:

1. See `mcporter call eve-hub.eve_findata_netcash args="--ticker FUTU"` as an available action
2. Execute it remotely on Eve's machine
3. Return the results to you

### How does the agent know what tools are available?

The mcporter skill teaches the agent how to use `mcporter list <server>` and `mcporter call <server.tool>`. The MCP protocol handles the rest:

- `mcporter list eve-hub` → returns all tool names + descriptions + parameter schemas
- `mcporter call eve-hub.<tool_name> args="..."` → executes the tool remotely

The agent reads the tool descriptions to decide which one to use for your request.

---

## Server Setup (for Eve's machine)

### 1. Bootstrap the venv
```bash
cd ~/.openclaw/workspace
bash skills/eve-hub/run.sh --help  # triggers venv creation + pip install
```

### 2. Install as auto-start service
```bash
bash skills/eve-hub/scripts/install_service.sh
```

This creates a launchd service that:
- Starts on boot
- Restarts on crash
- Passes API keys from Eve's environment to the MCP server
- Logs to `~/.openclaw/logs/eve-hub-mcp.log`

### 3. Verify
```bash
curl http://127.0.0.1:18800/health
# → {"ok":true,"service":"eve-hub-mcp","skills":43,"executable":35,"reference":8}
```

### Re-install after changes
If you add new API keys or change the port:
```bash
bash skills/eve-hub/scripts/install_service.sh [port]
```

---

## Skill Types

| Type | Has `run.sh` | MCP Tool Name | Behavior |
|------|-------------|---------------|----------|
| Executable | ✅ | `eve_<name>` | Runs `run.sh <args>` on Eve, returns output |
| Reference | ❌ | `eve_ref_<name>` | Returns SKILL.md content (instructions for your agent) |

### Executable skills (35)
Tools like `eve_findata_analyst`, `eve_company_wiki`, `eve_market_digest` — your agent calls these with arguments, Eve runs the script, and results come back.

### Reference skills (8)
Skills like `eve_ref_docx`, `eve_ref_pptx`, `eve_ref_transcript_polish` — these don't have executable scripts. Instead, they return the SKILL.md instructions so your local agent can follow them using its own tools (read, write, exec, etc.).

---

## API Keys / Environment

The MCP server needs access to API keys that skills depend on:
- `GEMINI_API_KEY` — used by company-wiki, many search skills
- `EXA_API_KEY` — used by exa-search

These are loaded from:
1. Environment variables passed via launchd service (auto-captured at install time)
2. `.env` files in skill directories (e.g., `skills/exa-search/.env`)
3. Global `.env` at `~/.openclaw/workspace/.env` or `~/.openclaw/.env`

---

## Security

- MCP server listens on `0.0.0.0:18800` — accessible only within the Tailscale tailnet
- No authentication layer (Tailscale mesh = trust boundary)
- All execution runs under Eve's user account
- Consider adding token auth if your tailnet includes untrusted devices

---

## Troubleshooting

**"Connection refused" from client:**
- Check Eve's MCP server is running: `curl http://100.78.235.49:18800/health`
- Verify Tailscale connectivity: `ping 100.78.235.49`

**Skill returns "API_KEY not set":**
- Re-install the launchd service to capture current env: `bash skills/eve-hub/scripts/install_service.sh`
- Or add the key to `~/.openclaw/workspace/.env`

**mcporter can't find eve-hub:**
- Run `mcporter config list` to verify registration
- Re-add: `mcporter config add eve-hub --url http://100.78.235.49:18800/sse`

**New skill not showing up:**
- Skills are discovered in real-time on each `tools/list` call
- Just add the skill to Eve's workspace and it appears immediately
- No server restart needed
