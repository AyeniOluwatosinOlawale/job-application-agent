#!/bin/bash
# Installs a systemd timer to run the agent every morning at 08:00 UTC
# Run as: sudo bash install_service.sh
set -e

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_USER="${SUDO_USER:-ubuntu}"
PYTHON="$APP_DIR/venv/bin/python"

echo "Installing service for user: $APP_USER"
echo "App directory: $APP_DIR"

# systemd service unit
cat > /etc/systemd/system/job-agent.service << EOF
[Unit]
Description=Job Application Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=$APP_USER
WorkingDirectory=$APP_DIR
ExecStart=$PYTHON main.py --once
StandardOutput=append:$APP_DIR/logs/service.log
StandardError=append:$APP_DIR/logs/service.log
EOF

# systemd timer unit — runs daily at 08:00 UTC
cat > /etc/systemd/system/job-agent.timer << EOF
[Unit]
Description=Run Job Application Agent every morning at 08:00 UTC

[Timer]
OnCalendar=*-*-* 08:00:00 UTC
Persistent=true

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable job-agent.timer
systemctl start job-agent.timer

echo ""
echo "=== Service installed and timer started ==="
echo ""
echo "Useful commands:"
echo "  Check timer status:    systemctl status job-agent.timer"
echo "  Run manually now:      systemctl start job-agent.service"
echo "  Watch live logs:       tail -f $APP_DIR/logs/service.log"
echo "  Disable timer:         systemctl disable job-agent.timer"
