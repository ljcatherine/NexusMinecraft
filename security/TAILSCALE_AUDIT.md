# Tailscale audit

- Live client version: 1.104.2; backend state `Running`; assigned IPv4 and IPv6 Tailscale addresses.
- Hostname: `panel.<tailnet>.ts.net`.
- Serve and Funnel both report HTTPS 443 proxying to `http://127.0.0.1:8080`.
- Funnel is enabled. Funnel routes traffic from the broader internet and is not limited to tailnet members; this is consistent with the user's stated goal of access for friends without a domain. See [Tailscale Funnel documentation](https://tailscale.com/kb/1223/funnel).
- Backend listens only on loopback. App authentication is independent from possession of a Tailscale connection; public users see an unauthenticated login, and protected APIs require a valid app session.
- The public setup uses loopback as the only trusted proxy address and configures the app's expected HTTPS origin/host. The current running config values were not printed because it contains sensitive settings. Proxy code rejects any non-loopback trusted-proxy configuration.
- Tailnet owner, device owner, device expiry, tags, grants/ACLs, Funnel policy, DNS settings, key expiry and other tailnet users' reachability were **NOT VERIFIED**; no control-plane admin integration was available.
- No tests using unauthorized tailnet devices or external internet were conducted.

Recommendation: keep the panel public only if that remains intentional. Share individual one-use invitations privately, use unique long passwords, remove accounts that no longer need access, and consider a tailnet-only Tailscale Serve endpoint or an identity-aware access gateway if public login is no longer required. Review Funnel enablement policy in the tailnet console.
