"""
Tests for the reservation system.
Run with: python3 test_reservations.py
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta

os.environ['WTF_CSRF_ENABLED'] = '0'

# Use the app's default SQLite DB (local dev) — tests run against it
# Clear DATABASE_URL to ensure SQLite fallback
if 'DATABASE_URL' in os.environ:
    del os.environ['DATABASE_URL']

from app import app, db, store_is_open, store_open_date, compute_expiry, get_active_reservation
from models import User, InventoryItem, InventoryCategory, ItemReservation, AppSetting

app.config['TESTING'] = True
app.config['WTF_CSRF_ENABLED'] = False

# Test-only login route (bypasses normal auth flow)
from flask_login import login_user as _login_user

@app.route('/_test_login/<int:user_id>')
def _test_login(user_id):
    user = User.query.get(user_id)
    if user:
        _login_user(user)
        return 'ok', 200
    return 'not found', 404

PASSED = 0
FAILED = 0


def status(name, ok, detail=""):
    global PASSED, FAILED
    if ok:
        PASSED += 1
        print(f"  PASS  {name}")
    else:
        FAILED += 1
        print(f"  FAIL  {name}  -- {detail}")


def fresh_data():
    """Clear all rows and insert fresh test data. Faster than recreating tables."""
    # Delete in dependency order
    ItemReservation.query.delete()
    InventoryItem.query.delete()
    InventoryCategory.query.delete()
    AppSetting.query.delete()
    User.query.delete()
    db.session.commit()

    cat = InventoryCategory(name='Furniture', icon='fa-couch')
    db.session.add(cat)
    db.session.flush()

    items = []
    for i in range(6):
        item = InventoryItem(
            description=f'Test Item {i+1}',
            price=25.0 + i * 10,
            quality=3,
            status='available',
            category_id=cat.id,
            photo_url='test_placeholder.jpg',
        )
        db.session.add(item)
        items.append(item)
    db.session.flush()

    user1 = User(email='buyer@test.com', full_name='Test Buyer')
    user2 = User(email='buyer2@test.com', full_name='Other Buyer')
    admin = User(email='admin@test.com', full_name='Admin User', is_admin=True, is_super_admin=True)
    db.session.add_all([user1, user2, admin])
    db.session.commit()

    AppSetting.set('store_open_date', '2025-01-01')

    return items, user1, user2, admin


def login(client, user):
    resp = client.get(f'/_test_login/{user.id}')
    assert resp.status_code == 200, f"Test login failed for user {user.id}"


# ── Helper function tests ──

def test_helpers():
    print("\n--- Helper functions ---")
    items, user1, user2, admin = fresh_data()

    AppSetting.set('store_open_date', '2025-01-01')
    status("store_is_open() True for past date", store_is_open())

    AppSetting.set('store_open_date', '2099-01-01')
    status("store_is_open() False for future date", not store_is_open())

    AppSetting.set('store_open_date', '2025-01-01')
    exp = compute_expiry()
    now = datetime.utcnow()
    diff_days = (exp - now).total_seconds() / 86400
    status("compute_expiry() ~3 days from now after open", 2.99 < diff_days < 3.01, f"{diff_days:.3f} days")

    AppSetting.set('store_open_date', '2099-06-01')
    exp = compute_expiry()
    expected = datetime.fromisoformat('2099-06-01') + timedelta(days=3)
    diff = abs((exp - expected).total_seconds())
    status("compute_expiry() anchors to future store_open_date", diff < 60, f"diff={diff}s")

    AppSetting.set('store_open_date', '2025-01-01')
    status("get_active_reservation() None when empty", get_active_reservation(items[0].id) is None)


# ── Reserve item route tests ──

def test_reserve_requires_login():
    print("\n--- Auth ---")
    items, user1, user2, admin = fresh_data()
    client = app.test_client()

    resp = client.post(f'/reserve_item/{items[0].id}', follow_redirects=False)
    loc = resp.headers.get('Location', '')
    status("POST /reserve_item redirects to login when not authenticated",
           resp.status_code == 302 and '/login' in loc, f"status={resp.status_code} loc={loc}")


def test_reserve_get_redirect():
    print("\n--- GET redirect ---")
    items, user1, user2, admin = fresh_data()
    client = app.test_client()
    login(client, user1)

    resp = client.get(f'/reserve_item/{items[0].id}', follow_redirects=False)
    loc = resp.headers.get('Location', '')
    status("GET /reserve_item redirects to product page",
           resp.status_code == 302 and f'/item/{items[0].id}' in loc)


def test_reserve_happy_path():
    print("\n--- Reserve happy path ---")
    items, user1, user2, admin = fresh_data()
    client = app.test_client()
    login(client, user1)

    item = items[0]
    resp = client.post(f'/reserve_item/{item.id}', follow_redirects=True)
    res = get_active_reservation(item.id)
    status("Reserve creates active reservation",
           resp.status_code == 200 and res is not None and res.user_id == user1.id)

    # Product page should show "Reserved by you"
    resp = client.get(f'/item/{item.id}')
    html = resp.data.decode()
    status("Product page shows 'Reserved by you'", 'Reserved by you until' in html)


def test_reserve_blocked_before_store_open():
    print("\n--- Pre-open blocking ---")
    items, user1, user2, admin = fresh_data()
    client = app.test_client()
    login(client, user1)

    AppSetting.set('store_open_date', '2099-01-01')
    resp = client.post(f'/reserve_item/{items[0].id}', follow_redirects=True)
    html = resp.data.decode()
    status("Reservation blocked before store opens", "open yet" in html.lower())
    AppSetting.set('store_open_date', '2025-01-01')


def test_reserve_duplicate_same_user():
    print("\n--- Duplicate same user ---")
    items, user1, user2, admin = fresh_data()
    client = app.test_client()
    login(client, user1)

    item = items[0]
    client.post(f'/reserve_item/{item.id}')
    resp = client.post(f'/reserve_item/{item.id}', follow_redirects=True)
    html = resp.data.decode()
    status("Same user can't reserve same item twice", "already reserved this item" in html)


def test_reserve_blocked_by_other_user():
    print("\n--- Blocked by other user ---")
    items, user1, user2, admin = fresh_data()

    # user1 reserves item using their own client
    c1 = app.test_client()
    login(c1, user1)
    c1.post(f'/reserve_item/{items[0].id}')

    # user2 tries same item using a different client
    c2 = app.test_client()
    login(c2, user2)
    resp = c2.post(f'/reserve_item/{items[0].id}', follow_redirects=True)
    html = resp.data.decode()
    status("Other user blocked from reserved item", "already reserved" in html)


def test_reserve_max_3():
    print("\n--- Max 3 limit ---")
    items, user1, user2, admin = fresh_data()
    client = app.test_client()
    login(client, user1)

    for i in range(3):
        client.post(f'/reserve_item/{items[i].id}')

    resp = client.post(f'/reserve_item/{items[3].id}', follow_redirects=True)
    html = resp.data.decode()
    status("4th reservation blocked", "only reserve 3" in html)


def test_reserve_sold_item():
    print("\n--- Sold item ---")
    items, user1, user2, admin = fresh_data()
    client = app.test_client()
    login(client, user1)

    items[0].status = 'sold'
    db.session.commit()

    resp = client.post(f'/reserve_item/{items[0].id}', follow_redirects=True)
    html = resp.data.decode()
    status("Cannot reserve sold item", "not available" in html)


# ── Cancel tests ──

def test_cancel_reservation():
    print("\n--- Cancel ---")
    items, user1, user2, admin = fresh_data()
    client = app.test_client()
    login(client, user1)

    item = items[0]
    client.post(f'/reserve_item/{item.id}')
    resp = client.post(f'/cancel_reservation/{item.id}', follow_redirects=True)
    html = resp.data.decode()

    res = get_active_reservation(item.id)
    record = ItemReservation.query.filter_by(item_id=item.id, user_id=user1.id).first()
    status("Cancel soft-deletes reservation",
           res is None and record is not None and record.cancelled_at is not None)
    status("Cancel flash message", "cancelled" in html.lower())


def test_cancel_nonexistent():
    print("\n--- Cancel nonexistent ---")
    items, user1, user2, admin = fresh_data()
    client = app.test_client()
    login(client, user1)

    resp = client.post(f'/cancel_reservation/{items[0].id}', follow_redirects=True)
    html = resp.data.decode()
    status("Cancel with no reservation shows error", "No active reservation" in html)


def test_re_reserve_after_cancel():
    print("\n--- Re-reserve after cancel ---")
    items, user1, user2, admin = fresh_data()
    client = app.test_client()
    login(client, user1)

    item = items[0]
    client.post(f'/reserve_item/{item.id}')
    client.post(f'/cancel_reservation/{item.id}')
    client.post(f'/reserve_item/{item.id}')

    res = get_active_reservation(item.id)
    status("Can re-reserve after cancel", res is not None and res.user_id == user1.id)


# ── Expiry tests ──

def test_expiry():
    print("\n--- Expiry ---")
    items, user1, user2, admin = fresh_data()
    client = app.test_client()

    item = items[0]
    r = ItemReservation(
        item_id=item.id, user_id=user1.id,
        expires_at=datetime.utcnow() - timedelta(days=1)
    )
    db.session.add(r)
    db.session.commit()

    status("Expired reservation returns None", get_active_reservation(item.id) is None)

    # Visit product page to trigger expiry email flag
    login(client, user1)
    client.get(f'/item/{item.id}')

    db.session.refresh(r)
    status("Expiry email flag set after page visit", r.expiry_email_sent == True)


# ── Inventory page tests ──

def test_inventory_page():
    print("\n--- Inventory page ---")
    items, user1, user2, admin = fresh_data()
    client = app.test_client()
    login(client, user1)

    # Reserve one item
    client.post(f'/reserve_item/{items[0].id}')

    resp = client.get('/inventory')
    html = resp.data.decode()
    status("Inventory shows 'Reserved' badge", 'Reserved</span>' in html)
    status("No countdown banner when open", 'Reservations open' not in html)

    # Set future date, check banner
    AppSetting.set('store_open_date', '2099-12-01')
    resp = client.get('/inventory')
    html = resp.data.decode()
    status("Countdown banner when store not open", 'Reservations open' in html)
    AppSetting.set('store_open_date', '2025-01-01')


# ── Product page states ──

def test_product_page_reserved_by_other():
    print("\n--- Product page: reserved by other ---")
    items, user1, user2, admin = fresh_data()

    # user1 reserves via their own client
    c1 = app.test_client()
    login(c1, user1)
    c1.post(f'/reserve_item/{items[0].id}')

    # user2 views via a different client
    c2 = app.test_client()
    login(c2, user2)
    resp = c2.get(f'/item/{items[0].id}')
    html = resp.data.decode()

    has_bookmark = 'fa-bookmark' in html
    no_reserve_btn = 'Reserve Item' not in html
    no_reserved_by_you = 'Reserved by you' not in html
    status("Other user sees Reserved badge, not 'Reserved by you'",
           has_bookmark and no_reserve_btn and no_reserved_by_you,
           f"bookmark={has_bookmark} no_reserve_btn={no_reserve_btn} no_reserved_by_you={no_reserved_by_you}")


def test_product_page_available():
    print("\n--- Product page: available ---")
    items, user1, user2, admin = fresh_data()
    client = app.test_client()
    login(client, user1)

    resp = client.get(f'/item/{items[1].id}')
    html = resp.data.decode()
    status("Unreserved item shows Reserve button", 'Reserve Item' in html)


def test_product_page_pre_open():
    print("\n--- Product page: pre-open ---")
    items, user1, user2, admin = fresh_data()
    client = app.test_client()
    login(client, user1)

    AppSetting.set('store_open_date', '2099-12-01')
    resp = client.get(f'/item/{items[1].id}')
    html = resp.data.decode()
    status("Pre-open hides Reserve button", 'Reservations open' in html and 'Reserve Item' not in html)
    AppSetting.set('store_open_date', '2025-01-01')


# ── Admin page ──

def test_admin_page():
    print("\n--- Admin page ---")
    items, user1, user2, admin = fresh_data()

    # Reserve an item as user1
    c1 = app.test_client()
    login(c1, user1)
    c1.post(f'/reserve_item/{items[0].id}')

    # View admin as admin
    c_admin = app.test_client()
    login(c_admin, admin)
    resp = c_admin.get('/admin')
    html = resp.data.decode()

    has_header = 'Reservation</th>' in html
    has_name = 'Test Buyer' in html
    status("Admin page shows Reservation column header", has_header,
           f"len={len(html)}, has lifecycle-table={'lifecycle-table' in html}")
    status("Admin shows reserver name", has_name,
           "name not found" if not has_name else "")


# ── Run all ──

if __name__ == '__main__':
    ctx = app.app_context()
    ctx.push()
    db.create_all()

    print(f"\nRunning reservation tests...\n")

    test_helpers()
    test_reserve_requires_login()
    test_reserve_get_redirect()
    test_reserve_happy_path()
    test_reserve_blocked_before_store_open()
    test_reserve_duplicate_same_user()
    test_reserve_blocked_by_other_user()
    test_reserve_max_3()
    test_reserve_sold_item()
    test_cancel_reservation()
    test_cancel_nonexistent()
    test_re_reserve_after_cancel()
    test_expiry()
    test_inventory_page()
    test_product_page_reserved_by_other()
    test_product_page_available()
    test_product_page_pre_open()
    test_admin_page()

    print(f"\n{'='*50}")
    print(f"Results: {PASSED} passed, {FAILED} failed out of {PASSED + FAILED}")
    print(f"{'='*50}\n")

    # Clean up test data
    fresh_data()  # resets to known state
    db.session.remove()
    ctx.pop()

    sys.exit(0 if FAILED == 0 else 1)
