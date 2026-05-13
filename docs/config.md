# Config

## Source Precedence

Configuration is resolved in this precedence order, from highest to lowest:

1. CLI arguments, such as `--provider`, `--model`, or `--base-url`.
2. Environment variables, such as `OPENAI_API_KEY`, `LAWCHERS_EMBEDDING_API_KEY`, or `LAWCHERS_OCR_API_KEY`.
3. Project config: `./.lawchers/config.json`.
4. User config: `$LAWCHERS_HOME/config.json` or `~/.lawchers/config.json`.
5. Defaults.

`loadConfig()` merges internally in this order: defaults, legacy user config, user config, project config, explicit overrides.

Merge semantics:

- Plain objects deep merge.
- Arrays replace previous arrays.
- `undefined` does not overwrite an existing value.
- `null` is an explicit overwrite.

## Provider Shape

```json
{
  "providers": {
    "embedding": {
      "type": "openai-compatible",
      "baseUrl": "https://api.openai.com/v1",
      "model": "text-embedding-3-small",
      "apiKeyEnv": "OPENAI_API_KEY"
    },
    "ocr": {
      "type": "disabled"
    },
    "rerank": {
      "type": "disabled"
    }
  }
}
```

## Secrets

- Config files should store provider names, endpoints, models, timeouts, and feature switches.
- API keys should be read from environment variables.
- Setup may write secrets only after explicit user approval.

## Provider Disabled

`type: "disabled"` is intentional and maps to `PROVIDER_DISABLED`. Missing credentials, unreachable providers, HTTP errors, and invalid provider responses map to `PROVIDER_UNAVAILABLE`.

## Doctor Checks

`lawchers doctor --json` should eventually check:

- Config JSON parseability.
- Supported provider type.
- Required endpoint/model/apiKeyEnv fields.
- Referenced environment variables.
- Optional provider connectivity.
- Data directory readability/writability.
- SQLite open and basic read/write.
