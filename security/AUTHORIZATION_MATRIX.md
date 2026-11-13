# Authorization matrix

Legend: **Any** means signed-in admin or viewer; **Admin** means server-side admin role; **No** means authentication is not accepted.

| Route / operation | Anonymous | Viewer | Admin |
|---|---:|---:|---:|
| `POST /api/login` | Login only | Login only | Login only |
| `POST /api/invites/redeem` | Valid one-use invite + exact Origin | Same | Same |
| `GET /api/me`, dashboard, logs, players, settings, diagnostics, extensions | 401 | Any | Any |
| `GET /api/accounts`, `GET /api/audit` | 401 | 403 | Admin |
| `POST /api/invites` | 403 | 403 | Admin + CSRF/Origin |
| `POST /api/logout` | 403 | Session + CSRF/Origin | Session + CSRF/Origin |
| `POST /api/servers/{sid}/power/{action}` | 403 | 403 | Admin + allowlisted action + CSRF |
| `POST /api/servers/{sid}/command`, `/players` | 403 | 403 | Admin + validation + CSRF |
| `GET /api/servers/{sid}/files` and `/file` | 401 | List only; file body now 403 | Admin |
| `POST /api/servers/{sid}/files`, `/upload` | 403 | 403 | Admin + CSRF + path/extension checks |
| `GET /api/servers/{sid}/download` | 401 | 403 | Admin |
| `PUT /api/servers/{sid}/settings` | 403 | 403 | Admin + allowlisted settings + CSRF |
| `GET /api/backups`, `/logs`, `/inspect` | 401 | Any | Any |
| `GET /api/backups/download`, `POST /run`, `/restore` | 403 | 403 | Admin + CSRF; restore additionally disabled by default |
| Restore job status | 401 | 403 | Admin |
| `/api/live`, server console WebSockets | Close/reject | Authenticated live/log stream | Authenticated live/log stream |

Server IDs are resolved against fixed config keys. Systemd helper actions are restricted to known units. File path handling rejects absolute paths, `..`, backslashes, colons, NUL and symlink components; all mutating file operations also require admin and CSRF. The fixture regression proves viewer file-body denial after the audit fix. Route matrix is based on source inspection and tests, not a production role-by-role dynamic test.
