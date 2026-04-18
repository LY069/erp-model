#!/bin/bash
# Double-click this file in Finder to start the ERP server.
# It will open a Terminal window, start the server, and open the dashboard in your browser.

# Go to the folder this script lives in
cd "$(dirname "$0")"

echo "============================================"
echo "  ERP Model Server"
echo "  Dashboard: http://localhost:5001"
echo "  Keep this window open."
echo "============================================"
echo ""

# Install dependencies if missing
python3 -c "import flask" 2>/dev/null || {
    echo "Installing Flask..."
    pip3 install flask flask-cors --quiet
}
python3 -c "import yfinance" 2>/dev/null || {
    echo "Installing data libraries..."
    pip3 install yfinance fredapi scipy pandas --quiet
}

# Seed DB if empty (first run only)
if [ ! -f ~/erp_model.db ]; then
    echo "First run — seeding 65 years of historical data..."
    python3 seed_historical.py --quiet
fi

# Start server (auto-opens browser)
python3 server.py
