# How to Run Tests Locally

This guide will help you run the test suite for Campus Swap on your local machine.

## Prerequisites

1. **Python 3.8+** installed
2. **Virtual environment** (recommended)
3. **Project dependencies** installed

## Quick Start

### Step 1: Navigate to Project Directory

```bash
cd "/Users/henryrussell/Documents/Documents - Henry's MacBook Air/campusSwap/realWebsite"
```

### Step 2: Activate Virtual Environment

```bash
# Mac/Linux
source venv/bin/activate

# Windows
venv\Scripts\activate
```

If you don't have a virtual environment yet:
```bash
python3 -m venv venv
source venv/bin/activate  # Mac/Linux
# or: venv\Scripts\activate  # Windows
```

### Step 3: Install Dependencies

```bash
pip install -r requirements.txt
```

This will install:
- pytest (testing framework)
- pytest-cov (coverage reporting)
- pytest-flask (Flask testing utilities)
- All other project dependencies

### Step 4: Run Tests

```bash
# Run all tests
pytest

# Run with verbose output (recommended)
pytest -v

# Run specific test file
pytest tests/test_email_sending.py -v

# Run specific test
pytest tests/test_email_sending.py::TestSendEmailFunction::test_send_email_basic -v
```

## Using the Test Script

You can also use the provided test runner script:

```bash
# Make script executable (first time only)
chmod +x run_tests.sh

# Run tests
./run_tests.sh

# Run specific test file
./run_tests.sh tests/test_email_sending.py
```

## Common Test Commands

### Run All Tests
```bash
pytest -v
```

### Run Specific Test Categories
```bash
# Only unit tests
pytest -m unit -v

# Only integration tests
pytest -m integration -v
```

### Run Tests with Coverage
```bash
# Terminal coverage report
pytest --cov=app --cov-report=term-missing -v

# HTML coverage report (opens in browser)
pytest --cov=app --cov-report=html
open htmlcov/index.html  # Mac
# or navigate to htmlcov/index.html in your browser
```

### Run Tests Matching a Pattern
```bash
# Run all email-related tests
pytest -k email -v

# Run all unsubscribe tests
pytest -k unsubscribe -v
```

### Debug Tests
```bash
# Show print statements
pytest -s -v

# Stop at first failure
pytest -x -v

# Show local variables on failure
pytest -l -v
```

## Test Files Overview

- **`tests/test_basic.py`** - Basic page loading tests
- **`tests/test_auth.py`** - Authentication tests (login, register, logout)
- **`tests/test_validation.py`** - Input validation tests
- **`tests/test_inventory.py`** - Marketplace functionality tests
- **`tests/test_admin.py`** - Admin panel tests
- **`tests/test_models.py`** - Database model tests
- **`tests/test_unsubscribe.py`** - Email unsubscribe flow tests
- **`tests/test_email_sending.py`** - Email sending functionality tests

## Understanding Test Output

When you run `pytest -v`, you'll see output like:

```
tests/test_email_sending.py::TestSendEmailFunction::test_send_email_basic PASSED    [ 10%]
tests/test_email_sending.py::TestSendEmailFunction::test_send_email_no_api_key PASSED [ 20%]
...
```

- ✅ **PASSED** = Test succeeded
- ❌ **FAILED** = Test failed (check error message)
- ⚠️ **ERROR** = Test couldn't run (usually setup issue)
- ⏭️ **SKIPPED** = Test was skipped (usually due to missing dependencies)

## Troubleshooting

### "Module not found" errors
```bash
# Make sure virtual environment is activated
source venv/bin/activate

# Reinstall dependencies
pip install -r requirements.txt
```

### "No tests found"
```bash
# Make sure you're in the project directory
pwd

# Run from project root
pytest tests/ -v
```

### Database errors
Tests use a temporary in-memory database, so this shouldn't happen. If it does:
- Check that `conftest.py` exists in `tests/` directory
- Make sure Flask-SQLAlchemy is installed

### Import errors
```bash
# Make sure you're running from project root
cd "/Users/henryrussell/Documents/Documents - Henry's MacBook Air/campusSwap/realWebsite"

# Check Python path
python -c "import sys; print(sys.path)"
```

## Email Tests Note

The email sending tests use **mocking** to avoid actually sending emails. This means:
- ✅ Tests run without needing a real Resend API key
- ✅ Tests run fast (no network calls)
- ✅ Tests don't send real emails
- ✅ Tests verify the email logic works correctly

The tests mock the `resend.Emails.send` function, so you can run them safely without any API keys configured.

## Running Tests Before Committing

It's a good practice to run tests before committing code:

```bash
# Quick test run
pytest -v

# Full test run with coverage
pytest --cov=app --cov-report=term-missing -v
```

## Next Steps

1. Run `pytest -v` to see all tests pass
2. Check coverage: `pytest --cov=app --cov-report=html`
3. Read test files to understand what's being tested
4. Write new tests for new features!

## Need Help?

- Check `tests/README.md` for more detailed testing documentation
- Look at existing test files for examples
- Check pytest documentation: https://docs.pytest.org/

Happy testing! 🎉
