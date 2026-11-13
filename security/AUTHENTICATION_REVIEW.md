# Authentication review

The panel has application accounts; Tailscale connectivity is not treated as authentication. Password hashes use Argon2id. Passwords must be at least 12 characters for CLI account creation/invitation activation. Random session tokens are 32-byte URL-safe values; only SHA-256 digests are stored. CSRF values are random and session-bound. Sessions expire after eight hours and logout deletes the stored digest. Account password replacement and rename revoke sessions.

The cookie is HttpOnly and SameSite=Strict, with Secure in public mode. Exact Origin and CSRF token are required for authenticated API mutations; login and invite redemption still enforce exact Origin. Host and HTTPS requirements apply in public mode. WebSockets require matching Origin and session and recheck expiry. Login and invitation attempts are rate-limited by source address; hash work is bounded by a four-slot semaphore. The app has no password reset endpoint; account provisioning/reset is local CLI only. Invitation tokens are one-use, expire after 24 hours, and are stored as digests.

Review found no hardcoded passwords or credentials in frontend source; RCON credentials are read from server properties by backend and are not returned in settings. `server.properties` and name-matched secret files are excluded from the file API. Backup archives remain sensitive and admin-downloadable.

Tests cover unauthenticated 401, expired sessions, logout, Origin/CSRF, public host/scheme enforcement, login rate limiting, invite one-use and role checks, and forwarded-header trust. Public Funnel means internet users can reach authentication endpoints. Per-IP rate limiting does not prevent distributed spraying, and forwarding behavior/source IP under the actual Funnel path was not dynamically validated.

Residual: account credential strength and existing account inventory were not inspected; no secrets were requested or printed. Keep admin membership limited to trusted people because admin powers include console commands and server files.
