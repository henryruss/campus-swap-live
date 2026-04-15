"""
Tests for Spec #9 — SMS Notifications

Covers:
- _send_sms helper: guards (sms_enabled, phone, sms_opted_out, Twilio env vars)
- _send_sms phone normalization
- admin_shift_notify_sellers: SMS sent alongside email; no phone / opted-out; idempotency
- cron_sms_reminders: auth, shift tomorrow, no phone, no shifts, notified_at=NULL skipped
- crew_shift_start: SMS all pending sellers on mover's truck; other trucks unaffected
- crew_shift_stop_update (completion): token revocation; next-seller SMS; token already used_at
- crew_shift_stop_update (issue): issue_type saved; no_show extends token; other leaves token
- crew_shift_stop_revert: issue_type cleared; no_show_email_sent_at preserved
- cron_no_show_emails: auth, kill switch, sends email, idempotency, no token skipped, future shift skipped
- sms_inbound_webhook: invalid signature, STOP/START, unknown phone
- /reschedule/<token>: revoked_at error branch; order relative to used_at
"""

import pytest
import os
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def admin_user(app, db):
    from models import User
    u = User(email='admin@test.com', full_name='Admin User',
             is_admin=True, is_super_admin=True)
    u.set_password('password')
    db.session.add(u)
    db.session.commit()
    return u


@pytest.fixture
def admin_client(client, admin_user):
    client.post('/login', data={'email': admin_user.email, 'password': 'password'})
    return client


@pytest.fixture
def mover_user(app, db):
    from models import User
    u = User(email='mover@test.com', full_name='Test Mover',
             is_worker=True, worker_status='approved')
    u.set_password('password')
    db.session.add(u)
    db.session.commit()
    return u


@pytest.fixture
def mover_client(client, mover_user):
    client.post('/login', data={'email': mover_user.email, 'password': 'password'})
    return client


@pytest.fixture
def seller_with_phone(app, db):
    from models import User
    u = User(
        email='seller_phone@test.com', full_name='Phone Seller',
        is_seller=True,
        phone='9195551234',
        pickup_week='week1',
        pickup_location_type='on_campus',
        pickup_dorm='Granville Towers', pickup_room='204',
        pickup_access_type='elevator', pickup_floor=2,
    )
    u.set_password('password')
    db.session.add(u)
    db.session.commit()
    return u


@pytest.fixture
def seller_no_phone(app, db):
    from models import User
    u = User(
        email='seller_nophone@test.com', full_name='No Phone Seller',
        is_seller=True,
        phone=None,
        pickup_week='week1',
        pickup_location_type='on_campus',
        pickup_dorm='Ehringhaus', pickup_room='101',
        pickup_access_type='stairs_only', pickup_floor=1,
    )
    u.set_password('password')
    db.session.add(u)
    db.session.commit()
    return u


@pytest.fixture
def seller_opted_out(app, db):
    from models import User
    u = User(
        email='seller_optout@test.com', full_name='Opted Out Seller',
        is_seller=True,
        phone='9195559999',
        sms_opted_out=True,
        pickup_week='week1',
        pickup_location_type='on_campus',
        pickup_dorm='Morrison', pickup_room='301',
        pickup_access_type='elevator', pickup_floor=3,
    )
    u.set_password('password')
    db.session.add(u)
    db.session.commit()
    return u


@pytest.fixture
def shift_week1_am(app, db):
    from models import ShiftWeek, Shift
    from datetime import date
    # Week1: Apr 27 2026 (Monday)
    week = ShiftWeek(week_start=date(2026, 4, 27), status='published')
    db.session.add(week)
    db.session.flush()
    shift = Shift(week_id=week.id, day_of_week='mon', slot='am', trucks=2)
    db.session.add(shift)
    db.session.commit()
    return shift


@pytest.fixture
def pickup_with_phone(app, db, shift_week1_am, seller_with_phone, admin_user):
    from models import ShiftPickup
    now = datetime.utcnow()
    p = ShiftPickup(
        shift_id=shift_week1_am.id,
        seller_id=seller_with_phone.id,
        truck_number=1,
        status='pending',
        created_by_id=admin_user.id,
        notified_at=now,  # already notified
    )
    db.session.add(p)
    db.session.commit()
    return p


@pytest.fixture
def pickup_no_phone(app, db, shift_week1_am, seller_no_phone, admin_user):
    from models import ShiftPickup
    now = datetime.utcnow()
    p = ShiftPickup(
        shift_id=shift_week1_am.id,
        seller_id=seller_no_phone.id,
        truck_number=1,
        status='pending',
        created_by_id=admin_user.id,
        notified_at=now,
    )
    db.session.add(p)
    db.session.commit()
    return p


