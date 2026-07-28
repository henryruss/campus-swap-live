"""
Year 1 Investor Board Report — one-time historical data pull.
Spec: report_investor_board_yearone.md

Read-only. Writes one JSON file per section to /tmp/board_report/ and prints a
plain-text summary to stdout.

Run:  python scripts/board_report_pull.py

DATA-REALITY DEVIATIONS FROM THE SPEC (see section_0_integrity.json for the full list):
  * arrived_at_store_at is effectively unused in production (2 rows, both with a NULL
    storage_location_id). The spec's Stage C definition therefore returns 0. We report
    the spec-literal number AND a storage_location_id-based Stage C, and use the latter
    as the headline. Same substitution for Section 1's date range.
  * IntakeFlag is empty (0 rows) — no damaged/missing reasons exist to cross-reference.
  * Neither Stage B+ mechanism named in the spec is the dominant one in production.
  * picked_up_at is unreliable: real-seller items sit in storage without it set.
"""
import json
import os
import sys
from collections import OrderedDict
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import (  # noqa: E402
    app, db, _rephoto_campaign_start_utc, _unit_metrics, _unit_sqft,
)
from models import (  # noqa: E402
    User, InventoryItem, InventoryCategory, ItemPhoto, StorageLocation,
    IntakeRecord, IntakeFlag, Shift, ShiftWeek, ShiftPickup, ShiftAssignment,
)
from sqlalchemy import and_, func, or_  # noqa: E402

OUT_DIR = '/tmp/board_report'
SECTIONS = OrderedDict()


def emit(name, payload):
    SECTIONS[name] = payload


def real_seller_ids():
    """Seller/user ids that count as real activity (not internal/tutorial)."""
    return db.session.query(User.id).filter(
        User.is_internal_account == False,  # noqa: E712
        User.is_tutorial_user == False,     # noqa: E712
    )


def real_items():
    """Base population: items owned by a real (non-internal, non-tutorial) seller."""
    return InventoryItem.query.filter(
        InventoryItem.seller_id.in_(real_seller_ids()),
        InventoryItem.date_added.isnot(None),
    )


def rephotographed_clause():
    """At least one warehouse re-photography campaign photo (captured_at on/after
    the campaign start). Mirrors app._rephotographed_clause but pins the date."""
    return InventoryItem.id.in_(
        db.session.query(ItemPhoto.item_id)
        .filter(ItemPhoto.captured_at.isnot(None),
                ItemPhoto.captured_at >= _rephoto_campaign_start_utc())
        .distinct()
    )


def live_shop_clause():
    """The ACTUAL buyer-facing filter used by /shop (app.py shop route), minus the
    stock-group collapse (which hides duplicate cards, not items)."""
    kept_or_matched = or_(
        InventoryItem.seller_id.in_(
            db.session.query(User.id).filter(User.is_internal_account == False)),  # noqa: E712
        InventoryItem.rephoto_disposition == 'kept',
    )
    return and_(
        InventoryItem.ai_approved == True,          # noqa: E712
        InventoryItem.status == 'available',
        InventoryItem.needs_new_photo == False,     # noqa: E712
        InventoryItem.status != 'rejected',
        InventoryItem.price.isnot(None),
        InventoryItem.price > 0,
        InventoryItem.storage_location_id.isnot(None),
        InventoryItem.rephoto_disposition.is_distinct_from('discarded'),
        rephotographed_clause(),
        kept_or_matched,
    )


# ─────────────────────────────────────────────────────────────────────────────
def section_0_integrity():
    """Field-health checks that determine how every other section must be read."""
    arrived = InventoryItem.query.filter(InventoryItem.arrived_at_store_at.isnot(None))
    arrived_and_stored = arrived.filter(InventoryItem.storage_location_id.isnot(None))
    stored_no_pickup = real_items().filter(
        InventoryItem.storage_location_id.isnot(None),
        InventoryItem.picked_up_at.is_(None)).count()

    internal_kept_live = InventoryItem.query.filter(
        InventoryItem.seller_id.in_(
            db.session.query(User.id).filter(User.is_internal_account == True)),  # noqa: E712
        live_shop_clause()).count()

    payload = {
        'arrived_at_store_at_rows_total': arrived.count(),
        'arrived_at_store_at_AND_storage_location_rows': arrived_and_stored.count(),
        'spec_stage_c_literal_count': arrived_and_stored.filter(
            InventoryItem.seller_id.in_(real_seller_ids())).count(),
        'intake_record_rows': IntakeRecord.query.count(),
        'intake_flag_rows': IntakeFlag.query.count(),
        'real_seller_items_in_storage_without_picked_up_at': stored_no_pickup,
        'internal_account_items_live_in_shop': internal_kept_live,
        'rephoto_campaign_start_utc': _rephoto_campaign_start_utc().isoformat(),
        'item_status_values_present': dict(
            db.session.query(InventoryItem.status, func.count())
            .group_by(InventoryItem.status).all()),
        'notes': [
            "arrived_at_store_at is a dead field in production: only 2 rows have it set and "
            "both have storage_location_id NULL, so the spec's Stage C (arrived_at_store_at "
            "AND storage_location_id) returns 0. Stage C is reported on storage_location_id.",
            "IntakeRecord/IntakeFlag are empty — the organizer intake page is deprecated "
            "(see CLAUDE.md), so no damaged/missing reasons exist to cross-reference.",
            "picked_up_at is set on a minority of items even when they are physically in "
            "storage, so Stage B undercounts real collection. Funnel monotonicity between "
            "Stage B and Stage C does NOT hold and cannot be made to hold from this data.",
            "Excluding is_internal_account items (per spec) also removes Campus-Swap-owned "
            "'kept' rephoto items that are genuinely live in the shop — counted here.",
            "status 'pending_logistics' exists in production but is absent from the spec's "
            "Section 2b status list; it is included in the per-status breakdowns.",
        ],
    }
    emit('section_0_integrity', payload)
    return payload


def section_1_glance(funnel):
    stored = real_items().filter(InventoryItem.storage_location_id.isnot(None))
    dmin, dmax = db.session.query(
        func.min(InventoryItem.date_added), func.max(InventoryItem.date_added)
    ).filter(InventoryItem.seller_id.in_(real_seller_ids())).one()
    amin, amax = db.session.query(
        func.min(InventoryItem.arrived_at_store_at), func.max(InventoryItem.arrived_at_store_at)
    ).one()

    payload = {
        'items_currently_in_storage': stored.count(),
        'items_currently_in_storage_label':
            'Items currently in storage (not items listed, not items live in shop)',
        'total_unique_sellers': db.session.query(
            func.count(func.distinct(InventoryItem.seller_id))).filter(
            InventoryItem.seller_id.in_(real_seller_ids()),
            InventoryItem.date_added.isnot(None)).scalar(),
        'date_range_source': 'date_added (SUBSTITUTED — see note)',
        'date_range_start': dmin.isoformat() if dmin else None,
        'date_range_end': dmax.isoformat() if dmax else None,
        'spec_date_range_arrived_at_store_at_start': amin.isoformat() if amin else None,
        'spec_date_range_arrived_at_store_at_end': amax.isoformat() if amax else None,
        'narrative_frame': 'inventory built and ready to sell — not a sales result',
        'note': 'The spec asked for min/max(arrived_at_store_at). Only 2 items in the entire '
                'database have that field set, so the range it produces is meaningless. '
                'date_added is used instead and both are reported.',
    }
    emit('section_1_glance', payload)
    return payload


