# Authentication and token refresh

BrainPalace issues a short-lived **access token** and a longer-lived
**refresh token**. The access token expires after 15 minutes. When it expires,
the client exchanges the refresh token for a new access token at the
`/auth/refresh` endpoint.

## Refresh flow

1. Client detects a `401 Unauthorized` on an API call.
2. Client POSTs the refresh token to `/auth/refresh`.
3. Server validates the refresh token, rotates it, and returns a new
   access/refresh pair.
4. If the refresh token is expired or revoked, the client must re-authenticate
   from scratch with username and password.

Refresh tokens are rotated on every use to limit replay risk. A reused
(already-rotated) refresh token revokes the entire token family.
