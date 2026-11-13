# Hardening recommendations

## Before broad sharing

- Apply this release's admin-only file-content change.
- Confirm `sudo nft list ruleset` contains the active non-loopback drop for TCP 25575/25576. Review host IPv4/IPv6 firewall and router port-forwarding; allow only the Minecraft game ports that friends actually need. Keep RCON inaccessible off-host.
- Decide explicitly that Funnel means public internet access. If all friends can use Tailscale, prefer Serve and a narrow tailnet grant; if public access is needed, keep app login independent and share invitations only with named friends.
- Use unique 16+ character passwords and remove accounts promptly. Each invited admin can run console commands, restart both servers, manage files and create more admins. Consider viewer role for friends who only need observation.

## Host and operations

- With a verified second administrative path and rollback, inspect live sudoers, helper, maintenance script, SSH settings, nftables, ACLs and systemd unit. Do not make connectivity changes without a tested rollback.
- Separate the Minecraft runtime Unix user from the SSH identity. Restrict Java filesystem access and secrets using dedicated service accounts and explicit ACLs; plan a reversible migration.
- Keep restore disabled until a reviewer validates the live maintenance script, locking and isolated restore fixtures.
- Keep at least one encrypted off-device backup copy and perform periodic isolated restore verification.
- Review Tailscale grants, Funnel policy, device expiry and node ownership in the control plane.

## Application and supply chain

- Replace path validation with directory-descriptor-relative no-follow file operations if local plugins are within the threat model.
- Stream uploads to bounded temporary storage, cap concurrent multipart work at the server boundary, and require a clear confirmation/provenance step for plugin/mod JAR installation.
- Add Python advisory scanning, secret scanning and SBOM generation to CI. Review host Debian/Tailscale updates through trusted signed repositories.
- Keep security headers, test viewer/admin route boundaries, and repeat the public proxy origin/session checks after deployment.
