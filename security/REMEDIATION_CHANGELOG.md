# Remediation changelog

## 2026-10-24 — PA-01 viewer server-file read

- Cause: `GET /api/servers/{sid}/file` required a valid session but did not require the admin role. It returned arbitrary editable server-file text, including third-party plugin/mod configuration that may contain secrets. Download and mutations were already admin-only.
- Change: require admin for file-content reads in `panel/app.py`. The frontend can continue listing files; viewers retain read-only dashboard, players, settings and log access.
- Regression coverage: `test_viewer_cannot_read_server_files` verifies listing is allowed and both file-body and download requests return 403.
- Verification: full local suite 18 passed, 2 skipped.
- Deployment: not applied to the server in this audit. Deploy via normal release after reviewing remaining host access controls.

## 2026-10-24 — Dedicated plugin/mod installation

- Added an admin-only Extensions upload flow with explicit trust confirmation and per-server fixed install directories (`plugins/` for Survival, `mods/` for SkyFactory).
- JAR uploads are size-limited, checked as ZIP/JAR archives, protected against filename traversal and overwrites, and written via a bounded atomic stream. The generic file uploader no longer accepts executable JARs. Installation does not restart a live server.
- Regression tests cover both server folders, authorization, confirmation, invalid archives/names, duplicate names, generic uploader rejection and request-size rejection.
- Verification: 21 tests passed, 2 platform-dependent skips; TypeScript check and Vite production build passed.
- Deployment: local workspace only; the installed panel has not been updated.

## Deferred

No live Tailscale, nftables, SSH, sudoers, systemd, RCON, maintenance or Minecraft changes were made. These could interrupt connectivity or running services and need host evidence/rollback preparation. Funnel remains enabled as the user previously requested internet access.
