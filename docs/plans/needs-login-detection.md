# Needs-Login Detection

- Created: 2026-07-08 10:05
- Last updated: 2026-07-08 10:05

## Problem

When the Claude Code OAuth session dies (refresh token rotated/rejected, or creds
cleared from the keychain), ClaudeWatch shows only the generic stale icon and backs
off up to 64 minutes. The user gets no hint that re-running `claude` and logging in
is the fix, and recovery after re-login can lag by a full backoff cycle
(observed 2026-07-08: creds restored at 09:44, next poll not until 10:46).

## Design

### Detection (`fetch_oauth_usage`)

Return a new `"needs_login"` sentinel (same convention as `"rate_limited"`) when
self-recovery is impossible:

1. Keychain item missing, or payload has no `accessToken`.
2. Token refresh endpoint rejects the refresh token with HTTP 400/401/403.
   `_refresh_oauth_token` distinguishes "rejected" (auth-dead) from network
   errors (transient, stays `None`).
3. Usage API still returns 401 after a successful refresh.

Transient failures (network, 5xx, parse errors) keep returning `None`.

### Display (menubar only)

New `_needs_login` flag on the app; set when a poll returns `"needs_login"`,
cleared on the next successful fetch.

- Menubar title: `🔑 login` (replaces the usage/countdown display).
- Dropdown `status_item`: `🔑 Claude login expired — run claude and log in again`.
- 5h/7d dropdown lines keep last stale values with the ⚪ icon.
- Tooltip: `Login expired — last updated <ago>`.

### Recovery

While `_needs_login`:

- API backoff no longer grows (no API retry can succeed without new creds).
- Every 30 s do a local keychain read (free, no rate-limit cost). Remember the
  access token that failed; when a different token appears (user re-logged-in),
  immediately poll the API. Menubar recovers within ~30 s of re-login instead of
  up to 64 min.

## Steps

1. Detection: `"needs_login"` sentinel from `fetch_oauth_usage` /
   `_refresh_oauth_token` + tests.
2. App state & display: `_needs_login` flag, menubar/dropdown/tooltip rendering,
   30 s keychain watch and fast recovery + tests.

## Testing

- Extend `test_status.py` (existing check-style harness) with mocked
  keychain/HTTP coverage of the sentinel paths and the state transitions.
- Live sanity check: restart the app, verify normal display; simulate
  needs-login by pointing the reader at a bogus account if practical.
