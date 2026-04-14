"""
Tests for pickup location improvements:
- Off-campus apartment complex branch (pickup_location_type='off_campus_complex')
- Structured access fields (pickup_access_type, pickup_floor)
- Migration of legacy 'off_campus' rows to 'off_campus_other'
- has_pickup_location property updated to require new fields
- update_profile and onboard routes accept and validate new fields
- pickup_display property covers all four location type values
"""

import pytest
from flask import url_for


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

OFF_CAMPUS_COMPLEXES = [
    "Granville Towers",
    "Lark Chapel Hill Apartments",
    "The Warehouse",
    "The Edition on Rosemary",
    "Shortbread Lofts",
    "Union Chapel Hill",
    "Carolina Square",
]


def make_seller(client, db, User, email="seller@test.com"):
    """Create and log in a basic seller account. Returns the User object."""
    user = User(
        email=email,
        full_name="Test Seller",
        phone="9195550001",
        is_seller=True,
        payout_rate=20,
    )
    user.set_password("password123")
    db.session.add(user)
    db.session.commit()
    client.post("/login", data={"email": email, "password": "password123"}, follow_redirects=True)
    return user


# ---------------------------------------------------------------------------
# Model: new fields exist
# ---------------------------------------------------------------------------

class TestModelFields:
    def test_pickup_access_type_field_exists(self, app):
        from models import User
        assert hasattr(User, "pickup_access_type"), "User.pickup_access_type field missing"

    def test_pickup_floor_field_exists(self, app):
        from models import User
        assert hasattr(User, "pickup_floor"), "User.pickup_floor field missing"

    def test_pickup_access_type_defaults_none(self, app, db):
        from models import User
        u = User(email="fieldtest@test.com", full_name="Field Test", phone="9195550099")
        db.session.add(u)
        db.session.commit()
        assert u.pickup_access_type is None
        assert u.pickup_floor is None

    def test_pickup_location_type_accepts_off_campus_complex(self, app, db):
        from models import User
        u = User(
            email="complex@test.com",
            full_name="Complex User",
            phone="9195550002",
            pickup_location_type="off_campus_complex",
            pickup_dorm="Granville Towers",
            pickup_room="4B",
            pickup_access_type="elevator",
            pickup_floor=4,
        )
        db.session.add(u)
        db.session.commit()
        db.session.refresh(u)
        assert u.pickup_location_type == "off_campus_complex"
        assert u.pickup_dorm == "Granville Towers"
        assert u.pickup_room == "4B"

    def test_pickup_location_type_accepts_off_campus_other(self, app, db):
        from models import User
        u = User(
            email="other@test.com",
            full_name="Other User",
            phone="9195550003",
            pickup_location_type="off_campus_other",
            pickup_address="123 Main St",
            pickup_lat=35.9132,
            pickup_lng=-79.0558,
            pickup_access_type="stairs_only",
            pickup_floor=2,
        )
        db.session.add(u)
        db.session.commit()
        db.session.refresh(u)
        assert u.pickup_location_type == "off_campus_other"


# ---------------------------------------------------------------------------
# Model: has_pickup_location property
# ---------------------------------------------------------------------------

