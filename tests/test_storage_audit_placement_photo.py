"""
Tests for:
  - Storage Audit Tool (/admin/storage/audit)
  - Driver Item Placement Flow (/crew/shift/<id>/placement, /crew/item/<id>/place)
  - Inventory Photo Refresh (/admin/item/<id>/replace_photo)

Routes under test:
  GET  /admin/storage/audit
  GET  /admin/storage/audit/search?q=
  POST /admin/item/<id>/set_location
  GET  /crew/shift/<id>/placement
  POST /crew/item/<id>/place
  POST /crew/item/<id>/not_picked_up
  POST /crew/shift/<id>/end  (confirmed=1 path, with placement guard)
  POST /admin/item/<id>/replace_photo
"""
import io
import json
import pytest
from datetime import datetime, date
from PIL import Image

from app import app as _app, db as _db
from models import (
    User, InventoryItem, StorageLocation, IntakeRecord, ItemPhoto,
    ShiftWeek, Shift, ShiftAssignment, ShiftPickup, ShiftRun, TutorialSession,
)


# ── db fixture ────────────────────────────────────────────────────────────────

@pytest.fixture
def db(client):
    """Expose the SQLAlchemy db instance (shares the test DB set up by client)."""
    with _app.app_context():
        yield _db


# ── shared user fixtures ───────────────────────────────────────────────────────

@pytest.fixture
def admin_user(client):
    with _app.app_context():
        u = User(email="admin@test.edu", full_name="Admin User",
                 is_admin=True, is_super_admin=True)
        u.set_password("password")
        _db.session.add(u)
        _db.session.commit()
        _ = u.id, u.email
        return u


@pytest.fixture
def super_admin(client):
    with _app.app_context():
        u = User(email="superadmin@test.edu", full_name="Super Admin",
                 is_admin=True, is_super_admin=True)
        u.set_password("password")
        _db.session.add(u)
        _db.session.commit()
        _ = u.id, u.email
        return u


@pytest.fixture
def campus_director(client):
    with _app.app_context():
        u = User(email="cd@unc.edu", full_name="Campus Director",
                 is_campus_director=True, is_admin=False, is_super_admin=False)
        u.set_password("password")
        _db.session.add(u)
        _db.session.flush()
        # Completed tutorial so the tutorial_gate before_request doesn't redirect
        ts = TutorialSession(user_id=u.id, step=7,
                             completed_at=datetime.utcnow(), is_retaking=False)
        _db.session.add(ts)
        _db.session.commit()
        _ = u.id, u.email
        return u


@pytest.fixture
def seller(client):
    with _app.app_context():
        u = User(email="seller@test.edu", full_name="Seller User",
                 is_seller=True, has_paid=True)
        u.set_password("password")
        _db.session.add(u)
        _db.session.commit()
        _ = u.id, u.email
        return u


@pytest.fixture
def approved_driver(client):
    with _app.app_context():
        u = User(email="driver@unc.edu", full_name="Test Driver",
                 is_worker=True, worker_status="approved")
        u.set_password("password")
        _db.session.add(u)
        _db.session.commit()
        _ = u.id, u.email
        return u


# ── storage location fixtures ─────────────────────────────────────────────────

@pytest.fixture
def storage_location(client):
    with _app.app_context():
        loc = StorageLocation(name="Unit A", address="123 Main St",
                              is_active=True, is_full=False)
        _db.session.add(loc)
        _db.session.commit()
        _ = loc.id, loc.name
        return loc


@pytest.fixture
def full_storage_location(client):
    with _app.app_context():
        loc = StorageLocation(name="Unit B (Full)", address="456 Main St",
                              is_active=True, is_full=True)
        _db.session.add(loc)
        _db.session.commit()
        _ = loc.id, loc.name
        return loc


@pytest.fixture
def inactive_storage_location(client):
    with _app.app_context():
        loc = StorageLocation(name="Unit C (Inactive)", address="789 Main St",
                              is_active=False, is_full=False)
        _db.session.add(loc)
        _db.session.commit()
        _ = loc.id, loc.name
        return loc


