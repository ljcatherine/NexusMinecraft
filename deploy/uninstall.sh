#!/bin/bash
set -euo pipefail
[[ $EUID == 0 ]] || { echo 'Run with sudo'; exit 1; }
systemctl disable --now ps5-panel.service
rm -f /etc/systemd/system/ps5-panel.service /etc/sudoers.d/ps5-panel /usr/local/libexec/ps5-panel-helper
systemctl daemon-reload
echo 'Panel stopped and helper removed. Application, database, configuration and Minecraft data preserved.'
echo 'RCON firewall retained deliberately. Disable RCON in both servers before removing its firewall service/drop-ins.'
