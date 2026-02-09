# Campus Swap Test Suite

Welcome to automated testing! This guide will help you understand and run the tests.

## What Are Tests?

Tests are automated checks that verify your code works correctly. Instead of manually clicking through your website every time you make a change, tests do it automatically.

**Benefits:**
- ✅ Catch bugs before users do
- ✅ Make changes with confidence
- ✅ Document how your code should work
- ✅ Save time (run 50 tests in seconds vs. manual testing)

## Test Types

### Unit Tests (`@pytest.mark.unit`)
- Test individual functions in isolation
- Fast and focused
- Example: Testing that `validate_email()` correctly rejects invalid emails

### Integration Tests (`@pytest.mark.integration`)
- Test full request/response cycles
- Simulate real user interactions
- Example: Testing that login form actually logs a user in

## Getting Started

### Step 1: Install Dependencies

```bash
# Make sure you're in your project directory
cd "/Users/henryrussell/Documents/Documents - Henry's MacBook Air/campusSwap/realWebsite"

# Activate your virtual environment
source venv/bin/activate  # or: venv\Scripts\activate on Windows

# Install testing libraries
pip install pytest pytest-cov pytest-flask
```

### Step 2: Run Your First Test

```bash
# Run all tests
pytest

# Run with verbose output (shows each test name)
pytest -v

# Run a specific test file
pytest tests/test_basic.py -v

# Run a specific test
pytest tests/test_basic.py::test_index_page_loads -v
```

### Step 3: View Coverage Report

```bash
# Run tests with coverage
pytest --cov=app --cov-report=html

# Open the coverage report
open htmlcov/index.html  # Mac
# or just navigate to htmlcov/index.html in your browser
```

## Understanding Test Output

When you run `pytest -v`, you'll see:

```
tests/test_basic.py::test_index_page_loads PASSED    [ 10%]
tests/test_basic.py::test_inventory_page_loads PASSED [ 20%]
tests/test_auth.py::TestLogin::test_login_success PASSED [ 30%]
...
```

- ✅ **PASSED** = Test worked correctly
- ❌ **FAILED** = Something broke (test will show what went wrong)
- ⚠️ **ERROR** = Test couldn't run (usually a setup issue)

## Test Files Explained

### `tests/test_basic.py`
**Start here!** Simple tests that verify pages load.
- Tests homepage, inventory page, health check
- Good for understanding how tests work

### `tests/test_validation.py`
Tests input validation functions.
- Email validation
- Price validation
- File upload validation
- Quality rating validation

### `tests/test_auth.py`
Tests user authentication.
- Registration flow
- Login/logout
- Protected routes

### `tests/test_inventory.py`
Tests marketplace functionality.
- Browsing inventory
- Search functionality
- Product detail pages
- Purchase flow

### `tests/test_admin.py`
Tests admin panel.
- Admin access control
- Category management
- Item management
- Data export

### `tests/test_models.py`
Tests database models.
- User model
- Category model
- Item model
- AppSetting model

## Common Commands

```bash
# Run all tests
pytest

# Run with detailed output
pytest -v

# Run only unit tests
pytest -m unit

# Run only integration tests
pytest -m integration

# Run tests and show print statements
pytest -s

# Run tests and stop at first failure
pytest -x

# Run tests and show local variables on failure
pytest -l

# Run with coverage report
pytest --cov=app --cov-report=term-missing
```

## Writing Your Own Tests

### Example: Test a New Route

```python
def test_my_new_route(client):
    """Test that my new route works"""
    response = client.get('/my_new_route')
    assert response.status_code == 200
    assert b'expected content' in response.data
```

### Example: Test with Authentication

```python
def test_protected_route(authenticated_client):
    """Test a route that requires login"""
    response = authenticated_client.get('/dashboard')
    assert response.status_code == 200
```

### Example: Test Form Submission

```python
def test_form_submission(client):
    """Test submitting a form"""
    response = client.post('/some_route', data={
        'field1': 'value1',
        'field2': 'value2'
    }, follow_redirects=True)
    
    assert response.status_code == 200
    assert b'success' in response.data.lower()
```

## Troubleshooting

### "Module not found" errors
- Make sure you're in the project directory
- Make sure your virtual environment is activated
- Run `pip install -r requirements.txt`

### Database errors
- Tests use a temporary database, so this shouldn't happen
- If it does, check that `conftest.py` is set up correctly

### Tests fail but code works
- Check that test data matches your actual data
- Verify test expectations are correct
- Some tests might need Stripe/Resend keys (they'll skip gracefully)

### "No tests found"
- Make sure test files start with `test_`
- Make sure you're in the right directory
- Try: `pytest tests/ -v`

## Next Steps

1. **Run the basic tests first**: `pytest tests/test_basic.py -v`
2. **Read through test files** to understand what they're testing
3. **Run all tests**: `pytest -v`
4. **Check coverage**: `pytest --cov=app --cov-report=html`
5. **Write tests for new features** as you add them

## Tips

- Run tests frequently (before committing code)
- Write tests for bugs you fix (prevents regressions)
- Aim for 70%+ code coverage
- Don't worry if some tests fail initially - that's normal!

Happy testing! 🎉
