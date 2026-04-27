# AhaDiff Auth Token Threat Model

## Scope

This note describes the v0.1 localhost auth model used by `ahadiff serve`.
It is not user identity authentication.
It is a same-machine write guard for the local viewer and local API clients.

## 1. Token Generation and Storage

- The token is generated when `ahadiff serve` starts.
- Generation happens in `src/ahadiff/cli.py` via `secrets.token_urlsafe(24)`.
- The generated value is injected into `ServeState.token`.
- `ServeState` keeps the token in process memory only.
- The token is not written to `.ahadiff/`, config files, cookies, or localStorage.
- The current viewer fetches the token from `GET /api/auth/token`.
- The viewer caches the token in module memory (`viewer/src/api/client.ts`).
- The bootstrap fetch is capped at 8 seconds in `viewer/src/api/client.ts`.
- On `401` or `403`, the viewer clears the cached token and retries exactly once.
- If the serve process restarts, the old cached token becomes invalid.

## 2. Token Transmission

- Read bootstrap path: `GET /api/auth/token` currently returns `{ token, expires_at }`.
- `expires_at` is currently `null`; it does not carry a real TTL contract yet.
- Write path: mutating API calls send the token in `X-AhaDiff-Token`.
- Current backend verification is header-based only.
- Current backend compares the supplied token with `hmac.compare_digest(...)`.
- Current frontend transmission is header-based only.
- Query-parameter auth is not part of the implementation.
- Query-parameter auth is intentionally avoided because URLs leak through:
  - browser history
  - address-bar copy/paste
  - devtools/network exports
  - intermediary logs if a proxy is introduced later
- `Authorization: Bearer` is also not the current contract.

## 3. Threat Vectors

### XSS Token Theft

- If the local viewer ever gains an XSS bug, in-page JavaScript can call `/api/auth/token`.
- The same script can reuse the returned token for write endpoints.
- This is the main reason the token must not be treated as a durable secret.

### CORS Abuse

- A hostile web page can try to issue cross-origin requests to localhost.
- It may also trigger browser preflight requests to probe behavior.
- If the server reflected permissive CORS headers, the page could read responses.

### Iframe Embedding

- A hostile page can try to embed the viewer in an iframe and drive it with clickjacking.
- Embedded localhost UI increases the chance of token bootstrap and write misuse.

### Localhost Scanning

- Other pages or local processes can scan localhost ports and detect that AhaDiff is running.
- Port discovery alone is not enough for writes, but it reduces attack entropy.

## 4. Mitigations in Place

- Loopback-only bind: v0.1 serve rejects non-`127.0.0.1` bind targets.
- Host guard: middleware rejects non-loopback `Host` headers.
- Write token: mutating endpoints require `X-AhaDiff-Token`.
- Origin gate: write requests require loopback `Origin` or `Referer`, and the parsed port must match the current serve port.
- Preflight rejection: invalid cross-origin `OPTIONS` preflights now fail with `403`.
- Malformed IPv6 origins and loopback origins on the wrong port are rejected before write routes run.
- Body gate: mutating requests with a body must be `application/json`, and middleware caps the body at 1 MiB before JSON parse.
- No CORS allowlist response: the server does not add `Access-Control-Allow-Origin`.
- Anti-iframe headers:
  - `X-Frame-Options: DENY`
  - `Content-Security-Policy: frame-ancestors 'none'`
- MIME hardening header:
  - `X-Content-Type-Options: nosniff`
- Referrer hardening header:
  - `Referrer-Policy: same-origin`
- The security headers above are applied to both normal responses and middleware-generated error responses.

## 5. Residual Risks

- Browser extensions with broad page access can still read localhost pages and tokens.
- Local malware running as the same user can still call localhost endpoints directly.
- A local user-space debugger or traffic interceptor can inspect process memory or requests.
- Read endpoints remain intentionally easier to access than write endpoints.
- The token is a CSRF-style write guard, not a machine-hard trust boundary.
- If future work adds remote binding, reverse proxies, or multi-user exposure, this model is
  insufficient and must be replaced with stronger authentication and session isolation.

## Bottom Line

The current design is acceptable only for the documented local-first boundary:
same machine, loopback bind, no permissive CORS, token on write requests, and no iframe embedding.
It reduces casual cross-origin abuse, but it does not defend against privileged local attackers.
