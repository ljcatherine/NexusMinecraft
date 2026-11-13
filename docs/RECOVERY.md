# Backup, restore and recovery

Existing nightly maintenance remains the primary backup system. Do not run another timer. Keep an off-host copy of completed sets. The panel's own SQLite database/config need a separate administrative backup; stop the panel while copying its data directory, then restart it.

Before a production restore, verify current complete archives, enough staging/rollback disk space and absence of maintenance. Obtain explicit confirmation. Never extract over a running world. Root helper validates and stages first, stops the affected unit, renames original to `/srv/minecraft/.panel-rollback-SERVER-TIMESTAMP`, swaps staging into place, grants ownership/ACLs, and starts it only if it was previously running. The rollback tree is retained. Current RCON values are retained. Inspect the console for successful world loading.

If interrupted, do not blindly rerun. Inspect the target, staging and rollback directories with the affected service stopped. Preserve all trees. If restoring the old tree manually, first move the failed new tree to a uniquely named sibling, then move the correct rollback tree into the exact original server root. Restore `ps5:ps5` ownership and panel ACLs. Do not use recursive delete to "clean up" during recovery. Restart the service and verify world/player data.

RCON setup snapshots are in `/var/lib/ps5-panel/rcon-setup/TIMESTAMP/`, readable only by root. Restore individual properties only with the corresponding Minecraft service stopped. Keep the loopback firewall active even when rolling back RCON settings.

If panel startup fails:

```bash
sudo systemctl status ps5-panel --no-pager
sudo journalctl -u ps5-panel -n 100 --no-pager
sudo systemctl cat ps5-panel
sudo -u ps5-panel test -r /etc/ps5-panel/config.json
sudo ss -lntp 'sport = :8080'
```

For invalid Origin/CSRF errors, use the exact configured URL and sign in again. For RCON failures, check each server's diagnostics and completion of the setup script; do not print passwords. For journal failures check membership in systemd-journal. Reset an administrator through `panel.cli user admin` instead of editing hashes manually.

Uninstall script preserves everything except panel unit/helper/sudo authorization. To fully remove later, first disable RCON in both server properties and restart those services. Only then remove the two `ps5-panel-rcon.conf` drop-ins and disable/remove ps5-rcon-firewall.service. Remove just the dedicated nft table (never flush the host firewall). Remove ps5-panel ACL entries explicitly with setfacl -x u:ps5-panel and default entries on known roots. Preserve other users' ACLs. Account, code, database and config may be archived after confirming no recovery is needed. Never remove Minecraft roots or backups as part of panel uninstall.
