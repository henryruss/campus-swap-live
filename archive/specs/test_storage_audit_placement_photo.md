# Test Spec: Storage Audit + Driver Placement + Photo Refresh

Tests for `feature_storage_audit.md` and `feature_driver_placement_photo_refresh.md`.

Uses pytest + pytest-flask with in-memory SQLite. Follow existing fixture patterns from `conftest.py`.

---

## Fixtures Needed

These supplement existing fixtures. Add to `conftest.py` if not already present.

```python
@pytest.fixture
def storage_location(db):
    """Active, non-full storage location."""
    loc = StorageLocation(name="Unit A", address="123 Main St", is_active=True, is_full=False)
    db.session.add(loc)
    db.session.commit()
    return loc

@pytest.fixture
def full_storage_location(db):
    """Active but full storage location — should not appear in dropdowns."""
    loc = StorageLocation(name="Unit B (Full)", address="456 Main St", is_active=True, is_full=True)
    db.session.add(loc)
    db.session.commit()
    return loc

@pytest.fixture
def inactive_storage_location(db):
    """Inactive storage location — should not appear in dropdowns."""
    loc = StorageLocation(name="Unit C (Inactive)", address="789 Main St", is_active=False, is_full=False)
    db.session.add(loc)
    db.session.commit()
    return loc

@pytest.fixture
def campus_director(db):
    """Approved campus director — not is_admin, has is_campus_director=True."""
    user = User(email="cd@unc.edu", full_name="Campus Director", is_campus_director=True,
                is_admin=False, is_super_admin=False)
    user.set_password("password")
    db.session.add(user)
    db.session.commit()
    return user

@pytest.fixture
def approved_driver(db):
    """Approved worker assigned as driver on a shift."""
    user = User(email="driver@unc.edu", full_name="Test Driver",
                is_worker=True, worker_status="approved")
    user.set_password("password")
    db.session.add(user)
    db.session.commit()
    return user

@pytest.fixture
def item_with_location(db, seller, storage_location):
    """Item with storage_location_id and storage_row set."""
    item = InventoryItem(
        description="Blue Couch",
        seller_id=seller.id,
        status="available",
        storage_location_id=storage_location.id,
        storage_row="back_left"
    )
    db.session.add(item)
    db.session.commit()
    return item

@pytest.fixture
def item_without_location(db, seller):
    """Item with no storage location or zone assigned."""
    item = InventoryItem(
        description="Red Lamp",
        seller_id=seller.id,
        status="available"
    )
    db.session.add(item)
    db.session.commit()
    return item

@pytest.fixture
def shift_with_driver(db, approved_driver, storage_location):
    """
    Shift with:
    - 1 truck
    - approved_driver assigned as driver on truck 1
    - 1 ShiftPickup (completed stop) with 2 items
    - ShiftRun in_progress
    - truck_unit_plan set to storage_location
    """
    week = ShiftWeek(week_start=date(2026, 5, 27), status="published")
    db.session.add(week)
    db.session.flush()

    shift = Shift(week_id=week.id, day_of_week="tue", slot="am", trucks=1,
                  truck_unit_plan=json.dumps({"1": storage_location.id}))
    db.session.add(shift)
    db.session.flush()

    assignment = ShiftAssignment(shift_id=shift.id, worker_id=approved_driver.id,
                                 role_on_shift="driver", truck_number=1)
    db.session.add(assignment)

    seller = User(email="seller_stop@unc.edu", full_name="Stop Seller", is_seller=True)
    seller.set_password("x")
    db.session.add(seller)
    db.session.flush()

    pickup = ShiftPickup(shift_id=shift.id, seller_id=seller.id, truck_number=1,
                         status="completed", storage_location_id=storage_location.id,
                         created_by_id=approved_driver.id)
    db.session.add(pickup)
    db.session.flush()

    item1 = InventoryItem(description="Desk Chair", seller_id=seller.id,
                          status="available", picked_up_at=datetime.utcnow())
    item2 = InventoryItem(description="Floor Lamp", seller_id=seller.id,
                          status="available", picked_up_at=datetime.utcnow())
    db.session.add_all([item1, item2])
    db.session.flush()

    run = ShiftRun(shift_id=shift.id, started_by_id=approved_driver.id,
                   started_at=datetime.utcnow(), status="in_progress")
    db.session.add(run)
    db.session.commit()

    return {"shift": shift, "assignment": assignment, "pickup": pickup,
            "seller": seller, "items": [item1, item2], "run": run}
```