# ── item fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture
def item_with_location(client, seller, storage_location):
    with _app.app_context():
        item = InventoryItem(
            description="Blue Couch",
            seller_id=seller.id,
            status="available",
            storage_location_id=storage_location.id,
            storage_row="back_left",
        )
        _db.session.add(item)
        _db.session.commit()
        _ = item.id, item.description
        return item


@pytest.fixture
def item_without_location(client, seller):
    with _app.app_context():
        item = InventoryItem(
            description="Red Lamp",
            seller_id=seller.id,
            status="available",
        )
        _db.session.add(item)
        _db.session.commit()
        _ = item.id, item.description
        return item


# ── shift fixture ─────────────────────────────────────────────────────────────

@pytest.fixture
def shift_with_driver(client, approved_driver, storage_location):
    """
    Shift with 1 truck, approved_driver assigned, 1 completed stop with 2 items,
    ShiftRun in_progress.
    """
    with _app.app_context():
        week = ShiftWeek(week_start=date(2026, 5, 27), status="published")
        _db.session.add(week)
        _db.session.flush()

        shift = Shift(
            week_id=week.id, day_of_week="tue", slot="am", trucks=1,
            truck_unit_plan=json.dumps({"1": storage_location.id}),
        )
        _db.session.add(shift)
        _db.session.flush()

        assignment = ShiftAssignment(
            shift_id=shift.id, worker_id=approved_driver.id,
            role_on_shift="driver", truck_number=1,
        )
        _db.session.add(assignment)

        stop_seller = User(email="stop_seller@unc.edu", full_name="Stop Seller",
                           is_seller=True)
        stop_seller.set_password("x")
        _db.session.add(stop_seller)
        _db.session.flush()

        pickup = ShiftPickup(
            shift_id=shift.id, seller_id=stop_seller.id, truck_number=1,
            status="completed", storage_location_id=storage_location.id,
            created_by_id=approved_driver.id,
        )
        _db.session.add(pickup)
        _db.session.flush()

        item1 = InventoryItem(description="Desk Chair", seller_id=stop_seller.id,
                              status="available", picked_up_at=datetime.utcnow())
        item2 = InventoryItem(description="Floor Lamp", seller_id=stop_seller.id,
                              status="available", picked_up_at=datetime.utcnow())
        _db.session.add_all([item1, item2])
        _db.session.flush()

        run = ShiftRun(shift_id=shift.id, started_by_id=approved_driver.id,
                       started_at=datetime.utcnow(), status="in_progress")
        _db.session.add(run)
        _db.session.commit()

        ids = {
            "shift_id": shift.id,
            "assignment_id": assignment.id,
            "pickup_id": pickup.id,
            "stop_seller_id": stop_seller.id,
            "item1_id": item1.id,
            "item2_id": item2.id,
            "run_id": run.id,
        }
        return ids


# ─────────────────────────────────────────────────────────────────────────────
# Part 1: Storage Audit Tool
# ─────────────────────────────────────────────────────────────────────────────

class TestStorageAuditAccess:
    def test_accessible_to_admin(self, client, admin_user):
        client.post("/login", data={"email": admin_user.email, "password": "password"})
        rv = client.get("/admin/storage/audit")
        assert rv.status_code == 200

    def test_accessible_to_super_admin(self, client, super_admin):
        client.post("/login", data={"email": super_admin.email, "password": "password"})
        rv = client.get("/admin/storage/audit")
        assert rv.status_code == 200

    def test_accessible_to_campus_director(self, client, campus_director):
        client.post("/login", data={"email": campus_director.email, "password": "password"})
        rv = client.get("/admin/storage/audit")
        assert rv.status_code == 200

    def test_blocked_for_regular_seller(self, client, seller):
        client.post("/login", data={"email": seller.email, "password": "password"})
        rv = client.get("/admin/storage/audit")
        assert rv.status_code in (302, 403)

    def test_blocked_for_anonymous(self, client):
        rv = client.get("/admin/storage/audit")
        assert rv.status_code in (302, 401)


