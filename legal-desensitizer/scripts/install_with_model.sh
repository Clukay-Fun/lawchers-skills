#!/usr/bin/env bash
# Install legal-desens and prepare the local NER model in one operator command.
#
# Default behavior:
#   1. pip install the project
#   2. import RobertaCrfNerModel from the local desktop app
#   3. run ner-inspect so the operator sees whether NER is ready
#
# Environment overrides:
#   LEGAL_DESENS_INSTALL_TARGET  Project path or wheel path. Defaults to repo root.
#   LEGAL_DESENS_MODEL_SRC       Source ydner_onnx directory. Defaults to app path.
#   LEGAL_DESENS_MODEL_TARGET    Target model directory.
#   LEGAL_DESENS_SKIP_MODEL=1    Install CLI only, skip model install.
#   LEGAL_DESENS_FORCE_MODEL=1   Reinstall model even if manifest matches.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

INSTALL_TARGET="${LEGAL_DESENS_INSTALL_TARGET:-$PROJECT_DIR}"
MODEL_SRC="${LEGAL_DESENS_MODEL_SRC:-/Applications/Desensitization/ydner_onnx}"
MODEL_TARGET="${LEGAL_DESENS_MODEL_TARGET:-}"
SKIP_MODEL="${LEGAL_DESENS_SKIP_MODEL:-0}"
FORCE_MODEL="${LEGAL_DESENS_FORCE_MODEL:-0}"

PIP="pip3"
if ! command -v pip3 >/dev/null 2>&1 && command -v pip >/dev/null 2>&1; then
    PIP="pip"
fi

echo "==> Installing legal-desens"
"$PIP" install "$INSTALL_TARGET"

echo ""
echo "==> Verifying CLI"
legal-desens --help >/dev/null
echo "    legal-desens: OK"

if [ "$SKIP_MODEL" = "1" ]; then
    echo ""
    echo "==> Skipping NER model install because LEGAL_DESENS_SKIP_MODEL=1"
    exit 0
fi

echo ""
echo "==> Installing NER model"
INSTALL_ARGS=(install-model --from-app --src "$MODEL_SRC")
if [ -n "$MODEL_TARGET" ]; then
    INSTALL_ARGS+=(--target "$MODEL_TARGET")
fi
if [ "$FORCE_MODEL" = "1" ]; then
    INSTALL_ARGS+=(--force)
fi

legal-desens "${INSTALL_ARGS[@]}"

echo ""
echo "==> Inspecting NER model"
if [ -n "$MODEL_TARGET" ]; then
    legal-desens ner-inspect --model-dir "$MODEL_TARGET" >/dev/null
else
    legal-desens ner-inspect >/dev/null
fi
echo "    NER model: OK"

echo ""
echo "==> Install complete"