---

## Part 1: Storage Audit Tool

### Auth / Access

```python
def test_storage_audit_accessible_to_admin(client, admin_user):
    client.post("/login", data={"email": admin_user.email, "password": "password"})
    rv = client.get("/admin/storage/audit")
    assert rv.status_code == 200

def test_storage_audit_accessible_to_super_admin(client, super_admin):
    client.post("/login", data={"email": super_admin.email, "password": "password"})
    rv = client.get("/admin/storage/audit")
    assert rv.status_code == 200

def test_storage_audit_accessible_to_campus_director(client, campus_director):
    client.post("/login", data={"email": campus_director.email, "password": "password"})
    rv = client.get("/admin/storage/audit")
    assert rv.status_code == 200

def test_storage_audit_blocked_for_regular_user(client, seller):
    client.post("/login", data={"email": seller.email, "password": "password"})
    rv = client.get("/admin/storage/audit")
    assert rv.status_code in (302, 403)

def test_storage_audit_blocked_for_anonymous(client):
    rv = client.get("/admin/storage/audit")
    assert rv.status_code in (302, 401)
```

### Search — Numeric (ID lookup)

```python
def test_audit_search_by_id_returns_matching_item(client, admin_user, item_with_location):
    client.post("/login", data={"email": admin_user.email, "password": "password"})
    rv = client.get(f"/admin/storage/audit/search?q={item_with_location.id}")
    assert rv.status_code == 200
    assert b"Blue Couch" in rv.data
    assert str(item_with_location.id).encode() in rv.data

def test_audit_search_by_id_no_match_returns_empty(client, admin_user):
    client.post("/login", data={"email": admin_user.email, "password": "password"})
    rv = client.get("/admin/storage/audit/search?q=999999")
    assert rv.status_code == 200
    assert b"Blue Couch" not in rv.data

def test_audit_search_empty_query_returns_empty(client, admin_user):
    client.post("/login", data={"email": admin_user.email, "password": "password"})
    rv = client.get("/admin/storage/audit/search?q=")
    assert rv.status_code == 200
    # No error, just empty results
```

### Search — Text (title / seller name)

```python
def test_audit_search_by_title_ilike(client, admin_user, item_with_location):
    client.post("/login", data={"email": admin_user.email, "password": "password"})
    rv = client.get("/admin/storage/audit/search?q=blue")
    assert rv.status_code == 200
    assert b"Blue Couch" in rv.data

def test_audit_search_case_insensitive(client, admin_user, item_with_location):
    client.post("/login", data={"email": admin_user.email, "password": "password"})
    rv = client.get("/admin/storage/audit/search?q=BLUE")
    assert rv.status_code == 200
    assert b"Blue Couch" in rv.data

def test_audit_search_excludes_tutorial_users(client, admin_user, db):
    tutorial_user = User(email="tut@unc.edu", full_name="Tutorial User",
                         is_tutorial_user=True, is_seller=True)
    tutorial_user.set_password("x")
    db.session.add(tutorial_user)
    db.session.flush()
    tut_item = InventoryItem(description="Tutorial Lamp", seller_id=tutorial_user.id,
                              status="available")
    db.session.add(tut_item)
    db.session.commit()

    client.post("/login", data={"email": admin_user.email, "password": "password"})
    rv = client.get("/admin/storage/audit/search?q=Tutorial Lamp")
    assert b"Tutorial Lamp" not in rv.data
```

### Set Location — Success Cases

