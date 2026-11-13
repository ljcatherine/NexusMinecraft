# Threat model

## Assets and boundaries

Assets: admin passwords/sessions, Tailscale node identity, RCON passwords, SSH access, server files and plugins, worlds/player data, backups, panel database/configuration and host privileges.

Boundaries: browser → public Tailscale Funnel TLS relay → tailscaled proxy → loopback HTTP backend → SQLite/filesystem/RCON/systemd helper → Java processes running as `ps5`. Funnel makes the browser entry public; HTTPS protects transport but does not assert a tailnet identity. App accounts provide the independent identity boundary. The panel service account has access to Minecraft roots and journal data. The Java process shares the `ps5` Unix identity with the interactive SSH account.

## Actors and paths

| Actor | Credible path | Control / residual risk |
|---|---|---|
| Internet user | Reach Funnel login → password guessing or exploit | TLS and independent login; IP throttling; public endpoint remains exposed to password spraying and software flaws. |
| Stolen panel admin | Use console, service restart, file writes, invitations, downloads | Full intended admin power; can install code as a plugin/mod and execute as `ps5`. Revoke account/session and restore from separate backups. |
| Viewer | Read dashboard/logs/player data; attempt API mutations or sensitive reads | Mutations and admin endpoints server-side blocked. File read now admin-only. Viewer still sees operational information. |
| Compromised tailnet device/user | Try LAN/tailnet panel, SSH, Minecraft, or RCON | App auth remains required; grants/ACLs not verified. RCON firewall runtime not verified. |
| Malicious Minecraft player | Exploit server/mod, social-engineer admin | Java process runs as `ps5`; this account also owns server files and is the SSH account. Host isolation from the Minecraft account is limited. |
| Malicious plugin/mod | Execute in Java process, read/write as `ps5`, attack host services | Minecraft itself is an execution environment; review provenance and retain offline backups. Root helper narrows direct sudo. |
| Local limited filesystem attacker | Symlink swap during file-manager checks | Request-time symlinks rejected, but filesystem operations are path-based and race-resistant `openat`/`openat2` enforcement is absent. |
| Host root/`ps5` user | Modify services, files, firewall, credentials | Trusted host administrators; panel does not contain this threat. |

## Main attack chains

1. Public password spray → stolen admin → unrestricted Minecraft console / plugin upload / server restart → Java code execution as `ps5`. Unique passwords, private invitations, prompt account revocation and rate-limit observability reduce likelihood.
2. Viewer account → privileged API request → expected 403. File content read previously crossed this boundary; fixed locally and covered by regression test.
3. Compromised plugin → `ps5` filesystem and SSH identity → server or host compromise. This is the most material shared-account design risk; panel compromise does not need root to damage worlds.
4. External traffic → wildcard Minecraft/RCON sockets → host rules/router → services. Runtime nftables and router state are not verified. The configured nftables rule intends to drop non-loopback RCON.
5. USB failure/theft → worlds and all on-device backups lost together. Maintain encrypted off-device copies and periodically verify restores.

See [SECURITY_AUDIT.md](SECURITY_AUDIT.md) for findings and evidence.