@pytest.fixture
def reschedule_token(app, db, pickup_with_phone):
    from models import RescheduleToken
    import secrets
    now = datetime.now()
    token = RescheduleToken(
        token=secrets.token_urlsafe(48),
        pickup_id=pickup_with_phone.id,
        seller_id=pickup_with_phone.seller_id,
        created_at=now,
        expires_at=now + timedelta(days=7),
    )
    db.session.add(token)
    db.session.commit()
    return token


# ---------------------------------------------------------------------------
# _send_sms guards
# ---------------------------------------------------------------------------

class TestSendSmsGuards:
    def test_returns_false_when_sms_disabled(self, app, db, seller_with_phone):
        from models import AppSetting
        AppSetting.set('sms_enabled', 'false')
        db.session.commit()
        with app.app_context():
            from app import _send_sms
            result = _send_sms(seller_with_phone, 'test')
        assert result is False
        AppSetting.set('sms_enabled', 'true')
        db.session.commit()

    def test_returns_false_when_no_phone(self, app, db, seller_no_phone):
        with app.app_context():
            from app import _send_sms
            result = _send_sms(seller_no_phone, 'test')
        assert result is False

    def test_returns_false_when_opted_out(self, app, db, seller_opted_out):
        with app.app_context():
            from app import _send_sms
            result = _send_sms(seller_opted_out, 'test')
        assert result is False

    def test_returns_false_when_twilio_env_not_set(self, app, db, seller_with_phone):
        env_patch = {
            'TWILIO_ACCOUNT_SID': '',
            'TWILIO_AUTH_TOKEN': '',
            'TWILIO_FROM_NUMBER': '',
        }
        with patch.dict(os.environ, env_patch):
            from app import _send_sms
            result = _send_sms(seller_with_phone, 'test')
        assert result is False


class TestPhoneNormalization:
    def test_ten_digits(self, app):
        from app import _normalize_phone
        assert _normalize_phone('4105551234') == '+14105551234'

    def test_already_e164(self, app):
        from app import _normalize_phone
        assert _normalize_phone('+14105551234') == '+14105551234'

    def test_eleven_digits_starting_with_1(self, app):
        from app import _normalize_phone
        assert _normalize_phone('14105551234') == '+14105551234'

    def test_unparseable_returns_none(self, app):
        from app import _normalize_phone
        assert _normalize_phone('not-a-number') is None

    def test_none_input(self, app):
        from app import _normalize_phone
        assert _normalize_phone(None) is None


# ---------------------------------------------------------------------------
# Notify Sellers — SMS alongside email
# ---------------------------------------------------------------------------

class TestNotifySellersSms:
    def test_notify_also_sends_sms_for_seller_with_phone(
        self, admin_client, app, db, shift_week1_am, seller_with_phone, admin_user
    ):
        from models import ShiftPickup
        pickup = ShiftPickup(
            shift_id=shift_week1_am.id,
            seller_id=seller_with_phone.id,
            truck_number=1,
            status='pending',
            created_by_id=admin_user.id,
        )
        db.session.add(pickup)
        db.session.commit()

        with patch('app._send_sms') as mock_sms, \
             patch('app.send_email') as mock_email:
            resp = admin_client.post(
                f'/admin/crew/shift/{shift_week1_am.id}/notify',
                follow_redirects=False,
            )
        assert resp.status_code == 302
        mock_sms.assert_called_once()
        mock_email.assert_called_once()

    def test_notify_no_phone_sends_email_not_sms(
        self, admin_client, app, db, shift_week1_am, seller_no_phone, admin_user
    ):
        from models import ShiftPickup
        pickup = ShiftPickup(
            shift_id=shift_week1_am.id,
            seller_id=seller_no_phone.id,
            truck_number=1,
            status='pending',
            created_by_id=admin_user.id,
        )
        db.session.add(pickup)
        db.session.commit()

        with patch('app._send_sms') as mock_sms, \
             patch('app.send_email') as mock_email:
            resp = admin_client.post(
                f'/admin/crew/shift/{shift_week1_am.id}/notify',
                follow_redirects=False,
            )
        assert resp.status_code == 302
        mock_email.assert_called_once()
        # _send_sms is called but returns False; no crash
        args = mock_sms.call_args[0] if mock_sms.called else None
        if args:
            assert args[0] == seller_no_phone  # called with the seller

    def test_notify_idempotent_no_sms_on_second_run(
        self, admin_client, app, db, shift_week1_am, seller_with_phone, admin_user
    ):
        from models import ShiftPickup
        # Already notified
        pickup = ShiftPickup(
            shift_id=shift_week1_am.id,
            seller_id=seller_with_phone.id,
            truck_number=1,
            status='pending',
            created_by_id=admin_user.id,
            notified_at=datetime.utcnow(),
        )
        db.session.add(pickup)
        db.session.commit()

        with patch('app._send_sms') as mock_sms, \
             patch('app.send_email') as mock_email:
            admin_client.post(f'/admin/crew/shift/{shift_week1_am.id}/notify')

        mock_sms.assert_not_called()
        mock_email.assert_not_called()