```python
def test_set_location_writes_to_item(client, admin_user, item_without_location, storage_location):
    client.post("/login", data={"email": admin_user.email, "password": "password"})
    rv = client.post(f"/admin/item/{item_without_location.id}/set_location", data={
        "storage_location_id": storage_location.id,
        "storage_row": "back_left",
        "storage_note": "shelf 2"
    })
    assert rv.status_code == 200
    data = rv.get_json()
    assert data["success"] is True

    db_item = InventoryItem.query.get(item_without_location.id)
    assert db_item.storage_location_id == storage_location.id
    assert db_item.storage_row == "back_left"
    assert db_item.storage_note == "shelf 2"

def test_set_location_campus_director_can_write(client, campus_director,
                                                 item_without_location, storage_location):
    client.post("/login", data={"email": campus_director.email, "password": "password"})
    rv = client.post(f"/admin/item/{item_without_location.id}/set_location", data={
        "storage_location_id": storage_location.id,
        "storage_row": "front_right"
    })
    assert rv.status_code == 200
    assert rv.get_json()["success"] is True

def test_set_location_clears_location_with_empty_string(client, admin_user,
                                                          item_with_location):
    client.post("/login", data={"email": admin_user.email, "password": "password"})
    rv = client.post(f"/admin/item/{item_with_location.id}/set_location", data={
        "storage_location_id": "",
        "storage_row": ""
    })
    assert rv.status_code == 200
    db_item = InventoryItem.query.get(item_with_location.id)
    assert db_item.storage_location_id is None
    assert db_item.storage_row is None

def test_set_location_all_six_zones_accepted(client, admin_user,
                                              item_without_location, storage_location):
    valid_zones = ["back_left", "middle_left", "front_left",
                   "back_right", "middle_right", "front_right"]
    client.post("/login", data={"email": admin_user.email, "password": "password"})
    for zone in valid_zones:
        rv = client.post(f"/admin/item/{item_without_location.id}/set_location", data={
            "storage_location_id": storage_location.id,
            "storage_row": zone
        })
        assert rv.status_code == 200, f"Zone {zone} was rejected"
        assert rv.get_json()["success"] is True
```

### Set Location — Validation Failures

```python
def test_set_location_rejects_invalid_zone(client, admin_user,
                                            item_without_location, storage_location):
    client.post("/login", data={"email": admin_user.email, "password": "password"})
    rv = client.post(f"/admin/item/{item_without_location.id}/set_location", data={
        "storage_location_id": storage_location.id,
        "storage_row": "shelf_3"  # free-text, not a valid enum value
    })
    assert rv.status_code == 400

def test_set_location_rejects_inactive_location(client, admin_user,
                                                  item_without_location,
                                                  inactive_storage_location):
    client.post("/login", data={"email": admin_user.email, "password": "password"})
    rv = client.post(f"/admin/item/{item_without_location.id}/set_location", data={
        "storage_location_id": inactive_storage_location.id,
        "storage_row": "back_left"
    })
    assert rv.status_code == 400

def test_set_location_blocked_for_regular_user(client, seller, item_without_location,
                                                storage_location):
    client.post("/login", data={"email": seller.email, "password": "password"})
    rv = client.post(f"/admin/item/{item_without_location.id}/set_location", data={
        "storage_location_id": storage_location.id,
        "storage_row": "back_left"
    })
    assert rv.status_code in (302, 403)
```

### Does NOT Touch Intake Fields

```python
def test_set_location_does_not_write_arrived_at_store_at(client, admin_user,
                                                           item_without_location,
                                                           storage_location):
    client.post("/login", data={"email": admin_user.email, "password": "password"})
    client.post(f"/admin/item/{item_without_location.id}/set_location", data={
        "storage_location_id": storage_location.id,
        "storage_row": "mid_left"
    })
    db_item = InventoryItem.query.get(item_without_location.id)
    assert db_item.arrived_at_store_at is None

def test_set_location_does_not_create_intake_record(client, admin_user,
                                                      item_without_location,
                                                      storage_location, db):
    count_before = IntakeRecord.query.count()
    client.post("/login", data={"email": admin_user.email, "password": "password"})
    client.post(f"/admin/item/{item_without_location.id}/set_location", data={
        "storage_location_id": storage_location.id,
        "storage_row": "front_left"
    })
    assert IntakeRecord.query.count() == count_before
```

### Admin Items — ID Filter