class TestStorageAuditSearch:
    def test_search_by_id_returns_matching_item(self, client, admin_user, item_with_location):
        client.post("/login", data={"email": admin_user.email, "password": "password"})
        rv = client.get(f"/admin/storage/audit/search?q={item_with_location.id}")
        assert rv.status_code == 200
        assert b"Blue Couch" in rv.data

    def test_search_by_id_no_match_returns_empty(self, client, admin_user):
        client.post("/login", data={"email": admin_user.email, "password": "password"})
        rv = client.get("/admin/storage/audit/search?q=999999")
        assert rv.status_code == 200
        assert b"Blue Couch" not in rv.data

    def test_search_empty_query_returns_empty(self, client, admin_user):
        client.post("/login", data={"email": admin_user.email, "password": "password"})
        rv = client.get("/admin/storage/audit/search?q=")
        assert rv.status_code == 200

    def test_search_by_title_ilike(self, client, admin_user, item_with_location):
        client.post("/login", data={"email": admin_user.email, "password": "password"})
        rv = client.get("/admin/storage/audit/search?q=blue")
        assert rv.status_code == 200
        assert b"Blue Couch" in rv.data

    def test_search_case_insensitive(self, client, admin_user, item_with_location):
        client.post("/login", data={"email": admin_user.email, "password": "password"})
        rv = client.get("/admin/storage/audit/search?q=BLUE")
        assert rv.status_code == 200
        assert b"Blue Couch" in rv.data

    def test_search_excludes_tutorial_users(self, client, admin_user, db):
        with _app.app_context():
            tut_user = User(email="tut@unc.edu", full_name="Tutorial User",
                            is_tutorial_user=True, is_seller=True)
            tut_user.set_password("x")
            _db.session.add(tut_user)
            _db.session.flush()
            tut_item = InventoryItem(description="Tutorial Lamp",
                                     seller_id=tut_user.id, status="available")
            _db.session.add(tut_item)
            _db.session.commit()

        client.post("/login", data={"email": admin_user.email, "password": "password"})
        rv = client.get("/admin/storage/audit/search?q=Tutorial+Lamp")
        assert b"Tutorial Lamp" not in rv.data


