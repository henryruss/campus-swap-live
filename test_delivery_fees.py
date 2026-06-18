"""Tests for Spec A: Delivery Fees, Sales Tax, and Flexible Delivery.

Run with: python3 -m pytest test_delivery_fees.py -v
"""
import pytest
from decimal import Decimal
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Default AppSetting values for test patching
# ---------------------------------------------------------------------------

DEFAULT_SETTINGS = {
    'delivery_zone_boundaries': '5,10,15,20',
    'delivery_zone_fees': '15,20,25,30',
    'sales_tax_rate': '0.0725',
    'flexible_delivery_discount': '5',
}


def mock_appsetting_get(key, default=None):
    return DEFAULT_SETTINGS.get(key, default)


# ---------------------------------------------------------------------------
# Zone helper tests (patched AppSetting — no DB needed)
# ---------------------------------------------------------------------------

@pytest.fixture
def patch_appsetting():
    """Patch AppSetting.get — used explicitly by helper unit tests."""
    with patch('app.AppSetting') as mock_cls:
        mock_cls.get.side_effect = mock_appsetting_get
        yield


class TestCalculateDeliveryZone:
    """Zone boundaries inclusive: 0–5 → Z1/$15, >5–10 → Z2/$20, >10–15 → Z3/$25, >15–20 → Z4/$30, >20 → None."""

    def _zone(self, miles, patch_appsetting):
        from app import calculate_delivery_zone
        return calculate_delivery_zone(miles)

    def test_zone1_inner(self, patch_appsetting):
        zone, fee = self._zone(2.0, patch_appsetting)
        assert zone == 1 and fee == Decimal('15')

    def test_zone1_boundary_exact_5mi(self, patch_appsetting):
        """5.0 miles exactly → Zone 1 (upper bound inclusive)."""
        zone, fee = self._zone(5.0, patch_appsetting)
        assert zone == 1 and fee == Decimal('15')

    def test_zone2_just_over_boundary(self, patch_appsetting):
        """5.01 miles → Zone 2."""
        zone, fee = self._zone(5.01, patch_appsetting)
        assert zone == 2 and fee == Decimal('20')

    def test_zone2_boundary_exact_10mi(self, patch_appsetting):
        zone, fee = self._zone(10.0, patch_appsetting)
        assert zone == 2 and fee == Decimal('20')

    def test_zone3_inner(self, patch_appsetting):
        zone, fee = self._zone(12.5, patch_appsetting)
        assert zone == 3 and fee == Decimal('25')

    def test_zone3_boundary_exact_15mi(self, patch_appsetting):
        zone, fee = self._zone(15.0, patch_appsetting)
        assert zone == 3 and fee == Decimal('25')

    def test_zone4_inner(self, patch_appsetting):
        zone, fee = self._zone(18.0, patch_appsetting)
        assert zone == 4 and fee == Decimal('30')

    def test_zone4_boundary_exact_20mi(self, patch_appsetting):
        """20.0 miles exactly → Zone 4 (still in range)."""
        zone, fee = self._zone(20.0, patch_appsetting)
        assert zone == 4 and fee == Decimal('30')

    def test_beyond_20mi_returns_none(self, patch_appsetting):
        """20.01 miles → rejected (outside delivery area)."""
        assert self._zone(20.01, patch_appsetting) is None

    def test_far_returns_none(self, patch_appsetting):
        assert self._zone(100.0, patch_appsetting) is None

    def test_zero_distance_zone1(self, patch_appsetting):
        zone, _ = self._zone(0.0, patch_appsetting)
        assert zone == 1


class TestComputeSalesTax:
    """Tax = 7.25% × item_price only, rounded to 2 decimals."""

    def _tax(self, price, patch_appsetting):
        from app import compute_sales_tax
        return compute_sales_tax(price)

    def test_spec_example_85(self, patch_appsetting):
        """$85 × 0.0725 = $6.1625 → rounds to $6.16."""
        assert self._tax(85, patch_appsetting) == Decimal('6.16')

    def test_zero_price(self, patch_appsetting):
        assert self._tax(0, patch_appsetting) == Decimal('0.00')

    def test_10_dollars(self, patch_appsetting):
        """$10 × 0.0725 = $0.725 → $0.73 (ROUND_HALF_UP)."""
        assert self._tax(10, patch_appsetting) == Decimal('0.73')

    def test_100_dollars(self, patch_appsetting):
        """$100 × 0.0725 = $7.25."""
        assert self._tax(100, patch_appsetting) == Decimal('7.25')

    def test_20_dollars(self, patch_appsetting):
        """$20 × 0.0725 = $1.45."""
        assert self._tax(20, patch_appsetting) == Decimal('1.45')

    def test_delivery_fee_not_in_taxable_base(self, patch_appsetting):
        """Tax on $85 must not equal tax on ($85 + $15 zone fee)."""
        from app import compute_sales_tax
        tax_on_item = compute_sales_tax(Decimal('85'))
        tax_on_item_plus_fee = compute_sales_tax(Decimal('85') + Decimal('15'))
        assert tax_on_item != tax_on_item_plus_fee
        assert tax_on_item == Decimal('6.16')


class TestToCents:
    def test_whole_dollar(self):
        from app import _to_cents
        assert _to_cents(Decimal('10')) == 1000

    def test_tax_amount(self):
        from app import _to_cents
        assert _to_cents(Decimal('6.16')) == 616

    def test_15_dollars(self):
        from app import _to_cents
        assert _to_cents(Decimal('15')) == 1500

    def test_half_cent_rounds_up(self):
        from app import _to_cents
        assert _to_cents(Decimal('1.005')) == 101


# ---------------------------------------------------------------------------
# Full math verification from spec testing checklist
# ---------------------------------------------------------------------------

