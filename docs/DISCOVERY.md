# Live discovery — 24 October 2026

Access: Windows OpenSSH using the user-provided key; SSH works. Sudo requires an interactive password, so the root-only maintenance script has not yet been read. No sudo password has been assumed from the SSH key passphrase.

Confirmed:

- Debian host `ps5`, custom Linux 7.1.7 x86_64; user ps5 UID/GID 1000, groups include sudo.
- Approximately 14 GiB RAM, 7 GiB swap, 229 GiB filesystem with 219 GiB available at discovery.
- Both Java services active, owned by ps5, restart-on-failure, SIGINT shutdown and 180-second stop timeout.
- Survival Java 25, Xms1G/Xmx4G, `/srv/minecraft/vanilla/server.jar`; status protocol returns **Spigot 26.3**, 20-player capacity. One player was connected during discovery.
- SkyFactory Java 8, Xms1G/Xmx5G, specified Forge JAR; status returns 1.12.2, 10-player capacity.
- Survival RCON disabled. SkyFactory RCON enabled on **25575**, listening on wildcard interfaces. Actual read-only `list` with this implementation succeeded.
- Proposed panel port 8080 unused at discovery.
- Minecraft roots owned ps5:ps5, directories 0755; backup-set directory root:root 0755. Existing properties were read without printing RCON passwords.
- One backup set: `backup-2026-10-24_20-10-10`, containing `vanilla.tar.gz` (2,052,941,934 bytes), `skyfactory.tar.gz` (316,450,880 bytes), and `.complete`. Existing `.maintenance.lock` is present.
- Midnight timer active, `OnCalendar=*-*-* 00:00:00 Australia/Melbourne`, Persistent=false, AccuracySec=1s.
- Maintenance service root-owned oneshot invokes `/bin/bash /usr/local/sbin/minecraft-maintenance`, 60-minute timeout. Script content unreadable without sudo.
- AromaBackup is active in SkyFactory; its journal reports a completed backup. It is not disabled or rescheduled by the panel.
- Python 3.11.2 installed; python3-venv / ensurepip absent, so backend tests on Debian require installer dependencies first.

No world files, server settings, services or backup data were modified during discovery. A small diagnostic source bundle was uploaded under the ps5 home directory. That bundle is not an installed service.
