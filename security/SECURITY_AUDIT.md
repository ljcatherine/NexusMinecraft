# Nexus Minecraft security audit

**Assessment date:** 2026-10-24  
**Scope:** repository, local tests and read-only checks of the Debian 12 host over SSH.  
**Status:** source review and local verification complete; several privileged host controls are explicitly not verified.

## Executive assessment

The panel has meaningful application controls: Argon2id passwords, hashed random session tokens, HttpOnly/SameSite cookies, CSRF and exact-Origin checks, per-IP login throttling, server-side admin checks, allowlisted systemd operations, a non-root service account, and loopback binding behind Tailscale. The live host confirms that both the backend and Tailscale proxy are configured as expected.

The access path is **public internet, not tailnet-only**. `tailscale funnel status` reports Funnel enabled at `https://panel.<tailnet>.ts.net`, proxying to `127.0.0.1:8080`; this also matches the user's earlier request to let friends access the panel without Tailscale. Funnel provides public HTTPS transport, not tailnet identity authentication. Application login is independently enforced. Anyone on the internet can reach the login page and authentication endpoints. The backend listens only on loopback, and unauthenticated `/api/me` returned 401 in the earlier safe check. Do not describe this deployment as private to Tailscale.

No confirmed unauthenticated administrative control, shell injection, SQL injection, or root bypass was found in the reviewed application. One confirmed confidentiality/authorization issue was fixed: viewer accounts could read arbitrary server files, including configuration files. A regression test now proves file-content access is admin-only. Local tests pass (18 passed, 2 platform-dependent skips); production frontend dependency audit reports zero known vulnerabilities. No application release has been deployed from this audit.

**Overall:** suitable for controlled access only if the owner intentionally accepts public login exposure, uses unique strong passwords, keeps invitations private, and confirms host firewall rules. The host's wildcard Minecraft/RCON listeners make that firewall confirmation material. Because sudo and the maintenance script could not be inspected, I cannot certify the complete host attack surface or backup job safety.

## Findings

| ID | Severity | Finding | Status |
|---|---|---|---|
| PA-01 | Medium | Viewer could read server files/configuration through `/api/servers/{sid}/file`. | Fixed locally; regression test passes. Deployment pending. |
| PA-02 | Informational | Tailscale Funnel publishes the panel URL to the public internet. | Confirmed and consistent with the user's request; app authentication remains required. |
| PA-03 | Medium (unverified host boundary) | Minecraft and RCON sockets bind wildcard addresses; actual nftables enforcement was not readable without sudo. | Firewall service/rule exists and is active by systemd status, but loaded rule set not verified. |
| PA-04 | Medium (operational) | Maintenance script and its retention/failure behavior could not be read or audited. | Not verified; sudo required. |
| PA-05 | Low (availability) | General text/config uploads remain buffered up to 64 MiB; multiple authorized uploads can use memory and temporary storage. | JAR extension uploads are capped at the ASGI boundary and streamed atomically. No stress test run. |
| PA-06 | Informational | Admin can upload plugin/mod JARs, issue arbitrary Minecraft console commands, and restart services. A malicious JAR executes as the `ps5` Minecraft account. | Intrinsic consequence of full administrator capability; grant admin only to trusted people. |
| PA-07 | Informational | World data and backup sets share the same external USB storage device. | Disaster-recovery risk; use a separate encrypted/off-device copy. |

No CVSS score is assigned where reachability or exploit preconditions cannot be established from available evidence. PA-01 is CWE-862/CWE-200. PA-03 maps to CWE-668 pending firewall verification. PA-05 is CWE-400. PA-06 is CWE-434 by design when an administrator deliberately installs executable server extensions.

## Architecture and live evidence

