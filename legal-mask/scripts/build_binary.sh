#!/usr/bin/env bash
# build_binary.sh — Build a single-file PyInstaller executable for legal-desens.
#
# Produces dist/legal-desens (single binary, no Python required at runtime).
# NER model is NOT bundled; install-model works at runtime.
#
# Requirements:
#   - Python 3.9+
#   - pip
#   - All project dependencies installed (pip install .)
#   - PyInstaller (pip install pyinstaller)
#
# The script will FAIL if PyInstaller is not installed or the build produces
# a binary that cannot pass basic smoke tests (--help, default rules loading).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Detect platform
OS="$(uname -s)"
ARCH="$(uname -m)"
case "$OS" in
    Darwin) PLATFORM="macos-${ARCH}" ;;
    Linux)  PLATFORM="linux-${ARCH}" ;;
    *)      echo "ERROR: unsupported OS $OS" >&2; exit 1 ;;
esac

DIST_DIR="$PROJECT_DIR/dist"
BINARY="$DIST_DIR/legal-desens"

echo "==> Building single executable for ${PLATFORM}"

# Resolve pip command (prefer pip3 on macOS)
PIP="pip3"
if ! command -v pip3 &>/dev/null && command -v pip &>/dev/null; then
    PIP="pip"
fi

# Ensure PyInstaller is on PATH (common on macOS with user installs)
for p in "$HOME/Library/Python/3.9/bin" "$HOME/.local/bin"; do
    case ":$PATH:" in *":$p:"*) ;; *) export PATH="$p:$PATH" ;; esac
done

# Step 0: Ensure PyInstaller is available
if ! python3 -c "import PyInstaller" 2>/dev/null; then
    echo "ERROR: PyInstaller not installed.  Run: pip install pyinstaller" >&2
    exit 1
fi

# Step 1: Ensure project is installed (so imports resolve)
echo ""
echo "==> Ensuring project is installed..."
if ! python3 -c "import legal_desens" 2>/dev/null; then
    "$PIP" install -q "$PROJECT_DIR"
fi

# Step 2: Clean previous binary build artifacts
echo ""
echo "==> Cleaning previous build..."
rm -rf "$PROJECT_DIR/build" "$PROJECT_DIR/__pycache__" "$BINARY" "$DIST_DIR/legal-desens-SHA256.txt"
mkdir -p "$DIST_DIR"

# Step 3: Run PyInstaller
echo ""
echo "==> Running PyInstaller..."
pyinstaller "$PROJECT_DIR/legal-desens.spec" \
    --distpath "$DIST_DIR" \
    --workpath "$PROJECT_DIR/build" \
    --noconfirm \
    --clean

# Step 4: Verify the binary exists
if [ ! -f "$BINARY" ]; then
    echo "ERROR: Binary not found at ${BINARY}" >&2
    exit 1
fi
chmod +x "$BINARY"

# Step 5: Smoke test — --help must succeed
echo ""
echo "==> Smoke testing binary..."
if ! "$BINARY" --help >/dev/null 2>&1; then
    echo "ERROR: Binary failed --help smoke test" >&2
    exit 1
fi
echo "    --help: OK"

# Step 6: Smoke test — default rules must load (no --rules flag)
# Create a temp sample with sensitive data
TMPDIR_SMOKE=$(mktemp -d)
trap 'rm -rf "$TMPDIR_SMOKE"' EXIT
cat > "$TMPDIR_SMOKE/sample.txt" <<'EOF'
Contact: 13812345678, email: test@example.com
ID: 110101199003076519
EOF

"$BINARY" redact "$TMPDIR_SMOKE/sample.txt" \
    --regex-only \
    --out "$TMPDIR_SMOKE/r.txt" \
    --map "$TMPDIR_SMOKE/m.json" \
    --audit "$TMPDIR_SMOKE/a.json" 2>/dev/null
echo "    redact (no --rules): OK"

"$BINARY" restore "$TMPDIR_SMOKE/r.txt" \
    --map "$TMPDIR_SMOKE/m.json" \
    --out "$TMPDIR_SMOKE/rs.txt" 2>/dev/null
echo "    restore: OK"

# Verify byte-level round trip
SRC_HASH=$(shasum -a256 "$TMPDIR_SMOKE/sample.txt" | cut -d' ' -f1)
RST_HASH=$(shasum -a256 "$TMPDIR_SMOKE/rs.txt" | cut -d' ' -f1)
if [ "$SRC_HASH" != "$RST_HASH" ]; then
    echo "ERROR: redact→restore SHA-256 mismatch!" >&2
    echo "    source : $SRC_HASH" >&2
    echo "    restored: $RST_HASH" >&2
    exit 1
fi
echo "    redact→restore byte-verified: OK"

# Step 7: Generate SHA-256 manifest
echo ""
echo "==> Generating SHA-256 manifest..."
(cd "$DIST_DIR" && shasum -a256 legal-desens > legal-desens-SHA256.txt)

BINARY_SIZE=$(wc -c < "$BINARY" | tr -d ' ')

echo ""
echo "==> Binary built successfully!"
echo "    Location : ${BINARY}"
echo "    Size     : ${BINARY_SIZE} bytes"
echo "    Platform : ${PLATFORM}"
echo "    Manifest : ${DIST_DIR}/legal-desens-SHA256.txt"
