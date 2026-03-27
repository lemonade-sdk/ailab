#!/bin/bash
# Quick installer for ailab
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "Installing ailab..."

COMPLETIONS="$HOME/.local/share/bash-completion/completions"
mkdir -p "$COMPLETIONS"

# pipx is the cleanest option - isolated venv, adds to PATH automatically
if command -v pipx &>/dev/null; then
    pipx install --editable "$SCRIPT_DIR"
    install -m 644 "$SCRIPT_DIR/ailab/scripts/ailab-completion.bash" "$COMPLETIONS/ailab"
    echo ""
    echo "Installation complete! Try:"
    echo "  ailab --help"
    echo "  ailab new mybox"
    exit 0
fi

# Fall back to a local venv with a wrapper script in ~/.local/bin
VENV="$HOME/.local/share/ailab/venv"
BIN="$HOME/.local/bin"

mkdir -p "$VENV" "$BIN" "$COMPLETIONS"
python3 -m venv "$VENV"
"$VENV/bin/pip" install --quiet --editable "$SCRIPT_DIR"

# Write a thin wrapper so the tool is on PATH
cat > "$BIN/ailab" <<EOF
#!/bin/bash
exec "$VENV/bin/ailab" "\$@"
EOF
chmod +x "$BIN/ailab"
install -m 644 "$SCRIPT_DIR/ailab/scripts/ailab-completion.bash" "$COMPLETIONS/ailab"

echo ""
echo "Installation complete!"
echo "Make sure $BIN is on your PATH, then try:"
echo "  ailab --help"
echo "  ailab new mybox"
