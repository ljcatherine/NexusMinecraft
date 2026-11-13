# Validation record

## Remote-access update, 24 October 2026

- Existing production panel verified HTTP 200 for the frontend and 401 for anonymous `/api/me`; systemd panel service active/enabled at about 39 MiB RSS. Both Minecraft services, the backup timer and RCON firewall service remain enabled.
- Original 10 backend tests passed on Debian, including POSIX symlink rejection.
- Both live Minecraft RCON endpoints subsequently returned `list` successfully: Survival 25575 and SkyFactory 25576. No disruptive command was used for these checks.
- Public-access update staged under `~/ps5-panel-public`; its 17-test backend suite passed on Debian. Four isolated restore fixture tests also passed.
- Two later validation-only tests cover trusted-proxy spoof rejection and POSIX shared-group atomic-write behavior. The final Windows suite passed 17 tests and skipped two POSIX-specific cases. The frontend production build passes; npm production audit reports zero known vulnerabilities.
- Tailscale installation, renaming the production admin account, the first friend invitations and external HTTPS/login/WebSocket checks were left for the owner to run interactively. (That Tailscale Funnel path has since been replaced by Cloudflare Access; see the README.)

Actually executed locally on Windows:

- Python dependency installation into isolated venv.
- React/TypeScript production build.
- pytest: **9 passed, 1 skipped** at initial backend milestone. The skip is Windows symlink creation permissions. Later changes require a final rerun recorded in the chat.
- Tests cover authentication/expiry/logout, CSRF/origin, viewer denial, path traversal, secret redaction, JSON validation, concurrent-edit revision conflict, edit snapshots, world protection, legacy capability filtering, rate limiting, authenticated WebSockets, archive traversal, command injection, legacy-compatible multiframe RCON.

Actually executed against the server, read-only:

- SSH, systemd unit inspection, runtime/permissions/port discovery.
- Java status queries against Survival 25565 (Spigot 26.3) and SkyFactory 25566 (1.12.2).
- New RCON client `list` on SkyFactory; successful response.

Not yet executed:

- Installer/service enable/boot, restricted sudo helper under systemd sandbox.
- Both-server start/stop/restart and post-restart readiness.
- Survival RCON (currently disabled), whitelist/OP mutations on either server.
- Browser UI visual review against deployed backend.
- Actual backup validation on the full 2.3 GiB set, manual maintenance run.
- Actual restore. Never test against the only world copy.
- Retention script review, restart and reboot recovery.

Post-install checklist:

1. Run pytest on Debian with a temporary filesystem, including symlink test.
2. Create admin/viewer; test login/logout/expiry and denied viewer writes.
3. Confirm RCON firewall drops LAN IPv4/IPv6 access while localhost works on both new ports.
4. With warning/countdown, restart each server, inspect console for Done, verify status protocol and RCON `list` after startup. Preserve existing ops/whitelist.
5. Make a disposable text file, upload/edit/download/rename/delete it. Test malformed JSON, symlink and traversal rejection.
6. Read maintenance script and confirm `.complete`, retention and `.maintenance.lock` semantics. Validate full existing archive without extraction, inspect midnight timer unchanged.
7. Test restore only on independent scratch roots with simulated services before enabling production restore usage.
8. Confirm service enabled; schedule an authorized reboot separately and verify panel/Minecraft/timer recover.
