#!/bin/bash

# Simple startup script for the ERP Model Flask server

set -e  # Exit on error

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║           ERP Model Flask Server                 ║"
echo "║         Starting on localhost:5001               ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is not installed"
    exit 1
fi

# Check if required modules are installed
python3 -c "import flask, flask_cors" 2>/dev/null || {
    echo "Error: Required Python packages not installed"
    echo "Install with: pip install flask flask-cors yfinance scipy pandas"
    exit 1
}

# Check if database exists
if [ ! -f "$HOME/erp_model.db" ]; then
    echo "Warning: Database not found at $HOME/erp_model.db"
    echo "Run 'python seed_historical.py' first to initialize the database"
    echo ""
fi

# Start the server
echo "Server starting... Open erp_dashboard.html in your browser"
echo "Press Ctrl+C to stop"
echo ""

python3 server.py