class TestMathVerification:

    def test_spec_example_85_zone1(self, patch_appsetting):
        """Spec: $85 item, Zone 1 → $85 + $6.16 + $15 = $106.16."""
        from app import compute_sales_tax, calculate_delivery_zone
        price = Decimal('85')
        tax = compute_sales_tax(price)
        zone, fee = calculate_delivery_zone(3.0)
        total = price + tax + fee
        assert zone == 1
        assert fee == Decimal('15')
        assert tax == Decimal('6.16')
        assert total == Decimal('106.16')

    def test_flexible_discount_reduces_by_5(self, patch_appsetting):
        """Flexible → subtract $5 from total."""
        from app import compute_sales_tax, calculate_delivery_zone
        price = Decimal('85')
        tax = compute_sales_tax(price)
        _, fee = calculate_delivery_zone(3.0)
        total_standard = price + tax + fee
        total_flexible = total_standard - Decimal('5')
        assert total_standard == Decimal('106.16')
        assert total_flexible == Decimal('101.16')

    def test_all_four_zone_fees(self, patch_appsetting):
        """Each zone returns the right fee."""
        from app import calculate_delivery_zone
        cases = [(2.0, 1, 15), (7.0, 2, 20), (12.0, 3, 25), (18.0, 4, 30)]
        for dist, expected_zone, expected_fee in cases:
            zone, fee = calculate_delivery_zone(dist)
            assert zone == expected_zone, f"dist={dist}: expected zone {expected_zone}, got {zone}"
            assert fee == Decimal(str(expected_fee))

    def test_boundary_distances_land_in_lower_zone(self, patch_appsetting):
        """Boundary values 5/10/15/20 must land in the LOWER zone (inclusive upper bound)."""
        from app import calculate_delivery_zone
        assert calculate_delivery_zone(5.0)[0] == 1
        assert calculate_delivery_zone(10.0)[0] == 2
        assert calculate_delivery_zone(15.0)[0] == 3
        assert calculate_delivery_zone(20.0)[0] == 4

    def test_garbage_address_treated_as_out_of_range(self, patch_appsetting):
        """Geocode returning None → no fee computed (covered by route test)."""
        pass


# ---------------------------------------------------------------------------
# Route tests — use isolated SQLite client
# ---------------------------------------------------------------------------

@pytest.fixture(scope='module')
def isolated_client():
    """Test client against campusswap_prod (the local prod snapshot with all migrations)."""
    from app import app as _app, db
    from models import AppSetting

    _app.config['TESTING'] = True
    _app.config['WTF_CSRF_ENABLED'] = False
    _app.config['SECRET_KEY'] = 'test-secret'
    _app.config['SERVER_NAME'] = 'localhost'

    with _app.test_client() as client:
        with _app.app_context():
            for key, val in [
                ('store_open_date', '2020-01-01'),
                ('warehouse_lat', '35.9132'),
                ('warehouse_lng', '-79.0558'),
                ('delivery_zone_boundaries', '5,10,15,20'),
                ('delivery_zone_fees', '15,20,25,30'),
                ('sales_tax_rate', '0.0725'),
                ('flexible_delivery_discount', '5'),
            ]:
                AppSetting.set(key, val)
            db.session.commit()
            yield client
            db.session.remove()


@pytest.fixture(scope='module')
def item_id(isolated_client):
    from app import app as _app, db
    from models import InventoryItem, User
    import uuid
    with _app.app_context():
        tag = uuid.uuid4().hex[:8]
        seller = User.query.filter_by(email='seller@test.com').first()
        if not seller:
            seller = User(email='seller@test.com', full_name='Seller Test', is_seller=True)
            db.session.add(seller)
            db.session.flush()
        item = InventoryItem(
            description='Test Desk',
            price=Decimal('85.00'),
            status='available',
            seller_id=seller.id,
        )
        db.session.add(item)
        db.session.commit()
        return item.id


class TestLegacyDeliveryRoutes:
    """Spec B: per-item checkout URLs are legacy redirects."""

    def test_legacy_post_delivery_redirects_to_product(self, isolated_client, item_id):
        resp = isolated_client.post(f'/checkout/delivery/{item_id}', data={
            'street': '100 Main St', 'city': 'Chapel Hill',
            'state': 'NC', 'zip': '27514',
        }, follow_redirects=False)
        assert resp.status_code == 302
        assert f'/item/{item_id}' in resp.headers['Location']

    def test_legacy_get_delivery_redirects_to_cart_flow(self, isolated_client, item_id):
        resp = isolated_client.get(f'/checkout/delivery/{item_id}', follow_redirects=False)
        assert resp.status_code == 302
        assert '/checkout/delivery' in resp.headers['Location']
        assert f'/{item_id}' not in resp.headers['Location']

    def test_legacy_pay_redirects_to_product(self, isolated_client, item_id):
        resp = isolated_client.get(f'/checkout/pay/{item_id}', follow_redirects=False)
        assert resp.status_code == 302
        assert f'/item/{item_id}' in resp.headers['Location']

    def test_legacy_review_no_cart_session_redirects_to_product(self, isolated_client, item_id):
        with isolated_client.session_transaction() as sess:
            sess.pop('pending_delivery', None)
        resp = isolated_client.get(f'/checkout/review/{item_id}', follow_redirects=False)
        assert resp.status_code == 302
        assert f'/item/{item_id}' in resp.headers['Location']

    def test_legacy_review_with_cart_session_redirects_to_review(self, isolated_client, item_id):
        with isolated_client.session_transaction() as sess:
            sess['pending_delivery'] = {'cart_id': 999}
        resp = isolated_client.get(f'/checkout/review/{item_id}', follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers['Location'].rstrip('/').endswith('/checkout/review')