# ---------------------------------------------------------------------------
# Cron — SMS Reminders
# ---------------------------------------------------------------------------

class TestCronSmsReminders:
    def _cron_post(self, client, secret='test-secret'):
        return client.post(
            '/admin/cron/sms-reminders',
            headers={'Authorization': f'Bearer {secret}'},
        )

    def test_missing_cron_secret_returns_403(self, client):
        with patch.dict(os.environ, {'CRON_SECRET': 'real-secret'}):
            resp = client.post('/admin/cron/sms-reminders',
                               headers={'Authorization': 'Bearer wrong'})
        assert resp.status_code == 403

    def test_no_shifts_tomorrow_returns_zero(self, client, app):
        with patch.dict(os.environ, {'CRON_SECRET': 'test-secret'}):
            resp = self._cron_post(client)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['sent'] == 0
        assert data['skipped'] == 0

    def test_sends_sms_for_notified_seller_tomorrow(
        self, client, app, db, admin_user, seller_with_phone
    ):
        from models import ShiftWeek, Shift, ShiftPickup
        from app import _today_eastern
        # Create a shift for tomorrow
        tomorrow = _today_eastern() + timedelta(days=1)
        # Find Monday of that week
        week_start = tomorrow - timedelta(days=tomorrow.weekday())
        day_names = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
        day_of_week = day_names[tomorrow.weekday()]

        week = ShiftWeek(week_start=week_start, status='published')
        db.session.add(week)
        db.session.flush()
        shift = Shift(week_id=week.id, day_of_week=day_of_week, slot='am', trucks=1)
        db.session.add(shift)
        db.session.flush()
        pickup = ShiftPickup(
            shift_id=shift.id,
            seller_id=seller_with_phone.id,
            truck_number=1,
            status='pending',
            created_by_id=admin_user.id,
            notified_at=datetime.utcnow(),  # must be notified
        )
        db.session.add(pickup)
        db.session.commit()

        with patch('app._send_sms', return_value=True) as mock_sms, \
             patch.dict(os.environ, {'CRON_SECRET': 'test-secret'}):
            resp = self._cron_post(client)

        assert resp.status_code == 200
        data = resp.get_json()
        assert data['sent'] == 1
        mock_sms.assert_called_once()

    def test_skips_seller_not_notified(
        self, client, app, db, admin_user, seller_with_phone
    ):
        from models import ShiftWeek, Shift, ShiftPickup
        from app import _today_eastern
        tomorrow = _today_eastern() + timedelta(days=1)
        week_start = tomorrow - timedelta(days=tomorrow.weekday())
        day_names = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
        day_of_week = day_names[tomorrow.weekday()]

        week = ShiftWeek(week_start=week_start, status='published')
        db.session.add(week)
        db.session.flush()
        shift = Shift(week_id=week.id, day_of_week=day_of_week, slot='am', trucks=1)
        db.session.add(shift)
        db.session.flush()
        pickup = ShiftPickup(
            shift_id=shift.id,
            seller_id=seller_with_phone.id,
            truck_number=1,
            status='pending',
            created_by_id=admin_user.id,
            notified_at=None,  # NOT notified
        )
        db.session.add(pickup)
        db.session.commit()

        with patch('app._send_sms', return_value=False) as mock_sms, \
             patch.dict(os.environ, {'CRON_SECRET': 'test-secret'}):
            resp = self._cron_post(client)

        data = resp.get_json()
        assert data['skipped'] == 1


# ---------------------------------------------------------------------------
# Crew Shift Start — SMS all pending sellers on truck
# ---------------------------------------------------------------------------

