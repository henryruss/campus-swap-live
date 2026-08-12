"""Tests for super-admin sale notifications and Resend send reliability.

Run with: python3 -m pytest test_order_notifications.py -v

Coverage:
- _is_undeliverable_placeholder(): proxy + no-MX internal domains skipped
- send_email() short-circuits on placeholder addresses (no Resend call)
- _resend_send_throttled(): spaces calls under the 2 req/s limit; retries 429
- _send_admin_sale_notification(): super admins only, unsubscribed excluded,
  content includes items/buyer/total, conflict banner when flagged
- _items_sold_email_html(): one grouped email per seller per order, correct
  per-item and total payout math; single-item output unchanged
- _send_delivery_scheduled_email(): one email per buyer order, not per item
- _maybe_send_delivery_completed_email(): fires only when every stop in the
  order is completed, exactly once, and not while a stop is flagged 'issue'
- buyer phone: captured from Stripe, denormalized to BuyerOrder, surfaced to ops
"""

import time
import uuid
import pytest


def _uid():
    return uuid.uuid4().hex[:10]


# ---------------------------------------------------------------------------
# Undeliverable placeholder guard
# ---------------------------------------------------------------------------

class TestUndeliverablePlaceholder:
    @pytest.mark.parametrize('addr', [
        'internal@campusswap.com',
        'INTERNAL@CampusSwap.com',
        '  internal@campusswap.com  ',
        'proxy+abc123@usecampusswap.com',
    ])
    def test_placeholders_detected(self, addr):
        from app import _is_undeliverable_placeholder
        assert _is_undeliverable_placeholder(addr) is True

    @pytest.mark.parametrize('addr', [
        'henry@usecampusswap.com',
        'team@usecampusswap.com',
        'buyer@gmail.com',
        '',
        None,
    ])
    def test_real_addresses_pass(self, addr):
        from app import _is_undeliverable_placeholder
        assert _is_undeliverable_placeholder(addr) is False

    def test_send_email_skips_placeholder_without_calling_resend(self, monkeypatch):
        """campusswap.com has no MX record — sending there hard-bounces."""
        import app as app_module

        calls = []
        monkeypatch.setattr(app_module, '_resend_send_throttled',
                            lambda data, **kw: calls.append(data))
        monkeypatch.setattr(app_module.resend, 'api_key', 'test-key')

        assert app_module.send_email('internal@campusswap.com', 'Sold', '<p>hi</p>') is False
        assert calls == []


# ---------------------------------------------------------------------------
# Resend throttle + 429 retry
# ---------------------------------------------------------------------------

class TestResendThrottle:
    def test_back_to_back_sends_are_spaced(self, monkeypatch):
        """A 3-item order fires 3 seller emails + 1 buyer email; unspaced that 429s."""
        import app as app_module

        stamps = []
        monkeypatch.setattr(app_module.resend.Emails, 'send',
                            lambda data: stamps.append(time.monotonic()))
        monkeypatch.setattr(app_module, '_resend_last_send_at', [0.0])

        for i in range(4):
            app_module._resend_send_throttled({'to': f'{i}@test.com'})

        gaps = [stamps[i] - stamps[i - 1] for i in range(1, len(stamps))]
        assert len(stamps) == 4
        assert all(g >= app_module._RESEND_MIN_INTERVAL - 0.01 for g in gaps), gaps

    def test_retries_on_rate_limit_then_succeeds(self, monkeypatch):
        import app as app_module

        attempts = []

        def flaky(data):
            attempts.append(data)
            if len(attempts) == 1:
                raise Exception('429 Too Many Requests: rate limit exceeded')
            return {'id': 'email_123'}

        monkeypatch.setattr(app_module.resend.Emails, 'send', flaky)
        monkeypatch.setattr(app_module, '_resend_last_send_at', [0.0])

        result = app_module._resend_send_throttled({'to': 'a@test.com'})
        assert len(attempts) == 2
        assert result == {'id': 'email_123'}

    def test_non_rate_limit_error_raises_immediately(self, monkeypatch):
        import app as app_module

        attempts = []

        def boom(data):
            attempts.append(data)
            raise Exception('422 invalid from address')

        monkeypatch.setattr(app_module.resend.Emails, 'send', boom)
        monkeypatch.setattr(app_module, '_resend_last_send_at', [0.0])

        with pytest.raises(Exception, match='422'):
            app_module._resend_send_throttled({'to': 'a@test.com'})
        assert len(attempts) == 1


# ---------------------------------------------------------------------------
# Super-admin sale notification
# ---------------------------------------------------------------------------

@pytest.fixture(scope='module')
def notif_app():
    from app import app as _app
    _app.config['TESTING'] = True
    _app.config['SERVER_NAME'] = 'localhost'
    return _app