class TestSetLocation:
    def test_writes_location_and_zone(self, client, admin_user, item_without_location,
                                      storage_location):
        client.post("/login", data={"email": admin_user.email, "password": "password"})
        rv = client.post(f"/admin/item/{item_without_location.id}/set_location", data={
            "storage_location_id": storage_location.id,
            "storage_row": "back_left",
            "storage_note": "shelf 2",
        })
        assert rv.status_code == 200
        assert rv.get_json()["success"] is True

        with _app.app_context():
            item = InventoryItem.query.get(item_without_location.id)
            assert item.storage_location_id == storage_location.id
            assert item.storage_row == "back_left"
            assert item.storage_note == "shelf 2"

    def test_campus_director_can_write(self, client, campus_director,
                                        item_without_location, storage_location):
        client.post("/login", data={"email": campus_director.email, "password": "password"})
        rv = client.post(f"/admin/item/{item_without_location.id}/set_location", data={
            "storage_location_id": storage_location.id,
            "storage_row": "front_right",
        })
        assert rv.status_code == 200
        assert rv.get_json()["success"] is True

    def test_clears_location_with_empty_string(self, client, admin_user, item_with_location):
        client.post("/login", data={"email": admin_user.email, "password": "password"})
        rv = client.post(f"/admin/item/{item_with_location.id}/set_location", data={
            "storage_location_id": "",
            "storage_row": "",
        })
        assert rv.status_code == 200
        with _app.app_context():
            item = InventoryItem.query.get(item_with_location.id)
            assert item.storage_location_id is None
            assert item.storage_row is None

    def test_all_six_zones_accepted(self, client, admin_user,
                                     item_without_location, storage_location):
        valid_zones = ["back_left", "middle_left", "front_left",
                       "back_right", "middle_right", "front_right"]
        client.post("/login", data={"email": admin_user.email, "password": "password"})
        for zone in valid_zones:
            rv = client.post(f"/admin/item/{item_without_location.id}/set_location", data={
                "storage_location_id": storage_location.id,
                "storage_row": zone,
            })
            assert rv.status_code == 200, f"Zone '{zone}' was rejected"
            assert rv.get_json()["success"] is True

    def test_rejects_invalid_zone(self, client, admin_user,
                                   item_without_location, storage_location):
        client.post("/login", data={"email": admin_user.email, "password": "password"})
        rv = client.post(f"/admin/item/{item_without_location.id}/set_location", data={
            "storage_location_id": storage_location.id,
            "storage_row": "shelf_3",
        })
        assert rv.status_code == 400

    def test_rejects_inactive_location(self, client, admin_user,
                                        item_without_location, inactive_storage_location):
        client.post("/login", data={"email": admin_user.email, "password": "password"})
        rv = client.post(f"/admin/item/{item_without_location.id}/set_location", data={
            "storage_location_id": inactive_storage_location.id,
            "storage_row": "back_left",
        })
        assert rv.status_code == 400

    def test_blocked_for_regular_user(self, client, seller, item_without_location,
                                       storage_location):
        client.post("/login", data={"email": seller.email, "password": "password"})
        rv = client.post(f"/admin/item/{item_without_location.id}/set_location", data={
            "storage_location_id": storage_location.id,
            "storage_row": "back_left",
        })
        assert rv.status_code in (302, 403)

    def test_does_not_write_arrived_at_store_at(self, client, admin_user,
                                                  item_without_location, storage_location):
        client.post("/login", data={"email": admin_user.email, "password": "password"})
        client.post(f"/admin/item/{item_without_location.id}/set_location", data={
            "storage_location_id": storage_location.id,
            "storage_row": "middle_left",
        })
        with _app.app_context():
            item = InventoryItem.query.get(item_without_location.id)
            assert item.arrived_at_store_at is None

    def test_does_not_create_intake_record(self, client, admin_user,
                                            item_without_location, storage_location):
        with _app.app_context():
            count_before = IntakeRecord.query.count()
        client.post("/login", data={"email": admin_user.email, "password": "password"})
        client.post(f"/admin/item/{item_without_location.id}/set_location", data={
            "storage_location_id": storage_location.id,
            "storage_row": "front_left",
        })
        with _app.app_context():
            assert IntakeRecord.query.count() == count_before


class TestAdminItemsIdFilter:
    def test_filter_by_id_shows_matching_item(self, client, admin_user,
                                               item_with_location, item_without_location):
        client.post("/login", data={"email": admin_user.email, "password": "password"})
        rv = client.get(f"/admin/items?item_id={item_with_location.id}")
        assert rv.status_code == 200
        assert b"Blue Couch" in rv.data
        assert b"Red Lamp" not in rv.data

    def test_filter_by_id_no_match_renders_without_error(self, client, admin_user):
        client.post("/login", data={"email": admin_user.email, "password": "password"})
        rv = client.get("/admin/items?item_id=999999")
        assert rv.status_code == 200


# ─────────────────────────────────────────────────────────────────────────────
# Part 2: Driver Item Placement Flow
# ─────────────────────────────────────────────────────────────────────────────

