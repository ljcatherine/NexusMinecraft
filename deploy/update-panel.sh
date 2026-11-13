#!/usr/bin/env bash
set -Eeuo pipefail

[[ $EUID == 0 ]] || { echo 'Run with sudo bash deploy/update-panel.sh'; exit 1; }
script_dir=$(cd -- "$(dirname -- "$0")" && pwd -P)
release="$script_dir/panel-update"
if [[ ! -d "$release" && -f "$script_dir/../panel/app.py" && -f "$script_dir/../frontend/dist/index.html" ]]; then
  release="$script_dir/.."
fi
app=/opt/ps5-server-panel
[[ -f "$release/panel/app.py" && -f "$release/panel/storage.py" && -f "$release/frontend/dist/index.html" ]] || {
  echo 'Expected panel-update/panel and panel-update/frontend/dist beside this script.' >&2
  exit 1
}
[[ ! -L "$release/panel" && ! -L "$release/frontend/dist" && -d "$app/panel" && -d "$app/frontend/dist" ]] || {
  echo 'Unexpected symlink or missing installed application directory; refusing update.' >&2
  exit 1
}
systemctl is-active --quiet ps5-panel.service || { echo 'Panel is not currently active; refusing update.' >&2; exit 1; }

stamp=$(date -u +%Y%m%dT%H%M%SZ)
backup=/var/lib/ps5-panel/update-$stamp
install -d -o root -g root -m 0700 "$backup"
cp -a "$app/panel" "$backup/panel"
cp -a "$app/frontend/dist" "$backup/dist"
updated=0
rollback() {
  rc=$?
  trap - ERR
  if (( updated )); then
    cp -a "$backup/panel/." "$app/panel/"
    cp -a "$backup/dist/." "$app/frontend/dist/"
    chown -R root:root "$app/panel" "$app/frontend/dist"
    chmod -R go-w "$app/panel" "$app/frontend/dist"
    systemctl restart ps5-panel.service || true
  fi
  echo "Panel update failed; previous code restored. Snapshot: $backup" >&2
  exit "$rc"
}
trap rollback ERR
updated=1
cp -a "$release/panel/." "$app/panel/"
cp -a "$release/frontend/dist/." "$app/frontend/dist/"
chown -R root:root "$app/panel" "$app/frontend/dist"
chmod -R go-w "$app/panel" "$app/frontend/dist"
systemctl restart ps5-panel.service
for attempt in {1..20}; do
  if systemctl is-active --quiet ps5-panel.service; then
    code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 3 http://127.0.0.1:8080/api/me || true)
    if [[ "$code" == 400 || "$code" == 401 || "$code" == 426 ]]; then
      trap - ERR
      echo "Panel update active. Snapshot: $backup"
      exit 0
    fi
  fi
  sleep 1
done
false
