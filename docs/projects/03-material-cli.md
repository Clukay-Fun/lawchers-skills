# Project 3: Material CLI

## Goal

Provide the shared local material parsing foundation for files, folders, and archives.

Future commands:

```bash
material parse <path>
material extract-text <path>
material prepare <path>
material inspect <path>
```

## Scope

- PDF, DOCX, TXT, MD, HTML, image, and spreadsheet parsing.
- Archive expansion with strict safety controls.
- Hidden file filtering and extension allowlists.
- Temp workspace creation, cleanup, and doctor cleanup.
- OCR provider order and fallback chain.
- Unified Markdown, plain text, sections, quality, and warning output.
- Colocated `material-tools` skill documentation under `packages/material-cli/skills/material-tools/`.

## Non-Goals

- No business evidence extraction.
- No legal fact classification.
- No Bridge turn resource lifecycle.
- No platform upload/download adapters.

## Target Output Shape

```json
{
  "ok": true,
  "result": {
    "fileName": "contract.pdf",
    "mimeType": "application/pdf",
    "localPath": "/absolute/path/to/file.pdf",
    "markdown": "",
    "plainText": "",
    "sections": [
      { "location": "PDF 1", "text": "" }
    ],
    "parserUsed": "pymupdf4llm",
    "quality": "high",
    "fallbackChain": ["pymupdf4llm"]
  },
  "warnings": []
}
```

## Development Phases

1. Define file inspection, parser result, warning, and quality schemas.
2. Implement path validation and allowed-root checks.
3. Implement temp workspace lifecycle.
4. Implement plain text, Markdown, HTML, and DOCX parsers.
5. Implement PDF parser fallback chain.
6. Implement image/OCR path as optional provider-backed behavior.
7. Implement archive expansion and folder preparation.
8. Add fixtures and CLI contract tests.

## Acceptance Criteria

- Unsupported files fail with stable JSON errors.
- Archive extraction blocks unsafe paths and oversized archives.
- Temp workspace cleanup is deterministic on normal exits.
- Parser fallback chain is visible in output.
- No parser logs full document text.

## Risks

- Heavy parser dependencies bloating every install.
- OCR provider costs or privacy surprises.
- Complex scanned PDFs producing false confidence.
