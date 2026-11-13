# Publish with Cloudflare

Nexus Minecraft is published on its own hostname (for example `minecraft.example.com`)
through the Nexus gateway and its Cloudflare Worker, behind Cloudflare Access. Nothing on
the server is exposed directly: the panel listens on `127.0.0.1:8080`, and the only path in
is the outbound Cloudflare Tunnel.

```
Browser ──► Cloudflare Access (owner only)
        ──► nexus-gateway Worker   (PANEL_HOSTNAME: serves only the panel on this hostname)
        ──► Workers VPC ──► cloudflared ──► Nexus gateway 127.0.0.1:8787
        ──► Nexus Minecraft 127.0.0.1:8080 (own login, CSRF, sessions)
```

The gateway, Worker and sign-in page live in
[NexusBackend](https://github.com/ljcatherine/NexusBackend). Set them up first.

## 1. Panel

In `/etc/ps5-panel/config.json`:

| Key | Value |
|---|---|
| `bind` | `127.0.0.1` |
| `port` | `8080` |
| `origin` | The panel's own HTTPS origin. The gateway rewrites requests to it, so it doesn't need to be publicly reachable. |
| `secure_cookie` | `true` |

## 2. Gateway

In the gateway's environment file, set both and grant `minecraft.panel` to your Access email
in `NEXUS_SUBJECT_PERMISSIONS_JSON`:

```sh
NEXUS_MINECRAFT_PANEL_ORIGIN=<the panel's origin from step 1>
NEXUS_MINECRAFT_PUBLIC_ORIGIN=https://minecraft.example.com
```

The gateway checks the browser's `Origin` against the public origin, rewrites it to the
panel's origin, and maps redirects and cookies back.

## 3. Worker

Add `minecraft.example.com` as a custom domain on the `nexus-gateway` Worker and set
`PANEL_HOSTNAME` to it. That hostname then serves only the panel (API, SSH and other routes
return 404 there), and the Worker strips Cloudflare's `CF_*` cookies before forwarding, so the
panel never sees your Access token.

## 4. Access

Make sure the Worker's Access application covers the new hostname and its Allow policy
includes only your email. With the Nexus sign-in page from NexusBackend's `auth/keycloak`
set as the only login method with instant authentication, opening the panel goes straight
to your Nexus sign-in.

## Check it

- Without signing in, `https://minecraft.example.com/` returns 401, or redirects a browser to sign-in.
- After signing in, the panel loads, and its scripts and styles return 200 (a 403 means the
  gateway's public origin doesn't match the hostname).
- `https://minecraft.example.com/v1/models` returns 404: the API isn't served on the panel's hostname.