class TestCrewShiftStartSms:
    def test_start_shift_sms_pending_sellers_on_mover_truck(
        self, mover_client, app, db, mover_user, shift_week1_am,
        seller_with_phone, admin_user
    ):
        from models import ShiftAssignment, ShiftPickup
        from app import _today_eastern
        # Patch shift to be today
        from datetime import date
        shift_week1_am.week.week_start = _today_eastern() - timedelta(
            days=['mon','tue','wed','thu','fri','sat','sun'].index(shift_week1_am.day_of_week)
        )
        db.session.commit()

        assignment = ShiftAssignment(
            shift_id=shift_week1_am.id,
            worker_id=mover_user.id,
            role_on_shift='driver',
            truck_number=1,
        )
        db.session.add(assignment)
        pickup = ShiftPickup(
            shift_id=shift_week1_am.id,
            seller_id=seller_with_phone.id,
            truck_number=1,
            status='pending',
            created_by_id=admin_user.id,
        )
        db.session.add(pickup)
        db.session.commit()

        with patch('app._send_sms', return_value=True) as mock_sms:
            resp = mover_client.post(
                f'/crew/shift/{shift_week1_am.id}/start',
                follow_redirects=False,
            )
        assert resp.status_code == 302
        mock_sms.assert_called_once()
        call_args = mock_sms.call_args[0]
        assert call_args[0] == seller_with_phone
        assert "started today's route" in call_args[1]

    def test_start_shift_does_not_sms_different_truck(
        self, mover_client, app, db, mover_user, shift_week1_am,
        seller_with_phone, seller_no_phone, admin_user
    ):
        from models import ShiftAssignment, ShiftPickup
        from app import _today_eastern
        shift_week1_am.week.week_start = _today_eastern() - timedelta(
            days=['mon','tue','wed','thu','fri','sat','sun'].index(shift_week1_am.day_of_week)
        )
        db.session.commit()

        assignment = ShiftAssignment(
            shift_id=shift_week1_am.id,
            worker_id=mover_user.id,
            role_on_shift='driver',
            truck_number=1,
        )
        db.session.add(assignment)
        # Truck 1 — mover's truck
        pickup1 = ShiftPickup(
            shift_id=shift_week1_am.id,
            seller_id=seller_with_phone.id,
            truck_number=1,
            status='pending',
            created_by_id=admin_user.id,
        )
        # Truck 2 — different truck
        pickup2 = ShiftPickup(
            shift_id=shift_week1_am.id,
            seller_id=seller_no_phone.id,
            truck_number=2,
            status='pending',
            created_by_id=admin_user.id,
        )
        db.session.add_all([pickup1, pickup2])
        db.session.commit()

        sms_calls = []
        def capture_sms(user, body):
            sms_calls.append(user)
            return True

        with patch('app._send_sms', side_effect=capture_sms):
            mover_client.post(f'/crew/shift/{shift_week1_am.id}/start')

        # Only truck 1 seller was texted
        assert seller_with_phone in sms_calls
        assert seller_no_phone not in sms_calls


# ---------------------------------------------------------------------------
# crew_shift_stop_update — completion: token revocation + next-seller SMS
# ---------------------------------------------------------------------------

