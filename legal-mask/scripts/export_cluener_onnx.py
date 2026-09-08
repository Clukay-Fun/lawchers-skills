"""Export CLUENER model to ONNX and compare with PyTorch."""
import json
import sys
import numpy as np
from pathlib import Path


def export_onnx(model_name, output_dir):
    """Export CLUENER to ONNX."""
    import torch
    from transformers import AutoTokenizer, AutoModelForTokenClassification

    print(f"Loading model: {model_name}")
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForTokenClassification.from_pretrained(model_name)
    model.eval()

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Save tokenizer files
    tokenizer.save_pretrained(str(output_dir))
    print(f"Saved tokenizer to: {output_dir}")

    # Export ONNX
    dummy_text = "测试文本"
    inputs = tokenizer(dummy_text, return_tensors="pt")
    input_names = ["input_ids", "attention_mask"]
    if "token_type_ids" in inputs:
        input_names.append("token_type_ids")

    output_path = output_dir / "model.onnx"
    print(f"Exporting ONNX to: {output_path}")

    torch.onnx.export(
        model,
        tuple(inputs[k] for k in input_names if k in inputs),
        str(output_path),
        input_names=input_names,
        output_names=["logits"],
        dynamic_axes={
            "input_ids": {0: "batch", 1: "seq"},
            "attention_mask": {0: "batch", 1: "seq"},
            "token_type_ids": {0: "batch", 1: "seq"},
            "logits": {0: "batch", 1: "seq"},
        },
        opset_version=14,
    )
    print(f"ONNX exported: {output_path}")

    # Save config with id2label
    config_path = output_dir / "config.json"
    model.config.save_pretrained(str(output_dir))
    print(f"Saved config to: {config_path}")

    return output_path


def compare_outputs(model_name, onnx_dir, text_file):
    """Compare PyTorch vs ONNX outputs."""
    import torch
    from transformers import AutoTokenizer, AutoModelForTokenClassification
    import onnxruntime as ort

    text = Path(text_file).read_text(encoding="utf-8")

    # Load PyTorch
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForTokenClassification.from_pretrained(model_name)
    model.eval()

    # Load ONNX
    onnx_path = Path(onnx_dir) / "model.onnx"
    sess = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])

    # Tokenize
    inputs = tokenizer(text, return_tensors="pt", return_offsets_mapping=True)
    offsets = inputs.pop("offset_mapping")[0].tolist()

    # PyTorch inference
    with torch.no_grad():
        pt_outputs = model(**{k: v for k, v in inputs.items() if k != "offset_mapping"})
        pt_logits = pt_outputs.logits.numpy()
        pt_preds = pt_logits.argmax(axis=-1)[0]

    # ONNX inference - check which inputs the model expects
    onnx_input_names = [inp.name for inp in sess.get_inputs()]
    feed = {}
    for k in ["input_ids", "attention_mask", "token_type_ids"]:
        if k in inputs and k in onnx_input_names:
            feed[k] = inputs[k].numpy()
    onnx_outputs = sess.run(None, feed)
    onnx_logits = onnx_outputs[0]
    onnx_preds = onnx_logits.argmax(axis=-1)[0]

    # Compare
    print(f"\n=== Comparison ===")
    print(f"PyTorch logits shape: {pt_logits.shape}")
    print(f"ONNX logits shape: {onnx_logits.shape}")

    # Logits difference
    max_diff = np.abs(pt_logits - onnx_logits).max()
    print(f"Max logits difference: {max_diff:.6f}")

    # Predictions match
    pred_match = (pt_preds == onnx_preds).all()
    print(f"Predictions identical: {pred_match}")

    if not pred_match:
        diff_positions = np.where(pt_preds != onnx_preds)[0]
        print(f"Different positions: {len(diff_positions)}")
        for pos in diff_positions[:5]:
            print(f"  Token {pos}: PT={pt_preds[pos]}, ONNX={onnx_preds[pos]}")

    return pred_match, max_diff


def main():
    model_name = sys.argv[1] if len(sys.argv) > 1 else "uer/roberta-base-finetuned-cluener2020-chinese"
    onnx_dir = "/tmp/cluener_onnx"
    text_file = "tests/fixtures/legal_smoke_suite.txt"

    # Export
    export_onnx(model_name, onnx_dir)

    # Compare
    match, diff = compare_outputs(model_name, onnx_dir, text_file)

    print(f"\n=== Summary ===")
    print(f"PyTorch-ONNX match: {match}")
    print(f"Max logits diff: {diff:.6f}")

    if match:
        print("PASS: PyTorch and ONNX outputs are identical")
    else:
        print("FAIL: PyTorch and ONNX outputs differ")
        sys.exit(1)


if __name__ == "__main__":
    main()