@pytest.fixture
def notif_fixtures(notif_app):
    """Super admin, plain admin, unsubscribed super admin, seller + 2 items."""
    from app import db
    from models import User, InventoryItem
    tag = _uid()

    with notif_app.app_context():
        super_admin = User(email=f'notif_super_{tag}@test.com', full_name='Super',
                           is_admin=True, is_super_admin=True, unsubscribed=False)
        plain_admin = User(email=f'notif_admin_{tag}@test.com', full_name='Admin',
                           is_admin=True, is_super_admin=False, unsubscribed=False)
        unsub_super = User(email=f'notif_unsub_{tag}@test.com', full_name='Unsub',
                           is_admin=True, is_super_admin=True, unsubscribed=True)
        seller = User(email=f'notif_seller_{tag}@test.com', full_name='Seller', is_seller=True)
        for u in (super_admin, plain_admin, unsub_super, seller):
            u.set_password('testpass123')
        db.session.add_all([super_admin, plain_admin, unsub_super, seller])
        db.session.commit()

        items = []
        for i in range(2):
            it = InventoryItem(
                seller_id=seller.id,
                description=f'Notif Test Dresser {i} {tag}',
                price=100 + i,
                status='sold',
            )
            db.session.add(it)
            items.append(it)
        db.session.commit()

        data = {
            'super_email': super_admin.email,
            'admin_email': plain_admin.email,
            'unsub_email': unsub_super.email,
            'item_ids': [it.id for it in items],
            'user_ids': [super_admin.id, plain_admin.id, unsub_super.id, seller.id],
        }
        yield data

        # Cleanup — these rows would otherwise pollute admin recipient lists
        from sqlalchemy import delete
        db.session.execute(delete(InventoryItem).where(InventoryItem.id.in_(data['item_ids'])))
        db.session.execute(delete(User).where(User.id.in_(data['user_ids'])))
        db.session.commit()


class TestAdminSaleNotification:
    def _capture(self, notif_app, monkeypatch, fixtures, **kwargs):
        import app as app_module
        from models import InventoryItem

        sent = []
        monkeypatch.setattr(app_module, 'send_email',
                            lambda to, subject, html, **kw: sent.append((to, subject, html)))
        with notif_app.app_context():
            items = [InventoryItem.query.get(i) for i in fixtures['item_ids']]
            app_module._send_admin_sale_notification(items, **kwargs)
        return sent

    def test_goes_to_super_admins_only(self, notif_app, monkeypatch, notif_fixtures):
        sent = self._capture(notif_app, monkeypatch, notif_fixtures,
                             buyer_email='buyer@gmail.com', buyer_name='Test Buyer',
                             delivery_address='1 Main St, Chapel Hill, NC 27516',
                             total_paid=201, order_id=999)
        recipients = [to for to, _, _ in sent]
        assert notif_fixtures['super_email'] in recipients
        assert notif_fixtures['admin_email'] not in recipients, 'plain admins must not be notified'
        assert notif_fixtures['unsub_email'] not in recipients, 'unsubscribed must be skipped'

    def test_subject_and_body_carry_order_details(self, notif_app, monkeypatch, notif_fixtures):
        sent = self._capture(notif_app, monkeypatch, notif_fixtures,
                             buyer_email='stacey@gmail.com', buyer_name='Stacey T',
                             delivery_address='102 Fraternity Court, Chapel Hill, NC 27516',
                             total_paid=166.24, order_id=4)
        assert sent, 'no notification sent'
        _, subject, html = sent[0]
        assert '2 items' in subject
        assert '166.24' in subject
        assert 'Order #4' in html
        assert 'stacey@gmail.com' in html
        assert 'Stacey T' in html
        assert '102 Fraternity Court' in html
        for item_id in notif_fixtures['item_ids']:
            assert f'#{item_id}' in html

    def test_conflict_note_rendered(self, notif_app, monkeypatch, notif_fixtures):
        sent = self._capture(notif_app, monkeypatch, notif_fixtures,
                             buyer_email='b@gmail.com', total_paid=50,
                             conflict_note='Double-sale on item #12 — refund required.')
        _, _, html = sent[0]
        assert 'Needs attention' in html
        assert 'Double-sale on item #12' in html

    def test_no_conflict_note_when_clean(self, notif_app, monkeypatch, notif_fixtures):
        sent = self._capture(notif_app, monkeypatch, notif_fixtures,
                             buyer_email='b@gmail.com', total_paid=50)
        _, _, html = sent[0]
        assert 'Needs attention' not in html

    def test_send_failure_does_not_raise(self, notif_app, monkeypatch, notif_fixtures):
        """A broken notification must never take down the Stripe webhook."""
        import app as app_module
        from models import InventoryItem

        def boom(*a, **kw):
            raise Exception('Resend down')

        monkeypatch.setattr(app_module, 'send_email', boom)
        with notif_app.app_context():
            items = [InventoryItem.query.get(i) for i in notif_fixtures['item_ids']]
            app_module._send_admin_sale_notification(items, buyer_email='b@gmail.com',
                                                     total_paid=50)  # must not raise


# ---------------------------------------------------------------------------
# Grouped seller emails
# ---------------------------------------------------------------------------