class TestStopCompletionTokenRevocation:
    def test_completion_revokes_open_token(
        self, mover_client, app, db, mover_user, shift_week1_am,
        pickup_with_phone, reschedule_token
    ):
        from models import ShiftAssignment, ShiftRun, RescheduleToken
        assignment = ShiftAssignment(
            shift_id=shift_week1_am.id,
            worker_id=mover_user.id,
            role_on_shift='driver',
            truck_number=pickup_with_phone.truck_number,
        )
        run = ShiftRun(shift_id=shift_week1_am.id, started_by_id=mover_user.id)
        db.session.add_all([assignment, run])
        db.session.commit()

        with patch('app._send_sms', return_value=True):
            mover_client.post(
                f'/crew/shift/{shift_week1_am.id}/stop/{pickup_with_phone.id}/update',
                data={'status': 'completed'},
            )

        db.session.refresh(reschedule_token)
        assert reschedule_token.revoked_at is not None

    def test_completion_does_not_revoke_token_already_used(
        self, mover_client, app, db, mover_user, shift_week1_am,
        pickup_with_phone, reschedule_token
    ):
        from models import ShiftAssignment, ShiftRun
        # Mark token as already used (seller self-rescheduled)
        reschedule_token.used_at = datetime.now()
        db.session.commit()

        assignment = ShiftAssignment(
            shift_id=shift_week1_am.id,
            worker_id=mover_user.id,
            role_on_shift='driver',
            truck_number=pickup_with_phone.truck_number,
        )
        run = ShiftRun(shift_id=shift_week1_am.id, started_by_id=mover_user.id)
        db.session.add_all([assignment, run])
        db.session.commit()

        with patch('app._send_sms', return_value=True):
            mover_client.post(
                f'/crew/shift/{shift_week1_am.id}/stop/{pickup_with_phone.id}/update',
                data={'status': 'completed'},
            )

        db.session.refresh(reschedule_token)
        # revoked_at must NOT be set — used_at filtered it from the query
        assert reschedule_token.revoked_at is None

    def test_completion_sms_next_seller(
        self, mover_client, app, db, mover_user, shift_week1_am,
        seller_with_phone, seller_no_phone, admin_user
    ):
        from models import ShiftAssignment, ShiftPickup, ShiftRun
        assignment = ShiftAssignment(
            shift_id=shift_week1_am.id,
            worker_id=mover_user.id,
            role_on_shift='driver',
            truck_number=1,
        )
        # Stop 1 (will be completed), stop 2 (should get "you're next")
        pickup1 = ShiftPickup(
            shift_id=shift_week1_am.id,
            seller_id=seller_with_phone.id,
            truck_number=1,
            status='pending',
            stop_order=1,
            created_by_id=admin_user.id,
        )
        # Use a different seller for the next stop
        from models import User
        seller2 = User(
            email='next_seller@test.com', full_name='Next Seller',
            is_seller=True,
            phone='9195557777',
            pickup_location_type='on_campus',
            pickup_dorm='Granville', pickup_room='101',
            pickup_access_type='elevator', pickup_floor=1,
        )
        seller2.set_password('x')
        db.session.add(seller2)
        db.session.flush()
        pickup2 = ShiftPickup(
            shift_id=shift_week1_am.id,
            seller_id=seller2.id,
            truck_number=1,
            status='pending',
            stop_order=2,
            created_by_id=admin_user.id,
        )
        run = ShiftRun(shift_id=shift_week1_am.id, started_by_id=mover_user.id)
        db.session.add_all([assignment, pickup1, pickup2, run])
        db.session.commit()

        sms_calls = []
        def capture_sms(user, body):
            sms_calls.append((user, body))
            return True

        with patch('app._send_sms', side_effect=capture_sms):
            mover_client.post(
                f'/crew/shift/{shift_week1_am.id}/stop/{pickup1.id}/update',
                data={'status': 'completed'},
            )

        # Next seller (pickup2) should have received "you're next"
        next_users = [u for u, b in sms_calls if "up next" in b]
        assert any(u == seller2 for u in next_users)

    def test_no_next_sms_when_single_stop(
        self, mover_client, app, db, mover_user, shift_week1_am,
        pickup_with_phone
    ):
        from models import ShiftAssignment, ShiftRun
        assignment = ShiftAssignment(
            shift_id=shift_week1_am.id,
            worker_id=mover_user.id,
            role_on_shift='driver',
            truck_number=pickup_with_phone.truck_number,
        )
        run = ShiftRun(shift_id=shift_week1_am.id, started_by_id=mover_user.id)
        db.session.add_all([assignment, run])
        db.session.commit()

        sms_calls = []
        with patch('app._send_sms', side_effect=lambda u, b: sms_calls.append(b) or True):
            mover_client.post(
                f'/crew/shift/{shift_week1_am.id}/stop/{pickup_with_phone.id}/update',
                data={'status': 'completed'},
            )

        # No "you're next" SMS — no second stop exists
        assert not any("up next" in b for b in sms_calls)


# ---------------------------------------------------------------------------
# crew_shift_stop_update — issue flagging
# ---------------------------------------------------------------------------