class TestPlacementList:
    def test_returns_items_from_completed_stops(self, client, approved_driver,
                                                 shift_with_driver):
        client.post("/login", data={"email": approved_driver.email, "password": "password"})
        rv = client.get(f"/crew/shift/{shift_with_driver['shift_id']}/placement")
        assert rv.status_code == 200
        assert b"Desk Chair" in rv.data
        assert b"Floor Lamp" in rv.data

    def test_blocked_for_non_worker(self, client, seller, shift_with_driver):
        client.post("/login", data={"email": seller.email, "password": "password"})
        rv = client.get(f"/crew/shift/{shift_with_driver['shift_id']}/placement")
        assert rv.status_code in (302, 403)

    def test_shows_default_unit_in_dropdown(self, client, approved_driver,
                                             shift_with_driver, storage_location):
        client.post("/login", data={"email": approved_driver.email, "password": "password"})
        rv = client.get(f"/crew/shift/{shift_with_driver['shift_id']}/placement")
        assert storage_location.name.encode() in rv.data

    def test_excludes_full_locations_from_dropdown(self, client, approved_driver,
                                                    shift_with_driver, full_storage_location):
        client.post("/login", data={"email": approved_driver.email, "password": "password"})
        rv = client.get(f"/crew/shift/{shift_with_driver['shift_id']}/placement")
        assert full_storage_location.name.encode() not in rv.data


class TestPlaceItem:
    def test_writes_location_and_zone(self, client, approved_driver,
                                       shift_with_driver, storage_location):
        client.post("/login", data={"email": approved_driver.email, "password": "password"})
        item_id = shift_with_driver["item1_id"]
        rv = client.post(f"/crew/item/{item_id}/place", data={
            "storage_location_id": storage_location.id,
            "storage_row": "middle_right",
        })
        assert rv.status_code == 200
        assert rv.get_json()["success"] is True

        with _app.app_context():
            item = InventoryItem.query.get(item_id)
            assert item.storage_location_id == storage_location.id
            assert item.storage_row == "middle_right"
            assert item.placement_status == "placed"

    def test_driver_can_use_different_unit(self, client, approved_driver,
                                            shift_with_driver, db):
        with _app.app_context():
            overflow = StorageLocation(name="Overflow Unit", address="overflow",
                                       is_active=True, is_full=False)
            _db.session.add(overflow)
            _db.session.commit()
            overflow_id = overflow.id

        client.post("/login", data={"email": approved_driver.email, "password": "password"})
        item_id = shift_with_driver["item1_id"]
        rv = client.post(f"/crew/item/{item_id}/place", data={
            "storage_location_id": overflow_id,
            "storage_row": "back_right",
        })
        assert rv.status_code == 200
        with _app.app_context():
            item = InventoryItem.query.get(item_id)
            assert item.storage_location_id == overflow_id

    def test_persists_after_re_entry(self, client, approved_driver,
                                      shift_with_driver, storage_location):
        client.post("/login", data={"email": approved_driver.email, "password": "password"})
        item_id = shift_with_driver["item1_id"]
        client.post(f"/crew/item/{item_id}/place", data={
            "storage_location_id": storage_location.id,
            "storage_row": "front_left",
        })
        rv = client.get(f"/crew/shift/{shift_with_driver['shift_id']}/placement")
        assert rv.status_code == 200
        # Row reflects placed status
        assert b"placed" in rv.data.lower()

    def test_rejects_invalid_zone(self, client, approved_driver,
                                   shift_with_driver, storage_location):
        client.post("/login", data={"email": approved_driver.email, "password": "password"})
        item_id = shift_with_driver["item1_id"]
        rv = client.post(f"/crew/item/{item_id}/place", data={
            "storage_location_id": storage_location.id,
            "storage_row": "shelf_A",
        })
        assert rv.status_code == 400

    def test_rejects_inactive_location(self, client, approved_driver,
                                        shift_with_driver, inactive_storage_location):
        client.post("/login", data={"email": approved_driver.email, "password": "password"})
        item_id = shift_with_driver["item1_id"]
        rv = client.post(f"/crew/item/{item_id}/place", data={
            "storage_location_id": inactive_storage_location.id,
            "storage_row": "back_left",
        })
        assert rv.status_code == 400

    def test_blocked_for_non_worker(self, client, seller, shift_with_driver,
                                     storage_location):
        client.post("/login", data={"email": seller.email, "password": "password"})
        item_id = shift_with_driver["item1_id"]
        rv = client.post(f"/crew/item/{item_id}/place", data={
            "storage_location_id": storage_location.id,
            "storage_row": "back_left",
        })
        assert rv.status_code in (302, 403)