class TestGroupedSellerEmail:
    def test_multi_item_email_lists_all_items_and_totals(self, notif_app, notif_fixtures):
        import app as app_module
        from models import InventoryItem

        with notif_app.app_context():
            items = [InventoryItem.query.get(i) for i in notif_fixtures['item_ids']]
            seller = items[0].seller
            html = app_module._items_sold_email_html(items, seller)

        # Items are priced 100 and 101 by the fixture; payout is 50%
        assert '2 of your items' in html
        for itm_desc, price, payout in [('Notif Test Dresser 0', '100.00', '50.00'),
                                        ('Notif Test Dresser 1', '101.00', '50.50')]:
            assert itm_desc in html
            assert f'${price}' in html
            assert f'${payout}' in html
        assert '$201.00' in html, 'total sale price missing'
        assert '$100.50' in html, 'total payout missing'

    def test_single_item_email_keeps_original_shape(self, notif_app, notif_fixtures):
        import app as app_module
        from models import InventoryItem

        with notif_app.app_context():
            item = InventoryItem.query.get(notif_fixtures['item_ids'][0])
            html = app_module._items_sold_email_html([item], item.seller)

        assert 'Cha-Ching!' in html
        assert 'Multiple items sold' not in html
        assert 'Sale price:' in html
        assert 'Your payout (50%):' in html
        assert '2 of your items' not in html

    def test_item_sold_wrapper_matches_single_item_path(self, notif_app, notif_fixtures):
        import app as app_module
        from models import InventoryItem

        with notif_app.app_context():
            item = InventoryItem.query.get(notif_fixtures['item_ids'][0])
            assert (app_module._item_sold_email_html(item, item.seller)
                    == app_module._items_sold_email_html([item], item.seller))

    def test_subject_switches_on_count(self):
        from app import _items_sold_subject
        assert _items_sold_subject(1) == "Your Item Has Sold! - Campus Swap"
        assert _items_sold_subject(3) == "Your Items Have Sold! - Campus Swap"

    def test_webhook_sends_one_email_per_seller_not_per_item(self, notif_app, monkeypatch,
                                                             notif_fixtures):
        """Two items from one seller in a single order => exactly one seller email."""
        import app as app_module
        from models import InventoryItem

        sent = []
        monkeypatch.setattr(app_module, 'send_email',
                            lambda to, subject, html, **kw: sent.append((to, subject)))

        with notif_app.app_context():
            sold_items = [InventoryItem.query.get(i) for i in notif_fixtures['item_ids']]
            seller_email = sold_items[0].seller.email

            # Mirrors the webhook's grouping block
            seller_items = {}
            for item in sold_items:
                seller_items.setdefault(item.seller_id, []).append(item)
            for seller_id, items in seller_items.items():
                seller = items[0].seller
                app_module.send_email(seller.email,
                                      app_module._items_sold_subject(len(items)),
                                      app_module._items_sold_email_html(items, seller))

        assert len(sent) == 1, f'expected 1 grouped email, got {len(sent)}'
        assert sent[0][0] == seller_email
        assert sent[0][1] == "Your Items Have Sold! - Campus Swap"


# ---------------------------------------------------------------------------
# Delivery notifications
# ---------------------------------------------------------------------------

