#!/usr/bin/env bash
# Install eve-hub MCP server as a launchd service (macOS)
# Usage: bash scripts/install_service.sh [--port 18800]

set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PYTHON="$SKILL_DIR/venv/bin/python"
SERVER_SCRIPT="$SKILL_DIR/scripts/eve_hub_mcp_server.py"
PORT="${1:-18800}"
PLIST_NAME="ai.openclaw.eve-hub-mcp"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_NAME}.plist"
LOG_DIR="$HOME/.openclaw/logs"

# Ensure venv exists
if [ ! -f "$VENV_PYTHON" ]; then
    echo "Error: venv not found. Run 'bash skills/eve-hub/run.sh --help' first to bootstrap."
    exit 1
fi

mkdir -p "$LOG_DIR"

cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${PLIST_NAME}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${VENV_PYTHON}</string>
        <string>${SERVER_SCRIPT}</string>
        <string>--port</string>
        <string>${PORT}</string>
        <string>--host</string>
        <string>0.0.0.0</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$(dirname "$SKILL_DIR")</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>${LOG_DIR}/eve-hub-mcp.log</string>
    <key>StandardErrorPath</key>
    <string>${LOG_DIR}/eve-hub-mcp.err.log</string>
</dict>
</plist>
EOF

# Load the service
launchctl bootout "gui/$(id -u)/${PLIST_NAME}" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"

echo "✅ eve-hub MCP server installed and started"
echo "   Port: ${PORT}"
echo "   Plist: ${PLIST_PATH}"
echo "   Logs: ${LOG_DIR}/eve-hub-mcp.log"
echo ""
echo "Register on remote OpenClaw instances:"
echo "   openclaw mcp set eve-hub '{\"url\":\"http://<tailscale-ip>:${PORT}/sse\"}'"
