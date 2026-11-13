# Network exposure

Observed by SSH on 2026-10-24. Neither Minecraft server was restarted.

| Interface | Listener | Observed binding | Assessment |
|---|---|---|---|
| LAN | Panel TCP 8080 | `127.0.0.1` | Not directly LAN-bound; LAN URL will not reach backend. |
| Tailscale | HTTPS TCP 443 | `100.77.92.74%tailscale0` and Tailscale IPv6 | Serve proxy listener. |
| Public internet | HTTPS TCP 443 Funnel | Public `*.ts.net` URL, proxy to `127.0.0.1:8080` | Confirmed public panel route; app login still required. |
| LAN/tailnet/public path depends on firewall | SSH TCP 22 | `0.0.0.0` and `[::]` | Reachability and SSH policy not verified. |
| LAN/tailnet/public path depends on firewall/router | Minecraft TCP 25565/25566 | wildcard | Bound on all interfaces; router/firewall reachability not verified. |
| LAN/tailnet/public path depends on firewall | RCON TCP 25575/25576 | wildcard | Configured nftables drop exists; live ruleset could not be read. Treat exposure as unresolved. |
| Host-local | SMTP 25, CUPS 631 | loopback | Local only as observed. |
| UDP | 5353, Tailscale UDP, other ephemeral | wildcard/Tailscale interface | Includes mDNS and Tailscale; no full protocol attribution performed. |

`tailscale status`, `tailscale ip -4`, `tailscale serve status`, `tailscale funnel status`, `ss -tulpn`, `ip -br address`, and `ip route` were inspected. The backend directly binds loopback; host forwarding to 443 is Tailscale's proxy. A previous unauthenticated `/api/me` check returned 401. No external probes, port scans or public endpoint testing were performed in this audit.

`sudo -n nft list ruleset` and `sudo -n ufw status verbose` returned “a password is required.” Router forwarding and IPv6 firewall state are therefore **NOT VERIFIED**. Do not infer from a loopback panel socket that wildcard Minecraft sockets are private.