@pytest.fixture
def delivery_fixtures(notif_app):
    """An Order with 3 line items + a solo legacy BuyerOrder, all as DeliveryStops.

    Committed so tests can open their own app context, then removed in FK order on
    teardown (bulk SQL DELETE per project convention) to leave the shared DB clean.
    """
    from app import db, _now_eastern
    from models import (User, InventoryItem, Order, BuyerOrder, Shift, ShiftWeek,
                        DeliveryStop)
    from decimal import Decimal
    tag = _uid()

    with notif_app.app_context():
        seller = User(email=f'deliv_seller_{tag}@test.com', full_name='Deliv Seller', is_seller=True)
        seller.set_password('testpass123')
        db.session.add(seller)
        db.session.flush()

        items = []
        for i in range(5):  # 5th stays unassigned, to exercise the ops delivery queue
            it = InventoryItem(seller_id=seller.id, description=f'Deliv Item {i} {tag}',
                               price=50 + i, status='sold')
            db.session.add(it)
            items.append(it)
        db.session.flush()

        # Cart order: 3 items, one buyer
        order = Order(buyer_email=f'deliv_buyer_{tag}@test.com', buyer_name='Deliv Buyer',
                      buyer_phone='+19195550123',
                      delivery_street='102 Fraternity Court', delivery_city='Chapel Hill',
                      delivery_state='NC', delivery_zip='27516', status='paid',
                      total_paid=Decimal('160.00'))
        db.session.add(order)
        db.session.flush()

        cart_bos = []
        for it in items[:3]:
            bo = BuyerOrder(item_id=it.id, order_id=order.id, buyer_email=order.buyer_email,
                            buyer_phone=order.buyer_phone,
                            delivery_address='102 Fraternity Court, Chapel Hill, NC 27516')
            db.session.add(bo)
            cart_bos.append(bo)

        # Legacy solo order: no parent Order
        solo_bo = BuyerOrder(item_id=items[3].id, buyer_email=f'solo_{tag}@test.com',
                             delivery_address='710 N Columbia St, Chapel Hill, NC 27516')
        db.session.add(solo_bo)

        # Unassigned (no DeliveryStop) — appears in the ops delivery queue
        unassigned_bo = BuyerOrder(item_id=items[4].id, buyer_email=f'unassigned_{tag}@test.com',
                                   buyer_phone='+19195559876',
                                   delivery_address='1 Main St, Chapel Hill, NC 27516')
        db.session.add(unassigned_bo)
        db.session.flush()

        week = ShiftWeek.query.filter_by(is_tutorial=False).first()
        shift = Shift(week_id=week.id, day_of_week='fri', slot='am', is_active=True)
        db.session.add(shift)
        db.session.flush()

        stops = []
        for i, bo in enumerate(cart_bos + [solo_bo], start=1):
            st = DeliveryStop(shift_id=shift.id, buyer_order_id=bo.id, truck_number=1,
                              stop_order=i, created_by_id=seller.id)
            db.session.add(st)
            stops.append(st)
        db.session.commit()

        data = {
            'shift_id': shift.id,
            'cart_stop_ids': [s.id for s in stops[:3]],
            'solo_stop_id': stops[3].id,
            'buyer_email': order.buyer_email,
            'solo_email': solo_bo.buyer_email,
            'buyer_phone': order.buyer_phone,
            'unassigned_phone': unassigned_bo.buyer_phone,
            'unassigned_email': unassigned_bo.buyer_email,
            '_cleanup': {
                'stop_ids': [s.id for s in stops],
                'bo_ids': [bo.id for bo in cart_bos] + [solo_bo.id, unassigned_bo.id],
                'order_id': order.id,
                'shift_id': shift.id,
                'item_ids': [it.id for it in items],
                'user_id': seller.id,
            },
        }
        yield data

    # Teardown in FK dependency order — bulk SQL DELETE per project convention
    with notif_app.app_context():
        c = data['_cleanup']
        from sqlalchemy import delete
        db.session.execute(delete(DeliveryStop).where(DeliveryStop.id.in_(c['stop_ids'])))
        db.session.execute(delete(BuyerOrder).where(BuyerOrder.id.in_(c['bo_ids'])))
        db.session.execute(delete(Order).where(Order.id == c['order_id']))
        db.session.execute(delete(Shift).where(Shift.id == c['shift_id']))
        db.session.execute(delete(InventoryItem).where(InventoryItem.id.in_(c['item_ids'])))
        db.session.execute(delete(User).where(User.id == c['user_id']))
        db.session.commit()


class TestDeliveryScheduledEmail:
    def test_one_email_per_order_not_per_item(self, notif_app, monkeypatch, delivery_fixtures):
        import app as app_module
        from models import DeliveryStop

        sent = []
        monkeypatch.setattr(app_module, 'send_email',
                            lambda to, subject, html, **kw: sent.append((to, subject, html)))

        with notif_app.app_context():
            stops = DeliveryStop.query.filter_by(shift_id=delivery_fixtures['shift_id']).all()
            assert len(stops) == 4, 'fixture should have 4 stops'
            groups = app_module._group_stops_by_buyer_order(stops)
            assert len(groups) == 2, '3-item cart order + 1 solo order => 2 groups'
            for g in groups:
                app_module._send_delivery_scheduled_email(g)

        assert len(sent) == 2, f'4 stops must produce 2 emails, got {len(sent)}'
        by_recipient = {to: html for to, _, html in sent}
        assert delivery_fixtures['buyer_email'] in by_recipient
        assert delivery_fixtures['solo_email'] in by_recipient

        multi = by_recipient[delivery_fixtures['buyer_email']]
        assert 'all 3 of your items' in multi
        assert 'Items (3)' in multi

        solo = by_recipient[delivery_fixtures['solo_email']]
        assert 'your item is scheduled' in solo
        assert 'Items (' not in solo

    def test_notified_at_stamped_on_every_stop_in_group(self, notif_app, monkeypatch,
                                                        delivery_fixtures):
        import app as app_module
        from models import DeliveryStop

        monkeypatch.setattr(app_module, 'send_email', lambda *a, **kw: True)
        with notif_app.app_context():
            stops = [DeliveryStop.query.get(i) for i in delivery_fixtures['cart_stop_ids']]
            app_module._send_delivery_scheduled_email(stops)
            assert all(s.notified_at is not None for s in stops)

    def test_copy_promises_email_not_day_of_heads_up(self, notif_app, monkeypatch,
                                                    delivery_fixtures):
        import app as app_module
        from models import DeliveryStop

        sent = []
        monkeypatch.setattr(app_module, 'send_email',
                            lambda to, subject, html, **kw: sent.append(html))
        with notif_app.app_context():
            stop = DeliveryStop.query.get(delivery_fixtures['solo_stop_id'])
            app_module._send_delivery_scheduled_email(stop)

        assert 'email you before your delivery date' in sent[0] \
            or 'email before your delivery date' in sent[0]
        assert 'heads-up on the day of delivery' not in sent[0]

    def test_accepts_single_stop_or_list(self, notif_app, monkeypatch, delivery_fixtures):
        import app as app_module
        from models import DeliveryStop

        monkeypatch.setattr(app_module, 'send_email', lambda *a, **kw: True)
        with notif_app.app_context():
            stop = DeliveryStop.query.get(delivery_fixtures['solo_stop_id'])
            assert app_module._send_delivery_scheduled_email(stop) is True
            stop.notified_at = None
            assert app_module._send_delivery_scheduled_email([stop]) is True


