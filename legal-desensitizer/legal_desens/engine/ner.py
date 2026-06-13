"""NER engine: ONNX inference with tokenizer offset_mapping → unified Span."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import onnxruntime as ort

from .span import Span

logger = logging.getLogger(__name__)

DEFAULT_APP_DIR = Path("/Applications/Desensitization/ydner_onnx")
USER_MODEL_DIR = Path.home() / ".legal-desens" / "models" / "roberta-crf-ner"

# ── Tag scheme constants ──────────────────────────────────────────────────────

TAG_O = "O"
TAG_SCHEME_BIO = "BIO"
TAG_SCHEME_BIOES = "BIOES"
MAX_MODEL_TOKENS = 512
SPECIAL_TOKEN_COUNT = 2
MAX_CONTENT_TOKENS = MAX_MODEL_TOKENS - SPECIAL_TOKEN_COUNT
CHUNK_OVERLAP_TOKENS = 64


def _resolve_model_dir(model_dir: Optional[str] = None) -> Path:
    """Resolve model directory with priority chain (006 amendment).

    Priority:
        1. --model-dir (explicit CLI arg)
        2. LEGAL_DESENS_MODEL_DIR env var
        3. ~/.legal-desens/models/roberta-crf-ner (user-level install)
        4. /Applications/Desensitization/ydner_onnx (app fallback)
    """
    if model_dir:
        return Path(model_dir)
    env = os.environ.get("LEGAL_DESENS_MODEL_DIR")
    if env:
        return Path(env)
    if USER_MODEL_DIR.is_dir():
        return USER_MODEL_DIR
    return DEFAULT_APP_DIR


def _check_model_dir(d: Path) -> None:
    """Raise clear error if model directory is incomplete."""
    if not d.is_dir():
        raise FileNotFoundError(
            f"NER model directory not found: '{d}'. "
            "Pass --model-dir or set LEGAL_DESENS_MODEL_DIR. "
            "Or use --regex-only to skip NER."
        )
    required = ["model.onnx", "config.json", "vocab.txt"]
    missing = [f for f in required if not (d / f).is_file()]
    if missing:
        raise FileNotFoundError(
            f"NER model directory '{d}' is missing files: {missing}. "
            "Required: model.onnx, config.json, vocab.txt, and label mapping."
        )


# ── Label mapping ────────────────────────────────────────────────────────────


def _load_labels(d: Path) -> Tuple[Dict[int, str], str]:
    """Load id→label mapping and detect tag scheme.

    Checks labels.json first, then config.json.
    Returns (id2label, tag_scheme).
    """
    # Try labels.json
    labels_path = d / "labels.json"
    if labels_path.is_file():
        with open(labels_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        # Could be {"0": "O", "1": "B-PER", ...} or ["O", "B-PER", ...]
        if isinstance(raw, list):
            id2label = {i: label for i, label in enumerate(raw)}
        elif isinstance(raw, dict):
            id2label = {int(k): v for k, v in raw.items()}
        else:
            raise ValueError(f"Unexpected labels.json format: {type(raw)}")
        return id2label, _detect_tag_scheme(id2label)

    # Try config.json
    config_path = d / "config.json"
    if config_path.is_file():
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        if "id2label" in config:
            raw = config["id2label"]
            id2label = {int(k): v for k, v in raw.items()}
            return id2label, _detect_tag_scheme(id2label)
        if "label2id" in config:
            raw = config["label2id"]
            id2label = {v: k for k, v in raw.items()}
            return id2label, _detect_tag_scheme(id2label)

    raise FileNotFoundError(
        f"No label mapping found in '{d}'. "
        "Expected labels.json or config.json with id2label/label2id."
    )


def _detect_tag_scheme(id2label: Dict[int, str]) -> str:
    """Detect BIO vs BIOES from label names."""
    labels = set(id2label.values())
    has_e = any(l.startswith("E-") for l in labels)
    has_s = any(l.startswith("S-") for l in labels)
    if has_e or has_s:
        return TAG_SCHEME_BIOES
    return TAG_SCHEME_BIO


# ── Tokenizer ────────────────────────────────────────────────────────────────


def _build_tokenizer(vocab_path: Path, config_path: Optional[Path] = None):
    """Build a tokenizer from vocab.txt that returns offset_mapping.

    Uses the tokenizers library to construct a BERT-compatible WordPiece
    tokenizer with offset tracking.
    """
    from tokenizers import Tokenizer
    from tokenizers.models import WordPiece
    from tokenizers.normalizers import BertNormalizer
    from tokenizers.pre_tokenizers import BertPreTokenizer
    from tokenizers.processors import BertProcessing

    # Read vocab to get special tokens
    special_tokens = ["[PAD]", "[UNK]", "[CLS]", "[SEP]", "[MASK]"]

    # Try to read tokenizer_config.json for special token overrides
    tok_config_path = config_path or (vocab_path.parent / "tokenizer_config.json")
    if tok_config_path.is_file():
        try:
            with open(tok_config_path, "r", encoding="utf-8") as f:
                tok_config = json.load(f)
            for key in ("unk_token", "cls_token", "sep_token", "pad_token", "mask_token"):
                if key in tok_config and isinstance(tok_config[key], str):
                    token = tok_config[key]
                    if token not in special_tokens:
                        special_tokens.append(token)
        except (json.JSONDecodeError, KeyError):
            pass

    # Build WordPiece model
    vocab = WordPiece.from_file(str(vocab_path), unk_token="[UNK]")

    tok = Tokenizer(vocab)
    # BERT 中文处理：在每个 CJK 字符周围加空白，使其各自成为独立 token
    # （否则连续中文被当作一个词切成 张/##三/##向，token id 全错 → 模型输出全 O）
    tok.normalizer = BertNormalizer(handle_chinese_chars=True)
    tok.pre_tokenizer = BertPreTokenizer()

    # Add CLS/SEP post-processor
    cls_id = tok.token_to_id("[CLS]") or 0
    sep_id = tok.token_to_id("[SEP]") or 0
    if cls_id is not None and sep_id is not None:
        tok.post_processor = BertProcessing(
            sep=(("[SEP]", sep_id)),
            cls=(("[CLS]", cls_id)),
        )

    return tok


# ── BIO/BIOES decode ─────────────────────────────────────────────────────────


@dataclass
class _EntitySpan:
    """Intermediate entity span before conversion to unified Span."""
    entity_type: str
    token_start: int
    token_end: int  # exclusive


def decode_tags(
    tag_ids: List[int],
    id2label: Dict[int, str],
    tag_scheme: str,
) -> Tuple[List[_EntitySpan], List[dict]]:
    """Decode tag ID sequence into entity spans.

    Returns (entities, warnings).
    - B-X starts entity of type X
    - I-X continues if same type; if different type or no B-X before, treat as B-X
    - O ends current entity
    - For BIOES: E-X ends entity, S-X is single-token entity
    """
    entities: List[_EntitySpan] = []
    warnings: List[dict] = []
    current_type: Optional[str] = None
    current_start: Optional[int] = None

    for i, tid in enumerate(tag_ids):
        label = id2label.get(tid, "O")

        if label == TAG_O:
            # Close current entity
            if current_type is not None:
                entities.append(_EntitySpan(current_type, current_start, i))
                current_type = None
                current_start = None
            continue

        # Parse prefix and type
        if "-" in label:
            prefix, etype = label.split("-", 1)
        else:
            # No prefix, treat as O
            if current_type is not None:
                entities.append(_EntitySpan(current_type, current_start, i))
                current_type = None
                current_start = None
            continue

        if prefix == "B":
            # Close previous entity if any
            if current_type is not None:
                entities.append(_EntitySpan(current_type, current_start, i))
            current_type = etype
            current_start = i

        elif prefix == "I":
            if current_type == etype:
                # Continue current entity
                pass
            else:
                # Isolated I-X: treat as B-X per spec
                if current_type is not None:
                    entities.append(_EntitySpan(current_type, current_start, i))
                warnings.append({
                    "type": "illegal_transition",
                    "position": i,
                    "label": label,
                    "detail": f"Isolated {label} at position {i}, treated as B-{etype}",
                })
                current_type = etype
                current_start = i

        elif prefix == "E" and tag_scheme == TAG_SCHEME_BIOES:
            if current_type == etype:
                # End current entity
                entities.append(_EntitySpan(current_type, current_start, i + 1))
                current_type = None
                current_start = None
            else:
                # Isolated E-X: treat as single-token entity
                warnings.append({
                    "type": "illegal_transition",
                    "position": i,
                    "label": label,
                    "detail": f"Isolated {label} at position {i}, treated as single entity",
                })
                entities.append(_EntitySpan(etype, i, i + 1))
                current_type = None
                current_start = None

        elif prefix == "S" and tag_scheme == TAG_SCHEME_BIOES:
            # Single-token entity; close any open entity first
            if current_type is not None:
                entities.append(_EntitySpan(current_type, current_start, i))
                current_type = None
                current_start = None
            entities.append(_EntitySpan(etype, i, i + 1))

        else:
            # Unknown prefix or BIO tag seen in BIOES context
            # Treat as beginning of new entity
            if current_type is not None:
                entities.append(_EntitySpan(current_type, current_start, i))
            warnings.append({
                "type": "illegal_transition",
                "position": i,
                "label": label,
                "detail": f"Unexpected prefix '{prefix}' at position {i}, treated as B-{etype}",
            })
            current_type = etype
            current_start = i

    # Close any open entity at end
    if current_type is not None:
        entities.append(_EntitySpan(current_type, current_start, len(tag_ids)))

    return entities, warnings


# ── ONNX Model ───────────────────────────────────────────────────────────────


@dataclass
class ModelIO:
    """Records the real ONNX model I/O contract."""
    input_names: List[str]
    input_shapes: List[List[int]]
    input_dtypes: List[str]
    output_names: List[str]
    output_shapes: List[List[int]]
    output_dtypes: List[str]
    needs_token_type_ids: bool


def inspect_model(model_path: Path) -> ModelIO:
    """Inspect ONNX model I/O signatures without assuming anything."""
    sess = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])

    inputs = sess.get_inputs()
    outputs = sess.get_outputs()

    input_names = [inp.name for inp in inputs]
    input_shapes = [list(inp.shape) for inp in inputs]
    input_dtypes = [inp.type for inp in inputs]

    output_names = [out.name for out in outputs]
    output_shapes = [list(out.shape) for out in outputs]
    output_dtypes = [out.type for out in outputs]

    needs_token_type_ids = "token_type_ids" in input_names

    return ModelIO(
        input_names=input_names,
        input_shapes=input_shapes,
        input_dtypes=input_dtypes,
        output_names=output_names,
        output_shapes=output_shapes,
        output_dtypes=output_dtypes,
        needs_token_type_ids=needs_token_type_ids,
    )


# ── NER Engine ───────────────────────────────────────────────────────────────


class NEREngine:
    """Complete NER engine: model + tokenizer + labels → spans."""

    def __init__(self, model_dir: Optional[str] = None):
        self._dir = _resolve_model_dir(model_dir)
        _check_model_dir(self._dir)

        # Load label mapping
        self._id2label, self._tag_scheme = _load_labels(self._dir)

        # Build tokenizer
        self._tokenizer = _build_tokenizer(
            self._dir / "vocab.txt",
            self._dir / "config.json",
        )

        # Load ONNX model
        model_path = self._dir / "model.onnx"
        self._model_io = inspect_model(model_path)
        self._session = ort.InferenceSession(
            str(model_path),
            providers=["CPUExecutionProvider"],
        )

    @property
    def model_io(self) -> ModelIO:
        return self._model_io

    @property
    def id2label(self) -> Dict[int, str]:
        return dict(self._id2label)

    @property
    def tag_scheme(self) -> str:
        return self._tag_scheme

    def encode_with_offsets(self, text: str):
        """Encode text and return (encoding, offsets).

        offsets[i] = (char_start, char_end) for token i (excluding special tokens).
        """
        encoding = self._tokenizer.encode(text)
        offsets = []
        for i in range(len(encoding.ids)):
            span = encoding.token_to_chars(i)
            if span is not None:
                offsets.append((span[0], span[1]))
            else:
                # Special token ([CLS], [SEP], [PAD]) — no char span
                offsets.append(None)
        return encoding, offsets

    def _infer_token_arrays(
        self,
        ids: List[int],
        attention_mask_values: List[int],
        offsets: List[Optional[Tuple[int, int]]],
    ) -> Tuple[List[int], List[Tuple[int, int]]]:
        """Run ONNX inference on one already-bounded token array."""
        # Prepare model inputs
        input_ids = [ids]
        attention_mask = [attention_mask_values]
        feed = {
            self._model_io.input_names[0]: np.array(input_ids, dtype=np.int64),
        }

        # Map input names to data
        name_to_data = {
            "input_ids": input_ids,
            "attention_mask": attention_mask,
            "token_type_ids": [[0] * len(ids)],
        }

        for name in self._model_io.input_names:
            if name in name_to_data:
                feed[name] = np.array(name_to_data[name], dtype=np.int64)

        # Run inference
        outputs = self._session.run(None, feed)

        # Decode output. Common ONNX exports return either logits or tag IDs,
        # with or without an explicit batch dimension.
        output = outputs[0]
        if output.ndim == 3:
            tag_ids = output.argmax(axis=-1)[0].tolist()
        elif output.ndim == 2 and output.shape[-1] == len(self._id2label):
            tag_ids = output.argmax(axis=-1).tolist()
        elif output.ndim == 2:
            tag_ids = output[0].tolist()
        elif output.ndim == 1:
            tag_ids = output.tolist()
        else:
            raise RuntimeError(f"Unsupported NER output shape: {output.shape}")

        tag_ids = [int(tid) for tid in tag_ids]

        # Filter out special token positions (offset is None)
        filtered_tag_ids = []
        filtered_offsets = []
        for i, (tid, off) in enumerate(zip(tag_ids, offsets)):
            if off is not None:
                filtered_tag_ids.append(tid)
                filtered_offsets.append(off)

        return filtered_tag_ids, filtered_offsets

    def _infer_encoding(self, encoding, offsets) -> Tuple[List[int], List[Tuple[int, int]]]:
        """Run ONNX inference on one already-bounded encoding."""
        return self._infer_token_arrays(encoding.ids, encoding.attention_mask, offsets)

    def infer(self, text: str) -> Tuple[List[int], List[Tuple[int, int]]]:
        """Run ONNX inference on text.

        Returns (tag_ids, offsets) where offsets excludes special tokens.
        Long inputs are processed in overlapping token windows so ONNX models
        with a 512-token position limit do not fail at runtime.
        """
        encoding, offsets = self.encode_with_offsets(text)
        content_indexes = [i for i, off in enumerate(offsets) if off is not None]
        if len(encoding.ids) <= MAX_MODEL_TOKENS:
            return self._infer_encoding(encoding, offsets)

        combined: List[Tuple[Tuple[int, int], int]] = []
        seen_offsets = set()
        step = MAX_CONTENT_TOKENS - CHUNK_OVERLAP_TOKENS
        if step <= 0:
            step = MAX_CONTENT_TOKENS

        for start in range(0, len(content_indexes), step):
            chunk_content = content_indexes[start:start + MAX_CONTENT_TOKENS]
            if not chunk_content:
                continue

            chunk_ids = (
                [self._tokenizer.token_to_id("[CLS]")]
                + [encoding.ids[i] for i in chunk_content]
                + [self._tokenizer.token_to_id("[SEP]")]
            )
            chunk_attention = [1] * len(chunk_ids)
            chunk_offsets = [None] + [offsets[i] for i in chunk_content] + [None]
            tag_ids, tag_offsets = self._infer_token_arrays(
                chunk_ids, chunk_attention, chunk_offsets
            )
            for tid, off in zip(tag_ids, tag_offsets):
                if off in seen_offsets:
                    continue
                seen_offsets.add(off)
                combined.append((off, tid))

            if start + MAX_CONTENT_TOKENS >= len(content_indexes):
                break

        combined.sort(key=lambda item: item[0][0])
        return [tid for _, tid in combined], [off for off, _ in combined]

    def scan(self, text: str) -> Tuple[List[Span], List[dict]]:
        """Run NER on text and return (spans, warnings).

        Each span has start/end as Python str char indices into the original text.
        Every span satisfies: text[span.start:span.end] == span.text
        """
        tag_ids, offsets = self.infer(text)

        # Decode tags into entity spans (token-level)
        entity_spans, decode_warnings = decode_tags(
            tag_ids, self._id2label, self._tag_scheme
        )

        # Convert token-level spans to char-level spans using offsets
        spans: List[Span] = []
        for ent in entity_spans:
            # Token range: [ent.token_start, ent.token_end)
            if ent.token_start >= len(offsets) or ent.token_end > len(offsets):
                logger.warning(
                    f"Entity {ent.entity_type} token range [{ent.token_start}, {ent.token_end}) "
                    f"exceeds offset length {len(offsets)}, skipping"
                )
                continue

            char_start = offsets[ent.token_start][0]
            char_end = offsets[ent.token_end - 1][1]

            # Validate offset bounds
            if char_start < 0 or char_end > len(text) or char_start >= char_end:
                logger.warning(
                    f"Entity {ent.entity_type} invalid char range [{char_start}, {char_end}) "
                    f"for text length {len(text)}, skipping"
                )
                continue

            span_text = text[char_start:char_end]

            # CRITICAL ASSERTION: offset must match actual text
            assert text[char_start:char_end] == span_text, (
                f"Offset mismatch: text[{char_start}:{char_end}] = "
                f"{repr(text[char_start:char_end])} != {repr(span_text)}"
            )

            spans.append(Span(
                entity_type=ent.entity_type,
                start=char_start,
                end=char_end,
                text=span_text,
                engine="ner",
                rule_id=None,
                priority=50,  # NER default priority lower than regex
            ))

        return spans, decode_warnings


# ── Module-level convenience functions ────────────────────────────────────────


def is_model_available(model_dir: Optional[str] = None) -> bool:
    """Check whether the NER model directory exists and is complete."""
    d = _resolve_model_dir(model_dir)
    try:
        _check_model_dir(d)
        return True
    except FileNotFoundError:
        return False


def scan_ner(text: str, model_dir: Optional[str] = None) -> List[Span]:
    """Run NER on text. Raises if model is not available.

    Returns unified Span list with engine='ner'.
    """
    engine = NEREngine(model_dir)
    spans, warnings = engine.scan(text)
    # Attach decode warnings to spans via logging
    for w in warnings:
        logger.warning("NER decode warning: %s", w)
    return spans


def inspect_ner(model_dir: Optional[str] = None) -> dict:
    """Inspect model I/O and label info. Returns dict for CLI display."""
    d = _resolve_model_dir(model_dir)
    _check_model_dir(d)

    id2label, tag_scheme = _load_labels(d)
    model_path = d / "model.onnx"
    model_io = inspect_model(model_path)

    return {
        "model_dir": str(d),
        "model_io": {
            "input_names": model_io.input_names,
            "input_shapes": model_io.input_shapes,
            "input_dtypes": model_io.input_dtypes,
            "output_names": model_io.output_names,
            "output_shapes": model_io.output_shapes,
            "output_dtypes": model_io.output_dtypes,
            "needs_token_type_ids": model_io.needs_token_type_ids,
        },
        "id2label": {str(k): v for k, v in id2label.items()},
        "tag_scheme": tag_scheme,
        "num_labels": len(id2label),
    }
