# Configuration via environment variables

BrainPalace reads configuration from environment variables and an optional
`config.yaml`. Environment variables always take precedence over the YAML file.

Common variables:

- `BRAINPALACE_STATE_DIR` — where the index and metadata live.
- `QUERY_CACHE_TTL` — query cache time-to-live in seconds.
- `ALLOW_SPECIAL_TOKENS_IN_TEXT` — when true, special-token literals such as
  `<|endoftext|>` in indexed text are counted as plain characters instead of
  crashing the tokenizer.