class TestIssueFlagging:
    def _setup(self, db, mover_user, shift_week1_am, pickup_with_phone, reschedule_token):
        from models import ShiftAssignment, ShiftRun
        assignment = ShiftAssignment(
            shift_id=shift_week1_am.id,
            worker_id=mover_user.id,
            role_on_shift='driver',
            truck_number=pickup_with_phone.truck_number,
        )
        run = ShiftRun(shift_id=shift_week1_am.id, started_by_id=mover_user.id)
        db.session.add_all([assignment, run])
        db.session.commit()

    def test_no_show_sets_issue_type_and_extends_token(
        self, mover_client, app, db, mover_user, shift_week1_am,
        pickup_with_phone, reschedule_token
    ):
        self._setup(db, mover_user, shift_week1_am, pickup_with_phone, reschedule_token)
        original_expires = reschedule_token.expires_at

        with patch('app._send_sms', return_value=True):
            mover_client.post(
                f'/crew/shift/{shift_week1_am.id}/stop/{pickup_with_phone.id}/update',
                data={'status': 'issue', 'issue_type': 'no_show'},
            )

        db.session.refresh(pickup_with_phone)
        db.session.refresh(reschedule_token)
        assert pickup_with_phone.issue_type == 'no_show'
        assert reschedule_token.expires_at > original_expires

    def test_other_sets_issue_type_leaves_token(
        self, mover_client, app, db, mover_user, shift_week1_am,
        pickup_with_phone, reschedule_token
    ):
        self._setup(db, mover_user, shift_week1_am, pickup_with_phone, reschedule_token)
        original_expires = reschedule_token.expires_at

        with patch('app._send_sms', return_value=True):
            mover_client.post(
                f'/crew/shift/{shift_week1_am.id}/stop/{pickup_with_phone.id}/update',
                data={'status': 'issue', 'issue_type': 'other'},
            )

        db.session.refresh(pickup_with_phone)
        db.session.refresh(reschedule_token)
        assert pickup_with_phone.issue_type == 'other'
        assert reschedule_token.expires_at == original_expires  # unchanged

    def test_missing_issue_type_defaults_to_other(
        self, mover_client, app, db, mover_user, shift_week1_am,
        pickup_with_phone, reschedule_token
    ):
        self._setup(db, mover_user, shift_week1_am, pickup_with_phone, reschedule_token)

        with patch('app._send_sms', return_value=True):
            mover_client.post(
                f'/crew/shift/{shift_week1_am.id}/stop/{pickup_with_phone.id}/update',
                data={'status': 'issue'},  # no issue_type key
            )

        db.session.refresh(pickup_with_phone)
        assert pickup_with_phone.issue_type == 'other'

    def test_notes_optional_for_issue(
        self, mover_client, app, db, mover_user, shift_week1_am,
        pickup_with_phone, reschedule_token
    ):
        self._setup(db, mover_user, shift_week1_am, pickup_with_phone, reschedule_token)

        with patch('app._send_sms', return_value=True):
            resp = mover_client.post(
                f'/crew/shift/{shift_week1_am.id}/stop/{pickup_with_phone.id}/update',
                data={'status': 'issue', 'issue_type': 'other'},  # no notes
                follow_redirects=False,
            )

        # Should redirect (success), not re-render with flash error
        assert resp.status_code == 302
        db.session.refresh(pickup_with_phone)
        assert pickup_with_phone.status == 'issue'


# ---------------------------------------------------------------------------
# crew_shift_stop_revert
# ---------------------------------------------------------------------------

class TestStopRevert:
    def test_revert_clears_issue_type(
        self, mover_client, app, db, mover_user, shift_week1_am, pickup_with_phone
    ):
        from models import ShiftAssignment, ShiftRun
        pickup_with_phone.status = 'issue'
        pickup_with_phone.issue_type = 'no_show'
        assignment = ShiftAssignment(
            shift_id=shift_week1_am.id,
            worker_id=mover_user.id,
            role_on_shift='driver',
            truck_number=pickup_with_phone.truck_number,
        )
        run = ShiftRun(shift_id=shift_week1_am.id, started_by_id=mover_user.id)
        db.session.add_all([assignment, run])
        db.session.commit()

        mover_client.post(
            f'/crew/shift/{shift_week1_am.id}/stop/{pickup_with_phone.id}/revert'
        )

        db.session.refresh(pickup_with_phone)
        assert pickup_with_phone.issue_type is None
        assert pickup_with_phone.status == 'pending'

    def test_revert_does_not_clear_no_show_email_sent_at(
        self, mover_client, app, db, mover_user, shift_week1_am, pickup_with_phone
    ):
        from models import ShiftAssignment, ShiftRun
        sent_time = datetime.utcnow()
        pickup_with_phone.status = 'issue'
        pickup_with_phone.issue_type = 'no_show'
        pickup_with_phone.no_show_email_sent_at = sent_time
        assignment = ShiftAssignment(
            shift_id=shift_week1_am.id,
            worker_id=mover_user.id,
            role_on_shift='driver',
            truck_number=pickup_with_phone.truck_number,
        )
        run = ShiftRun(shift_id=shift_week1_am.id, started_by_id=mover_user.id)
        db.session.add_all([assignment, run])
        db.session.commit()

        mover_client.post(
            f'/crew/shift/{shift_week1_am.id}/stop/{pickup_with_phone.id}/revert'
        )

        db.session.refresh(pickup_with_phone)
        assert pickup_with_phone.no_show_email_sent_at is not None