def section_2_funnel():
    base = real_items()
    stage_a = base.count()
    seller_submitted = base.filter(InventoryItem.is_quick_capture == False).count()  # noqa: E712
    crew_created = base.filter(InventoryItem.is_quick_capture == True).count()       # noqa: E712

    stage_b = base.filter(InventoryItem.picked_up_at.isnot(None)).count()
    never_picked = base.filter(InventoryItem.picked_up_at.is_(None)).count()

    # Stage B+ — actual production mechanisms (verified against app.py creation paths)
    field_qc = base.filter(InventoryItem.is_quick_capture == True,                   # noqa: E712
                           InventoryItem.quick_capture_shift_id.isnot(None)).count()
    warehouse_logged = base.filter(
        InventoryItem.is_quick_capture == True,                                      # noqa: E712
        InventoryItem.quick_capture_shift_id.is_(None),
        InventoryItem.picked_up_at.isnot(None)).count()
    matched_rephoto_stubs = base.filter(
        InventoryItem.is_quick_capture == True,                                      # noqa: E712
        InventoryItem.quick_capture_shift_id.is_(None),
        InventoryItem.picked_up_at.is_(None)).count()
    unknown_item_flags = IntakeFlag.query.filter(
        IntakeFlag.flag_type.in_(['unknown_item', 'extra_item'])).count()

    stage_c = base.filter(InventoryItem.storage_location_id.isnot(None)).count()
    stage_c_spec_literal = base.filter(
        InventoryItem.arrived_at_store_at.isnot(None),
        InventoryItem.storage_location_id.isnot(None)).count()
    picked_not_stored = base.filter(
        InventoryItem.picked_up_at.isnot(None),
        InventoryItem.storage_location_id.is_(None)).count()

    rejected_total = base.filter(InventoryItem.status == 'rejected').count()
    rejected_before_pickup = base.filter(InventoryItem.status == 'rejected',
                                         InventoryItem.picked_up_at.is_(None)).count()
    rejected_after_storage = base.filter(InventoryItem.status == 'rejected',
                                         InventoryItem.storage_location_id.isnot(None)).count()
    rejected_flag_reasons = dict(
        db.session.query(IntakeFlag.flag_type, func.count())
        .filter(IntakeFlag.flag_type.in_(['damaged', 'missing']))
        .group_by(IntakeFlag.flag_type).all())

    stage_d = base.filter(rephotographed_clause()).count()
    stage_e_spec = base.filter(
        InventoryItem.ai_approved == True,                                           # noqa: E712
        InventoryItem.needs_new_photo == False,                                      # noqa: E712
        InventoryItem.status != 'rejected',
        InventoryItem.price.isnot(None),
        InventoryItem.price > 0,
        InventoryItem.storage_location_id.isnot(None)).count()
    stage_e_live = base.filter(live_shop_clause()).count()
    stage_e_live_all_owners = InventoryItem.query.filter(live_shop_clause()).count()

    payload = {
        'population': 'items with date_added set, owned by a non-internal non-tutorial seller',
        'stages': [
            {'stage': 'A', 'label': 'Items listed', 'count': stage_a,
             'additions': None, 'losses': None,
             'breakdown': {'seller_submitted': seller_submitted,
                           'crew_created_at_warehouse_or_field': crew_created},
             'caption': f'{stage_a} items entered the system — {seller_submitted} submitted by '
                        f'sellers online, {crew_created} created by crew in the field or at '
                        f'the warehouse.'},
            {'stage': 'B', 'label': 'Items with a recorded pickup (picked_up_at set)',
             'count': stage_b, 'additions': 0, 'losses': never_picked,
             'caption': f'{stage_b} items carry a pickup timestamp; {never_picked} do not. '
                        f'This gap is NOT all no-shows — picked_up_at was inconsistently '
                        f'recorded, and many untimestamped items are physically in storage.',
             'reliability': 'LOW — see section_0_integrity'},
            {'stage': 'B+', 'label': 'Extra items collected beyond the original listing',
             'count': field_qc + warehouse_logged + matched_rephoto_stubs,
             'additions': field_qc + warehouse_logged + matched_rephoto_stubs, 'losses': 0,
             'breakdown': {
                 'field_quick_capture_with_shift': field_qc,
                 'warehouse_logged_items': warehouse_logged,
                 'matched_rephoto_stubs': matched_rephoto_stubs,
                 'intake_unknown_or_extra_item_flags': unknown_item_flags},
             'caption': f'{field_qc} item captured by a mover in the field; {warehouse_logged} '
                        f'logged directly at the warehouse; {matched_rephoto_stubs} created as '
                        f're-photography stubs and later matched to a real seller. The intake '
                        f'"unknown item" mechanism the spec named produced 0 records.',
             'mechanism_note': 'Neither of the two candidate mechanisms in the spec is the '
                               'dominant one. Three creation paths set is_quick_capture=True: '
                               'crew_quick_capture (field), admin_warehouse_log_item '
                               '(warehouse), admin_rephoto_create_stub (rephoto). IntakeFlag '
                               'is empty, so the unknown-item path contributed nothing.'},
            {'stage': 'C', 'label': 'Items in storage (storage_location_id set)',
             'count': stage_c, 'additions': None, 'losses': picked_not_stored,
             'spec_literal_count': stage_c_spec_literal,
             'caption': f'{stage_c} items are logged into a storage location. '
                        f'{picked_not_stored} items have a pickup timestamp but no storage '
                        f'location. The spec\'s definition (arrived_at_store_at AND '
                        f'storage_location_id) yields {stage_c_spec_literal} because '
                        f'arrived_at_store_at is unused in production.'},
            {'stage': 'C-minus', 'label': 'Items deemed unsellable (rejected)',
             'count': rejected_total, 'additions': 0, 'losses': rejected_total,
             'breakdown': {'rejected_before_pickup': rejected_before_pickup,
                           'rejected_after_arriving_in_storage': rejected_after_storage,
                           'intake_flag_reasons': rejected_flag_reasons or {'damaged': 0,
                                                                           'missing': 0}},
             'caption': f'{rejected_total} items rejected — {rejected_before_pickup} before '
                        f'pickup, {rejected_after_storage} after reaching storage. No '
                        f'damaged/missing intake flags exist to explain why.'},
            {'stage': 'D', 'label': 'Re-photographed under the warehouse campaign',
             'count': stage_d, 'additions': None, 'losses': None,
             'signal': 'ItemPhoto.captured_at >= rephoto_campaign_start',
             'caption': f'{stage_d} items have at least one campaign photo taken on or after '
                        f'{_rephoto_campaign_start_utc().date()}.'},
            {'stage': 'E', 'label': 'Live in shop (buyer-visible)',
             'count': stage_e_live, 'additions': None, 'losses': stage_d - stage_e_live,
             'spec_filter_count': stage_e_spec,
             'live_filter_count_all_owners': stage_e_live_all_owners,
             'caption': f'{stage_e_live} real-seller items are buyer-visible right now under '
                        f'the actual /shop filter. Including Campus-Swap-owned "kept" items, '
                        f'{stage_e_live_all_owners} items are live in the shop in total.',
             'filter_note': "The spec's Stage E filter omits status=='available', the "
                            "discarded-disposition exclusion, the re-photographed gate and "
                            "the matched-or-kept gate that /shop actually applies; the "
                            "spec-literal number is reported alongside the real one."},
        ],
    }
    emit('section_2_funnel', payload)
    return payload