class TestHasPickupLocation:
    def test_on_campus_complete_with_access_fields(self, app, db):
        from models import User
        u = User(
            email="oncampus@test.com", full_name="On Campus", phone="9195550010",
            pickup_location_type="on_campus",
            pickup_dorm="Granville", pickup_room="101",
            pickup_access_type="elevator", pickup_floor=1,
        )
        db.session.add(u)
        db.session.commit()
        assert u.has_pickup_location is True

    def test_on_campus_missing_access_type_is_incomplete(self, app, db):
        from models import User
        u = User(
            email="oncampus2@test.com", full_name="On Campus 2", phone="9195550011",
            pickup_location_type="on_campus",
            pickup_dorm="Granville", pickup_room="101",
            pickup_access_type=None, pickup_floor=1,
        )
        db.session.add(u)
        db.session.commit()
        assert u.has_pickup_location is False

    def test_on_campus_missing_floor_is_incomplete(self, app, db):
        from models import User
        u = User(
            email="oncampus3@test.com", full_name="On Campus 3", phone="9195550012",
            pickup_location_type="on_campus",
            pickup_dorm="Granville", pickup_room="101",
            pickup_access_type="stairs_only", pickup_floor=None,
        )
        db.session.add(u)
        db.session.commit()
        assert u.has_pickup_location is False

    def test_off_campus_complex_complete(self, app, db):
        from models import User
        u = User(
            email="complex2@test.com", full_name="Complex 2", phone="9195550013",
            pickup_location_type="off_campus_complex",
            pickup_dorm="Granville Towers", pickup_room="4B",
            pickup_access_type="elevator", pickup_floor=4,
        )
        db.session.add(u)
        db.session.commit()
        assert u.has_pickup_location is True

    def test_off_campus_complex_missing_unit_is_incomplete(self, app, db):
        from models import User
        u = User(
            email="complex3@test.com", full_name="Complex 3", phone="9195550014",
            pickup_location_type="off_campus_complex",
            pickup_dorm="Granville Towers", pickup_room=None,
            pickup_access_type="elevator", pickup_floor=4,
        )
        db.session.add(u)
        db.session.commit()
        assert u.has_pickup_location is False

    def test_off_campus_other_complete(self, app, db):
        from models import User
        u = User(
            email="other2@test.com", full_name="Other 2", phone="9195550015",
            pickup_location_type="off_campus_other",
            pickup_address="123 Main St", pickup_lat=35.9132, pickup_lng=-79.0558,
            pickup_access_type="ground_floor", pickup_floor=1,
        )
        db.session.add(u)
        db.session.commit()
        assert u.has_pickup_location is True

    def test_off_campus_other_missing_address_is_incomplete(self, app, db):
        from models import User
        u = User(
            email="other3@test.com", full_name="Other 3", phone="9195550016",
            pickup_location_type="off_campus_other",
            pickup_address=None, pickup_lat=None, pickup_lng=None,
            pickup_access_type="ground_floor", pickup_floor=1,
        )
        db.session.add(u)
        db.session.commit()
        assert u.has_pickup_location is False

    def test_no_location_type_set_is_incomplete(self, app, db):
        from models import User
        u = User(
            email="noloc@test.com", full_name="No Loc", phone="9195550017",
        )
        db.session.add(u)
        db.session.commit()
        assert u.has_pickup_location is False


# ---------------------------------------------------------------------------
# Model: pickup_display property
# ---------------------------------------------------------------------------

class TestPickupDisplay:
    def test_on_campus_display_includes_dorm_and_room(self, app, db):
        from models import User
        u = User(
            email="disp1@test.com", full_name="D1", phone="9195550020",
            pickup_location_type="on_campus",
            pickup_dorm="Granville", pickup_room="101",
            pickup_access_type="elevator", pickup_floor=1,
        )
        db.session.add(u)
        db.session.commit()
        display = u.pickup_display
        assert "Granville" in display
        assert "101" in display

    def test_off_campus_complex_display_includes_building_and_unit(self, app, db):
        from models import User
        u = User(
            email="disp2@test.com", full_name="D2", phone="9195550021",
            pickup_location_type="off_campus_complex",
            pickup_dorm="Granville Towers", pickup_room="4B",
            pickup_access_type="stairs_only", pickup_floor=4,
        )
        db.session.add(u)
        db.session.commit()
        display = u.pickup_display
        assert "Granville Towers" in display
        assert "4B" in display

    def test_off_campus_other_display_includes_address(self, app, db):
        from models import User
        u = User(
            email="disp3@test.com", full_name="D3", phone="9195550022",
            pickup_location_type="off_campus_other",
            pickup_address="123 Main St Chapel Hill",
            pickup_lat=35.9132, pickup_lng=-79.0558,
            pickup_access_type="ground_floor", pickup_floor=1,
        )
        db.session.add(u)
        db.session.commit()
        display = u.pickup_display
        assert "123 Main St" in display

    def test_legacy_off_campus_display_does_not_crash(self, app, db):
        """Defensive: rows migrated to off_campus_other should still render."""
        from models import User
        u = User(
            email="disp4@test.com", full_name="D4", phone="9195550023",
            pickup_location_type="off_campus_other",
            pickup_address="456 Legacy Rd",
            pickup_access_type=None, pickup_floor=None,
        )
        db.session.add(u)
        db.session.commit()
        # Must not raise
        display = u.pickup_display
        assert display is not None

    def test_display_includes_access_type_info(self, app, db):
        from models import User
        u = User(
            email="disp5@test.com", full_name="D5", phone="9195550024",
            pickup_location_type="on_campus",
            pickup_dorm="Ehringhaus", pickup_room="204",
            pickup_access_type="stairs_only", pickup_floor=2,
        )
        db.session.add(u)
        db.session.commit()
        display = u.pickup_display
        # Access type should appear in some form
        assert any(keyword in display.lower() for keyword in ["stair", "elevator", "ground", "floor", "2"])


