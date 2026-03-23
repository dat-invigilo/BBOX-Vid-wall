#!/bin/bash
# Development Setup Script

set -e

echo "======================================"
echo "Video Wall Development Setup"
echo "======================================"

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 not found"
    exit 1
fi

echo "✓ Python $(python3 --version) found"

# Create virtual environment
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate 2>/dev/null || . venv/Scripts/activate

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip

# Install requirements
echo "Installing dependencies..."
pip install -r requirements.txt

# Install development dependencies
echo "Installing development dependencies..."
pip install pytest pylint black

echo ""
echo "======================================"
echo "✓ Setup complete!"
echo "======================================"
echo ""
echo "To activate the environment:"
echo "  source venv/bin/activate"
echo ""
echo "To run the application:"
echo "  python app.py"
echo ""
echo "To run tests:"
echo "  python -m pytest test_app.py"
echo ""
echo "To lint code:"
echo "  pylint *.py"
echo ""
