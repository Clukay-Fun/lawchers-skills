# Optional NER Models (Best-Effort Candidates)

This document records candidate NER models that can be used with `--model-dir` or `install-model --url`. These are **optional best-effort enhancements**, not default, and not security guarantees.

## Default Mode

**No NER model is required.** The default `--regex-only` mode handles structured PII reliably:

- Phone numbers (Chinese mobile)
- ID card numbers (18-digit)
- Email addresses
- Case numbers (案号)
- Unified social credit codes (统一社会信用代码)
- Monetary amounts (金额 — Chinese numerals + Arabic digits)

Regex is deterministic, auditable, and requires no model download.

## Candidate: shibing624/bert4ner-base-chinese

| Field | Detail |
|-------|--------|
| Model | `shibing624/bert4ner-base-chinese` |
| License | Apache-2.0 (model weights) |
| Training data | People's Daily + CNER (layer-b: underlying news text copyright belongs to original authors; weights released under Apache) |
| Entity types | PER / ORG / LOC / TIME (BIO scheme) |
| Format | HF token-classification → exportable to ONNX |

### GitHub Release Asset Distribution

Do not commit model weights to git. Publish exported model archives as GitHub Release Assets in this repository.

Recommended release layout:

```text
Repository: https://github.com/Clukay-Fun/lawchers-skills
Tag:        legal-desens-ner-v0.1
Asset:      bert4ner-base-chinese-onnx.zip
```

The asset archive must extract directly to a model directory containing:

```text
model.onnx
config.json
vocab.txt
labels.json
```

Install command template:

```bash
legal-desens install-model \
  --url "https://github.com/Clukay-Fun/lawchers-skills/releases/download/legal-desens-ner-v0.1/bert4ner-base-chinese-onnx.zip" \
  --sha256 "d572400b7b46c104bb41f95f6c665ded5274aecf14cd49fd9c3d7bf2b6d55703"
```

Before publishing a URL in docs, compute and record the archive hash:

```bash
shasum -a 256 bert4ner-base-chinese-onnx.zip
```

Release notes must include:

- upstream model name and URL
- upstream license
- known limitations below
- SHA-256: `d572400b7b46c104bb41f95f6c665ded5274aecf14cd49fd9c3d7bf2b6d55703`
- statement that NER is optional best-effort, not a safety guarantee

### Known Limitations (Desensitization Perspective)

These are **inherent to the general-domain training data** and apply to any similar model:

- **Misses company names**: "某某科技有限公司" often only partially captured as LOC (administrative region), not ORG
- **Misses address tail segments**: door numbers like "100号" frequently dropped; addresses become fragmented
- **No MONEY entity**: monetary amounts are not covered by this model — rely on regex
- **General news domain, not legal domain**: performance on legal-specific entities (court names, case parties, legal terms) is untested
- **Recall does not meet desensitization safety standards**: must not be treated as a security guarantee

### How to Use

1. Export the HF model to ONNX (see `scripts/export_hf_ner_onnx.py`):
   ```bash
   python scripts/export_hf_ner_onnx.py \
     --hf-model shibing624/bert4ner-base-chinese \
     --output-dir ~/.legal-desens/models/bert4ner-base-chinese
   ```

2. Verify the export:
   ```bash
   legal-desens ner-inspect --model-dir ~/.legal-desens/models/bert4ner-base-chinese
   ```

3. Use with redact:
   ```bash
   legal-desens redact input.txt --level strict \
     --model-dir ~/.legal-desens/models/bert4ner-base-chinese \
     --out out.txt --map m.json --audit a.json
   ```

### Audit Annotation

When NER is enabled (with any model, including bert4ner), the audit output and map will include:

- `mode: "regex+ner"` (not `regex-only`)
- A `best_effort_notice` warning in audit, indicating NER results are best-effort
- Agent reports must state "regex+ner (best-effort)" and note possible misses

## Adding More Candidates

To add a new candidate model, it must:

1. Be exportable to ONNX with `model.onnx` + `config.json` + `vocab.txt`
2. Have a permissive license (Apache-2.0, MIT, BSD) — no AGPL/GPL
3. Be documented here with license, training data, entity types, and known limitations
4. Never be set as default or treated as a security guarantee
