# Security test results

Date: 2026-10-24. Local workspace tests were run after the viewer read fix.

| Test/check | Result | Evidence |
|---|---|---|
| Python test suite | PASS: 21 passed, 2 skipped | `.venv/Scripts/python -m pytest -q`; skips are POSIX ownership semantics and Windows symlink support. |
| Viewer file confidentiality | PASS | New regression: viewer can list tree but gets 403 for file body and download. |
| Extension installation | PASS | Both server destinations, admin role, trust confirmation, safe filename, ZIP validity, no overwrite, legacy uploader rejection and request size cap tested. |
| Authentication, session expiry/logout, rate limit, CSRF/Origin | PASS | Existing unit/integration tests. |
| Path traversal, symlink escape, world write protection | PASS in fixtures | Existing tests; live hostile race not attempted. |
| Archive traversal and RCON packet framing | PASS in fixtures | Existing safe fixture tests. |
| Frontend production dependency audit | PASS: zero reported | `npm audit --prefix frontend --omit=dev --json`. |
| Backend direct unauthenticated API | PASS for tested path | Earlier unauthenticated `/api/me` returned 401. No public endpoint sweep run. |
| Backend bind | PASS as configured | Live `ss`: panel TCP 8080 is `127.0.0.1`. |
| Tailscale Funnel exposure | FINDING | Live Serve/Funnel status says Funnel on; no public probing performed. |
| RCON firewall | NOT VERIFIED | Service active and repo rule found; live nftables state requires sudo. |
| Tailnet ACL/grants and unauthorized-device tests | NOT VERIFIED | No control-plane access; no external device test. |
| Router port forwarding / external Minecraft reachability | NOT VERIFIED | Router not inspected; no external scan. |
| Backup script, permissions and live restore | NOT VERIFIED | Script root-only; no sudo password or live destructive test. |
| Python advisory scanner, SBOM, SAST, secret scanner | NOT RUN | Tools not present/run. |
| Load/DoS testing | NOT RUN | Explicitly excluded for production safety. |

No Minecraft commands, world edits, uploads, backup jobs or service restarts were performed during this audit.