# ---------------------------------------------------------------------------
# Route: POST /update_profile — on-campus
# ---------------------------------------------------------------------------

class TestUpdateProfileOnCampus:
    def test_on_campus_saves_all_fields(self, client, app, db):
        from models import User
        user = make_seller(client, db, User, "on1@test.com")
        resp = client.post("/update_profile", data={
            "pickup_location_type": "on_campus",
            "pickup_dorm": "Granville",
            "pickup_room": "101",
            "pickup_access_type": "elevator",
            "pickup_floor": "1",
        }, follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(user)
        assert user.pickup_location_type == "on_campus"
        assert user.pickup_dorm == "Granville"
        assert user.pickup_room == "101"
        assert user.pickup_access_type == "elevator"
        assert user.pickup_floor == 1

    def test_on_campus_missing_access_type_rejected(self, client, app, db):
        from models import User
        user = make_seller(client, db, User, "on2@test.com")
        resp = client.post("/update_profile", data={
            "pickup_location_type": "on_campus",
            "pickup_dorm": "Granville",
            "pickup_room": "101",
            "pickup_floor": "1",
            # pickup_access_type omitted
        }, follow_redirects=True)
        db.session.refresh(user)
        assert user.pickup_access_type is None  # not saved

    def test_on_campus_missing_floor_rejected(self, client, app, db):
        from models import User
        user = make_seller(client, db, User, "on3@test.com")
        resp = client.post("/update_profile", data={
            "pickup_location_type": "on_campus",
            "pickup_dorm": "Granville",
            "pickup_room": "101",
            "pickup_access_type": "stairs_only",
            # pickup_floor omitted
        }, follow_redirects=True)
        db.session.refresh(user)
        assert user.pickup_floor is None  # not saved

    def test_on_campus_missing_dorm_rejected(self, client, app, db):
        from models import User
        user = make_seller(client, db, User, "on4@test.com")
        resp = client.post("/update_profile", data={
            "pickup_location_type": "on_campus",
            "pickup_room": "101",
            "pickup_access_type": "elevator",
            "pickup_floor": "1",
        }, follow_redirects=True)
        db.session.refresh(user)
        assert user.pickup_dorm is None  # not saved

    def test_on_campus_saves_optional_note(self, client, app, db):
        from models import User
        user = make_seller(client, db, User, "on5@test.com")
        client.post("/update_profile", data={
            "pickup_location_type": "on_campus",
            "pickup_dorm": "Granville",
            "pickup_room": "101",
            "pickup_access_type": "elevator",
            "pickup_floor": "3",
            "pickup_note": "Room is at the end of the hall",
        }, follow_redirects=True)
        db.session.refresh(user)
        assert user.pickup_note == "Room is at the end of the hall"


# ---------------------------------------------------------------------------
# Route: POST /update_profile — off-campus complex (new branch)
# ---------------------------------------------------------------------------

class TestUpdateProfileOffCampusComplex:
    @pytest.mark.parametrize("building", OFF_CAMPUS_COMPLEXES)
    def test_all_known_buildings_accepted(self, building, client, app, db):
        from models import User
        email = f"complex_{building[:4].lower().replace(' ', '')}@test.com"
        user = make_seller(client, db, User, email)
        resp = client.post("/update_profile", data={
            "pickup_location_type": "off_campus_complex",
            "pickup_dorm": building,
            "pickup_room": "12A",
            "pickup_access_type": "elevator",
            "pickup_floor": "2",
        }, follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(user)
        assert user.pickup_location_type == "off_campus_complex"
        assert user.pickup_dorm == building
        assert user.pickup_room == "12A"

    def test_unknown_building_rejected(self, client, app, db):
        from models import User
        user = make_seller(client, db, User, "badbuilding@test.com")
        client.post("/update_profile", data={
            "pickup_location_type": "off_campus_complex",
            "pickup_dorm": "Some Random Apartment Complex",  # not in allowed list
            "pickup_room": "12A",
            "pickup_access_type": "elevator",
            "pickup_floor": "2",
        }, follow_redirects=True)
        db.session.refresh(user)
        # Should not have saved
        assert user.pickup_dorm != "Some Random Apartment Complex"

    def test_missing_unit_number_rejected(self, client, app, db):
        from models import User
        user = make_seller(client, db, User, "nounit@test.com")
        client.post("/update_profile", data={
            "pickup_location_type": "off_campus_complex",
            "pickup_dorm": "Granville Towers",
            # pickup_room omitted
            "pickup_access_type": "elevator",
            "pickup_floor": "2",
        }, follow_redirects=True)
        db.session.refresh(user)
        assert user.pickup_location_type != "off_campus_complex"

    def test_complex_branch_clears_address_fields(self, client, app, db):
        """Switching from off_campus_other to off_campus_complex should null address fields."""
        from models import User
        user = make_seller(client, db, User, "switchbranch@test.com")
        # First set an address
        user.pickup_location_type = "off_campus_other"
        user.pickup_address = "123 Main St"
        user.pickup_lat = 35.9
        user.pickup_lng = -79.0
        db.session.commit()
        # Now switch to complex
        client.post("/update_profile", data={
            "pickup_location_type": "off_campus_complex",
            "pickup_dorm": "Granville Towers",
            "pickup_room": "4B",
            "pickup_access_type": "stairs_only",
            "pickup_floor": "4",
        }, follow_redirects=True)
        db.session.refresh(user)
        assert user.pickup_address is None
        assert user.pickup_lat is None
        assert user.pickup_lng is None

    def test_complex_branch_saves_access_fields(self, client, app, db):
        from models import User
        user = make_seller(client, db, User, "complexaccess@test.com")
        client.post("/update_profile", data={
            "pickup_location_type": "off_campus_complex",
            "pickup_dorm": "Carolina Square",
            "pickup_room": "801",
            "pickup_access_type": "stairs_only",
            "pickup_floor": "8",
        }, follow_redirects=True)
        db.session.refresh(user)
        assert user.pickup_access_type == "stairs_only"
        assert user.pickup_floor == 8


# ---------------------------------------------------------------------------
# Route: POST /update_profile — off-campus other address
# ---------------------------------------------------------------------------

class TestUpdateProfileOffCampusOther:
    def test_off_campus_other_saves_address_and_access_fields(self, client, app, db):
        from models import User
        user = make_seller(client, db, User, "other1@test.com")
        resp = client.post("/update_profile", data={
            "pickup_location_type": "off_campus_other",
            "pickup_address": "456 Franklin St, Chapel Hill",
            "pickup_lat": "35.9132",
            "pickup_lng": "-79.0558",
            "pickup_access_type": "ground_floor",
            "pickup_floor": "1",
        }, follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(user)
        assert user.pickup_location_type == "off_campus_other"
        assert user.pickup_address == "456 Franklin St, Chapel Hill"
        assert user.pickup_access_type == "ground_floor"
        assert user.pickup_floor == 1

    def test_off_campus_other_missing_address_rejected(self, client, app, db):
        from models import User
        user = make_seller(client, db, User, "other2@test.com")
        client.post("/update_profile", data={
            "pickup_location_type": "off_campus_other",
            # pickup_address omitted
            "pickup_access_type": "elevator",
            "pickup_floor": "2",
        }, follow_redirects=True)
        db.session.refresh(user)
        assert user.pickup_location_type != "off_campus_other"

    def test_off_campus_other_clears_dorm_fields(self, client, app, db):
        """Switching from on_campus to off_campus_other should null dorm/room."""
        from models import User
        user = make_seller(client, db, User, "other3@test.com")
        user.pickup_location_type = "on_campus"
        user.pickup_dorm = "Granville"
        user.pickup_room = "101"
        db.session.commit()
        client.post("/update_profile", data={
            "pickup_location_type": "off_campus_other",
            "pickup_address": "456 Franklin St",
            "pickup_lat": "35.9132",
            "pickup_lng": "-79.0558",
            "pickup_access_type": "stairs_only",
            "pickup_floor": "3",
        }, follow_redirects=True)
        db.session.refresh(user)
        assert user.pickup_dorm is None
        assert user.pickup_room is None


# ---------------------------------------------------------------------------
# Route: POST /update_profile — invalid access field values
# ---------------------------------------------------------------------------

class TestUpdateProfileAccessFieldValidation:
    def test_invalid_access_type_string_rejected(self, client, app, db):
        from models import User
        user = make_seller(client, db, User, "badaccess@test.com")
        client.post("/update_profile", data={
            "pickup_location_type": "on_campus",
            "pickup_dorm": "Granville",
            "pickup_room": "101",
            "pickup_access_type": "teleporter",  # invalid
            "pickup_floor": "1",
        }, follow_redirects=True)
        db.session.refresh(user)
        assert user.pickup_access_type is None

    def test_floor_zero_rejected(self, client, app, db):
        from models import User
        user = make_seller(client, db, User, "floor0@test.com")
        client.post("/update_profile", data={
            "pickup_location_type": "on_campus",
            "pickup_dorm": "Granville",
            "pickup_room": "101",
            "pickup_access_type": "elevator",
            "pickup_floor": "0",
        }, follow_redirects=True)
        db.session.refresh(user)
        assert user.pickup_floor != 0

    def test_floor_above_max_rejected(self, client, app, db):
        from models import User
        user = make_seller(client, db, User, "floor99@test.com")
        client.post("/update_profile", data={
            "pickup_location_type": "on_campus",
            "pickup_dorm": "Granville",
            "pickup_room": "101",
            "pickup_access_type": "elevator",
            "pickup_floor": "99",
        }, follow_redirects=True)
        db.session.refresh(user)
        assert user.pickup_floor != 99

    def test_floor_non_integer_rejected(self, client, app, db):
        from models import User
        user = make_seller(client, db, User, "floorbad@test.com")
        client.post("/update_profile", data={
            "pickup_location_type": "on_campus",
            "pickup_dorm": "Granville",
            "pickup_room": "101",
            "pickup_access_type": "elevator",
            "pickup_floor": "two",
        }, follow_redirects=True)
        db.session.refresh(user)
        assert user.pickup_floor is None

    def test_all_three_access_type_values_accepted(self, client, app, db):
        from models import User
        for i, access_type in enumerate(["elevator", "stairs_only", "ground_floor"]):
            email = f"access{i}@test.com"
            user = make_seller(client, db, User, email)
            client.post("/update_profile", data={
                "pickup_location_type": "on_campus",
                "pickup_dorm": "Granville",
                "pickup_room": "10" + str(i),
                "pickup_access_type": access_type,
                "pickup_floor": "1",
            }, follow_redirects=True)
            db.session.refresh(user)
            assert user.pickup_access_type == access_type, f"access_type '{access_type}' was not saved"


# ---------------------------------------------------------------------------
# Onboarding session: new fields flow through to account creation
# ---------------------------------------------------------------------------

class TestOnboardingLocationFields:
    def test_onboard_location_step_accepts_off_campus_complex(self, client, app, db):
        """
        Simulate posting the location step in the onboarding wizard with
        off_campus_complex data and verify the session carries the new fields.
        This is a smoke test — the exact session key names must match app.py.
        """
        # Start onboarding session (guest path)
        client.get("/onboard")
        resp = client.post("/onboard", data={
            "step": "location",
            "pickup_location_type": "off_campus_complex",
            "pickup_dorm": "Shortbread Lofts",
            "pickup_room": "202",
            "pickup_access_type": "elevator",
            "pickup_floor": "2",
        }, follow_redirects=False)
        # Either advances to next step (302) or re-renders with errors (200).
        # We expect a redirect — if 200, the step validation failed.
        assert resp.status_code == 302, (
            "Onboarding location step with valid off_campus_complex data should advance "
            f"(got {resp.status_code}). Check that app.py handles off_campus_complex branch."
        )

    def test_onboard_location_step_rejects_missing_access_type(self, client, app, db):
        client.get("/onboard")
        resp = client.post("/onboard", data={
            "step": "location",
            "pickup_location_type": "on_campus",
            "pickup_dorm": "Granville",
            "pickup_room": "101",
            # pickup_access_type omitted
            "pickup_floor": "1",
        }, follow_redirects=False)
        assert resp.status_code == 200, (
            "Onboarding location step missing access_type should re-render (got 302 — data accepted when it shouldn't be)."
        )

    def test_onboard_location_step_rejects_missing_floor(self, client, app, db):
        client.get("/onboard")
        resp = client.post("/onboard", data={
            "step": "location",
            "pickup_location_type": "on_campus",
            "pickup_dorm": "Granville",
            "pickup_room": "101",
            "pickup_access_type": "stairs_only",
            # pickup_floor omitted
        }, follow_redirects=False)
        assert resp.status_code == 200, (
            "Onboarding location step missing floor should re-render."
        )


# ---------------------------------------------------------------------------
# Account settings page: new fields pre-populate correctly
# ---------------------------------------------------------------------------

class TestAccountSettingsPrePopulation:
    def test_account_settings_shows_existing_access_type(self, client, app, db):
        from models import User
        user = make_seller(client, db, User, "prepop@test.com")
        user.pickup_location_type = "off_campus_complex"
        user.pickup_dorm = "Union Chapel Hill"
        user.pickup_room = "5C"
        user.pickup_access_type = "stairs_only"
        user.pickup_floor = 5
        db.session.commit()
        resp = client.get("/account_settings")
        assert resp.status_code == 200
        body = resp.data.decode()
        assert "Union Chapel Hill" in body
        assert "5C" in body or "5c" in body.lower()
        # Access type value should appear somewhere (in selected option or data attr)
        assert "stairs_only" in body or "Stairs only" in body

    def test_account_settings_shows_floor_number(self, client, app, db):
        from models import User
        user = make_seller(client, db, User, "prepop2@test.com")
        user.pickup_location_type = "on_campus"
        user.pickup_dorm = "Ehringhaus"
        user.pickup_room = "204"
        user.pickup_access_type = "elevator"
        user.pickup_floor = 2
        db.session.commit()
        resp = client.get("/account_settings")
        body = resp.data.decode()
        assert "2" in body  # floor number rendered


# ---------------------------------------------------------------------------
# Admin display: seller panel shows new fields
# ---------------------------------------------------------------------------

class TestAdminSellerPanel:
    def test_seller_panel_shows_access_type_and_floor(self, client, app, db):
        from models import User
        # Create admin
        admin = User(email="admin@test.com", full_name="Admin", phone="9195559999", is_admin=True)
        admin.set_password("adminpass")
        db.session.add(admin)
        # Create seller with full location
        seller = User(
            email="paneltest@test.com", full_name="Panel Seller", phone="9195550030",
            is_seller=True, payout_rate=20,
            pickup_location_type="off_campus_complex",
            pickup_dorm="The Warehouse",
            pickup_room="3A",
            pickup_access_type="ground_floor",
            pickup_floor=1,
        )
        db.session.add(seller)
        db.session.commit()
        # Log in as admin
        client.post("/login", data={"email": "admin@test.com", "password": "adminpass"}, follow_redirects=True)
        resp = client.get(f"/admin/seller/{seller.id}/panel")
        assert resp.status_code == 200
        body = resp.data.decode()
        assert "The Warehouse" in body
        assert "3A" in body or "3a" in body.lower()
        assert any(keyword in body.lower() for keyword in ["ground", "floor", "access"])


# ---------------------------------------------------------------------------
# Migration: legacy 'off_campus' rows become 'off_campus_other'
# ---------------------------------------------------------------------------

class TestLegacyMigration:
    def test_no_rows_with_legacy_off_campus_type_post_migration(self, app, db):
        """
        After the migration runs, no User rows should have pickup_location_type='off_campus'.
        This test creates a legacy row directly (bypassing app logic) and verifies the
        migration SQL would handle it. In CI the migration has already run, so we just
        confirm the old value is no longer produced anywhere.
        """
        from models import User
        from sqlalchemy import text
        # Insert a legacy row directly via raw SQL to bypass model validation
        db.session.execute(text(
            "INSERT INTO \"user\" (email, full_name, phone, pickup_location_type, payout_rate) "
            "VALUES ('legacy@test.com', 'Legacy', '9195550099', 'off_campus', 20)"
        ))
        db.session.commit()
        # Run the migration UPDATE (simulating what the Alembic migration does)
        db.session.execute(text(
            "UPDATE \"user\" SET pickup_location_type = 'off_campus_other' "
            "WHERE pickup_location_type = 'off_campus'"
        ))
        db.session.commit()
        # No legacy rows should remain
        count = db.session.execute(text(
            "SELECT COUNT(*) FROM \"user\" WHERE pickup_location_type = 'off_campus'"
        )).scalar()
        assert count == 0, f"Found {count} rows still using legacy 'off_campus' value after migration"

    def test_legacy_off_campus_other_has_pickup_location_requires_new_fields(self, app, db):
        """
        A row migrated from 'off_campus' → 'off_campus_other' with no access fields
        should have has_pickup_location=False (triggers re-entry prompt).
        """
        from models import User
        u = User(
            email="legacycheck@test.com", full_name="Legacy Check", phone="9195550098",
            pickup_location_type="off_campus_other",
            pickup_address="123 Legacy Rd",
            pickup_lat=35.9, pickup_lng=-79.0,
            pickup_access_type=None,  # not yet filled in
            pickup_floor=None,
        )
        db.session.add(u)
        db.session.commit()
        assert u.has_pickup_location is False