class TestNotPickedUp:
    def test_sets_placement_status(self, client, approved_driver, shift_with_driver):
        client.post("/login", data={"email": approved_driver.email, "password": "password"})
        item_id = shift_with_driver["item1_id"]
        rv = client.post(f"/crew/item/{item_id}/not_picked_up")
        assert rv.status_code == 200
        assert rv.get_json()["success"] is True

        with _app.app_context():
            item = InventoryItem.query.get(item_id)
            assert item.placement_status == "not_picked_up"

    def test_clears_location_if_not_intake_confirmed(self, client, approved_driver,
                                                       shift_with_driver, storage_location):
        item_id = shift_with_driver["item1_id"]
        with _app.app_context():
            item = InventoryItem.query.get(item_id)
            item.storage_location_id = storage_location.id
            item.storage_row = "back_left"
            # arrived_at_store_at is None — intake never confirmed
            _db.session.commit()

        client.post("/login", data={"email": approved_driver.email, "password": "password"})
        client.post(f"/crew/item/{item_id}/not_picked_up")

        with _app.app_context():
            item = InventoryItem.query.get(item_id)
            assert item.storage_location_id is None
            assert item.storage_row is None

    def test_preserves_location_if_intake_confirmed(self, client, approved_driver,
                                                      shift_with_driver, storage_location):
        item_id = shift_with_driver["item1_id"]
        with _app.app_context():
            item = InventoryItem.query.get(item_id)
            item.storage_location_id = storage_location.id
            item.storage_row = "back_left"
            item.arrived_at_store_at = datetime.utcnow()
            _db.session.commit()

        client.post("/login", data={"email": approved_driver.email, "password": "password"})
        client.post(f"/crew/item/{item_id}/not_picked_up")

        with _app.app_context():
            item = InventoryItem.query.get(item_id)
            assert item.storage_location_id == storage_location.id


class TestEndShiftPlacementGuard:
    def test_blocked_when_items_unplaced(self, client, approved_driver, shift_with_driver):
        client.post("/login", data={"email": approved_driver.email, "password": "password"})
        rv = client.post(
            f"/crew/shift/{shift_with_driver['shift_id']}/end",
            data={"confirmed": "1"},
        )
        assert rv.status_code == 400

    def test_allowed_when_all_items_placed(self, client, approved_driver,
                                            shift_with_driver, storage_location):
        with _app.app_context():
            for item_id in [shift_with_driver["item1_id"], shift_with_driver["item2_id"]]:
                item = InventoryItem.query.get(item_id)
                item.storage_location_id = storage_location.id
                item.storage_row = "back_left"
                item.placement_status = "placed"
            _db.session.commit()

        client.post("/login", data={"email": approved_driver.email, "password": "password"})
        rv = client.post(
            f"/crew/shift/{shift_with_driver['shift_id']}/end",
            data={"confirmed": "1"},
        )
        assert rv.status_code in (200, 302)

    def test_allowed_when_all_items_not_picked_up(self, client, approved_driver,
                                                    shift_with_driver):
        with _app.app_context():
            for item_id in [shift_with_driver["item1_id"], shift_with_driver["item2_id"]]:
                item = InventoryItem.query.get(item_id)
                item.placement_status = "not_picked_up"
            _db.session.commit()

        client.post("/login", data={"email": approved_driver.email, "password": "password"})
        rv = client.post(
            f"/crew/shift/{shift_with_driver['shift_id']}/end",
            data={"confirmed": "1"},
        )
        assert rv.status_code in (200, 302)

    def test_allowed_mixed_placed_and_not_picked_up(self, client, approved_driver,
                                                      shift_with_driver, storage_location):
        with _app.app_context():
            item1 = InventoryItem.query.get(shift_with_driver["item1_id"])
            item1.placement_status = "placed"
            item1.storage_location_id = storage_location.id
            item1.storage_row = "front_right"
            item2 = InventoryItem.query.get(shift_with_driver["item2_id"])
            item2.placement_status = "not_picked_up"
            _db.session.commit()

        client.post("/login", data={"email": approved_driver.email, "password": "password"})
        rv = client.post(
            f"/crew/shift/{shift_with_driver['shift_id']}/end",
            data={"confirmed": "1"},
        )
        assert rv.status_code in (200, 302)

    def test_sets_completed_at_on_assignment(self, client, approved_driver,
                                              shift_with_driver, storage_location):
        with _app.app_context():
            for item_id in [shift_with_driver["item1_id"], shift_with_driver["item2_id"]]:
                item = InventoryItem.query.get(item_id)
                item.placement_status = "placed"
                item.storage_location_id = storage_location.id
                item.storage_row = "back_left"
            _db.session.commit()

        client.post("/login", data={"email": approved_driver.email, "password": "password"})
        client.post(
            f"/crew/shift/{shift_with_driver['shift_id']}/end",
            data={"confirmed": "1"},
        )

        with _app.app_context():
            from models import ShiftAssignment as SA
            assignment = SA.query.get(shift_with_driver["assignment_id"])
            assert assignment.completed_at is not None


