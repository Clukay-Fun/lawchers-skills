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

## Recommended package: CLUENER RoBERTa ONNX

| Field | Detail |
|-------|--------|
| Upstream model | `uer/roberta-base-finetuned-cluener2020-chinese` |
| Training data | CLUENER2020 train set |
| Entity types used by this project | PERSON / ORG / ADDRESS |
| Raw labels | name, company, government, organization, address, scene, plus non-PII classes |
| Format | ONNX token classification, 32 BIOES labels |
| License | Upstream model card does not state a weights license; verify before commercial redistribution |

```text
ModelScope: https://modelscope.cn/models/Clukay416/legal-desens-cluener-onnx
Asset:      cluener-roberta-base-onnx.zip
SHA-256:    13958b2a4aff99fef17c22d844963d10cc0fd6fbbd83b01844fef527b23e1b6a
```

Install:

```bash
legal-desens install-model \
  --url "https://modelscope.cn/models/Clukay416/legal-desens-cluener-onnx/resolve/master/cluener-roberta-base-onnx.zip" \
  --sha256 "13958b2a4aff99fef17c22d844963d10cc0fd6fbbd83b01844fef527b23e1b6a"
legal-desens ner-inspect
```

`legal-desensitizer` maps `name` to `PERSON`, company/government/organization
to `ORG`, and address/scene to `ADDRESS`. Book, game, movie, and position labels
are preserved as non-PII by the bundled profiles.

## Adding More Candidates

To add a new candidate model, it must:

1. Be exportable to ONNX with `model.onnx` + `config.json` + `vocab.txt`
2. Have a permissive license (Apache-2.0, MIT, BSD) — no AGPL/GPL
3. Be documented here with license, training data, entity types, and known limitations
4. Never be set as default or treated as a security guarantee
