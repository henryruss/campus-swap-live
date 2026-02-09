# Testing Guide for Campus Swap

## Quick Start

```bash
# 1. Install dependencies
pip install pytest pytest-cov pytest-flask

# 2. Run all tests
pytest -v

# 3. Run with coverage
pytest --cov=app --cov-report=html
```

## What Gets Tested?

### ✅ Currently Tested
- Basic page loading (homepage, inventory, about)
- Health check endpoint
- User registration and login
- Inventory browsing and search
- Product detail pages
- Admin access control
- Admin item/category management
- Input validation (email, price, quality, files)
- Database models

### 🔄 Can Be Added Later
- Stripe webhook handling (requires mock Stripe)
- Email sending (requires mock Resend)
- File upload processing
- Complex admin workflows
- Edge cases and error scenarios

## Running Tests

### Basic Commands

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run specific test file
pytest tests/test_auth.py

# Run specific test
pytest tests/test_auth.py::TestLogin::test_login_success

# Run with coverage
pytest --cov=app --cov-report=html
```

### Useful Options

- `-v` or `-vv` - Verbose output (shows test names)
- `-s` - Show print statements
- `-x` - Stop at first failure
- `-k "keyword"` - Run tests matching keyword
- `--cov=app` - Show code coverage
- `--cov-report=html` - Generate HTML coverage report

## Understanding Test Results

### Passing Test
```
tests/test_basic.py::test_index_page_loads PASSED
```
✅ Everything worked!

### Failing Test
```
tests/test_auth.py::TestLogin::test_login_success FAILED
...
AssertionError: assert b'dashboard' in response.data
```
❌ Test found a problem - check the error message

### Error
```
tests/test_auth.py::TestLogin::test_login_success ERROR
...
AttributeError: 'NoneType' object has no attribute 'data'
```
⚠️ Test couldn't run - usually a setup issue

## Coverage Report

After running `pytest --cov=app --cov-report=html`:

1. Open `htmlcov/index.html` in your browser
2. See which lines of code are tested (green) vs untested (red)
3. Aim for 70%+ coverage

## Adding New Tests

When you add a new feature:

1. **Write a test first** (or right after)
2. **Test the happy path** (normal usage)
3. **Test error cases** (invalid input, missing data)
4. **Test edge cases** (boundary conditions)

### Example: Testing a New Route

```python
def test_my_new_feature(client):
    """Test my new feature works"""
    response = client.get('/my_new_route')
    assert response.status_code == 200
    assert b'expected content' in response.data
```

## Continuous Testing

Run tests:
- ✅ Before committing code
- ✅ Before deploying
- ✅ When fixing bugs (write a test for the bug!)
- ✅ When adding features

## Common Issues

### Tests fail locally but work in production
- Check environment variables
- Verify test database is separate from production
- Check that test fixtures match production data

### "No tests found"
- Make sure test files are in `tests/` directory
- Make sure test files start with `test_`
- Make sure test functions start with `test_`

### Import errors
- Make sure you're in the project root directory
- Make sure virtual environment is activated
- Run `pip install -r requirements.txt`

## Test Organization

```
tests/
├── __init__.py          # Makes tests a package
├── conftest.py          # Shared fixtures (test data)
├── test_basic.py        # Basic page tests
├── test_auth.py         # Authentication tests
├── test_inventory.py    # Marketplace tests
├── test_admin.py        # Admin panel tests
├── test_models.py       # Database model tests
└── test_validation.py   # Input validation tests
```

## Best Practices

1. **One assertion per test** (when possible)
2. **Descriptive test names** - `test_login_with_wrong_password` not `test_login2`
3. **Test behavior, not implementation** - Test what users see, not internal details
4. **Keep tests fast** - Unit tests should be instant
5. **Keep tests independent** - Each test should work alone
6. **Use fixtures** - Reuse common test data

## Next Steps

1. ✅ Run `pytest tests/test_basic.py -v` to see tests work
2. ✅ Read through test files to understand them
3. ✅ Run full test suite: `pytest -v`
4. ✅ Check coverage: `pytest --cov=app --cov-report=html`
5. ✅ Write tests for any bugs you fix
6. ✅ Add tests when adding new features
