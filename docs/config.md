# Config

## Source Precedence

Configuration is resolved in this precedence order, from highest to lowest:

1. CLI arguments, such as `--home` or `--config-file`.
2. Environment variables, such as `OPENAI_API_KEY`, `LAWCHERS_EMBEDDING_API_KEY`, or `LAWCHERS_OCR_API_KEY`.
3. Explicit config file: `--config-file <path>`.
4. Project config: `./.lawchers/config.json`.
5. User config: `$LAWCHERS_HOME/config.json`.
6. Defaults.

`loadConfig()` merges internally in this order: defaults, user config, project config, explicit config file, explicit code overrides.

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

## Memory Config

No memory config is required. The default is a local deterministic rule extractor:

```json
{
  "memory": {
    "extractor": {
      "type": "rule",
      "confidenceThreshold": 0.5
    }
  }
}
```

Optional fields:

- `memory.dbPath`: explicit SQLite DB path.
- `memory.extractor.type`: `rule` or `noop`.
- `memory.extractor.confidenceThreshold`: minimum confidence for the rule extractor.

The current memory module reads `$LAWCHERS_HOME/config.json`, project `.lawchers/config.json`, and `--config-file <path>`.

## Secrets

- Config files should store provider names, endpoints, models, timeouts, and feature switches.
- API keys should be read from environment variables.
- Setup may write secrets only after explicit user approval.

## Provider Disabled

`type: "disabled"` is intentional and maps to `PROVIDER_DISABLED`. Missing credentials, unreachable providers, HTTP errors, and invalid provider responses map to `PROVIDER_UNAVAILABLE`.

## Doctor Checks

`lawchers doctor` should check:

- Config JSON parseability.
- Supported provider type.
- Required endpoint/model/apiKeyEnv fields.
- Referenced environment variables.
- Optional provider connectivity.
- Data directory readability/writability.
- SQLite open and basic read/write.
