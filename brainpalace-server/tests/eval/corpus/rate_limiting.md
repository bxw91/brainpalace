# Rate limiting

The API enforces a **token-bucket** rate limit per client. Each client gets a
bucket of 100 tokens that refills at 10 tokens per second. Every request
consumes one token. When the bucket is empty the server returns
`429 Too Many Requests` with a `Retry-After` header.

Burst traffic up to the bucket size is allowed; sustained traffic is capped at
the refill rate. Rate-limit state is keyed by API key, not IP address, so
clients behind a shared NAT are not penalised for each other.