```python
def test_admin_items_filter_by_id(client, admin_user, item_with_location,
                                   item_without_location):
    client.post("/login", data={"email": admin_user.email, "password": "password"})
    rv = client.get(f"/admin/items?item_id={item_with_location.id}")
    assert rv.status_code == 200
    assert b"Blue Couch" in rv.data
    assert b"Red Lamp" not in rv.data

def test_admin_items_id_filter_no_match_returns_empty_table(client, admin_user):
    client.post("/login", data={"email": admin_user.email, "password": "password"})
    rv = client.get("/admin/items?item_id=999999")
    assert rv.status_code == 200
    # Table renders without error, no items shown
```

---

## Part 2: Driver Item Placement Flow

### Placement List

```python
def test_placement_list_returns_items_from_completed_stops(client, approved_driver,
                                                             shift_with_driver):
    client.post("/login", data={"email": approved_driver.email, "password": "password"})
    shift_id = shift_with_driver["shift"].id
    rv = client.get(f"/crew/shift/{shift_id}/placement")
    assert rv.status_code == 200
    assert b"Desk Chair" in rv.data
    assert b"Floor Lamp" in rv.data

def test_placement_list_blocked_for_non_worker(client, seller, shift_with_driver):
    client.post("/login", data={"email": seller.email, "password": "password"})
    rv = client.get(f"/crew/shift/{shift_with_driver['shift'].id}/placement")
    assert rv.status_code in (302, 403)

def test_placement_list_shows_correct_default_unit(client, approved_driver,
                                                    shift_with_driver, storage_location):
    client.post("/login", data={"email": approved_driver.email, "password": "password"})
    rv = client.get(f"/crew/shift/{shift_with_driver['shift'].id}/placement")
    assert storage_location.name.encode() in rv.data

def test_placement_list_excludes_full_locations_from_dropdown(client, approved_driver,
                                                               shift_with_driver,
                                                               full_storage_location):
    client.post("/login", data={"email": approved_driver.email, "password": "password"})
    rv = client.get(f"/crew/shift/{shift_with_driver['shift'].id}/placement")
    assert full_storage_location.name.encode() not in rv.data
```

### Place Item — Success

```python
def test_place_item_writes_location_and_zone(client, approved_driver,
                                              shift_with_driver, storage_location):
    client.post("/login", data={"email": approved_driver.email, "password": "password"})
    item = shift_with_driver["items"][0]
    rv = client.post(f"/crew/item/{item.id}/place", data={
        "storage_location_id": storage_location.id,
        "storage_row": "middle_right"
    })
    assert rv.status_code == 200
    assert rv.get_json()["success"] is True

    db_item = InventoryItem.query.get(item.id)
    assert db_item.storage_location_id == storage_location.id
    assert db_item.storage_row == "middle_right"
    assert db_item.placement_status == "placed"

def test_place_item_driver_can_override_unit(client, approved_driver,
                                              shift_with_driver, db,
                                              inactive_storage_location):
    # Create a second active location to represent overflow unit
    overflow = StorageLocation(name="Overflow Unit", address="overflow",
                                is_active=True, is_full=False)
    db.session.add(overflow)
    db.session.commit()

    client.post("/login", data={"email": approved_driver.email, "password": "password"})
    item = shift_with_driver["items"][0]
    rv = client.post(f"/crew/item/{item.id}/place", data={
        "storage_location_id": overflow.id,
        "storage_row": "back_right"
    })
    assert rv.status_code == 200
    db_item = InventoryItem.query.get(item.id)
    assert db_item.storage_location_id == overflow.id

def test_place_item_persists_after_re_entry(client, approved_driver,
                                             shift_with_driver, storage_location):
    """Previously placed items show correct state on reload."""
    client.post("/login", data={"email": approved_driver.email, "password": "password"})
    item = shift_with_driver["items"][0]
    client.post(f"/crew/item/{item.id}/place", data={
        "storage_location_id": storage_location.id,
        "storage_row": "front_left"
    })

    # Re-fetch placement list
    rv = client.get(f"/crew/shift/{shift_with_driver['shift'].id}/placement")
    assert rv.status_code == 200
    # Item should show as placed — check for data-placement-status="placed" or status label
    assert b"placed" in rv.data.lower() or b"Placed" in rv.data
```

### Place Item — Validation