class TestDeliveryCompletedEmail:
    def _complete(self, app_module, stop):
        from app import db, _now_eastern
        stop.status = 'completed'
        stop.completed_at = _now_eastern().replace(tzinfo=None)
        db.session.flush()
        return app_module._maybe_send_delivery_completed_email(stop)

    def test_fires_only_after_last_stop_completed(self, notif_app, monkeypatch,
                                                  delivery_fixtures):
        import app as app_module
        from models import DeliveryStop

        sent = []
        monkeypatch.setattr(app_module, 'send_email',
                            lambda to, subject, html, **kw: sent.append((to, subject, html)))

        with notif_app.app_context():
            stops = [DeliveryStop.query.get(i) for i in delivery_fixtures['cart_stop_ids']]
            results = [self._complete(app_module, s) for s in stops]

        assert results == [False, False, True], results
        assert len(sent) == 1, 'exactly one delivered email per order'
        to, subject, html = sent[0]
        assert to == delivery_fixtures['buyer_email']
        assert 'delivered' in subject.lower()
        assert 'All 3 of your items' in html

    def test_does_not_resend_when_stop_remarked(self, notif_app, monkeypatch,
                                               delivery_fixtures):
        import app as app_module
        from models import DeliveryStop

        sent = []
        monkeypatch.setattr(app_module, 'send_email',
                            lambda to, subject, html, **kw: sent.append(to))
        with notif_app.app_context():
            stops = [DeliveryStop.query.get(i) for i in delivery_fixtures['cart_stop_ids']]
            for s in stops:
                self._complete(app_module, s)
            assert len(sent) == 1
            # crew re-taps completed on the last stop
            again = self._complete(app_module, stops[-1])

        assert again is False
        assert len(sent) == 1, 'must not re-send'

    def test_issue_stop_holds_email_back(self, notif_app, monkeypatch, delivery_fixtures):
        import app as app_module
        from app import db
        from models import DeliveryStop

        sent = []
        monkeypatch.setattr(app_module, 'send_email',
                            lambda to, subject, html, **kw: sent.append(to))
        with notif_app.app_context():
            stops = [DeliveryStop.query.get(i) for i in delivery_fixtures['cart_stop_ids']]
            self._complete(app_module, stops[0])
            self._complete(app_module, stops[1])
            stops[2].status = 'issue'
            db.session.flush()

            assert app_module._maybe_send_delivery_completed_email(stops[0]) is False
            assert sent == [], 'flagged order must not get a "delivered!" email'

            # Issue resolved later
            assert self._complete(app_module, stops[2]) is True
            assert len(sent) == 1

    def test_solo_order_gets_single_item_copy(self, notif_app, monkeypatch,
                                             delivery_fixtures):
        import app as app_module
        from models import DeliveryStop

        sent = []
        monkeypatch.setattr(app_module, 'send_email',
                            lambda to, subject, html, **kw: sent.append((to, html)))
        with notif_app.app_context():
            stop = DeliveryStop.query.get(delivery_fixtures['solo_stop_id'])
            assert self._complete(app_module, stop) is True

        to, html = sent[0]
        assert to == delivery_fixtures['solo_email']
        assert 'Your item has been delivered' in html
        assert 'All ' not in html.replace('Delivered to', '')


class TestBuyerPhoneCapture:
    def test_stripe_checkout_enables_phone_collection(self):
        """Both checkout paths must ask Stripe for a phone number."""
        source = open('app.py').read()
        assert source.count("phone_number_collection={'enabled': True}") == 2, \
            'cart checkout and legacy single-item checkout both need phone collection'

    def test_models_have_phone_columns(self):
        from models import Order, BuyerOrder
        assert hasattr(Order, 'buyer_phone')
        assert hasattr(BuyerOrder, 'buyer_phone')

    def test_delivery_queue_exposes_phone(self, notif_app, delivery_fixtures):
        import app as app_module
        notif_app.config['SERVER_NAME'] = 'localhost'
        with notif_app.test_request_context('/'):
            groups = app_module._build_delivery_queue()
        assert groups, 'queue should not be empty'
        assert all('buyer_phone' in g for g in groups), 'every queue card exposes buyer_phone'
        mine = [g for g in groups if g['buyer_email'] == delivery_fixtures['unassigned_email']]
        assert len(mine) == 1, 'unassigned order should appear exactly once'
        assert mine[0]['buyer_phone'] == delivery_fixtures['unassigned_phone']

    def test_admin_sale_notification_includes_phone(self, notif_app, monkeypatch,
                                                    notif_fixtures):
        import app as app_module
        from models import InventoryItem

        sent = []
        monkeypatch.setattr(app_module, 'send_email',
                            lambda to, subject, html, **kw: sent.append(html))
        with notif_app.app_context():
            items = [InventoryItem.query.get(i) for i in notif_fixtures['item_ids']]
            app_module._send_admin_sale_notification(items, buyer_email='b@gmail.com',
                                                    buyer_phone='+19195550123', total_paid=50)
        assert '+19195550123' in sent[0]
        assert 'Buyer phone' in sent[0]


