#!/bin/bash
# Oracle Cloud Ubuntu setup script for Job Application Agent
set -e

echo "=== Installing system dependencies ==="
sudo apt-get update -qq
sudo apt-get install -y python3-pip python3-venv git \
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libxcomposite1 \
    libxdamage1 libxfixes3 libxrandr2 libgbm1 libxkbcommon0 \
    libpango-1.0-0 libcairo2 libasound2 libatspi2.0-0

echo "=== Creating virtual environment ==="
python3 -m venv venv
source venv/bin/activate

echo "=== Installing Python dependencies ==="
pip install --upgrade pip -q
pip install -r requirements.txt -q

echo "=== Installing Playwright Chromium ==="
playwright install chromium
playwright install-deps chromium

echo "=== Creating required directories ==="
mkdir -p logs

echo "=== Setting up .env ==="
if [ ! -f .env ]; then
    cp .env.example .env
    echo ""
    echo ">>> .env created from .env.example — fill in your credentials:"
    echo "    nano .env"
else
    echo ">>> .env already exists — skipping"
fi

echo ""
echo "=== Setup complete ==="
echo ""
echo "Next steps:"
echo "  1. Edit credentials:  nano .env"
echo "  2. Test one run:       source venv/bin/activate && python main.py --once"
echo "  3. Install service:    sudo bash install_service.sh"
