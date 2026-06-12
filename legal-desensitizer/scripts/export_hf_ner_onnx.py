#!/usr/bin/env python3
"""Export a HuggingFace token-classification NER model to ONNX.

Produces a directory compatible with `legal-desens --model-dir`:
    <output-dir>/
    ├── model.onnx
    ├── config.json      (contains id2label mapping)
    ├── vocab.txt
    └── tokenizer_config.json (optional, for special token overrides)

Usage:
    python scripts/export_hf_ner_onnx.py \
        --hf-model shibing624/bert4ner-base-chinese \
        --output-dir ~/.legal-desens/models/bert4ner-base-chinese

    # Or from a local directory:
    python scripts/export_hf_ner_onnx.py \
        --hf-model /path/to/local/hf-model \
        --output-dir /path/to/output

After export, verify with:
    legal-desens ner-inspect --model-dir /path/to/output
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export HF token-classification NER model to ONNX for --model-dir"
    )
    parser.add_argument(
        "--hf-model",
        required=True,
        help="HuggingFace model name or local path (e.g. shibing624/bert4ner-base-chinese)",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Output directory for ONNX model + config + vocab",
    )
    parser.add_argument(
        "--opset",
        type=int,
        default=14,
        help="ONNX opset version (default: 14)",
    )
    args = parser.parse_args(argv)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── 1. Load HF model and tokenizer ────────────────────────────────────────

    try:
        from transformers import AutoModelForTokenClassification, AutoTokenizer
    except ImportError:
        print(
            "ERROR: transformers is required for export. Install with:\n"
            "  pip install transformers torch onnx",
            file=sys.stderr,
        )
        return 1

    print(f"Loading model: {args.hf_model}")
    model = AutoModelForTokenClassification.from_pretrained(args.hf_model)
    tokenizer = AutoTokenizer.from_pretrained(args.hf_model)

    # ── 2. Export to ONNX ─────────────────────────────────────────────────────

    try:
        import torch
        from transformers.onnx import export
    except ImportError:
        print(
            "ERROR: torch and onnx are required. Install with:\n"
            "  pip install torch onnx",
            file=sys.stderr,
        )
        return 1

    onnx_path = output_dir / "model.onnx"

    # Build dummy input for tracing
    dummy_text = "测试文本"
    inputs = tokenizer(dummy_text, return_tensors="pt")

    print(f"Exporting to ONNX (opset {args.opset})...")

    # Manual ONNX export via torch
    input_names = list(inputs.keys())
    output_names = ["logits"]

    dynamic_axes = {
        name: {0: "batch", 1: "sequence"} for name in input_names
    }
    dynamic_axes["logits"] = {0: "batch", 1: "sequence"}

    torch.onnx.export(
        model,
        tuple(inputs[k] for k in input_names),
        str(onnx_path),
        input_names=input_names,
        output_names=output_names,
        dynamic_axes=dynamic_axes,
        opset_version=args.opset,
    )
    print(f"  -> {onnx_path}")

    # ── 3. Save config.json with id2label ─────────────────────────────────────

    config_src = Path(args.hf_model) / "config.json"
    if config_src.is_file():
        shutil.copy2(config_src, output_dir / "config.json")
    else:
        # Build config from model
        config = {
            "id2label": {
                str(i): label
                for i, label in model.config.id2label.items()
            },
            "label2id": {
                label: i
                for i, label in model.config.id2label.items()
            },
        }
        with open(output_dir / "config.json", "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
    print(f"  -> {output_dir / 'config.json'}")

    # ── 4. Save vocab.txt ─────────────────────────────────────────────────────

    vocab_src = Path(args.hf_model) / "vocab.txt"
    if vocab_src.is_file():
        shutil.copy2(vocab_src, output_dir / "vocab.txt")
    else:
        # Extract from tokenizer
        vocab = tokenizer.get_vocab()
        # Sort by id for deterministic output
        sorted_vocab = sorted(vocab.items(), key=lambda x: x[1])
        with open(output_dir / "vocab.txt", "w", encoding="utf-8") as f:
            for token, _ in sorted_vocab:
                f.write(token + "\n")
    print(f"  -> {output_dir / 'vocab.txt'}")

    # ── 5. Save tokenizer_config.json (special tokens) ────────────────────────

    tok_config_src = Path(args.hf_model) / "tokenizer_config.json"
    if tok_config_src.is_file():
        shutil.copy2(tok_config_src, output_dir / "tokenizer_config.json")
        print(f"  -> {output_dir / 'tokenizer_config.json'}")

    # ── 6. Verify ─────────────────────────────────────────────────────────────

    print("\nVerifying export...")
    required = ["model.onnx", "config.json", "vocab.txt"]
    missing = [f for f in required if not (output_dir / f).is_file()]
    if missing:
        print(f"ERROR: Missing files after export: {missing}", file=sys.stderr)
        return 1

    # Quick ONNX load check
    try:
        import onnxruntime as ort

        sess = ort.InferenceSession(
            str(onnx_path), providers=["CPUExecutionProvider"]
        )
        inp_names = [i.name for i in sess.get_inputs()]
        out_names = [o.name for o in sess.get_outputs()]
        print(f"  ONNX inputs:  {inp_names}")
        print(f"  ONNX outputs: {out_names}")
    except Exception as e:
        print(f"WARNING: ONNX load check failed: {e}", file=sys.stderr)

    print(f"\nExport complete: {output_dir}")
    print(f"Verify with: legal-desens ner-inspect --model-dir {output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