# ---------------------------------------------------------------------------
# Sender identity / reply-to
# ---------------------------------------------------------------------------

class TestSenderAndReplyTo:
    def _send(self, monkeypatch, notif_app, env=None):
        import app as app_module

        captured = {}
        monkeypatch.setattr(app_module.resend, 'api_key', 'test-key')
        monkeypatch.setattr(app_module, '_resend_send_throttled',
                            lambda data, **kw: captured.update(data))
        for key, val in (env or {}).items():
            if val is None:
                monkeypatch.delenv(key, raising=False)
            else:
                monkeypatch.setenv(key, val)
        with notif_app.test_request_context('/'):
            app_module.send_email('buyer@example.com', 'Test', '<p>hi</p>')
        return captured

    def test_reply_to_is_set_so_customer_replies_land_somewhere(self, monkeypatch, notif_app):
        sent = self._send(monkeypatch, notif_app,
                          {'RESEND_FROM_EMAIL': None, 'RESEND_REPLY_TO': None})
        assert sent['reply_to'] == 'team@usecampusswap.com'

    def test_default_sender_is_noreply(self, monkeypatch, notif_app):
        """From is unmonitored; replies route via Reply-To and the footer contact link."""
        sent = self._send(monkeypatch, notif_app, {'RESEND_FROM_EMAIL': None})
        assert 'noreply@usecampusswap.com' in sent['from']

    def test_every_email_links_to_the_contact_page(self, monkeypatch, notif_app):
        """From is unmonitored, so there must always be a working route to a human."""
        sent = self._send(monkeypatch, notif_app, {'RESEND_FROM_EMAIL': None})
        assert '/contact' in sent['html']
        assert 'Need help with your order?' in sent['html']

    def test_contact_link_also_in_plain_text_part(self, monkeypatch, notif_app):
        """html_to_text runs on unwrapped content, so the link must be appended separately."""
        sent = self._send(monkeypatch, notif_app, {'RESEND_FROM_EMAIL': None})
        assert '/contact' in sent['text']

    def test_both_are_env_overridable(self, monkeypatch, notif_app):
        sent = self._send(monkeypatch, notif_app, {
            'RESEND_FROM_EMAIL': 'Campus Swap <bots@usecampusswap.com>',
            'RESEND_REPLY_TO': 'support@usecampusswap.com',
        })
        assert sent['from'] == 'Campus Swap <bots@usecampusswap.com>'
        assert sent['reply_to'] == 'support@usecampusswap.com'

    def test_blank_reply_to_omits_the_field(self, monkeypatch, notif_app):
        sent = self._send(monkeypatch, notif_app, {'RESEND_REPLY_TO': ''})
        assert 'reply_to' not in sent

    def test_explicit_from_email_still_wins(self, monkeypatch, notif_app):
        import app as app_module
        captured = {}
        monkeypatch.setattr(app_module.resend, 'api_key', 'test-key')
        monkeypatch.setattr(app_module, '_resend_send_throttled',
                            lambda data, **kw: captured.update(data))
        with notif_app.test_request_context('/'):
            app_module.send_email('buyer@example.com', 'Test', '<p>hi</p>',
                                  from_email='Campus Swap <alerts@usecampusswap.com>')
        assert captured['from'] == 'Campus Swap <alerts@usecampusswap.com>'


# ---------------------------------------------------------------------------
# Ops delivery card must keep showing the route while the run is live
# ---------------------------------------------------------------------------