class TestZoneEnumHelper:
    def test_accepts_all_valid_values(self):
        from app import _validate_storage_zone
        valid = ["back_left", "middle_left", "front_left",
                 "back_right", "middle_right", "front_right"]
        for zone in valid:
            ok, err = _validate_storage_zone(zone)
            assert ok is True, f"Zone '{zone}' should be valid"
            assert err is None

    def test_rejects_free_text(self):
        from app import _validate_storage_zone
        for bad in ["shelf_3", "A1", "Row 1"]:
            ok, err = _validate_storage_zone(bad)
            assert ok is False, f"Zone '{bad}' should be rejected"
            assert err is not None

    def test_accepts_empty_string_as_clear(self):
        from app import _validate_storage_zone
        ok, err = _validate_storage_zone("")
        assert ok is True

    def test_accepts_none_as_clear(self):
        from app import _validate_storage_zone
        ok, err = _validate_storage_zone(None)
        assert ok is True


# ─────────────────────────────────────────────────────────────────────────────
# Part 3: Inventory Photo Refresh
# ─────────────────────────────────────────────────────────────────────────────

def _make_png_bytes():
    """Return bytes of a valid 10x10 red PNG that PIL can open."""
    buf = io.BytesIO()
    img = Image.new("RGB", (10, 10), color=(255, 0, 0))
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


