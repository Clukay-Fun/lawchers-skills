"""Evaluate CLUENER candidate model on legal smoke suite."""
import json
import sys
from pathlib import Path


def eval_cluener_pytorch(model_name, text_file):
    """Run CLUENER PyTorch model and return spans."""
    import torch
    from transformers import AutoTokenizer, AutoModelForTokenClassification

    print(f"Loading model: {model_name}")
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForTokenClassification.from_pretrained(model_name)
    model.eval()

    text = Path(text_file).read_text(encoding="utf-8")
    print(f"Input text length: {len(text)} chars")

    # Tokenize with offset_mapping
    inputs = tokenizer(text, return_tensors="pt", return_offsets_mapping=True)
    offsets = inputs.pop("offset_mapping")[0].tolist()

    with torch.no_grad():
        outputs = model(**inputs)
        logits = outputs.logits
        pred_ids = logits.argmax(dim=-1)[0].tolist()

    # Get label mapping
    id2label = model.config.id2label
    print(f"Labels: {list(id2label.values())[:10]}...")

    # Decode spans
    spans = []
    current_type = None
    current_start = None
    prev_end = 0

    for i, (pred_id, offset) in enumerate(zip(pred_ids, offsets)):
        if offset[0] == 0 and offset[1] == 0:
            # Special token
            if current_type:
                spans.append({"entity_type": current_type, "start": current_start, "end": prev_end})
                current_type = None
            continue

        label = id2label.get(pred_id, "O")
        prev_end = offset[1]

        if label == "O":
            if current_type:
                spans.append({"entity_type": current_type, "start": current_start, "end": offset[0]})
                current_type = None
            continue

        if "-" in label:
            prefix, etype = label.split("-", 1)
        else:
            prefix, etype = "O", label

        if prefix == "B":
            if current_type:
                spans.append({"entity_type": current_type, "start": current_start, "end": offset[0]})
            current_type = etype
            current_start = offset[0]
        elif prefix == "I" and current_type == etype:
            continue
        else:
            if current_type:
                spans.append({"entity_type": current_type, "start": current_start, "end": offset[0]})
            current_type = etype
            current_start = offset[0]

    if current_type:
        spans.append({"entity_type": current_type, "start": current_start, "end": len(text)})

    # Validate spans
    validated = []
    for s in spans:
        span_text = text[s["start"]:s["end"]]
        if span_text:
            validated.append({**s, "text": span_text})

    return validated, text


def main():
    model_name = sys.argv[1] if len(sys.argv) > 1 else "uer/roberta-base-finetuned-cluener2020-chinese"
    text_file = sys.argv[2] if len(sys.argv) > 2 else "tests/fixtures/legal_smoke_suite.txt"

    spans, text = eval_cluener_pytorch(model_name, text_file)

    print(f"\n=== Results ===")
    print(f"Total spans: {len(spans)}")

    by_type = {}
    for s in spans:
        t = s["entity_type"]
        by_type[t] = by_type.get(t, 0) + 1
    print(f"By type: {json.dumps(by_type, ensure_ascii=False)}")

    if len(spans) == 0:
        print("WARNING: All O - no entities detected!")
        sys.exit(1)

    print(f"\nSample spans:")
    for s in spans[:10]:
        print(f"  {s['entity_type']}: '{s['text']}' [{s['start']}:{s['end']}]")

    # Save for comparison
    output = {
        "model": model_name,
        "text_file": text_file,
        "text_length": len(text),
        "spans": spans,
        "by_type": by_type
    }
    out_path = "/tmp/cluener_pytorch_spans.json"
    with open(out_path, "w") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\nSaved to: {out_path}")


if __name__ == "__main__":
    main()
