# Quick Start: Running Tests

## Step 1: Install Testing Tools

Open your terminal and run:

```bash
# Navigate to your project
cd "/Users/henryrussell/Documents/Documents - Henry's MacBook Air/campusSwap/realWebsite"

# Activate your virtual environment
source venv/bin/activate

# Install testing libraries
pip install pytest pytest-cov pytest-flask
```

## Step 2: Run Your First Test

```bash
# Run the simplest tests first
pytest tests/test_basic.py -v
```

**Expected output:**
```
tests/test_basic.py::test_index_page_loads PASSED
tests/test_basic.py::test_inventory_page_loads PASSED
tests/test_basic.py::test_health_check_endpoint PASSED
...
```

✅ If you see "PASSED" - congratulations! Your tests are working!

## Step 3: Run All Tests

```bash
# Run everything
pytest -v
```

This will run all test files:
- `test_basic.py` - Basic page loading
- `test_validation.py` - Input validation
- `test_auth.py` - Login/registration
- `test_inventory.py` - Marketplace
- `test_admin.py` - Admin panel
- `test_models.py` - Database models

## Step 4: See What's Tested (Coverage)

```bash
# Generate coverage report
pytest --cov=app --cov-report=html

# Open the report
open htmlcov/index.html
```

This shows you:
- 🟢 Green = Code that's tested
- 🔴 Red = Code that's not tested yet
- Percentage = How much of your code is covered

## Understanding Test Output

### ✅ Passing Test
```
tests/test_basic.py::test_index_page_loads PASSED
```
Everything worked!

### ❌ Failing Test
```
tests/test_auth.py::TestLogin::test_login_success FAILED
AssertionError: assert b'dashboard' in response.data
```
Something broke - the test tells you what went wrong.

### ⚠️ Error
```
tests/test_auth.py::TestLogin::test_login_success ERROR
AttributeError: ...
```
Test couldn't run - usually a setup issue.

## Common Commands

```bash
# Run all tests
pytest

# Run with details
pytest -v

# Run specific file
pytest tests/test_auth.py

# Run specific test
pytest tests/test_auth.py::test_login_success

# Run only unit tests
pytest -m unit

# Run only integration tests  
pytest -m integration

# Run with coverage
pytest --cov=app --cov-report=html

# Stop at first failure
pytest -x

# Show print statements
pytest -s
```

## What Each Test File Does

### `test_basic.py` ⭐ START HERE
Tests that pages load correctly.
- Homepage loads
- Inventory page loads
- Health check works

**Run:** `pytest tests/test_basic.py -v`

### `test_validation.py`
Tests input validation functions.
- Email validation
- Price validation
- File upload validation

**Run:** `pytest tests/test_validation.py -v`

### `test_auth.py`
Tests user authentication.
- User registration
- Login/logout
- Protected routes

**Run:** `pytest tests/test_auth.py -v`

### `test_inventory.py`
Tests marketplace features.
- Browsing items
- Search functionality
- Product pages

**Run:** `pytest tests/test_inventory.py -v`

### `test_admin.py`
Tests admin panel.
- Admin access control
- Managing items/categories

**Run:** `pytest tests/test_admin.py -v`

### `test_models.py`
Tests database models.
- User model
- Item model
- Category model

**Run:** `pytest tests/test_models.py -v`

## Troubleshooting

### "pytest: command not found"
```bash
pip install pytest pytest-cov pytest-flask
```

### "Module not found"
Make sure you're in the project directory and venv is activated:
```bash
source venv/bin/activate
cd "/Users/henryrussell/Documents/Documents - Henry's MacBook Air/campusSwap/realWebsite"
```

### Tests fail but website works
- Some tests might need Stripe/Resend keys (they'll skip gracefully)
- Check that test data matches your actual setup
- Read the error message - it tells you what went wrong

### "No tests found"
- Make sure test files are in `tests/` directory
- Make sure files start with `test_`
- Try: `pytest tests/ -v`

## Next Steps

1. ✅ Run `pytest tests/test_basic.py -v` - See tests work!
2. ✅ Run `pytest -v` - Run all tests
3. ✅ Run `pytest --cov=app --cov-report=html` - See coverage
4. ✅ Read test files to understand what they test
5. ✅ Write tests when you add new features

## Pro Tips

- **Run tests before committing code** - Catch bugs early!
- **Write tests for bugs you fix** - Prevents them coming back
- **Start with simple tests** - Test that pages load
- **Don't worry about 100% coverage** - 70% is great!

## Need Help?

- Read `tests/README.md` for detailed explanations
- Read `TESTING_GUIDE.md` for advanced usage
- Check test file comments - they explain what each test does

Happy testing! 🎉