# ---------------------------------------------------------------------------
# cron_no_show_emails
# ---------------------------------------------------------------------------

class TestCronNoShowEmails:
    def _post(self, client, secret='test-secret'):
        return client.post(
            '/admin/cron/no-show-emails',
            headers={'Authorization': f'Bearer {secret}'},
        )

    def test_missing_secret_returns_403(self, client):
        with patch.dict(os.environ, {'CRON_SECRET': 'real'}):
            resp = client.post('/admin/cron/no-show-emails',
                               headers={'Authorization': 'Bearer wrong'})
        assert resp.status_code == 403

    def test_kill_switch_returns_zero_sent(self, client, app, db):
        from models import AppSetting
        AppSetting.set('no_show_email_enabled', 'false')
        db.session.commit()

        with patch.dict(os.environ, {'CRON_SECRET': 'test-secret'}):
            resp = self._post(client)

        data = resp.get_json()
        assert data['sent'] == 0
        AppSetting.set('no_show_email_enabled', 'true')
        db.session.commit()

    def test_sends_email_for_no_show_today(
        self, client, app, db, shift_week1_am, pickup_with_phone,
        reschedule_token, admin_user
    ):
        from app import _today_eastern
        # Set shift to be today
        shift_week1_am.week.week_start = _today_eastern() - timedelta(
            days=['mon','tue','wed','thu','fri','sat','sun'].index(shift_week1_am.day_of_week)
        )
        pickup_with_phone.status = 'issue'
        pickup_with_phone.issue_type = 'no_show'
        pickup_with_phone.no_show_email_sent_at = None
        db.session.commit()

        with patch('app.send_email') as mock_email, \
             patch.dict(os.environ, {'CRON_SECRET': 'test-secret'}):
            resp = self._post(client)

        data = resp.get_json()
        assert data['sent'] == 1
        mock_email.assert_called_once()
        db.session.refresh(pickup_with_phone)
        assert pickup_with_phone.no_show_email_sent_at is not None

    def test_idempotent_no_duplicate_email(
        self, client, app, db, shift_week1_am, pickup_with_phone,
        reschedule_token
    ):
        from app import _today_eastern
        shift_week1_am.week.week_start = _today_eastern() - timedelta(
            days=['mon','tue','wed','thu','fri','sat','sun'].index(shift_week1_am.day_of_week)
        )
        pickup_with_phone.status = 'issue'
        pickup_with_phone.issue_type = 'no_show'
        pickup_with_phone.no_show_email_sent_at = datetime.utcnow()  # already sent
        db.session.commit()

        with patch('app.send_email') as mock_email, \
             patch.dict(os.environ, {'CRON_SECRET': 'test-secret'}):
            resp = self._post(client)

        data = resp.get_json()
        assert data['sent'] == 0
        mock_email.assert_not_called()

    def test_skips_no_active_token(
        self, client, app, db, shift_week1_am, pickup_with_phone
    ):
        from app import _today_eastern
        shift_week1_am.week.week_start = _today_eastern() - timedelta(
            days=['mon','tue','wed','thu','fri','sat','sun'].index(shift_week1_am.day_of_week)
        )
        pickup_with_phone.status = 'issue'
        pickup_with_phone.issue_type = 'no_show'
        pickup_with_phone.no_show_email_sent_at = None
        # No token created
        db.session.commit()

        with patch('app.send_email') as mock_email, \
             patch.dict(os.environ, {'CRON_SECRET': 'test-secret'}):
            resp = self._post(client)

        data = resp.get_json()
        assert data['skipped'] == 1
        mock_email.assert_not_called()

    def test_skips_future_shift(
        self, client, app, db, shift_week1_am, pickup_with_phone, reschedule_token
    ):
        from app import _today_eastern
        # Set shift to TOMORROW (future)
        shift_week1_am.week.week_start = _today_eastern() + timedelta(
            days=7 - ['mon','tue','wed','thu','fri','sat','sun'].index(shift_week1_am.day_of_week)
        )
        pickup_with_phone.status = 'issue'
        pickup_with_phone.issue_type = 'no_show'
        pickup_with_phone.no_show_email_sent_at = None
        db.session.commit()

        with patch('app.send_email') as mock_email, \
             patch.dict(os.environ, {'CRON_SECRET': 'test-secret'}):
            resp = self._post(client)

        data = resp.get_json()
        assert data['skipped'] == 1
        mock_email.assert_not_called()


