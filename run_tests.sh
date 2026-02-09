#!/bin/bash
# Simple script to run tests with helpful output

echo "🧪 Campus Swap Test Runner"
echo "=========================="
echo ""

# Check if virtual environment is activated
if [[ "$VIRTUAL_ENV" == "" ]]; then
    echo "⚠️  Warning: Virtual environment not activated"
    echo "   Run: source venv/bin/activate"
    echo ""
fi

# Check if pytest is installed
if ! command -v pytest &> /dev/null; then
    echo "❌ pytest not found. Installing..."
    pip install pytest pytest-cov pytest-flask
    echo ""
fi

echo "Running tests..."
echo ""

# Run tests with options
pytest "$@" -v --tb=short

echo ""
echo "✅ Tests complete!"
echo ""
echo "💡 Tips:"
echo "   - Run 'pytest --cov=app --cov-report=html' for coverage report"
echo "   - Run 'pytest tests/test_basic.py' to run just basic tests"
echo "   - Run 'pytest -k login' to run tests matching 'login'"