```python
def test_place_item_rejects_invalid_zone(client, approved_driver,
                                          shift_with_driver, storage_location):
    client.post("/login", data={"email": approved_driver.email, "password": "password"})
    item = shift_with_driver["items"][0]
    rv = client.post(f"/crew/item/{item.id}/place", data={
        "storage_location_id": storage_location.id,
        "storage_row": "shelf_A"
    })
    assert rv.status_code == 400

def test_place_item_rejects_inactive_location(client, approved_driver,
                                               shift_with_driver,
                                               inactive_storage_location):
    client.post("/login", data={"email": approved_driver.email, "password": "password"})
    item = shift_with_driver["items"][0]
    rv = client.post(f"/crew/item/{item.id}/place", data={
        "storage_location_id": inactive_storage_location.id,
        "storage_row": "back_left"
    })
    assert rv.status_code == 400

def test_place_item_blocked_for_non_worker(client, seller, shift_with_driver,
                                            storage_location):
    client.post("/login", data={"email": seller.email, "password": "password"})
    item = shift_with_driver["items"][0]
    rv = client.post(f"/crew/item/{item.id}/place", data={
        "storage_location_id": storage_location.id,
        "storage_row": "back_left"
    })
    assert rv.status_code in (302, 403)
```

### Not Picked Up

```python
def test_not_picked_up_sets_placement_status(client, approved_driver,
                                              shift_with_driver):
    client.post("/login", data={"email": approved_driver.email, "password": "password"})
    item = shift_with_driver["items"][0]
    rv = client.post(f"/crew/item/{item.id}/not_picked_up")
    assert rv.status_code == 200
    assert rv.get_json()["success"] is True

    db_item = InventoryItem.query.get(item.id)
    assert db_item.placement_status == "not_picked_up"

def test_not_picked_up_clears_location_if_not_intake_confirmed(client, approved_driver,
                                                                  shift_with_driver,
                                                                  storage_location, db):
    """If item was tentatively placed but not intake-confirmed, location is cleared."""
    item = shift_with_driver["items"][0]
    # Manually set a location (simulating a prior place action, no arrived_at_store_at)
    item.storage_location_id = storage_location.id
    item.storage_row = "back_left"
    db.session.commit()

    client.post("/login", data={"email": approved_driver.email, "password": "password"})
    client.post(f"/crew/item/{item.id}/not_picked_up")

    db_item = InventoryItem.query.get(item.id)
    assert db_item.storage_location_id is None
    assert db_item.storage_row is None

def test_not_picked_up_preserves_location_if_intake_confirmed(client, approved_driver,
                                                                shift_with_driver,
                                                                storage_location, db):
    """If arrived_at_store_at is set (organizer already intake'd it), don't clear location."""
    item = shift_with_driver["items"][0]
    item.storage_location_id = storage_location.id
    item.storage_row = "back_left"
    item.arrived_at_store_at = datetime.utcnow()
    db.session.commit()

    client.post("/login", data={"email": approved_driver.email, "password": "password"})
    client.post(f"/crew/item/{item.id}/not_picked_up")

    db_item = InventoryItem.query.get(item.id)
    # Location preserved because intake already confirmed it
    assert db_item.storage_location_id == storage_location.id
```

### End Shift Guard

