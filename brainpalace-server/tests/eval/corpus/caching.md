# Query result caching

Query results are cached in memory with a time-to-live (TTL). The default TTL
is one hour. When the cache is full the least-recently-used (LRU) entry is
evicted to make room for new entries.

The cache is invalidated automatically whenever an indexing job completes, so
stale results are never served after the corpus changes. Non-deterministic
query modes (graph, multi) are never cached.