def section_2b_composition():
    """Base population: PHYSICAL items in storage, all owners (seller-owned and
    Campus-Swap-owned), deduplicated on rephoto replacement so this total matches
    the reconciliation in section 8. Tutorial accounts excluded."""
    tutorial = db.session.query(User.id).filter(User.is_tutorial_user == True)  # noqa: E712
    internal = db.session.query(User.id).filter(User.is_internal_account == True)  # noqa: E712
    base_filters = (
        InventoryItem.seller_id.notin_(tutorial),
        InventoryItem.date_added.isnot(None),
        InventoryItem.storage_location_id.isnot(None),
        InventoryItem.replaced_by_item_id.is_(None),
    )
    rows = db.session.query(
        InventoryItem.category_id, InventoryCategory.name, InventoryItem.status, func.count()
    ).outerjoin(InventoryCategory, InventoryCategory.id == InventoryItem.category_id).filter(
        *base_filters).group_by(InventoryItem.category_id, InventoryCategory.name,
                                InventoryItem.status).all()
    owner_rows = db.session.query(
        InventoryItem.category_id, func.count()
    ).filter(*base_filters, InventoryItem.seller_id.in_(internal)).group_by(
        InventoryItem.category_id).all()
    cs_by_cat = {cid or 0: n for cid, n in owner_rows}

    cats = {}
    for cat_id, cat_name, status, n in rows:
        key = cat_id or 0
        c = cats.setdefault(key, {'category_id': cat_id,
                                  'category_name': cat_name or 'Uncategorized',
                                  'total': 0, 'by_status': {}})
        c['total'] += n
        c['by_status'][status] = c['by_status'].get(status, 0) + n
    for key, c in cats.items():
        c['campus_swap_items'] = cs_by_cat.get(key, 0)
        c['seller_items'] = c['total'] - c['campus_swap_items']

    all_statuses = ['pending_valuation', 'needs_info', 'approved', 'available',
                    'rejected', 'pending_logistics']
    for c in cats.values():
        for s in all_statuses:
            c['by_status'].setdefault(s, 0)

    categories = sorted(cats.values(), key=lambda c: c['total'], reverse=True)
    grand = {'total': sum(c['total'] for c in categories),
             'by_status': {s: sum(c['by_status'][s] for c in categories) for s in all_statuses}}

    payload = {
        'base_population': 'PHYSICAL items in storage, all owners, rephoto-deduplicated',
        'note': 'This predates the re-photography / shop-eligibility filtering applied in '
                'Section 2 Stages D and E. Total ties to section 8 physical_items_in_storage.',
        'categories': categories,
        'grand_total': grand,
    }
    emit('section_2b_composition', payload)
    return payload


def section_3_origin():
    rows = db.session.query(User.pickup_location_type, func.count(InventoryItem.id)).join(
        InventoryItem, InventoryItem.seller_id == User.id).filter(
        InventoryItem.seller_id.in_(real_seller_ids()),
        InventoryItem.date_added.isnot(None)).group_by(User.pickup_location_type).all()

    buckets = {'on_campus': 0, 'off_campus_complex': 0, 'off_campus_other': 0, 'not_set': 0}
    for loc, n in rows:
        buckets[loc if loc in buckets else 'not_set'] += n
    total = sum(buckets.values())

    payload = {
        'base_population': 'Stage A — all listed items by real sellers',
        'total_items': total,
        'buckets': [{'bucket': k, 'item_count': v,
                     'pct_of_total': round(100.0 * v / total, 1) if total else 0.0}
                    for k, v in buckets.items()],
        'footnote': 'Reflects the seller\'s registered pickup_location_type, not a per-item '
                    'verification of dwelling type.',
        'note': 'A fourth "not_set" bucket was required — pickup_location_type is NULL for a '
                'large share of accounts, including every seller whose items were created by '
                'crew at the warehouse. The spec\'s three buckets do not cover the data.',
    }
    emit('section_3_origin', payload)
    return payload


def _pricing_aggregate():
    """Intake estimate vs. listed price across every seller item carrying both."""
    q = db.session.query(
        func.count(),
        func.avg(InventoryItem.suggested_price),
        func.avg(InventoryItem.price),
        func.count().filter(InventoryItem.price > InventoryItem.suggested_price),
        func.count().filter(InventoryItem.price < InventoryItem.suggested_price),
        func.count().filter(InventoryItem.price == InventoryItem.suggested_price),
    ).filter(
        InventoryItem.seller_id.in_(real_seller_ids()),
        InventoryItem.storage_location_id.isnot(None),
        InventoryItem.replaced_by_item_id.is_(None),
        InventoryItem.suggested_price > 0,
        InventoryItem.price > 0,
    )
    n, sug, lst, higher, lower, same = q.one()
    sug = float(sug) if sug is not None else None
    lst = float(lst) if lst is not None else None
    return {
        'n': n,
        'avg_suggested': round(sug, 2) if sug is not None else None,
        'avg_listed': round(lst, 2) if lst is not None else None,
        'pct_diff': round(100.0 * (lst - sug) / sug, 1) if sug else None,
        'listed_higher': higher, 'listed_lower': lower, 'unchanged': same,
    }


def section_4_pricing():
    rows = db.session.query(
        InventoryItem.category_id, InventoryCategory.name,
        func.count(InventoryItem.id),
        func.avg(InventoryItem.suggested_price),
        func.avg(InventoryItem.price),
        func.count(InventoryItem.suggested_price),
        func.count(InventoryItem.price),
    ).outerjoin(InventoryCategory, InventoryCategory.id == InventoryItem.category_id).filter(
        # Seller-owned only: suggested_price is an intake estimate that exists for seller
        # submissions. Campus-Swap-owned items have no estimate and some carry a $0
        # placeholder while in processing, which would corrupt both averages.
        InventoryItem.seller_id.in_(real_seller_ids()),
        InventoryItem.date_added.isnot(None),
        InventoryItem.storage_location_id.isnot(None),
        InventoryItem.replaced_by_item_id.is_(None),
        InventoryItem.suggested_price.isnot(None), InventoryItem.suggested_price > 0,
        InventoryItem.price.isnot(None), InventoryItem.price > 0,
    ).group_by(InventoryItem.category_id, InventoryCategory.name).all()

    cats = []
    for cat_id, name, n, avg_sug, avg_price, n_sug, n_price in rows:
        avg_sug = float(avg_sug) if avg_sug is not None else None
        avg_price = float(avg_price) if avg_price is not None else None
        pct = (round(100.0 * (avg_price - avg_sug) / avg_sug, 1)
               if avg_sug and avg_price is not None and avg_sug > 0 else None)
        cats.append({
            'category_id': cat_id, 'category_name': name or 'Uncategorized',
            'item_count': n,
            'avg_suggested_price': round(avg_sug, 2) if avg_sug is not None else None,
            'avg_listed_price': round(avg_price, 2) if avg_price is not None else None,
            'pct_diff_listed_vs_suggested': pct,
            'items_with_suggested_price': n_sug, 'items_with_listed_price': n_price,
        })
    cats.sort(key=lambda c: c['item_count'], reverse=True)

    payload = {
        'base_population': 'seller-owned physical items in storage carrying BOTH a '
                           'suggested and a listed price',
        'label': 'suggested vs. listed (NOT a discount — nothing has sold)',
        'categories': cats,
        'total_items_priced_both_ways': sum(c['item_count'] for c in cats),
        'aggregate': _pricing_aggregate(),
        'note': 'Scoped to seller-owned items with both prices set. Campus-Swap-owned items '
                'have no intake estimate and are excluded from this comparison only.',
    }
    emit('section_4_pricing', payload)
    return payload


def section_5_storage():
    locs = StorageLocation.query.order_by(StorageLocation.name).all()
    out = []
    for loc in locs:
        n = InventoryItem.query.filter(
            InventoryItem.storage_location_id == loc.id,
            InventoryItem.status != 'rejected').count()
        n_real = InventoryItem.query.filter(
            InventoryItem.storage_location_id == loc.id,
            InventoryItem.status != 'rejected',
            InventoryItem.seller_id.in_(real_seller_ids())).count()
        out.append({'storage_location_id': loc.id, 'name': loc.name,
                    'item_count_all_owners': n, 'item_count_real_sellers': n_real,
                    'is_full': bool(loc.is_full), 'is_active': bool(loc.is_active),
                    'capacity_note': loc.capacity_note})
    payload = {
        'locations': out,
        'grand_total_items_all_owners': sum(o['item_count_all_owners'] for o in out),
        'grand_total_items_real_sellers': sum(o['item_count_real_sellers'] for o in out),
        'note': 'Cost intentionally excluded per spec. Both an all-owners and a real-seller '
                'count are given because units physically hold Campus-Swap-owned items too.',
    }
    emit('section_5_storage', payload)
    return payload


