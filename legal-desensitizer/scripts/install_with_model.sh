#!/usr/bin/env bash
# Install legal-desens and prepare the local NER model in one operator command.
#
# Default behavior:
#   1. pip install the project
#   2. install a NER model from LEGAL_DESENS_MODEL_URL, or legacy-import from
#      LEGAL_DESENS_MODEL_SRC when no URL is set
#   3. run ner-inspect so the operator sees whether NER is ready
#
# Environment overrides:
#   LEGAL_DESENS_INSTALL_TARGET  Project path or wheel path. Defaults to repo root.
#   LEGAL_DESENS_MODEL_URL       Model archive URL, e.g. GitHub Release Asset.
#   LEGAL_DESENS_MODEL_SHA256    Required when LEGAL_DESENS_MODEL_URL is set.
#   LEGAL_DESENS_MODEL_SRC       Source ydner_onnx directory. Defaults to app path.
#   LEGAL_DESENS_MODEL_TARGET    Target model directory.
#   LEGAL_DESENS_WHEELHOUSE      Optional offline wheelhouse directory.
#   LEGAL_DESENS_PIP_EXTRA_ARGS  Extra pip args, e.g. "-i https://pypi.tuna.tsinghua.edu.cn/simple".
#   LEGAL_DESENS_SKIP_MODEL=1    Install CLI only, skip model install.
#   LEGAL_DESENS_FORCE_MODEL=1   Reinstall model even if manifest matches.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

INSTALL_TARGET="${LEGAL_DESENS_INSTALL_TARGET:-$PROJECT_DIR}"
DEFAULT_MODEL_URL="https://github.com/Clukay-Fun/lawchers-skills/releases/download/legal-desens-ner-v0.1/bert4ner-base-chinese-onnx.zip"
DEFAULT_MODEL_SHA256="d572400b7b46c104bb41f95f6c665ded5274aecf14cd49fd9c3d7bf2b6d55703"
MODEL_URL="${LEGAL_DESENS_MODEL_URL:-$DEFAULT_MODEL_URL}"
MODEL_SHA256="${LEGAL_DESENS_MODEL_SHA256:-$DEFAULT_MODEL_SHA256}"
MODEL_SRC="${LEGAL_DESENS_MODEL_SRC:-/Applications/Desensitization/ydner_onnx}"
MODEL_TARGET="${LEGAL_DESENS_MODEL_TARGET:-}"
WHEELHOUSE="${LEGAL_DESENS_WHEELHOUSE:-}"
PIP_EXTRA_ARGS="${LEGAL_DESENS_PIP_EXTRA_ARGS:-}"
SKIP_MODEL="${LEGAL_DESENS_SKIP_MODEL:-0}"
FORCE_MODEL="${LEGAL_DESENS_FORCE_MODEL:-0}"

if [ "$SKIP_MODEL" != "1" ] && [ -n "$MODEL_URL" ] && [ -z "$MODEL_SHA256" ]; then
    echo "ERROR: LEGAL_DESENS_MODEL_SHA256 is required when LEGAL_DESENS_MODEL_URL is set." >&2
    exit 1
fi

PYTHON="${LEGAL_DESENS_PYTHON:-python3}"
if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "ERROR: python3 not found. Set LEGAL_DESENS_PYTHON=/path/to/python." >&2
    exit 1
fi

PIP=("$PYTHON" -m pip)

echo "==> Installing legal-desens"
if [ -n "$WHEELHOUSE" ] && [ -d "$WHEELHOUSE" ]; then
    echo "    Using local wheelhouse: $WHEELHOUSE"
    "${PIP[@]}" install --no-index --find-links "$WHEELHOUSE" legal-desens
else
    # shellcheck disable=SC2086
    "${PIP[@]}" install --prefer-binary $PIP_EXTRA_ARGS "$INSTALL_TARGET"
fi

echo ""
echo "==> Verifying CLI"
"$PYTHON" -m legal_desens.cli --help >/dev/null
echo "    legal-desens: OK"

if [ "$SKIP_MODEL" = "1" ]; then
    echo ""
    echo "==> Skipping NER model install because LEGAL_DESENS_SKIP_MODEL=1"
    exit 0
fi

echo ""
echo "==> Installing NER model"
if [ -n "$MODEL_URL" ]; then
    INSTALL_ARGS=(install-model --url "$MODEL_URL" --sha256 "$MODEL_SHA256")
else
    INSTALL_ARGS=(install-model --from-app --src "$MODEL_SRC")
fi
if [ -n "$MODEL_TARGET" ]; then
    INSTALL_ARGS+=(--target "$MODEL_TARGET")
fi
if [ "$FORCE_MODEL" = "1" ]; then
    INSTALL_ARGS+=(--force)
fi

"$PYTHON" -m legal_desens.cli "${INSTALL_ARGS[@]}"

echo ""
echo "==> Inspecting NER model"
if [ -n "$MODEL_TARGET" ]; then
    "$PYTHON" -m legal_desens.cli ner-inspect --model-dir "$MODEL_TARGET" >/dev/null
else
    "$PYTHON" -m legal_desens.cli ner-inspect >/dev/null
fi
echo "    NER model: OK"

echo ""
echo "==> Install complete"