class TestOpsDeliveryCardDuringRun:
    """The stop list used to be in the {% else %} of `if card.delivery_live`, so
    starting a run replaced the whole route with a one-line progress summary."""

    def _login_admin(self, client, notif_app):
        from models import User
        with notif_app.app_context():
            aid = User.query.filter_by(is_super_admin=True).first().id
        with client.session_transaction() as sess:
            sess['_user_id'] = str(aid)
            sess['_fresh'] = True

    def _get_ops(self, notif_app, shift_id):
        notif_app.config['WTF_CSRF_ENABLED'] = False
        with notif_app.test_client() as c:
            self._login_admin(c, notif_app)
            r = c.get(f'/admin/ops?shift_id={shift_id}')
            assert r.status_code == 200, r.status_code
            return r.get_data(as_text=True)

    def test_stops_visible_before_and_during_the_run(self, notif_app, delivery_fixtures):
        from app import db, _now_eastern
        from models import DeliveryRun, DeliveryStop

        shift_id = delivery_fixtures['shift_id']

        before = self._get_ops(notif_app, shift_id)
        assert 'maps/dir/?api=1' in before, 'pre-run card should offer directions'
        pre_rows = before.count('class="stop-row"')
        assert pre_rows >= 4, f'expected the 4 fixture stops pre-run, saw {pre_rows}'

        with notif_app.app_context():
            from models import User
            aid = User.query.filter_by(is_super_admin=True).first().id
            db.session.add(DeliveryRun(shift_id=shift_id, status='in_progress',
                                       started_at=_now_eastern().replace(tzinfo=None),
                                       started_by_id=aid))
            db.session.commit()
        db.session.expire_all()
        try:
            during = self._get_ops(notif_app, shift_id)
            assert during.count('class="stop-row"') == pre_rows, \
                'starting the run must not hide the stop list'
            assert 'delivered' in during, 'progress summary should still render'
            assert 'maps/dir/?api=1' in during, 'directions must survive the run starting'
        finally:
            with notif_app.app_context():
                db.session.execute(db.delete(DeliveryRun).where(DeliveryRun.shift_id == shift_id))
                db.session.commit()

    def test_stop_rows_show_an_item_photo(self, notif_app, delivery_fixtures):
        """Ops needs to see which physical item is going on the truck."""
        body = self._get_ops(notif_app, delivery_fixtures['shift_id'])
        rows = body.count('class="stop-row"')
        thumbs = body.count('stop-thumb-sm')
        # every row gets either a photo or an explicit placeholder
        assert thumbs >= rows, f'{rows} stop rows but only {thumbs} thumbnails'
        assert 'loading="lazy"' in body or 'stop-thumb-sm placeholder' in body

    def test_completed_and_issue_stops_show_their_state(self, notif_app, delivery_fixtures):
        from app import db, _now_eastern
        from models import DeliveryRun, DeliveryStop

        shift_id = delivery_fixtures['shift_id']
        with notif_app.app_context():
            from models import User
            aid = User.query.filter_by(is_super_admin=True).first().id
            db.session.add(DeliveryRun(shift_id=shift_id, status='in_progress',
                                       started_at=_now_eastern().replace(tzinfo=None),
                                       started_by_id=aid))
            stops = DeliveryStop.query.filter_by(shift_id=shift_id).order_by(DeliveryStop.id).all()
            stops[0].status = 'completed'
            stops[0].completed_at = _now_eastern().replace(tzinfo=None)
            stops[1].status = 'issue'
            stops[1].notes = 'Buyer not home'
            db.session.commit()
        # expire_on_commit=False is set on this session, and the test-client request
        # reuses the fixture's still-pushed app context — and therefore its session.
        # Expire on THAT session (outside the inner context) or the page renders
        # stale 'pending' rows.
        db.session.expire_all()
        try:
            body = self._get_ops(notif_app, shift_id)
            assert 'stop-num-circle completed' in body
            assert 'stop-num-circle issue' in body
            assert 'Buyer not home' in body, 'issue notes should be visible to ops'
        finally:
            with notif_app.app_context():
                db.session.execute(db.delete(DeliveryRun).where(DeliveryRun.shift_id == shift_id))
                db.session.commit()


# ---------------------------------------------------------------------------
# No email may tell a customer to reply or write to a bare mailbox
# ---------------------------------------------------------------------------

class TestNoReplyToEmailCopy:
    """Mail is sent from an unmonitored noreply@, and team@/hello@ were both
    non-existent mailboxes that hard-bounced every customer message. Support
    routing must go through the contact form."""

    def test_no_source_tells_customers_to_reply(self):
        import re
        src = open('app.py').read()
        offenders = re.findall(r'.{0,60}[Rr]eply to this email.{0,40}', src)
        # The only permitted mentions are explanatory code comments
        real = [o for o in offenders if not o.lstrip().startswith('#')
                and 'hard-bounced' not in o and 'unmonitored' not in o]
        assert not real, f'email copy still tells customers to reply: {real}'

    def test_no_dead_mailbox_links_anywhere(self):
        import glob
        import re
        bad = []
        for path in ['app.py'] + glob.glob('templates/**/*.html', recursive=True):
            src = open(path).read()
            if 'mailto:hello@usecampusswap.com' in src:
                bad.append(path)
        assert not bad, f'hello@usecampusswap.com does not exist; dead links in: {bad}'

    def test_contact_url_points_at_the_form(self, notif_app):
        from app import _contact_url, _contact_link
        with notif_app.test_request_context('/'):
            assert _contact_url().endswith('/contact')
            assert '/contact' in _contact_link()
            assert 'Contact our team' in _contact_link()

    def test_buyer_emails_route_support_to_the_contact_form(self, monkeypatch, notif_app,
                                                           delivery_fixtures):
        import re
        import app as app_module
        from models import DeliveryStop

        captured = []
        monkeypatch.setattr(app_module, '_resend_send_throttled',
                            lambda d, **kw: captured.append(dict(d)))
        monkeypatch.setattr(app_module.resend, 'api_key', 'test-key')
        monkeypatch.setenv('SUPPRESS_EMAILS', '0')

        with notif_app.test_request_context('/'):
            stops = DeliveryStop.query.filter_by(shift_id=delivery_fixtures['shift_id']).all()
            app_module._send_delivery_scheduled_email(stops[:3])

        assert captured, 'no email captured'
        html = captured[0]['html']
        assert not re.search(r'[Rr]eply to this email', html)
        assert 'mailto:' not in html
        assert '/contact' in html