def section_6_pickup_logistics():
    weeks = ShiftWeek.query.filter(ShiftWeek.is_tutorial == False).order_by(  # noqa: E712
        ShiftWeek.week_start).all()
    out = []
    for wk in weeks:
        shift_ids = [s.id for s in wk.shifts]
        if not shift_ids:
            out.append({'week_start': wk.week_start.isoformat(), 'status': wk.status,
                        'shifts': 0, 'truck_shifts_used': 0, 'pickups_scheduled': 0,
                        'pickups_completed': 0, 'items_picked_up': 0})
            continue
        truck_shifts = db.session.query(
            func.count(func.distinct(func.concat(
                ShiftPickup.shift_id, '-', ShiftPickup.truck_number)))
        ).filter(ShiftPickup.shift_id.in_(shift_ids)).scalar() or 0
        scheduled = ShiftPickup.query.filter(ShiftPickup.shift_id.in_(shift_ids)).count()
        # status only — every issue-flagged stop ALSO carries a completed_at timestamp
        # (the crew closes the stop out, then flags it), so completed_at overcounts.
        completed = ShiftPickup.query.filter(
            ShiftPickup.shift_id.in_(shift_ids),
            ShiftPickup.status == 'completed').count()
        no_show = ShiftPickup.query.filter(
            ShiftPickup.shift_id.in_(shift_ids),
            ShiftPickup.status == 'issue',
            ShiftPickup.issue_type == 'no_show').count()
        other_issue = ShiftPickup.query.filter(
            ShiftPickup.shift_id.in_(shift_ids),
            ShiftPickup.status == 'issue',
            ShiftPickup.issue_type.is_distinct_from('no_show')).count()
        never_actioned = ShiftPickup.query.filter(
            ShiftPickup.shift_id.in_(shift_ids),
            ShiftPickup.status == 'pending').count()
        seller_ids = [r[0] for r in db.session.query(ShiftPickup.seller_id).filter(
            ShiftPickup.shift_id.in_(shift_ids)).distinct().all()]
        items = InventoryItem.query.filter(
            InventoryItem.picked_up_at.isnot(None),
            InventoryItem.seller_id.in_(seller_ids or [-1]),
            InventoryItem.seller_id.in_(real_seller_ids())).count() if seller_ids else 0
        # Spec-literal: items whose picked_up_at falls inside this week's 7-day window.
        wk_end = wk.week_start + timedelta(days=7)
        items_in_window = real_items().filter(
            InventoryItem.picked_up_at >= wk.week_start,
            InventoryItem.picked_up_at < wk_end).count()
        out.append({'week_start': wk.week_start.isoformat(), 'status': wk.status,
                    'shifts': len(shift_ids), 'truck_shifts_used': truck_shifts,
                    'pickups_scheduled': scheduled, 'pickups_completed': completed,
                    'no_show': no_show, 'other_issue': other_issue,
                    'never_actioned': never_actioned,
                    'items_picked_up_in_week_window': items_in_window,
                    'items_picked_up_from_those_sellers': items})

    all_shift_ids = [s.id for wk in weeks for s in wk.shifts]
    totals = {
        'weeks': len(weeks),
        'shifts': len(all_shift_ids),
        'truck_shifts_run': db.session.query(func.count(func.distinct(func.concat(
            ShiftPickup.shift_id, '-', ShiftPickup.truck_number)))).filter(
            ShiftPickup.shift_id.in_(all_shift_ids or [-1])).scalar() or 0,
        'pickups_scheduled': ShiftPickup.query.filter(
            ShiftPickup.shift_id.in_(all_shift_ids or [-1])).count(),
        'pickups_completed': ShiftPickup.query.filter(
            ShiftPickup.shift_id.in_(all_shift_ids or [-1]),
            ShiftPickup.status == 'completed').count(),
        'no_show': ShiftPickup.query.filter(
            ShiftPickup.shift_id.in_(all_shift_ids or [-1]),
            ShiftPickup.status == 'issue',
            ShiftPickup.issue_type == 'no_show').count(),
        'other_issue': ShiftPickup.query.filter(
            ShiftPickup.shift_id.in_(all_shift_ids or [-1]),
            ShiftPickup.status == 'issue',
            ShiftPickup.issue_type.is_distinct_from('no_show')).count(),
        'never_actioned': ShiftPickup.query.filter(
            ShiftPickup.shift_id.in_(all_shift_ids or [-1]),
            ShiftPickup.status == 'pending').count(),
        'total_items_with_pickup_timestamp': real_items().filter(
            InventoryItem.picked_up_at.isnot(None)).count(),
    }
    payload = {
        'weeks': out, 'totals': totals,
        'note': 'Truck-shifts counted as distinct (shift_id, truck_number) pairs on '
                'ShiftPickup — Shift.trucks is the plan, not what ran. Per-week item counts '
                'attribute items by the sellers scheduled that week, since picked_up_at '
                'timestamps do not reliably fall inside the week window.',
    }
    emit('section_6_pickup_logistics', payload)
    return payload


def section_7_crew():
    q = db.session.query(ShiftAssignment).join(
        Shift, Shift.id == ShiftAssignment.shift_id).join(
        ShiftWeek, ShiftWeek.id == Shift.week_id).filter(
        ShiftWeek.is_tutorial == False,                                 # noqa: E712
        ShiftAssignment.worker_id.in_(crew_worker_ids()))
    assignments = q.all()
    by_role = {}
    for a in assignments:
        by_role[a.role_on_shift] = by_role.get(a.role_on_shift, 0) + 1
    crew_ids = {a.worker_id for a in assignments}
    weeks_covered = db.session.query(func.count(func.distinct(ShiftWeek.id))).join(
        Shift, Shift.week_id == ShiftWeek.id).join(
        ShiftAssignment, ShiftAssignment.shift_id == Shift.id).filter(
        ShiftWeek.is_tutorial == False).scalar() or 0                    # noqa: E712
    completed = sum(1 for a in assignments if a.completed_at is not None)

    payload = {
        'total_shift_assignments': len(assignments),
        'assignments_marked_complete': completed,
        'by_role': {'mover_driver': by_role.get('driver', 0),
                    'organizer': by_role.get('organizer', 0),
                    'other': sum(v for k, v in by_role.items()
                                 if k not in ('driver', 'organizer'))},
        'distinct_crew_members': len(crew_ids),
        'weeks_with_staffed_shifts': weeks_covered,
        'headline': f'{len(crew_ids)} crew members covered {len(assignments)} total shift '
                    f'assignments across {weeks_covered} weeks',
        'note': "role_on_shift stores 'driver' for what the board deck calls a mover. "
                "Tutorial weeks and internal/tutorial accounts excluded.",
    }
    emit('section_7_crew', payload)
    return payload


