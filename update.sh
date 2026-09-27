#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "============================================="
echo "   Updating CineTag"
echo "============================================="

# 1. Check Git
if ! command -v git &>/dev/null; then
    echo "❌ Error: git is not installed or not in PATH."
    exit 1
fi

# 2. Pull latest release from repository
echo "📥 Pulling latest updates from GitHub..."
git pull --ff-only || {
    echo "⚠️ Fast-forward pull failed. Attempting git pull..."
    git pull
}

# 3. Update virtual environment dependencies
if [ -d ".venv" ]; then
    echo "📦 Updating Python dependencies in .venv..."
    source .venv/bin/activate
    pip install --upgrade pip --quiet
    pip install -r requirements.txt --quiet
else
    echo "ℹ️ No .venv found; will be created on first ./run.sh launch."
fi

# 4. Ensure permissions
chmod +x run.sh update.sh 2>/dev/null || true

echo "============================================="
echo "✅ Update successful! Run ./run.sh to start."
echo "============================================="
