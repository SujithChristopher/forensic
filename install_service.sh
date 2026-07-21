#!/bin/bash

# Must run as root to write to /etc/systemd/system/
if [[ "$EUID" -ne 0 ]]; then
    echo "Please run with sudo: sudo bash install_service.sh"
    exit 1
fi

# Auto-detect script location and current user (SUDO_USER gives the real user under sudo)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CURRENT_USER="${SUDO_USER:-$(logname 2>/dev/null || whoami)}"
PYTHON_BIN="$(su -c 'which python3' "$CURRENT_USER" 2>/dev/null || which python3)"

SERVICE_NAME="data-recorder"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

echo "Installing ${SERVICE_NAME}.service"
echo "  User:    ${CURRENT_USER}"
echo "  Path:    ${SCRIPT_DIR}/main.py"
echo "  Python:  ${PYTHON_BIN}"
echo ""

cat > "${SERVICE_FILE}" << EOF
[Unit]
Description=Forensic Data Recorder
After=network.target

[Service]
ExecStart=${PYTHON_BIN} ${SCRIPT_DIR}/main.py
WorkingDirectory=${SCRIPT_DIR}
Restart=always
RestartSec=5
User=${CURRENT_USER}

[Install]
WantedBy=multi-user.target
EOF

echo "Service file written to ${SERVICE_FILE}"

systemctl daemon-reload
systemctl start "${SERVICE_NAME}.service"
systemctl enable "${SERVICE_NAME}.service"

echo ""
systemctl status "${SERVICE_NAME}.service" --no-pager