class TestReplacePhoto:
    def _png_upload(self, name="test.png"):
        return (_make_png_bytes(), name)

    def test_sets_needs_photo_refresh(self, client, admin_user,
                                       item_without_location):
        client.post("/login", data={"email": admin_user.email, "password": "password"})
        rv = client.post(
            f"/admin/item/{item_without_location.id}/replace_photo",
            data={"photo": self._png_upload()},
            content_type="multipart/form-data",
        )
        assert rv.status_code == 200
        assert rv.get_json()["success"] is True
        with _app.app_context():
            item = InventoryItem.query.get(item_without_location.id)
            assert item.needs_photo_refresh is True

    def test_updates_photo_url(self, client, admin_user, item_without_location):
        original_url = item_without_location.photo_url
        client.post("/login", data={"email": admin_user.email, "password": "password"})
        client.post(
            f"/admin/item/{item_without_location.id}/replace_photo",
            data={"photo": self._png_upload("new_photo.png")},
            content_type="multipart/form-data",
        )
        with _app.app_context():
            item = InventoryItem.query.get(item_without_location.id)
            assert item.photo_url != original_url
            assert item.photo_url is not None

    def test_campus_director_can_upload(self, client, campus_director,
                                         item_without_location):
        client.post("/login", data={"email": campus_director.email, "password": "password"})
        rv = client.post(
            f"/admin/item/{item_without_location.id}/replace_photo",
            data={"photo": self._png_upload("cd_photo.png")},
            content_type="multipart/form-data",
        )
        assert rv.status_code == 200
        assert rv.get_json()["success"] is True

    def test_blocked_for_seller(self, client, seller, item_without_location):
        client.post("/login", data={"email": seller.email, "password": "password"})
        rv = client.post(
            f"/admin/item/{item_without_location.id}/replace_photo",
            data={"photo": self._png_upload("bad.png")},
            content_type="multipart/form-data",
        )
        assert rv.status_code in (302, 403)

    def test_does_not_touch_gallery_photos(self, client, admin_user,
                                            item_without_location, db):
        with _app.app_context():
            gallery = ItemPhoto(item_id=item_without_location.id,
                                photo_url="gallery1.jpg")
            _db.session.add(gallery)
            _db.session.commit()
            count_before = ItemPhoto.query.filter_by(
                item_id=item_without_location.id
            ).count()

        client.post("/login", data={"email": admin_user.email, "password": "password"})
        client.post(
            f"/admin/item/{item_without_location.id}/replace_photo",
            data={"photo": self._png_upload("cover.png")},
            content_type="multipart/form-data",
        )

        with _app.app_context():
            count_after = ItemPhoto.query.filter_by(
                item_id=item_without_location.id
            ).count()
        assert count_after == count_before


class TestNeedsRefreshFilter:
    def test_filter_shows_only_flagged_items(self, client, admin_user, db, seller):
        with _app.app_context():
            item_refresh = InventoryItem(description="Needs BG Replace",
                                          seller_id=seller.id, status="available",
                                          needs_photo_refresh=True)
            item_clean = InventoryItem(description="Clean Photo",
                                        seller_id=seller.id, status="available",
                                        needs_photo_refresh=False)
            _db.session.add_all([item_refresh, item_clean])
            _db.session.commit()

        client.post("/login", data={"email": admin_user.email, "password": "password"})
        rv = client.get("/admin/items?needs_refresh=1")
        assert rv.status_code == 200
        assert b"Needs BG Replace" in rv.data
        assert b"Clean Photo" not in rv.data

    def test_no_filter_shows_all_items(self, client, admin_user, db, seller):
        with _app.app_context():
            item_refresh = InventoryItem(description="Needs BG Replace",
                                          seller_id=seller.id, status="available",
                                          needs_photo_refresh=True)
            item_clean = InventoryItem(description="Clean Photo",
                                        seller_id=seller.id, status="available",
                                        needs_photo_refresh=False)
            _db.session.add_all([item_refresh, item_clean])
            _db.session.commit()

        client.post("/login", data={"email": admin_user.email, "password": "password"})
        rv = client.get("/admin/items")
        assert b"Needs BG Replace" in rv.data
        assert b"Clean Photo" in rv.data

    def test_combines_with_id_filter(self, client, admin_user, db, seller):
        with _app.app_context():
            item = InventoryItem(description="Targeted Item",
                                  seller_id=seller.id, status="available",
                                  needs_photo_refresh=True)
            _db.session.add(item)
            _db.session.commit()
            item_id = item.id

        client.post("/login", data={"email": admin_user.email, "password": "password"})
        rv = client.get(f"/admin/items?item_id={item_id}&needs_refresh=1")
        assert rv.status_code == 200
        assert b"Targeted Item" in rv.data


class TestRegressionSellerUpload:
    def test_new_item_defaults_needs_photo_refresh_to_false(self, client, seller):
        with _app.app_context():
            item = InventoryItem(description="Seller Item",
                                  seller_id=seller.id, status="pending_valuation")
            _db.session.add(item)
            _db.session.commit()
            db_item = InventoryItem.query.get(item.id)
            assert db_item.needs_photo_refresh is False
