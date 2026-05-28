#!/usr/bin/env bash
set -euo pipefail

GCA_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$GCA_ROOT/.env"

echo "================================================"
echo "  GCAgents - itch.io Setup Helper"
echo "================================================"
echo ""

if [ -f "$ENV_FILE" ]; then
    echo "Found existing .env file"
else
    echo "No .env file found, creating from template..."
    cp "$GCA_ROOT/.env.example" "$ENV_FILE"
    echo "Created .env from template"
fi
echo ""

echo "Step 1: Register itch.io account"
echo "  → Open https://itch.io/register"
echo "  → Complete registration"
echo "  → Verify your email"
echo ""

echo "Step 2: Create a game page"
echo "  → Go to https://itch.io/game/new"
echo "  → Set title: 'gcagents-test' (or any name)"
echo "  → Check 'This file will be played in the browser'"
echo "  → Don't upload files yet (agent will do this)"
echo ""

echo "Step 3: Get API key"
echo "  → Go to https://itch.io/user/settings/api-keys"
echo "  → Generate a new API key"
echo "  → Copy the key"
echo ""

echo "Step 4: Install butler CLI"
if command -v butler &> /dev/null; then
    echo "  ✓ butler already installed: $(butler --version 2>/dev/null || echo 'version unknown')"
else
    echo "  → Download from https://itchio.itch.io/butler"
    echo "  → Or: scoop install butler (Windows)"
    echo "  → Or: brew install butler (macOS)"
    echo "  → Or: unzip to /usr/local/bin (Linux)"
fi
echo ""

echo "Step 5: Enter your credentials"
read -p "  itch.io username: " USERNAME
read -p "  Butler API key: " API_KEY

if [ -n "$USERNAME" ] && [ -n "$API_KEY" ]; then
    if grep -q "BUTLER_USERNAME=" "$ENV_FILE"; then
        sed -i "s/^BUTLER_USERNAME=.*/BUTLER_USERNAME=$USERNAME/" "$ENV_FILE"
        sed -i "s/^BUTLER_API_KEY=.*/BUTLER_API_KEY=$API_KEY/" "$ENV_FILE"
    else
        echo "BUTLER_USERNAME=$USERNAME" >> "$ENV_FILE"
        echo "BUTLER_API_KEY=$API_KEY" >> "$ENV_FILE"
    fi
    echo ""
    echo "✓ Credentials saved to .env"
else
    echo ""
    echo "⚠ No credentials entered. Edit .env manually later."
fi

echo ""
echo "Step 6: Verify butler login"
if command -v butler &> /dev/null; then
    echo "  Run: butler login"
    echo "  Enter the API key when prompted"
    echo ""
    echo "  Test with: butler ping"
else
    echo "  Install butler first, then run: butler login"
fi

echo ""
echo "================================================"
echo "  Setup complete! Next steps:"
echo "  1. Fill remaining API keys in .env (DEEPSEEK_API_KEY etc.)"
echo "  2. docker compose up -d postgres redis"
echo "  3. pip install -e ."
echo "  4. python scripts/e2e_test.py --mock"
echo "================================================"
