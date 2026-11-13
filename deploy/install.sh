#!/bin/bash
set -euo pipefail
[[ $EUID == 0 ]] || { echo 'Run with sudo bash deploy/install.sh'; exit 1; }
cd "$(dirname "$0")/.."
source /etc/os-release
[[ "$ID" == debian && "$VERSION_ID" == 12 ]] || { echo 'This installer supports Debian 12 only'; exit 1; }
[[ -f frontend/dist/index.html ]] || { echo 'Build frontend first: npm ci --prefix frontend && npm run build --prefix frontend'; exit 1; }
for unit in mc-vanilla.service mc-skyfactory.service minecraft-maintenance.service minecraft-maintenance.timer; do
  systemctl cat "$unit" >/dev/null
done
if ! systemctl is-active --quiet ps5-panel.service && ss -lntH 'sport = :8080' | grep -q .; then
  echo 'Port 8080 is already in use. Resolve before installing.'; exit 1
fi
apt-get update
apt-get install -y python3 python3-venv acl sudo nftables
id ps5-panel >/dev/null 2>&1 || useradd --system --home-dir /var/lib/ps5-panel --shell /usr/sbin/nologin ps5-panel
usermod -a -G ps5,systemd-journal ps5-panel
install -d -o root -g root -m 0755 /opt/ps5-server-panel /usr/local/libexec
install -d -o root -g ps5-panel -m 0750 /etc/ps5-panel
install -d -o ps5-panel -g ps5-panel -m 0750 /var/lib/ps5-panel
if [[ "$(pwd -P)" != /opt/ps5-server-panel ]]; then
  cp -a panel deploy requirements.txt requirements.lock.txt /opt/ps5-server-panel/
  install -d /opt/ps5-server-panel/frontend
  cp -a frontend/dist /opt/ps5-server-panel/frontend/
fi
chown -R root:root /opt/ps5-server-panel
chmod -R go-w /opt/ps5-server-panel
python3 -m venv /opt/ps5-server-panel/.venv
/opt/ps5-server-panel/.venv/bin/pip install -r /opt/ps5-server-panel/requirements.lock.txt
if [[ ! -f /etc/ps5-panel/config.json ]]; then
  install -o root -g ps5-panel -m 0640 config.example.json /etc/ps5-panel/config.json
fi
install -o root -g root -m 0755 deploy/ps5-panel-helper /usr/local/libexec/ps5-panel-helper
install -o root -g root -m 0755 deploy/rcon-firewall.py /usr/local/libexec/ps5-rcon-firewall
install -o root -g root -m 0644 deploy/ps5-rcon-firewall.service /etc/systemd/system/ps5-rcon-firewall.service
for unit in mc-vanilla mc-skyfactory; do
  install -d -m 0755 "/etc/systemd/system/$unit.service.d"
  printf '[Unit]\nRequires=ps5-rcon-firewall.service\nAfter=ps5-rcon-firewall.service\n' > "/etc/systemd/system/$unit.service.d/ps5-panel-rcon.conf"
done
cat > /etc/sudoers.d/ps5-panel <<'SUDO'
ps5-panel ALL=(root) NOPASSWD: /usr/local/libexec/ps5-panel-helper
SUDO
chmod 0440 /etc/sudoers.d/ps5-panel
visudo -cf /etc/sudoers.d/ps5-panel
# Grant application access without changing Minecraft ownership or permissions globally.
for directory in /srv/minecraft/vanilla /srv/minecraft/skyfactory; do
  setfacl -R -m u:ps5-panel:rwX "$directory"
  find "$directory" -type d -exec setfacl -m d:u:ps5-panel:rwx {} +
done
# Backups are read-only to the panel; never create a competing scheduler.
setfacl -R -m u:ps5-panel:rX /srv/minecraft/backups
find /srv/minecraft/backups -type d -exec setfacl -m d:u:ps5-panel:rX {} +
# The panel can read the maintenance script, but cannot change it.
setfacl -m u:ps5-panel:r /usr/local/sbin/minecraft-maintenance
install -o root -g root -m 0644 deploy/ps5-panel.service /etc/systemd/system/ps5-panel.service
systemctl daemon-reload
systemctl enable --now ps5-rcon-firewall.service
systemctl enable --now ps5-panel.service
echo 'Installed. Initialize an administrator:'
echo 'cd /opt/ps5-server-panel && sudo -u ps5-panel .venv/bin/python -m panel.cli user admin'
echo 'Then configure RCON: sudo /opt/ps5-server-panel/.venv/bin/python deploy/configure-rcon.py'
echo "Panel URL: the origin in /etc/ps5-panel/config.json"
