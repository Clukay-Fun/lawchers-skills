#!/usr/bin/env bash
# build_wheelhouse.sh — Build an offline wheelhouse for legal-desens.
#
# Produces dist/wheelhouse-<platform>/ containing all dependency wheels
# (precompiled only) plus the project wheel itself.  The resulting directory
# can be used with:
#   pip install --no-index --find-links=dist/wheelhouse-<platform> legal-desens
#
# Requirements:
#   - Python 3.9+
#   - pip
#
# The script will FAIL (not silently degrade) if any dependency has no
# precompiled wheel for the current platform.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Detect platform tag
OS="$(uname -s)"
ARCH="$(uname -m)"

case "$OS" in
    Darwin) PLATFORM="macos-${ARCH}" ;;
    Linux)  PLATFORM="linux-${ARCH}" ;;
    *)      echo "ERROR: unsupported OS $OS" >&2; exit 1 ;;
esac

OUT_DIR="$PROJECT_DIR/dist/wheelhouse-${PLATFORM}"

echo "==> Building wheelhouse for ${PLATFORM}"
echo "    Output: ${OUT_DIR}"

# Clean previous output
rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR"

# Resolve pip command (prefer pip3 on macOS)
PIP="pip3"
if ! command -v pip3 &>/dev/null && command -v pip &>/dev/null; then
    PIP="pip"
fi

# Step 1: Download all dependency wheels (precompiled only)
echo ""
echo "==> Downloading dependency wheels (binary only)..."

# Parse dependencies from pyproject.toml
DEPS=$(python3 -c "
import re, pathlib
toml = pathlib.Path('$PROJECT_DIR/pyproject.toml').read_text()
m = re.search(r'dependencies\s*=\s*\[(.*?)\]', toml, re.DOTALL)
if m:
    for item in re.findall(r'\"([^\"]+)\"', m.group(1)):
        # Strip version constraints: 'onnxruntime>=1.14' -> 'onnxruntime'
        name = re.split(r'[><=!~]', item)[0].strip()
        print(name)
")

# Optional: use a PyPI mirror via PIP_INDEX_URL env var
EXTRA_PIP_ARGS=""
if [ -n "${PIP_INDEX_URL:-}" ]; then
    EXTRA_PIP_ARGS="-i $PIP_INDEX_URL"
fi

# shellcheck disable=SC2086
"$PIP" download \
    --dest "$OUT_DIR" \
    --only-binary=:all: \
    $EXTRA_PIP_ARGS \
    $DEPS

# Verify every downloaded file is a .whl (no .tar.gz / source)
for f in "$OUT_DIR"/*; do
    case "$f" in
        *.whl) ;;
        *)
            echo "ERROR: non-wheel file found: $f" >&2
            echo "       This means a dependency has no precompiled wheel for ${PLATFORM}." >&2
            echo "       Aborting — the wheelhouse must be fully precompiled." >&2
            exit 1
            ;;
    esac
done

# Step 2: Build the project wheel
echo ""
echo "==> Building project wheel..."
"$PIP" wheel "$PROJECT_DIR" --wheel-dir "$OUT_DIR" --no-deps

# Step 3: Verify project wheel is present
PROJECT_WHEEL=$(ls "$OUT_DIR"/legal_desens-*.whl 2>/dev/null | head -1)
if [ -z "$PROJECT_WHEEL" ]; then
    echo "ERROR: project wheel not found in ${OUT_DIR}" >&2
    exit 1
fi

# Step 4: Generate SHA-256 manifest
echo ""
echo "==> Generating SHA-256 manifest..."
(cd "$OUT_DIR" && shasum -a256 *.whl > SHA256SUMS.txt)

WHEEL_COUNT=$(ls "$OUT_DIR"/*.whl | wc -l | tr -d ' ')

echo ""
echo "==> Wheelhouse built successfully!"
echo "    Location : ${OUT_DIR}"
echo "    Wheels   : ${WHEEL_COUNT}"
echo "    Manifest : ${OUT_DIR}/SHA256SUMS.txt"
echo ""
echo "Install command (offline):"
echo "    pip install --no-index --find-links=${OUT_DIR} legal-desens"