```python
def test_end_shift_blocked_when_items_unplaced(client, approved_driver,
                                                shift_with_driver):
    """Cannot end shift while any item still has placement_status=None."""
    client.post("/login", data={"email": approved_driver.email, "password": "password"})
    shift_id = shift_with_driver["shift"].id
    rv = client.post(f"/crew/shift/{shift_id}/complete")
    assert rv.status_code == 400

def test_end_shift_allowed_when_all_items_placed(client, approved_driver,
                                                  shift_with_driver, storage_location, db):
    items = shift_with_driver["items"]
    for item in items:
        item.storage_location_id = storage_location.id
        item.storage_row = "back_left"
        item.placement_status = "placed"
    db.session.commit()

    client.post("/login", data={"email": approved_driver.email, "password": "password"})
    shift_id = shift_with_driver["shift"].id
    rv = client.post(f"/crew/shift/{shift_id}/complete")
    assert rv.status_code in (200, 302)

def test_end_shift_allowed_when_all_items_not_picked_up(client, approved_driver,
                                                          shift_with_driver, db):
    items = shift_with_driver["items"]
    for item in items:
        item.placement_status = "not_picked_up"
    db.session.commit()

    client.post("/login", data={"email": approved_driver.email, "password": "password"})
    rv = client.post(f"/crew/shift/{shift_with_driver['shift'].id}/complete")
    assert rv.status_code in (200, 302)

def test_end_shift_allowed_mixed_placed_and_not_picked_up(client, approved_driver,
                                                            shift_with_driver,
                                                            storage_location, db):
    items = shift_with_driver["items"]
    items[0].placement_status = "placed"
    items[0].storage_location_id = storage_location.id
    items[0].storage_row = "front_right"
    items[1].placement_status = "not_picked_up"
    db.session.commit()

    client.post("/login", data={"email": approved_driver.email, "password": "password"})
    rv = client.post(f"/crew/shift/{shift_with_driver['shift'].id}/complete")
    assert rv.status_code in (200, 302)

def test_end_shift_sets_completed_at_on_assignment(client, approved_driver,
                                                    shift_with_driver, storage_location, db):
    items = shift_with_driver["items"]
    for item in items:
        item.placement_status = "placed"
        item.storage_location_id = storage_location.id
        item.storage_row = "back_left"
    db.session.commit()

    client.post("/login", data={"email": approved_driver.email, "password": "password"})
    rv = client.post(f"/crew/shift/{shift_with_driver['shift'].id}/complete")
    assert rv.status_code in (200, 302)

    assignment = shift_with_driver["assignment"]
    db.session.refresh(assignment)
    assert assignment.completed_at is not None
```

### Zone Enum Shared Helper

```python
def test_zone_enum_helper_accepts_all_valid_values():
    """_validate_storage_zone() returns True for all 6 valid zone strings."""
    from app import _validate_storage_zone
    valid = ["back_left", "middle_left", "front_left",
             "back_right", "middle_right", "front_right"]
    for zone in valid:
        assert _validate_storage_zone(zone) is True

def test_zone_enum_helper_rejects_free_text():
    from app import _validate_storage_zone
    assert _validate_storage_zone("shelf_3") is False
    assert _validate_storage_zone("A1") is False
    assert _validate_storage_zone("") is False
    assert _validate_storage_zone(None) is False
```

---

## Part 3: Inventory Photo Refresh

### Replace Photo — Success

```python
def test_replace_photo_sets_needs_photo_refresh(client, admin_user,
                                                  item_without_location, tmp_path):
    client.post("/login", data={"email": admin_user.email, "password": "password"})

    # Create a minimal JPEG-like file for upload
    fake_image = (tmp_path / "test.jpg")
    fake_image.write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)  # minimal JPEG header

    with open(fake_image, "rb") as f:
        rv = client.post(
            f"/admin/item/{item_without_location.id}/replace_photo",
            data={"photo": (f, "test.jpg")},
            content_type="multipart/form-data"
        )

    assert rv.status_code == 200
    data = rv.get_json()
    assert data["success"] is True

    db_item = InventoryItem.query.get(item_without_location.id)
    assert db_item.needs_photo_refresh is True

def test_replace_photo_updates_photo_url(client, admin_user,
                                          item_without_location, tmp_path):
    client.post("/login", data={"email": admin_user.email, "password": "password"})
    original_url = item_without_location.photo_url

    fake_image = tmp_path / "new_photo.jpg"
    fake_image.write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)

    with open(fake_image, "rb") as f:
        client.post(
            f"/admin/item/{item_without_location.id}/replace_photo",
            data={"photo": (f, "new_photo.jpg")},
            content_type="multipart/form-data"
        )

    db_item = InventoryItem.query.get(item_without_location.id)
    assert db_item.photo_url != original_url
    assert db_item.photo_url is not None

def test_replace_photo_campus_director_can_upload(client, campus_director,
                                                    item_without_location, tmp_path):
    client.post("/login", data={"email": campus_director.email, "password": "password"})

    fake_image = tmp_path / "cd_photo.jpg"
    fake_image.write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)

    with open(fake_image, "rb") as f:
        rv = client.post(
            f"/admin/item/{item_without_location.id}/replace_photo",
            data={"photo": (f, "cd_photo.jpg")},
            content_type="multipart/form-data"
        )
    assert rv.status_code == 200
    assert rv.get_json()["success"] is True
```