def section_8_board_headline():
    """The presentation-facing numbers: a seller funnel and a physical-item
    reconciliation that closes. Deduplicates rephoto matches so no physical item
    is counted twice (an original seller listing and the rephotographed item that
    replaced it both retain a storage_location_id)."""
    real = real_seller_ids()
    internal = db.session.query(User.id).filter(User.is_internal_account == True)  # noqa: E712

    listed = real_items().filter(InventoryItem.is_quick_capture == False).count()  # noqa: E712
    sellers_listed = db.session.query(
        func.count(func.distinct(InventoryItem.seller_id))).filter(
        InventoryItem.seller_id.in_(real),
        InventoryItem.is_quick_capture == False).scalar()                          # noqa: E712

    stored_seller_rows = real_items().filter(
        InventoryItem.storage_location_id.isnot(None)).count()
    stored_seller_physical = real_items().filter(
        InventoryItem.storage_location_id.isnot(None),
        InventoryItem.replaced_by_item_id.is_(None)).count()
    dedup_removed = stored_seller_rows - stored_seller_physical

    cs_stored = InventoryItem.query.filter(
        InventoryItem.seller_id.in_(internal),
        InventoryItem.storage_location_id.isnot(None)).count()
    cs_kept = InventoryItem.query.filter(
        InventoryItem.seller_id.in_(internal),
        InventoryItem.rephoto_disposition == 'kept').count()
    cs_backlog = InventoryItem.query.filter(
        InventoryItem.seller_id.in_(internal),
        InventoryItem.rephoto_disposition.is_(None)).count()
    cs_discarded = InventoryItem.query.filter(
        InventoryItem.seller_id.in_(internal),
        InventoryItem.rephoto_disposition == 'discarded').count()

    live = InventoryItem.query.filter(live_shop_clause())
    live_total = live.count()
    live_seller = InventoryItem.query.filter(
        live_shop_clause(), InventoryItem.seller_id.in_(real)).count()
    live_value, live_avg = db.session.query(
        func.sum(InventoryItem.price), func.avg(InventoryItem.price)
    ).filter(live_shop_clause()).one()

    # Seller-side acquisition funnel
    accounts = User.query.filter(User.id.in_(real)).count()
    seller_accounts = User.query.filter(User.id.in_(real), User.is_seller == True).count()  # noqa: E712
    sellers_scheduled = db.session.query(
        func.count(func.distinct(ShiftPickup.seller_id))).filter(
        ShiftPickup.seller_id.in_(real)).scalar()
    sellers_completed = db.session.query(
        func.count(func.distinct(ShiftPickup.seller_id))).filter(
        ShiftPickup.seller_id.in_(real),
        ShiftPickup.status == 'completed').scalar()

    # Weekly listing curve (seller submissions only)
    weekly = db.session.query(
        func.date_trunc('week', InventoryItem.date_added).label('wk'), func.count()
    ).filter(InventoryItem.seller_id.in_(real),
             InventoryItem.is_quick_capture == False).group_by('wk').order_by('wk').all()  # noqa: E712

    per_seller = db.session.query(func.count(InventoryItem.id)).filter(
        InventoryItem.seller_id.in_(real),
        InventoryItem.is_quick_capture == False).group_by(  # noqa: E712
        InventoryItem.seller_id).all()
    counts = sorted(c[0] for c in per_seller)

    # Per-unit physical split for the storage chart
    units = []
    for loc in StorageLocation.query.order_by(StorageLocation.name).all():
        s = InventoryItem.query.filter(
            InventoryItem.storage_location_id == loc.id,
            InventoryItem.seller_id.in_(real),
            InventoryItem.replaced_by_item_id.is_(None)).count()
        c = InventoryItem.query.filter(
            InventoryItem.storage_location_id == loc.id,
            InventoryItem.seller_id.in_(internal)).count()
        if s or c:
            units.append({'name': loc.name, 'seller_items': s, 'campus_swap_items': c,
                          'total': s + c, 'is_full': bool(loc.is_full)})
    units.sort(key=lambda u: u['total'], reverse=True)

    payload = {
        'items_listed_by_sellers': listed,
        'sellers_who_listed': sellers_listed,
        'seller_items_in_storage_physical': stored_seller_physical,
        'seller_items_in_storage_rows_before_dedup': stored_seller_rows,
        'rephoto_duplicate_rows_removed': dedup_removed,
        'campus_swap_items_kept': cs_kept,
        'campus_swap_items_in_storage': cs_stored,
        'campus_swap_backlog_unmatched': cs_backlog,
        'campus_swap_discarded': cs_discarded,
        'physical_items_in_storage': stored_seller_physical + cs_stored,
        'live_in_shop_total': live_total,
        'live_in_shop_seller_owned': live_seller,
        'live_in_shop_campus_swap_owned': live_total - live_seller,
        'live_inventory_list_value': round(float(live_value or 0), 2),
        'live_inventory_avg_price': round(float(live_avg or 0), 2),
        'seller_funnel': [
            {'stage': 'Accounts created', 'count': accounts},
            {'stage': 'Signed up to sell', 'count': seller_accounts},
            {'stage': 'Listed at least one item', 'count': sellers_listed},
            {'stage': 'Scheduled a pickup', 'count': sellers_scheduled},
            {'stage': 'Pickup completed', 'count': sellers_completed},
        ],
        'weekly_listings': [{'week_start': str(w)[:10], 'count': n} for w, n in weekly],
        'items_per_seller': {
            'mean': round(sum(counts) / len(counts), 1) if counts else 0,
            'median': counts[len(counts) // 2] if counts else 0,
            'max': counts[-1] if counts else 0,
        },
        'storage_units': units,
    }
    emit('section_8_board_headline', payload)
    return payload


def section_9_distributions():
    """Supporting distributions: live-inventory price bands, items per seller,
    and shift load per crew member."""
    bands = [('Under $25', 0, 25), ('$25–49', 25, 50), ('$50–99', 50, 100),
             ('$100–199', 100, 200), ('$200+', 200, 10 ** 9)]
    price_bands = []
    for label, lo, hi in bands:
        n = InventoryItem.query.filter(
            live_shop_clause(), InventoryItem.price >= lo, InventoryItem.price < hi).count()
        price_bands.append({'band': label, 'count': n})

    real = real_seller_ids()
    per_seller = [c[0] for c in db.session.query(func.count(InventoryItem.id)).filter(
        InventoryItem.seller_id.in_(real),
        InventoryItem.is_quick_capture == False).group_by(  # noqa: E712
        InventoryItem.seller_id).all()]
    buckets = [('1 item', 1, 1), ('2 items', 2, 2), ('3–5 items', 3, 5),
               ('6–10 items', 6, 10), ('11+ items', 11, 10 ** 9)]
    seller_bands = [{'band': lab, 'count': sum(1 for c in per_seller if lo <= c <= hi)}
                    for lab, lo, hi in buckets]

    crew_load = db.session.query(
        ShiftAssignment.worker_id, func.count()
    ).join(Shift, Shift.id == ShiftAssignment.shift_id).join(
        ShiftWeek, ShiftWeek.id == Shift.week_id).filter(
        ShiftWeek.is_tutorial == False,                                   # noqa: E712
        ShiftAssignment.worker_id.in_(crew_worker_ids())).group_by(
        ShiftAssignment.worker_id).all()
    loads = sorted((n for _, n in crew_load), reverse=True)
    total_shifts = sum(loads)
    top3 = sum(loads[:3])

    live_by_cat = db.session.query(
        InventoryCategory.name, func.count(InventoryItem.id),
        func.avg(InventoryItem.price), func.sum(InventoryItem.price)
    ).outerjoin(InventoryCategory, InventoryCategory.id == InventoryItem.category_id).filter(
        live_shop_clause()).group_by(InventoryCategory.name).all()
    live_cats = sorted(
        [{'category_name': nm or 'Uncategorized', 'count': n,
          'avg_price': round(float(a), 0), 'list_value': round(float(s), 0)}
         for nm, n, a, s in live_by_cat],
        key=lambda c: c['list_value'], reverse=True)

    units_total = StorageLocation.query.filter(StorageLocation.is_active == True).count()  # noqa: E712
    units_holding = db.session.query(
        func.count(func.distinct(InventoryItem.storage_location_id))).filter(
        InventoryItem.storage_location_id.isnot(None),
        InventoryItem.replaced_by_item_id.is_(None)).scalar()

    payload = {
        'live_price_bands': price_bands,
        'live_by_category': live_cats,
        'active_storage_units': units_total,
        'storage_units_holding_inventory': units_holding,
        'items_per_seller_bands': seller_bands,
        'crew_shift_loads': [{'crew': f'Crew {chr(65 + i)}', 'shifts': n}
                             for i, n in enumerate(loads)],
        'crew_top3_share_pct': round(100.0 * top3 / total_shifts, 0) if total_shifts else 0,
        'crew_top3_shifts': top3,
        'crew_total_shifts': total_shifts,
    }
    emit('section_9_distributions', payload)
    return payload


BEDDING_RE = r'mattress|topper|headboard|bed frame|bedframe|futon|pillow|cushion'

# The founder was assigned to shifts while testing the crew-facing pages. Those are not
# real worked shifts, so he is excluded from every crew count.
FOUNDER_EMAIL = 'henry.russell28@gmail.com'

# Physically empty at the end of the season, confirmed by Henry 2026-07-28. Its single
# remaining item record still points here from before the re-organisation.
EMPTY_UNITS = {'Unit 119'}

# The mattress unit. Bedding is photo-exempt, so it holds no re-photographed items and
# never appears in a campaign-based unit count.
BEDDING_UNIT = 'Unit 121'


def _founder_id():
    row = User.query.filter(func.lower(User.email) == FOUNDER_EMAIL).first()
    return row.id if row else -1


def crew_worker_ids():
    """Real crew: approved workers excluding the founder's test assignments."""
    return db.session.query(User.id).filter(
        User.id.in_(real_seller_ids()),
        User.id != _founder_id(),
    )


def section_10_truth():
    """THE REPORT'S SOURCE OF TRUTH (rules confirmed by Henry, 2026-07-28).

    Inventory is whatever physically sits in the eight units the warehouse actually
    occupies after the re-organisation. Everything else in the schema is history:

      * TRASH_UNITS hold retired records — superseded originals, an unused June
        pipeline batch, and listings that were never collected. Excluded entirely.
      * A superseded original (replaced_by_item_id set) is the same physical object
        as its re-photographed replacement. Excluded so nothing counts twice.
      * PHYSICAL_COUNTS is a hand count of every unit taken during the
        re-organisation. It is the authority on how much we have; the system holds
        fewer rows because the twin mattresses are still recorded as one listing.
      * Sellers are counted as those with an item physically in a unit today — the
        population that matches the items we report collecting.
    """
    REAL_UNIT_LABELS = {
        'Unit 119': 'Mattress Unit',
        'Unit 121': 'Dresser Unit',
        'Unit 203': 'Mini Fridge Wall / Couch Unit',
        'Unit 204': 'Tables, Desks & Shelves Unit',
        'Unit 214': 'Couch Unit',
        'Unit 240': 'Chairs & Accessories Unit',
        'Unit 354': 'Overflow Unit',
        'Unit 362': 'Small Couch Unit',
    }
    # Hand count of each unit, taken during the re-organisation.
    PHYSICAL_COUNTS = {'Unit 119': 58, 'Unit 121': 46, 'Unit 203': 71, 'Unit 204': 67,
                       'Unit 214': 19, 'Unit 240': 53, 'Unit 354': 39, 'Unit 362': 10}
    TRASH_UNITS = ('Unit 835', 'Unit 756')

    campaign = db.session.query(ItemPhoto.item_id).filter(ItemPhoto.captured_at.isnot(None))
    internal = db.session.query(User.id).filter(User.is_internal_account == True)  # noqa: E712
    real = real_seller_ids()
    matched_ids = db.session.query(InventoryItem.replaced_by_item_id).filter(
        InventoryItem.replaced_by_item_id.isnot(None))
    unit_ids = [r[0] for r in db.session.query(StorageLocation.id).filter(
        StorageLocation.name.in_(list(REAL_UNIT_LABELS)))]

    def inv(*extra):
        return InventoryItem.query.filter(
            InventoryItem.storage_location_id.in_(unit_ids),
            InventoryItem.replaced_by_item_id.is_(None), *extra)

    recorded_ids = [i.id for i in inv()]
    recorded = len(recorded_ids)
    physical = sum(PHYSICAL_COUNTS.values())
    cs_owned = inv(InventoryItem.seller_id.in_(internal)).count()
    seller_owned = recorded - cs_owned

    # ── listed for sale: every priced item in the warehouse ─────────────────
    # Includes items whose photo is being re-processed — they are priced and go live
    # as the queue clears, so counting only what renders this second understates the
    # book. Excludes rejected and discarded items, which are never for sale.
    shop_q = inv(
        InventoryItem.price > 0,
        InventoryItem.status != 'rejected',
        InventoryItem.rephoto_disposition.is_distinct_from('discarded'))
    shop_ids = [i.id for i in shop_q]
    rendering_now = inv(
        InventoryItem.price > 0,
        InventoryItem.ai_approved == True,                        # noqa: E712
        InventoryItem.status == 'available',
        InventoryItem.needs_new_photo == False,                   # noqa: E712
        InventoryItem.rephoto_disposition.is_distinct_from('discarded'),
        InventoryItem.id.in_(campaign),
        or_(InventoryItem.seller_id.notin_(internal),
            InventoryItem.rephoto_disposition == 'kept')).count()
    awaiting_photo = len(shop_ids) - rendering_now
    list_value, avg_price = db.session.query(
        func.sum(InventoryItem.price), func.avg(InventoryItem.price)
    ).filter(InventoryItem.id.in_(shop_ids)).one()
    awaiting = recorded - len(shop_ids)
    blank_records = inv(func.coalesce(InventoryItem.description, '') == '').count()

    # ── sellers ─────────────────────────────────────────────────────────────
    def n_sellers(*extra):
        return db.session.query(func.count(func.distinct(InventoryItem.seller_id))).filter(
            InventoryItem.seller_id.in_(real), *extra).scalar()

    sellers_collected_from = db.session.query(
        func.count(func.distinct(InventoryItem.seller_id))).filter(
        InventoryItem.id.in_(recorded_ids), InventoryItem.seller_id.in_(real)).scalar()
    submissions = InventoryItem.query.filter(
        InventoryItem.seller_id.in_(real),
        InventoryItem.is_quick_capture == False,                 # noqa: E712
        InventoryItem.date_added.isnot(None)).count()
    submission_sellers = n_sellers(InventoryItem.is_quick_capture == False)  # noqa: E712
    sellers_completed_pickup = db.session.query(
        func.count(func.distinct(ShiftPickup.seller_id))).filter(
        ShiftPickup.seller_id.in_(real), ShiftPickup.status == 'completed').scalar()

    # ── campaign accounting (the warehouse count itself) ────────────────────
    def camp(*extra):
        return InventoryItem.query.filter(InventoryItem.id.in_(campaign), *extra)

    no_disp = InventoryItem.rephoto_disposition.is_(None)
    has_descr = func.coalesce(InventoryItem.description, '') != ''
    buckets = {
        'matched_to_original': camp(InventoryItem.id.in_(matched_ids)).count(),
        'kept_for_campus_swap': camp(InventoryItem.rephoto_disposition == 'kept').count(),
        'seller_assigned_no_original': camp(
            ~InventoryItem.id.in_(matched_ids), no_disp,
            InventoryItem.seller_id.in_(real)).count(),
        'campus_swap_no_disposition': camp(
            ~InventoryItem.id.in_(matched_ids), no_disp,
            InventoryItem.seller_id.in_(internal), has_descr).count(),
        'discarded': camp(InventoryItem.rephoto_disposition == 'discarded').count(),
        'awaiting_details': camp(~InventoryItem.id.in_(matched_ids), no_disp,
                                 InventoryItem.seller_id.in_(internal), ~has_descr).count(),
    }
    buckets['total_photographed'] = sum(buckets.values())
    kept_listings = db.session.query(func.count(func.distinct(func.coalesce(
        InventoryItem.stock_group_id, func.cast(InventoryItem.id, db.String))))).filter(
        InventoryItem.id.in_(campaign),
        InventoryItem.rephoto_disposition == 'kept').scalar()

    # ── breakdowns, all on real-unit inventory ─────────────────────────────
    cat_rows = db.session.query(
        InventoryCategory.name, func.count(InventoryItem.id),
        func.count(InventoryItem.id).filter(InventoryItem.seller_id.in_(internal))
    ).outerjoin(InventoryCategory, InventoryCategory.id == InventoryItem.category_id).filter(
        InventoryItem.id.in_(recorded_ids)).group_by(InventoryCategory.name).all()
    categories = sorted(
        [{'category_name': nm or 'Awaiting classification', 'total': n,
          'campus_swap_items': cs, 'seller_items': n - cs} for nm, n, cs in cat_rows],
        key=lambda c: c['total'], reverse=True)

    furn_rows = db.session.query(
        InventoryCategory.name, func.count(InventoryItem.id),
        func.count(InventoryItem.id).filter(InventoryItem.seller_id.in_(internal)),
        func.avg(InventoryItem.price).filter(InventoryItem.price > 0),
    ).outerjoin(InventoryCategory,
                InventoryCategory.id == InventoryItem.subcategory_id).filter(
        InventoryItem.id.in_(recorded_ids),
        InventoryItem.category_id.in_(db.session.query(InventoryCategory.id).filter(
            InventoryCategory.name == 'Furniture'))).group_by(InventoryCategory.name).all()
    furniture_subcategories = sorted(
        [{'name': nm or 'Unclassified', 'total': n, 'campus_swap_items': cs,
          'seller_items': n - cs,
          'avg_price': round(float(a), 0) if a is not None else None}
         for nm, n, cs, a in furn_rows], key=lambda c: c['total'], reverse=True)

    units = []
    for name, label in REAL_UNIT_LABELS.items():
        loc = StorageLocation.query.filter_by(name=name).first()
        rec = inv(InventoryItem.storage_location_id == loc.id).count() if loc else 0
        units.append({'name': name, 'label': label,
                      'number': name.replace('Unit ', ''),
                      'recorded': rec, 'physical': PHYSICAL_COUNTS[name],
                      'gap': PHYSICAL_COUNTS[name] - rec})
    units.sort(key=lambda u: u['physical'], reverse=True)

    # Per-unit economics (size, value, density). Uses the app's own helper so the
    # report and the site's CSV export can never drift apart.
    unit_metrics = []
    for name, label in REAL_UNIT_LABELS.items():
        loc = StorageLocation.query.filter_by(name=name).first()
        if not loc:
            continue
        m = _unit_metrics(loc)
        m.pop('loc', None)
        m['label'] = label
        m['number'] = name.replace('Unit ', '')
        m['physical'] = PHYSICAL_COUNTS[name]
        unit_metrics.append(m)
    unit_metrics.sort(key=lambda m: -(m['value_per_sqft'] or 0))
    _sqft = sum(m['sqft'] or 0 for m in unit_metrics)
    _val = sum(m['value'] for m in unit_metrics)
    _it = sum(m['items'] for m in unit_metrics)
    unit_totals = {
        'sqft': _sqft, 'items': _it, 'value': round(_val, 2),
        'value_per_sqft': round(_val / _sqft, 2) if _sqft else None,
        'items_per_100_sqft': round(100.0 * _it / _sqft, 1) if _sqft else None,
        'avg_price': round(_val / sum(m['items_priced'] for m in unit_metrics), 2)
                     if sum(m['items_priced'] for m in unit_metrics) else None,
    }

    bands = [('Under $25', 0, 25), ('$25–49', 25, 50), ('$50–99', 50, 100),
             ('$100–199', 100, 200), ('$200+', 200, 10 ** 9)]
    price_bands = [{'band': lab, 'count': InventoryItem.query.filter(
        InventoryItem.id.in_(shop_ids), InventoryItem.price >= lo,
        InventoryItem.price < hi).count()} for lab, lo, hi in bands]

    val_rows = db.session.query(
        InventoryCategory.name, func.count(InventoryItem.id),
        func.avg(InventoryItem.price), func.sum(InventoryItem.price)
    ).outerjoin(InventoryCategory, InventoryCategory.id == InventoryItem.category_id).filter(
        InventoryItem.id.in_(shop_ids)).group_by(InventoryCategory.name).all()
    live_by_category = sorted(
        [{'category_name': nm or 'Uncategorised', 'count': n,
          'avg_price': round(float(a), 0), 'list_value': round(float(s), 0)}
         for nm, n, a, s in val_rows], key=lambda c: c['list_value'], reverse=True)

    per_seller = [c[0] for c in db.session.query(func.count(InventoryItem.id)).filter(
        InventoryItem.seller_id.in_(real),
        InventoryItem.is_quick_capture == False).group_by(  # noqa: E712
        InventoryItem.seller_id).all()]
    sb = [('1 item', 1, 1), ('2 items', 2, 2), ('3–5 items', 3, 5),
          ('6–10 items', 6, 10), ('11+ items', 11, 10 ** 9)]
    seller_bands = [{'band': lab, 'count': sum(1 for c in per_seller if lo <= c <= hi)}
                    for lab, lo, hi in sb]

    origin_rows = db.session.query(
        User.pickup_location_type, func.count(InventoryItem.id)).join(
        InventoryItem, InventoryItem.seller_id == User.id).filter(
        InventoryItem.seller_id.in_(real),
        InventoryItem.is_quick_capture == False,                 # noqa: E712
        InventoryItem.date_added.isnot(None)).group_by(User.pickup_location_type).all()
    obk = {'on_campus': 0, 'off_campus_complex': 0, 'off_campus_other': 0, 'not_set': 0}
    for loc_t, n in origin_rows:
        obk[loc_t if loc_t in obk else 'not_set'] += n
    otot = sum(obk.values()) or 1
    origin = [{'bucket': k, 'item_count': v, 'pct_of_total': round(100.0 * v / otot, 1)}
              for k, v in obk.items()]

    bldg_rows = db.session.query(
        User.pickup_location_type, User.pickup_dorm, func.count(InventoryItem.id)
    ).join(InventoryItem, InventoryItem.seller_id == User.id).filter(
        InventoryItem.seller_id.in_(real),
        InventoryItem.is_quick_capture == False,                 # noqa: E712
        InventoryItem.date_added.isnot(None),
        User.pickup_dorm.isnot(None)).group_by(
        User.pickup_location_type, User.pickup_dorm).all()
    buildings = sorted([{'name': d, 'type': lt, 'items': n} for lt, d, n in bldg_rows],
                       key=lambda b: b['items'], reverse=True)

    weekly = db.session.query(
        func.date_trunc('week', InventoryItem.date_added).label('wk'), func.count()
    ).filter(InventoryItem.seller_id.in_(real),
             InventoryItem.is_quick_capture == False).group_by('wk').order_by('wk').all()  # noqa: E712

    retired = InventoryItem.query.filter(
        InventoryItem.storage_location_id.in_(
            db.session.query(StorageLocation.id).filter(
                StorageLocation.name.in_(TRASH_UNITS)))).count()

    payload = {
        # headline
        'items_on_hand_physical': physical,
        'items_recorded': recorded,
        'unrecorded_gap': physical - recorded,
        'seller_items_collected': seller_owned,
        'sellers_collected_from': sellers_collected_from,
        'campus_swap_owned': cs_owned,
        'shop_items': len(shop_ids),
        'rendering_now': rendering_now,
        'awaiting_photo_processing': awaiting_photo,
        'awaiting_details_or_price': awaiting,
        'blank_records': blank_records,
        'list_value': round(float(list_value or 0), 2),
        'avg_list_price': round(float(avg_price or 0), 2),
        # seller funnel context
        'submissions': submissions,
        'submission_sellers': submission_sellers,
        'sellers_completed_pickup': sellers_completed_pickup,
        'listings_without_an_item_on_hand': submissions - seller_owned,
        'sellers_who_listed_but_have_nothing_on_hand':
            submission_sellers - sellers_collected_from,
        # the warehouse count
        'campaign_buckets': buckets,
        'kept_distinct_listings': kept_listings,
        # storage
        'storage_units': units,
        'unit_metrics': unit_metrics,
        'unit_totals': unit_totals,
        'storage_units_retained': len(units),
        'storage_units_ever_rented': StorageLocation.query.count(),
        'retired_records_in_trash_units': retired,
        # breakdowns
        'categories': categories,
        'furniture_subcategories': furniture_subcategories,
        'price_bands': price_bands,
        'live_by_category': live_by_category,
        'items_per_seller_bands': seller_bands,
        'items_per_seller': {
            'mean': round(sum(per_seller) / len(per_seller), 1) if per_seller else 0,
            'median': sorted(per_seller)[len(per_seller) // 2] if per_seller else 0,
            'max': max(per_seller) if per_seller else 0},
        'origin_buckets': origin,
        'pickup_buildings': buildings,
        'weekly_listings': [{'week_start': str(w)[:10], 'count': n} for w, n in weekly],
        'notes': [
            'Inventory = the eight units the warehouse occupies after re-organisation. '
            'Units 835 and 756 hold retired records and are excluded.',
            'Physical count is a hand count of every unit; the system holds fewer rows '
            'because the twin mattresses are still recorded as a single listing.',
            'Sellers are counted as those with an item physically in a unit today, so the '
            'seller count and the item count describe the same population.',
        ],
    }
    emit('section_10_truth', payload)
    return payload


def _bg_queue_count():
    from app import _background_removal_review_query
    return _background_removal_review_query().count()


# ─────────────────────────────────────────────────────────────────────────────
def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    with app.app_context():
        integ = section_0_integrity()
        funnel = section_2_funnel()
        glance = section_1_glance(funnel)
        comp = section_2b_composition()
        origin = section_3_origin()
        pricing = section_4_pricing()
        storage = section_5_storage()
        logistics = section_6_pickup_logistics()
        crew = section_7_crew()
        head = section_8_board_headline()
        dist = section_9_distributions()
        truth = section_10_truth()

        for name, payload in SECTIONS.items():
            with open(os.path.join(OUT_DIR, f'{name}.json'), 'w') as fh:
                json.dump(payload, fh, indent=2, default=str)
        with open(os.path.join(OUT_DIR, 'all_sections.json'), 'w') as fh:
            json.dump(SECTIONS, fh, indent=2, default=str)

        # ── stdout summary ──────────────────────────────────────────────────
        p = print
        p('')
        p('=' * 72)
        p('CAMPUS SWAP — YEAR 1 BOARD REPORT DATA PULL')
        p(f'generated {datetime.utcnow().isoformat()}Z  ·  output → {OUT_DIR}')
        p('=' * 72)

        p('\n-- SECTION 1: SEASON AT A GLANCE ' + '-' * 38)
        p(f'  Items currently in storage      {glance["items_currently_in_storage"]:>6}')
        p(f'  Total unique sellers            {glance["total_unique_sellers"]:>6}')
        p(f'  Activity range (date_added)     {str(glance["date_range_start"])[:10]}'
          f' → {str(glance["date_range_end"])[:10]}')

        p('\n-- SECTION 2: ITEM FUNNEL ' + '-' * 45)
        p(f'  {"STAGE":<10}{"COUNT":>7}   LABEL')
        for s in funnel['stages']:
            p(f'  {s["stage"]:<10}{s["count"]:>7}   {s["label"]}')
        p('')
        for s in funnel['stages']:
            p(f'  [{s["stage"]}] {s["caption"]}')

        p('\n-- SECTION 2b: COMPOSITION (in storage) ' + '-' * 31)
        p(f'  {"CATEGORY":<26}{"TOTAL":>6}{"AVAIL":>7}{"PEND":>6}{"REJ":>5}')
        for c in comp['categories']:
            b = c['by_status']
            p(f'  {c["category_name"][:25]:<26}{c["total"]:>6}{b["available"]:>7}'
              f'{b["pending_valuation"]:>6}{b["rejected"]:>5}')
        g = comp['grand_total']
        p(f'  {"TOTAL":<26}{g["total"]:>6}{g["by_status"]["available"]:>7}'
          f'{g["by_status"]["pending_valuation"]:>6}{g["by_status"]["rejected"]:>5}')

        p('\n-- SECTION 3: WHERE ITEMS CAME FROM ' + '-' * 35)
        for b in origin['buckets']:
            p(f'  {b["bucket"]:<22}{b["item_count"]:>6}  {b["pct_of_total"]:>5}%')

        p('\n-- SECTION 4: PRICING (suggested vs listed) ' + '-' * 27)
        p(f'  {"CATEGORY":<26}{"N":>5}{"SUGG":>9}{"LISTED":>9}{"DIFF":>8}')
        for c in pricing['categories']:
            sug = f'${c["avg_suggested_price"]:.0f}' if c['avg_suggested_price'] else '—'
            lst = f'${c["avg_listed_price"]:.0f}' if c['avg_listed_price'] else '—'
            d = f'{c["pct_diff_listed_vs_suggested"]:+.0f}%' \
                if c['pct_diff_listed_vs_suggested'] is not None else '—'
            p(f'  {c["category_name"][:25]:<26}{c["item_count"]:>5}{sug:>9}{lst:>9}{d:>8}')

        p('\n-- SECTION 5: STORAGE UTILIZATION ' + '-' * 37)
        p(f'  {"UNIT":<28}{"ITEMS":>7}{"REAL":>7}  FULL')
        for loc in storage['locations']:
            p(f'  {loc["name"][:27]:<28}{loc["item_count_all_owners"]:>7}'
              f'{loc["item_count_real_sellers"]:>7}  {"YES" if loc["is_full"] else ""}')
        p(f'  {"TOTAL":<28}{storage["grand_total_items_all_owners"]:>7}'
          f'{storage["grand_total_items_real_sellers"]:>7}')

        p('\n-- SECTION 6: PICKUP LOGISTICS ' + '-' * 40)
        p(f'  {"WEEK":<13}{"SHIFTS":>7}{"TRUCKS":>8}{"SCHED":>7}{"DONE":>6}{"ITEMS":>7}')
        for w in logistics['weeks']:
            p(f'  {w["week_start"]:<13}{w["shifts"]:>7}{w["truck_shifts_used"]:>8}'
              f'{w["pickups_scheduled"]:>7}{w["pickups_completed"]:>6}'
              f'{w.get("items_picked_up_in_week_window", 0):>7}')
        t = logistics['totals']
        p(f'  {"TOTAL":<13}{t["shifts"]:>7}{t["truck_shifts_run"]:>8}'
          f'{t["pickups_scheduled"]:>7}{t["pickups_completed"]:>6}')

        p('\n-- SECTION 7: CREW COVERAGE ' + '-' * 43)
        p(f'  {crew["headline"]}')
        p(f'  movers {crew["by_role"]["mover_driver"]}  ·  organizers '
          f'{crew["by_role"]["organizer"]}  ·  marked complete '
          f'{crew["assignments_marked_complete"]}')

        p('\n-- DATA INTEGRITY FLAGS (read before using any number) ' + '-' * 16)
        p(f'  arrived_at_store_at populated rows        '
          f'{integ["arrived_at_store_at_rows_total"]:>5}')
        p(f'  ... of those also having storage set      '
          f'{integ["arrived_at_store_at_AND_storage_location_rows"]:>5}')
        p(f'  SPEC Stage C as literally defined         '
          f'{integ["spec_stage_c_literal_count"]:>5}   <-- unusable')
        p(f'  IntakeRecord rows                        {integ["intake_record_rows"]:>5}')
        p(f'  IntakeFlag rows                          {integ["intake_flag_rows"]:>5}')
        p(f'  In storage but no picked_up_at           '
          f'{integ["real_seller_items_in_storage_without_picked_up_at"]:>6}')
        p(f'  Campus-Swap-owned items live in shop     '
          f'{integ["internal_account_items_live_in_shop"]:>5}   (excluded by spec rule)')
        p('')
        for n in integ['notes']:
            p(f'  ! {n}')
        p('')
        p(f'Wrote {len(SECTIONS)} JSON files to {OUT_DIR}/')
        p('')


if __name__ == '__main__':
    main()