- FastAPI/Starlette backend, SQLite account/session store, React/TypeScript static frontend, RCON client, systemd helper, existing Minecraft maintenance job.
- Panel unit is active as `ps5-panel.service`, process user `ps5-panel`, and listens on `127.0.0.1:8080` only.
- Tailscale 1.104.2 is connected. Funnel and Serve status both show HTTPS port 443 proxying to loopback port 8080. Tailscale assigned IPv4 and IPv6 addresses; control-plane policy was not inspected.
- `mc-vanilla.service`, `mc-skyfactory.service`, `minecraft-maintenance.timer`, and `ps5-rcon-firewall.service` were active. Both Java servers were running during inspection; neither was restarted.
- `ss -tulpn` showed SSH on all IPv4/IPv6 interfaces, Minecraft TCP 25565/25566 on wildcard interfaces, and RCON TCP 25575/25576 on wildcard interfaces. The panel itself was not wildcard-bound. No database listener was observed.
- `sudo -n nft`, `sudo -n ufw`, `sudo -n visudo`, and sudoers inspection were unavailable because the SSH account requires an interactive sudo password. The repository's nftables unit installs an `inet` input rule dropping non-loopback TCP 25575/25576, but runtime enforcement is not confirmed.
- Router forwarding, external Minecraft reachability, tailnet grants/ACLs, device expiry, SSH configuration, kernel patch provenance, storage encryption, and off-device restore verification were not verified.

## Authentication and authorization

Passwords use Argon2id. The app sets an 8-hour, HttpOnly, SameSite=Strict session cookie, Secure in public mode. Session IDs are stored as SHA-256 digests. Login/invite redemption use a four-slot password hash semaphore and limit attempts by source address to eight per 15 minutes. Mutations require exact Origin and session CSRF token. WebSockets require exact Origin and a live session and recheck expiry. Admin checks are server-side. See [AUTHENTICATION_REVIEW.md](AUTHENTICATION_REVIEW.md) and [AUTHORIZATION_MATRIX.md](AUTHORIZATION_MATRIX.md).

The frontend escapes console and log text through React text rendering; syntax highlighting uses highlight.js escaped output. Security headers include CSP, frame denial, no-sniff, no-referrer and no-store. Restore remains disabled by default. File operations reject traversal and symlinks at check time; concurrent local symlink races are not closed with descriptor-relative operations.

## Privilege, RCON and backups

The application runs unprivileged and invokes a fixed root-owned helper through sudo. The helper uses isolated Python, fixed executable paths, fixed Minecraft unit names, no shell, constrained arguments, locks, and a staged restore with rollback. The panel service has systemd filesystem protections and resource limits. `NoNewPrivileges` is absent because this design requires a sudo transition. `systemd-analyze security` reported exposure 7.4 MEDIUM; this aggregate score is not itself a vulnerability and includes intentional capabilities.

Both RCON listeners bind wildcard addresses on the live host. The repository's firewall service drops non-loopback access to those ports, and RCON credentials are read server-side and never sent to the browser. The firewall is not independently verified in the live ruleset. RCON itself is unencrypted and should remain loopback-only.

Restore is locked by default and fixture tests reject traversal. The root helper stages regular files only, rejects links/devices and cross-server archives, preserves current RCON settings, and retains a rollback directory. The live maintenance script, backup permissions, archive retention, available disk and recovery behavior remain unverified. The panel exposes backup downloads only to admins; those archives may contain historical credentials.

## Dependencies and test coverage

Full `npm audit` reported zero vulnerabilities in 112 resolved dependencies, including development/optional dependencies (46 production packages). Python runtime dependencies are pinned in `requirements.lock.txt`; no Python advisory scanner or SBOM generator was available/run. No automated upgrade was made. See [DEPENDENCY_AUDIT.md](DEPENDENCY_AUDIT.md).

The local suite passed 21 tests with 2 skips (POSIX ACL semantics and platform-specific symlink support). The test suite exercises auth/session expiration, role checks, CSRF/origin, rate limits, symlink rejection, path traversal, archive traversal, RCON framing, settings, invitation flow, viewer file denial and extension upload policy. The live hosts were not subjected to fuzzing, load testing, world mutation or restore. See [SECURITY_TEST_RESULTS.md](SECURITY_TEST_RESULTS.md).

## Standards and limitations

Assessment used the [OWASP ASVS 5.0.0](https://asvs.owasp.org/) as the verification baseline, the [OWASP WSTG 4.2 stable guide](https://owasp.org/www-project-web-security-testing-guide/) for test methodology, and CWE categories for findings. This is a focused application and host review, not a formal certification or exhaustive penetration test.

**Before calling the deployment fully assessed:** verify `sudo nft list ruleset`, inspect sudoers/helper and `/usr/local/sbin/minecraft-maintenance`, inspect router forwards, review tailnet grants/ACLs and Funnel policy, and confirm an off-device backup restore. Apply this audit's application fix via the normal release/install workflow, then recheck the test suite and public login behavior.
