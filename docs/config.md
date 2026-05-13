# Config

## Source Precedence

Configuration is resolved in this order:

1. CLI arguments, such as `--provider`, `--model`, or `--base-url`.
2. Environment variables, such as `OPENAI_API_KEY`, `LAWCHERS_EMBEDDING_API_KEY`, or `LAWCHERS_OCR_API_KEY`.
3. Project config: `./.lawchers/config.json`.
4. User config: `$LAWCHERS_HOME/config.json` or `~/.lawchers/config.json`.
5. Defaults.

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

## Doctor Checks

`lawchers doctor --json` should eventually check:

- Config JSON parseability.
- Supported provider type.
- Required endpoint/model/apiKeyEnv fields.
- Referenced environment variables.
- Optional provider connectivity.
- Data directory readability/writability.
- SQLite open and basic read/write.