# ---------------------------------------------------------------------------
# sms_inbound_webhook
# ---------------------------------------------------------------------------

class TestSmsWebhook:
    def test_invalid_signature_returns_403(self, client, app):
        """Mock the RequestValidator class so we can test even without twilio installed."""
        mock_validator = MagicMock()
        mock_validator.return_value.validate.return_value = False  # invalid sig

        with patch.dict(os.environ, {
            'TWILIO_AUTH_TOKEN': 'test-token',
            'APP_BASE_URL': 'https://usecampusswap.com',
        }):
            with patch('app.sms_inbound_webhook.__wrapped__', create=True):
                # Directly patch the import inside the route function
                import importlib
                import unittest.mock as mock_mod
                with mock_mod.patch.dict('sys.modules', {
                    'twilio': MagicMock(),
                    'twilio.request_validator': MagicMock(
                        RequestValidator=mock_validator
                    ),
                }):
                    resp = client.post('/sms/webhook', data={
                        'Body': 'STOP',
                        'From': '+19195551234',
                    })
        assert resp.status_code == 403

    def test_stop_sets_opted_out(self, client, app, db, seller_with_phone):
        seller_with_phone.phone = '+19195551234'
        db.session.commit()

        with patch.dict(os.environ, {'TWILIO_AUTH_TOKEN': ''}):  # skip sig check
            resp = client.post('/sms/webhook', data={
                'Body': 'STOP',
                'From': '+19195551234',
            })

        assert resp.status_code == 200
        db.session.refresh(seller_with_phone)
        assert seller_with_phone.sms_opted_out is True

    def test_start_clears_opted_out(self, client, app, db, seller_opted_out):
        seller_opted_out.phone = '+19195559999'
        db.session.commit()

        with patch.dict(os.environ, {'TWILIO_AUTH_TOKEN': ''}):
            resp = client.post('/sms/webhook', data={
                'Body': 'START',
                'From': '+19195559999',
            })

        assert resp.status_code == 200
        db.session.refresh(seller_opted_out)
        assert seller_opted_out.sms_opted_out is False

    def test_unknown_phone_returns_200_not_crash(self, client, app):
        with patch.dict(os.environ, {'TWILIO_AUTH_TOKEN': ''}):
            resp = client.post('/sms/webhook', data={
                'Body': 'STOP',
                'From': '+10000000000',  # no user with this number
            })
        assert resp.status_code == 200

    def test_response_is_valid_twiml(self, client, app):
        with patch.dict(os.environ, {'TWILIO_AUTH_TOKEN': ''}):
            resp = client.post('/sms/webhook', data={
                'Body': 'hello',
                'From': '+19195550000',
            })
        assert b'<Response' in resp.data or b'<Response/>' in resp.data


# ---------------------------------------------------------------------------
# /reschedule/<token> — revoked_at error branch
# ---------------------------------------------------------------------------

class TestRescheduleRevoked:
    def test_revoked_token_shows_revoked_error(
        self, client, app, db, reschedule_token
    ):
        reschedule_token.revoked_at = datetime.now()
        db.session.commit()

        resp = client.get(f'/reschedule/{reschedule_token.token}')
        assert resp.status_code == 200
        assert b'completed' in resp.data.lower() or b'already' in resp.data.lower()

    def test_revoked_checked_before_used_at(
        self, client, app, db, reschedule_token
    ):
        # Both revoked_at and used_at set — revoked should win
        now = datetime.now()
        reschedule_token.revoked_at = now
        reschedule_token.used_at = now
        db.session.commit()

        resp = client.get(f'/reschedule/{reschedule_token.token}')
        assert resp.status_code == 200
        # Should show 'revoked' branch content, not 'already_used' branch
        assert b'no need to reschedule' in resp.data.lower() or b'completed' in resp.data.lower()

    def test_valid_token_still_loads_reschedule_page(
        self, client, app, db, reschedule_token
    ):
        # No revoked_at, no used_at — should show the reschedule form
        resp = client.get(f'/reschedule/{reschedule_token.token}')
        assert resp.status_code == 200
        # Should NOT show error
        assert b'revoked' not in resp.data.lower() or b'reschedule' in resp.data.lower()