class TestCrewSeesBuyerContact:
    def test_macro_shows_buyer_name_and_phone(self):
        src = open('templates/crew/_delivery_stop_card.html').read()
        assert 'buyer_name' in src, 'driver needs the buyer name at the door'
        assert 'href="tel:{{ buyer_phone }}"' in src
        assert 'No phone on file' in src, 'absence of a phone must be explicit, not blank'

    def test_phone_falls_back_from_line_item_to_parent_order(self):
        src = open('templates/crew/_delivery_stop_card.html').read()
        assert 'order.buyer_phone or (order.order.buyer_phone' in src


class TestAdminSetBuyerPhone:
    def _client(self, notif_app):
        from models import User
        notif_app.config['WTF_CSRF_ENABLED'] = False
        c = notif_app.test_client()
        with notif_app.app_context():
            aid = User.query.filter_by(is_super_admin=True).first().id
        with c.session_transaction() as sess:
            sess['_user_id'] = str(aid)
            sess['_fresh'] = True
        return c

    def test_sets_phone_on_order_and_every_line_item(self, notif_app, delivery_fixtures):
        from app import db
        from models import BuyerOrder, DeliveryStop

        with notif_app.app_context():
            stop = DeliveryStop.query.get(delivery_fixtures['cart_stop_ids'][0])
            bo_id, order_id = stop.buyer_order_id, stop.buyer_order.order_id

        c = self._client(notif_app)
        r = c.post(f'/admin/delivery/order/{bo_id}/phone', data={'phone': '916-599-8646'})
        assert r.status_code == 200
        assert r.get_json()['phone'] == '(916) 599-8646'

        with notif_app.app_context():
            db.session.expire_all()
            siblings = BuyerOrder.query.filter_by(order_id=order_id).all()
            assert len(siblings) == 3
            assert all(b.buyer_phone == '(916) 599-8646' for b in siblings), \
                'all line items in the order must agree'
            assert siblings[0].order.buyer_phone == '(916) 599-8646'

    def test_normalizes_common_formats(self, notif_app, delivery_fixtures):
        from models import DeliveryStop
        with notif_app.app_context():
            bo_id = DeliveryStop.query.get(delivery_fixtures['cart_stop_ids'][0]).buyer_order_id
        c = self._client(notif_app)
        for raw in ['(916) 599-8646', '9165998646', '+1 916 599 8646', '916.599.8646']:
            r = c.post(f'/admin/delivery/order/{bo_id}/phone', data={'phone': raw})
            assert r.get_json()['phone'] == '(916) 599-8646', raw

    def test_rejects_invalid_number(self, notif_app, delivery_fixtures):
        from models import DeliveryStop
        with notif_app.app_context():
            bo_id = DeliveryStop.query.get(delivery_fixtures['cart_stop_ids'][0]).buyer_order_id
        c = self._client(notif_app)
        r = c.post(f'/admin/delivery/order/{bo_id}/phone', data={'phone': '12345'})
        assert r.status_code == 400
        assert 'valid 10-digit' in r.get_json()['error']

    def test_empty_submit_clears_the_phone(self, notif_app, delivery_fixtures):
        from app import db
        from models import BuyerOrder, DeliveryStop
        with notif_app.app_context():
            bo_id = DeliveryStop.query.get(delivery_fixtures['cart_stop_ids'][0]).buyer_order_id
        c = self._client(notif_app)
        c.post(f'/admin/delivery/order/{bo_id}/phone', data={'phone': '9165998646'})
        r = c.post(f'/admin/delivery/order/{bo_id}/phone', data={'phone': ''})
        assert r.get_json()['phone'] is None
        with notif_app.app_context():
            db.session.expire_all()
            assert BuyerOrder.query.get(bo_id).buyer_phone is None

    def test_requires_ops_access(self, notif_app, delivery_fixtures):
        from models import DeliveryStop
        with notif_app.app_context():
            bo_id = DeliveryStop.query.get(delivery_fixtures['cart_stop_ids'][0]).buyer_order_id
        notif_app.config['WTF_CSRF_ENABLED'] = False
        with notif_app.test_client() as c:
            with c.session_transaction() as sess:
                sess.clear()
            r = c.post(f'/admin/delivery/order/{bo_id}/phone', data={'phone': '9165998646'})
        assert r.status_code in (302, 401, 403)
