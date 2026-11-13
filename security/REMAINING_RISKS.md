# Remaining risks

1. **Public login surface:** Funnel makes the app reachable from the general internet. This is intentional from the earlier request, but expands exposure beyond a tailnet. A stolen admin can fully operate both servers. Apply the local file-read fix before calling deployment current.
2. **Firewall and game port reachability:** Minecraft and RCON listeners bind wildcard addresses. The intended RCON nftables rule is present in source and firewall service is active, but the live rule set and router are unverified. Until checked, external reachability of 25565/25566/25575/25576 is unresolved.
3. **Shared `ps5` identity:** SSH and Minecraft Java use the same Unix user. A malicious mod/plugin has the user's filesystem authority. This is a host boundary risk, not a root-helper bypass.
4. **Maintenance/backup script:** Root-only maintenance script and live backup retention/failure semantics could not be reviewed. Both worlds and backups share one USB device.
5. **Filesystem TOCTOU:** Symlink checks are path-based; local/plugin code can race directory changes between validation and use.
6. **Upload resource use and executable artifacts:** authenticated admins can consume bounded but substantial memory/disk with multiple multipart uploads and install executable JARs. An admin already holds broad Minecraft control; do not grant this role to untrusted users.
7. **Tailnet policy:** ACL/grants, device expiry and device ownership were not available. Network identity policy cannot be claimed least privilege.
8. **Verification gaps:** no external port scan, unauthorized-device test, Python advisory scanner, SBOM, SAST, secret scan, host package audit, or production load test.