### Replace Photo — Auth / Validation

```python
def test_replace_photo_blocked_for_seller(client, seller,
                                           item_without_location, tmp_path):
    client.post("/login", data={"email": seller.email, "password": "password"})
    fake_image = tmp_path / "bad.jpg"
    fake_image.write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)

    with open(fake_image, "rb") as f:
        rv = client.post(
            f"/admin/item/{item_without_location.id}/replace_photo",
            data={"photo": (f, "bad.jpg")},
            content_type="multipart/form-data"
        )
    assert rv.status_code in (302, 403)

def test_replace_photo_does_not_touch_gallery_photos(client, admin_user,
                                                       item_without_location,
                                                       db, tmp_path):
    """Gallery photos (ItemPhoto records) are not modified."""
    gallery_photo = ItemPhoto(item_id=item_without_location.id,
                               photo_url="/var/data/gallery1.jpg")
    db.session.add(gallery_photo)
    db.session.commit()
    count_before = ItemPhoto.query.filter_by(item_id=item_without_location.id).count()

    client.post("/login", data={"email": admin_user.email, "password": "password"})
    fake_image = tmp_path / "cover.jpg"
    fake_image.write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)

    with open(fake_image, "rb") as f:
        client.post(
            f"/admin/item/{item_without_location.id}/replace_photo",
            data={"photo": (f, "cover.jpg")},
            content_type="multipart/form-data"
        )

    count_after = ItemPhoto.query.filter_by(item_id=item_without_location.id).count()
    assert count_after == count_before
```

### Needs Refresh Filter on Admin Items

```python
def test_admin_items_needs_refresh_filter(client, admin_user, db, seller):
    item_needs_refresh = InventoryItem(description="Needs BG Replace",
                                        seller_id=seller.id, status="available",
                                        needs_photo_refresh=True)
    item_clean = InventoryItem(description="Clean Photo",
                                seller_id=seller.id, status="available",
                                needs_photo_refresh=False)
    db.session.add_all([item_needs_refresh, item_clean])
    db.session.commit()

    client.post("/login", data={"email": admin_user.email, "password": "password"})
    rv = client.get("/admin/items?needs_refresh=1")
    assert rv.status_code == 200
    assert b"Needs BG Replace" in rv.data
    assert b"Clean Photo" not in rv.data

def test_admin_items_needs_refresh_filter_off_shows_all(client, admin_user, db, seller):
    item_needs_refresh = InventoryItem(description="Needs BG Replace",
                                        seller_id=seller.id, status="available",
                                        needs_photo_refresh=True)
    item_clean = InventoryItem(description="Clean Photo",
                                seller_id=seller.id, status="available",
                                needs_photo_refresh=False)
    db.session.add_all([item_needs_refresh, item_clean])
    db.session.commit()

    client.post("/login", data={"email": admin_user.email, "password": "password"})
    rv = client.get("/admin/items")
    assert b"Needs BG Replace" in rv.data
    assert b"Clean Photo" in rv.data

def test_needs_refresh_filter_combines_with_id_filter(client, admin_user, db, seller):
    """Both filters can be active simultaneously."""
    item = InventoryItem(description="Targeted Item", seller_id=seller.id,
                          status="available", needs_photo_refresh=True)
    db.session.add(item)
    db.session.commit()

    client.post("/login", data={"email": admin_user.email, "password": "password"})
    rv = client.get(f"/admin/items?item_id={item.id}&needs_refresh=1")
    assert rv.status_code == 200
    assert b"Targeted Item" in rv.data
```

### Regression — Seller Upload Flow Unaffected

```python
def test_seller_upload_does_not_set_needs_photo_refresh(client, seller, db):
    """Normal seller item submission never sets needs_photo_refresh=True."""
    # This test verifies the field defaults to False on any item not
    # touched by the replace_photo route.
    item = InventoryItem(description="Seller Item", seller_id=seller.id,
                          status="pending_valuation")
    db.session.add(item)
    db.session.commit()

    db_item = InventoryItem.query.get(item.id)
    assert db_item.needs_photo_refresh is False
```
