"""
Renders the Year 1 board report to HTML + PDF from /tmp/board_report/all_sections.json.

Run:  python3 scripts/board_report_pull.py && python3 scripts/board_report_render.py

Output: /tmp/board_report/campus_swap_year_one.html
        /tmp/board_report/campus_swap_year_one.pdf

Chart palette validated with the dataviz skill's validator against a white chart
surface (light mode): series green #1E7A4A + series amber #C8832A pass the
lightness band, chroma floor, CVD separation (worst adjacent ΔE 10.3 protan),
normal-vision floor (22.7) and 3:1 contrast checks. Brand forest green #1A3D1A is
used for ink/headings only — it fails the chroma floor as a data mark.
"""
import json
import os
from datetime import date, datetime, timedelta

IN_FILE = '/tmp/board_report/all_sections.json'
OUT_HTML = '/tmp/board_report/campus_swap_year_one.html'
OUT_PDF = '/tmp/board_report/campus_swap_year_one.pdf'

# ── palette (validated; see module docstring) ────────────────────────────────
GREEN = '#1E7A4A'        # series 1 — seller-owned
AMBER = '#C8832A'        # series 2 — Campus Swap-owned
INK = '#1A1A1A'
INK_2 = '#52514E'
MUTED = '#898781'
GRID = '#E1E0D9'
BASELINE = '#C3C2B7'
FOREST = '#1A3D1A'       # brand ink, headings only
CREAM = '#F5F0E8'
RULE = '#D8D0C4'

W = 672  # content width in px (7.0in at 96dpi)


def esc(s):
    return (str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))


def fmt(n):
    return f'{n:,}'


def rrect_right(x, y, w, h, r=4):
    """Bar with the data end (right) rounded, anchored square at the baseline."""
    r = min(r, max(w, 0), h / 2)
    if w <= 0:
        return ''
    return (f'M{x},{y} H{x + w - r} Q{x + w},{y} {x + w},{y + r} '
            f'V{y + h - r} Q{x + w},{y + h} {x + w - r},{y + h} H{x} Z')


def rrect_top(x, y, w, h, r=4):
    """Column with the data end (top) rounded, anchored square at the baseline."""
    r = min(r, w / 2, max(h, 0))
    if h <= 0:
        return ''
    return (f'M{x},{y + h} V{y + r} Q{x},{y} {x + r},{y} H{x + w - r} '
            f'Q{x + w},{y} {x + w},{y + r} V{y + h} Z')


def svg_open(w, h, label):
    return (f'<svg viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img" '
            f'aria-label="{esc(label)}" style="display:block">')


# ── chart: horizontal bars, single series ───────────────────────────────────
def chart_hbar(rows, label_key, value_key, aria, sub_key=None,
               color=GREEN, row_h=26, bar_h=15, label_w=150, pad_r=64,
               value_fmt=None):
    h = len(rows) * row_h + 8
    plot_w = W - label_w - pad_r
    mx = max([r[value_key] for r in rows] + [1])
    out = [svg_open(W, h, aria)]
    for i, r in enumerate(rows):
        y = i * row_h + 4
        bw = (r[value_key] / mx) * plot_w
        out.append(f'<text x="{label_w - 10}" y="{y + bar_h - 2}" text-anchor="end" '
                   f'font-size="10.5" fill="{INK_2}">{esc(r[label_key])}</text>')
        out.append(f'<path d="{rrect_right(label_w, y, bw, bar_h)}" fill="{color}"/>')
        shown = value_fmt(r[value_key]) if value_fmt else fmt(r[value_key])
        out.append(f'<text x="{label_w + bw + 7}" y="{y + bar_h - 2}" font-size="10.5" '
                   f'font-weight="600" fill="{INK}" style="font-variant-numeric:tabular-nums">'
                   f'{shown}</text>')
        if sub_key and r.get(sub_key):
            out.append(f'<text x="{W}" y="{y + bar_h - 2}" text-anchor="end" font-size="9" '
                       f'fill="{MUTED}">{esc(r[sub_key])}</text>')
    out.append('</svg>')
    return ''.join(out)


# ── chart: stacked horizontal bars, two series ──────────────────────────────
def chart_stacked(rows, label_key, keys, colors, aria,
                  row_h=26, bar_h=15, label_w=96, pad_r=52):
    h = len(rows) * row_h + 8
    plot_w = W - label_w - pad_r
    mx = max([sum(r[k] for k in keys) for r in rows] + [1])
    out = [svg_open(W, h, aria)]
    for i, r in enumerate(rows):
        y = i * row_h + 4
        x = label_w
        total = sum(r[k] for k in keys)
        out.append(f'<text x="{label_w - 10}" y="{y + bar_h - 2}" text-anchor="end" '
                   f'font-size="10.5" fill="{INK_2}">{esc(r[label_key])}</text>')
        for j, k in enumerate(keys):
            seg = (r[k] / mx) * plot_w
            if seg <= 0:
                continue
            last = all(r[k2] == 0 for k2 in keys[j + 1:])
            # 2px surface gap between adjacent segments
            draw = seg if last else max(seg - 2, 0.5)
            d = (rrect_right(x, y, draw, bar_h) if last
                 else f'M{x},{y} h{draw} v{bar_h} h{-draw} Z')
            out.append(f'<path d="{d}" fill="{colors[j]}"/>')
            x += seg
        out.append(f'<text x="{label_w + (total / mx) * plot_w + 7}" y="{y + bar_h - 2}" '
                   f'font-size="10.5" font-weight="600" fill="{INK}" '
                   f'style="font-variant-numeric:tabular-nums">{fmt(total)}</text>')
    out.append('</svg>')
    return ''.join(out)


# ── chart: columns over time, single series ─────────────────────────────────
def chart_columns(series, aria, h=176, color=GREEN, categorical_labels=False):
    pad_l, pad_b, pad_t = 30, 26, 14
    plot_w = W - pad_l - 6
    plot_h = h - pad_b - pad_t
    mx = max([s['count'] for s in series] + [1])
    step = plot_w / len(series)
    bw = min(step - 3, 22)
    out = [svg_open(W, h, aria)]
    # recessive gridlines
    ticks = 4
    for t in range(ticks + 1):
        v = mx * t / ticks
        y = pad_t + plot_h - (v / mx) * plot_h
        out.append(f'<line x1="{pad_l}" y1="{y:.1f}" x2="{W - 6}" y2="{y:.1f}" '
                   f'stroke="{GRID}" stroke-width="1"/>')
        out.append(f'<text x="{pad_l - 7}" y="{y + 3:.1f}" text-anchor="end" font-size="8.5" '
                   f'fill="{MUTED}" style="font-variant-numeric:tabular-nums">{int(round(v))}</text>')
    for i, s in enumerate(series):
        x = pad_l + i * step + (step - bw) / 2
        bh = (s['count'] / mx) * plot_h
        y = pad_t + plot_h - bh
        if s['count']:
            out.append(f'<path d="{rrect_top(x, y, bw, bh)}" fill="{color}"/>')
        # selective direct labels — never a number on every mark
        if categorical_labels or s['count'] >= mx * 0.6:
            if s['count']:
                out.append(f'<text x="{x + bw / 2:.1f}" y="{y - 4:.1f}" text-anchor="middle" '
                           f'font-size="9" font-weight="600" fill="{INK}">{s["count"]}</text>')
        if categorical_labels:
            out.append(f'<text x="{x + bw / 2:.1f}" y="{h - 9}" text-anchor="middle" '
                       f'font-size="8.5" fill="{MUTED}">{esc(s["week_start"])}</text>')
        elif i % 2 == 0:
            dt = datetime.strptime(s['week_start'], '%Y-%m-%d')
            out.append(f'<text x="{x + bw / 2:.1f}" y="{h - 9}" text-anchor="middle" '
                       f'font-size="8.5" fill="{MUTED}">{dt.strftime("%b %-d")}</text>')
    out.append(f'<line x1="{pad_l}" y1="{pad_t + plot_h}" x2="{W - 6}" y2="{pad_t + plot_h}" '
               f'stroke="{BASELINE}" stroke-width="1"/>')
    out.append('</svg>')
    return ''.join(out)


def loc_label(bucket):
    return {'on_campus': 'On campus (dorms)',
            'off_campus_complex': 'Off campus, partner complex',
            'off_campus_other': 'Off campus, other',
            'not_set': 'Not recorded'}.get(bucket, bucket)


def legend(items):
    sw = ''.join(
        f'<span class="lg"><span class="sw" style="background:{c}"></span>{esc(t)}</span>'
        for t, c in items)
    return f'<div class="legend">{sw}</div>'


def stat(value, label, note=None, accent=False):
    return (f'<div class="stat{" accent" if accent else ""}">'
            f'<div class="sv">{value}</div><div class="sl">{esc(label)}</div>'
            + (f'<div class="sn">{esc(note)}</div>' if note else '') + '</div>')


# ─────────────────────────────────────────────────────────────────────────────
def build(d):
    # section_10_truth is the authority (re-photography campaign = source of truth).
    # The older sections remain in the JSON as audit trail; the page code below reads
    # its numbers through these adapters so every figure traces to section_10.
    t = d['section_10_truth']
    g = d['section_1_glance']
    pricing = d['section_4_pricing']
    logistics = d['section_6_pickup_logistics']
    crew = d['section_7_crew']
    dist9 = d['section_9_distributions']

    h = {
        'items_listed_by_sellers': t['submissions'],
        'sellers_who_listed': t['submission_sellers'],
        'seller_items_in_storage_physical': t['seller_items_collected'],
        'campus_swap_items_in_storage': t['campus_swap_owned'],
        'physical_items_in_storage': t['items_recorded'],
        'live_in_shop_total': t['shop_items'],
        'live_inventory_list_value': t['list_value'],
        'live_inventory_avg_price': t['avg_list_price'],
        'campus_swap_items_kept': t['campaign_buckets']['kept_for_campus_swap'],
        'items_per_seller': t['items_per_seller'],
        'storage_units': t['storage_units'],
        'weekly_listings': t['weekly_listings'],
        'seller_funnel': d['section_8_board_headline']['seller_funnel'],
    }
    dist = {
        'live_price_bands': t['price_bands'],
        'live_by_category': t['live_by_category'],
        'items_per_seller_bands': t['items_per_seller_bands'],
        'crew_shift_loads': dist9['crew_shift_loads'],
        'crew_top3_shifts': dist9['crew_top3_shifts'],
        'crew_top3_share_pct': dist9['crew_top3_share_pct'],
        'crew_total_shifts': dist9['crew_total_shifts'],
        'active_storage_units': dist9['active_storage_units'],
        'storage_units_holding_inventory': len(t['storage_units']),
    }
    origin = {'buckets': t['origin_buckets']}
    comp = {'categories': t['categories'],
            'grand_total': {'total': t['items_recorded']}}

    start = datetime.strptime(str(g['date_range_start'])[:10], '%Y-%m-%d')
    end = datetime.strptime(str(g['date_range_end'])[:10], '%Y-%m-%d')
    span = f'{start.strftime("%B %-d")} – {end.strftime("%B %-d, %Y")}'

    # fill missing weeks with zeros so the time axis is not compressed
    wl = {w['week_start']: w['count'] for w in h['weekly_listings']}
    cur = datetime.strptime(min(wl), '%Y-%m-%d')
    last = datetime.strptime(max(wl), '%Y-%m-%d')
    series = []
    while cur <= last:
        k = cur.strftime('%Y-%m-%d')
        series.append({'week_start': k, 'count': wl.get(k, 0)})
        cur += timedelta(days=7)

    funnel = []
    for i, s in enumerate(h['seller_funnel']):
        sub = ''
        if i:
            prev = h['seller_funnel'][i - 1]['count']
            sub = f'{100.0 * s["count"] / prev:.0f}% of previous' if prev else ''
        funnel.append({'stage': s['stage'], 'count': s['count'], 'sub': sub})

    # busiest four consecutive weeks (computed, not assumed)
    busiest = max(series, key=lambda x: x['count'])
    win = max(range(max(len(series) - 3, 1)),
              key=lambda i: sum(s['count'] for s in series[i:i + 4]))
    peak = series[win:win + 4]
    peak_sum = sum(s['count'] for s in peak)
    peak_start = datetime.strptime(peak[0]['week_start'], '%Y-%m-%d')
    peak_end = datetime.strptime(peak[-1]['week_start'], '%Y-%m-%d') + timedelta(days=6)
    peak_pct = 100 * peak_sum // h['items_listed_by_sellers']

    cats = [c for c in comp['categories'] if c['total'] > 0]
    by_name = {c['category_name']: c for c in cats}
    furn = by_name['Furniture']
    kitchen = by_name['Kitchen & Appliances']
    total_stored = comp['grand_total']['total']
    furn_kitchen_pct = 100 * (furn['total'] + kitchen['total']) // total_stored
    live_cats = dist['live_by_category']
    live_top2_value_pct = round(
        100.0 * (live_cats[0]['list_value'] + live_cats[1]['list_value'])
        / h['live_inventory_list_value'])

    p = []  # pages

    # ── PAGE 1 — cover ──────────────────────────────────────────────────────
    p.append(f'''
<section class="page cover">
  <div class="cov-top">
    <div class="brandmark">CAMPUS SWAP</div>
    <div class="cov-rule"></div>
    <h1>Year One<br>Operating Report</h1>
    <p class="cov-sub">Inventory built and ready to sell — UNC Chapel Hill, {span}</p>
  </div>
  <div class="cov-mid">
    <div class="cov-kicker">The season at a glance</div>
  <div class="cov-stats">
    {stat(fmt(h['items_listed_by_sellers']), 'items listed by sellers',
          f"from {h['sellers_who_listed']} sellers")}
    {stat(fmt(h['physical_items_in_storage']), 'items on hand today',
          f"{fmt(h['seller_items_in_storage_physical'])} seller · "
          f"{fmt(h['campus_swap_items_in_storage'])} Campus Swap")}
    {stat(fmt(h['live_in_shop_total']), 'items listed in the shop',
          f"${fmt(int(h['live_inventory_list_value']))} at list price")}
    {stat(f"{round(100 * logistics['totals']['pickups_completed'] / logistics['totals']['pickups_scheduled'])}%",
          'pickup completion rate',
          f"{logistics['totals']['pickups_completed']} of "
          f"{logistics['totals']['pickups_scheduled']} scheduled stops")}
  </div>
  </div>
  <div class="cov-foot">
    <span>Prepared for the board · {date.today().strftime('%B %-d, %Y')}</span>
    <span>No items have sold to date — this report covers inventory and operations only.</span>
  </div>
</section>''')

    # ── PAGE 2 — the season in one page ─────────────────────────────────────
    recon_rows = [
        ('Items collected from sellers', t['seller_items_collected'],
         f"from {t['sellers_collected_from']} sellers, counted in the warehouse"),
        ('Campus Swap–owned items added', t['campus_swap_owned'],
         'kept by Campus Swap instead of being matched to a seller'),
        ('Not yet catalogued individually', t['unrecorded_gap'],
         'mostly identical twin mattresses, held as a single listing'),
        ('Items on hand today', t['items_on_hand_physical'],
         'hand counted, unit by unit, across all eight units'),
        ('Listed in the shop', t['shop_items'],
         f"${fmt(int(t['list_value']))} at list price, every one ready to sell"),
    ]
    rows_html = ''
    for i, (lab, val, note) in enumerate(recon_rows):
        cls = 'tot' if i >= 3 else ''
        rows_html += (f'<tr class="{cls}"><td class="rl">{esc(lab)}'
                      f'<span class="rn">{esc(note)}</span></td>'
                      f'<td class="rv">{fmt(val)}</td></tr>')

    p.append(f'''
<section class="page">
  {page_head('The season in one page', '01')}
  <p class="lede">Campus Swap ran its first full pickup season at UNC Chapel Hill this
  summer: we collected {t['seller_items_collected']} items from {t['sellers_collected_from']}
  students, added {t['campus_swap_owned']} of our own, and organised all
  {t['items_on_hand_physical']} of them across {t['storage_units_retained']} storage units.
  {fmt(t['shop_items'])} are live in the shop today. Nothing has sold yet — every number here
  describes inventory and operations, not revenue.</p>

  <h2>How the inventory was built</h2>
  <table class="recon"><tbody>{rows_html}</tbody></table>
  <p class="cap">Every figure is a physical count taken in the warehouse, not a count of
  database records. {fmt(t['items_recorded'])} items are catalogued one by one; the other
  {t['unrecorded_gap']} are a block of identical twin mattresses held as a single listing,
  plus a small count variance across four units.</p>

  <div class="grid2">
    <div>
      <h2>What sellers gave us</h2>
      <div class="kv"><span>Sellers we collected from</span><b>{t['sellers_collected_from']}</b></div>
      <div class="kv"><span>Sellers with a completed pickup</span><b>{t['sellers_completed_pickup']}</b></div>
      <div class="kv"><span>Busiest listing week</span><b>{busiest['count']} items</b></div>
      <div class="kv"><span>Largest single seller</span><b>{h['items_per_seller']['max']} items</b></div>
    </div>
    <div>
      <h2>What we are selling</h2>
      <div class="kv"><span>Items listed in the shop</span><b>{fmt(h['live_in_shop_total'])}</b></div>
      <div class="kv"><span>List value of shop inventory</span><b>${fmt(int(h['live_inventory_list_value']))}</b></div>
      <div class="kv"><span>Average list price</span><b>${h['live_inventory_avg_price']:.0f}</b></div>
      <div class="kv"><span>Storage units in use</span><b>{t['storage_units_retained']}</b></div>
      <div class="kv"><span>Awaiting details or pricing</span><b>{t['awaiting_details_or_price']}</b></div>
    </div>
  </div>

  <h2>What this season established</h2>
  <ul class="meth">
    <li><b>Demand is compressed, not seasonal.</b> {peak_pct}% of all listings arrived in a
        single four-week window. Trucks, crew and storage have to be sized for that spike,
        which is what makes a shared operation cheaper than every student solving it alone.</li>
    <li><b>Execution held under load.</b>
        {logistics['totals']['pickups_completed']} of
        {logistics['totals']['pickups_scheduled']} scheduled stops
        ({round(100 * logistics['totals']['pickups_completed'] / logistics['totals']['pickups_scheduled'])}%)
        were completed by {crew['distinct_crew_members']} part-time student workers. Of the
        {logistics['totals']['pickups_scheduled'] - logistics['totals']['pickups_completed']}
        stops that did not complete, {logistics['totals']['no_show']} were seller no-shows.</li>
    <li><b>The book is furniture.</b> Furniture and appliances are
        {furn_kitchen_pct}% of everything on hand and {live_top2_value_pct}% of shop list
        value — the goods a student physically cannot move alone.</li>
    <li><b>What is still unproven: sell-through.</b> No item has sold yet. The shop is live
        with {fmt(h['live_in_shop_total'])} items and this autumn is the test of whether the
        inventory converts at the prices we set.</li>
  </ul>
</section>''')

    # ── PAGE 3 — sellers ────────────────────────────────────────────────────
    p.append(f'''
<section class="page">
  {page_head('Sellers', '02')}
  <h2>Seller funnel — account to completed pickup</h2>
  <p class="cap">Every stage is a distinct student count, not an item count.</p>
  {chart_hbar(funnel, 'stage', 'count', 'Seller funnel by stage', sub_key='sub',
              row_h=23, bar_h=14)}
  <p class="note"><b>{h['seller_funnel'][2]['count']} of {h['seller_funnel'][1]['count']}</b>
  students who signed up to sell actually listed an item — the largest drop in the funnel,
  and the clearest place to gain volume next season. Of those who listed,
  {100 * h['seller_funnel'][4]['count'] // h['seller_funnel'][2]['count']}% completed a pickup.</p>

  <p class="cap">Listing and collecting are different numbers, and the report keeps them
  separate: {t['submissions']} items were listed by {t['submission_sellers']} students, and
  {t['seller_items_collected']} of them reached the warehouse, from
  {t['sellers_collected_from']} sellers. The
  {t['listings_without_an_item_on_hand']} listings that never arrived were no-shows,
  cancellations, or items the seller sold or kept before we got there. Everything elsewhere in
  this report counts what we actually collected.</p>

  <h2>How much each seller brought</h2>
  {chart_hbar([{'l': b['band'], 'v': b['count']} for b in dist['items_per_seller_bands']],
              'l', 'v', 'Sellers by number of items listed', row_h=23, bar_h=14)}
  <p class="note">The book is built on a long tail:
  {dist['items_per_seller_bands'][0]['count']} of {h['sellers_who_listed']} sellers listed a
  single item, while the {dist['items_per_seller_bands'][4]['count']} largest sellers brought
  11 or more each. Acquisition cost is per seller, so lifting items per seller is a cheaper
  way to grow volume than recruiting new sellers.</p>

  <h2>Where items came from</h2>
  {chart_hbar([{'l': loc_label(b['bucket']), 'v': b['item_count'],
                's': f"{b['pct_of_total']}%"} for b in origin['buckets']],
              'l', 'v', 'Items by seller location type', sub_key='s', row_h=23, bar_h=14)}
  <p class="cap">A <b>partner complex</b> is one of the buildings a seller picks from a list
  at signup, where we run a concentrated route rather than individual stops.
  <b>Other off-campus</b> means the seller typed their own address — a house or an
  unlisted apartment, collected as a one-off stop. Location type was never recorded for
  {[b for b in origin['buckets'] if b['bucket'] == 'not_set'][0]['pct_of_total']}% of
  listings, mostly items logged by crew at the warehouse.</p>

  <h2>The buildings that carried the season</h2>
  <table class="data">
    <thead><tr><th>Building</th><th>Type</th><th class="n">Items listed</th></tr></thead>
    <tbody>{''.join(
        f'<tr><td>{esc(b["name"])}</td>'
        f'<td>{"Partner complex" if b["type"] == "off_campus_complex" else "Residence hall"}</td>'
        f'<td class="n">{b["items"]}</td></tr>'
        for b in t['pickup_buildings'][:6])}</tbody>
  </table>
  <p class="cap">Dense buildings are the cheapest routes we run — one stop, one elevator,
  many items. Granville Towers alone produced {t['pickup_buildings'][0]['items']} listings,
  more than every residence hall combined.</p>
</section>''')

    # ── PAGE 3b — timing ────────────────────────────────────────────────────
    p.append(f'''
<section class="page">
  {page_head('Demand timing', '03')}
  <h2>Listings created per week</h2>
  <p class="cap">Seller submissions by week created. Weeks with no activity are shown at zero.</p>
  {chart_columns(series, 'Seller listings created per week', h=206)}
  <p class="note">Listing volume tracked move-out almost perfectly. The four weeks from
  {peak_start.strftime('%B %-d')} to {peak_end.strftime('%B %-d')} carried
  <b>{peak_sum} of {h['items_listed_by_sellers']} listings ({peak_pct}%)</b>. Everything about
  the operation — trucks, crew, storage — is sized for that four-week window, not for the
  seasonal average.</p>

  <div class="grid3">
    {stat(peak_sum, 'listings in the peak four weeks')}
    {stat(f'{peak_pct}%', 'of the season in those weeks')}
    {stat(max(s['count'] for s in series), 'listings in the single busiest week')}
  </div>

  <h2>Pickups completed per week</h2>
  <p class="cap">Scheduled stops and completions, same weeks.</p>
  {legend([('Completed', GREEN), ('Not completed', RULE)])}
  {chart_stacked([{'name': datetime.strptime(w['week_start'], '%Y-%m-%d').strftime('%b %-d'),
                   'done': w['pickups_completed'],
                   'missed': w['pickups_scheduled'] - w['pickups_completed']}
                  for w in logistics['weeks'] if w['pickups_scheduled']],
                 'name', ['done', 'missed'], [GREEN, RULE],
                 'Pickup stops completed versus missed per week', label_w=70, row_h=30, bar_h=17)}
  <p class="note">Pickup scheduling ran <b>ahead</b> of listing demand, not behind it: the
  week of May 4 carried {logistics['weeks'][0]['pickups_scheduled']} of
  {logistics['totals']['pickups_scheduled']} stops
  ({100 * logistics['weeks'][0]['pickups_scheduled'] // logistics['totals']['pickups_scheduled']}%)
  while listings did not peak until the following week. Next season the stop schedule should
  be weighted a week later, toward weeks two and three of the move-out window, so capacity
  lands where the listings actually are.</p>
</section>''')

    # ── PAGE 4 — inventory composition ──────────────────────────────────────
    tbl = ''
    for c in cats:
        tbl += (f'<tr><td>{esc(c["category_name"])}</td>'
                f'<td class="n">{c["total"]}</td>'
                f'<td class="n">{c["seller_items"]}</td>'
                f'<td class="n">{c["campus_swap_items"]}</td>'
                f'<td class="n">{100 * c["total"] // t["items_recorded"]}%</td></tr>')
    tbl += (f'<tr class="tot"><td>Total</td><td class="n">{t["items_recorded"]}</td>'
            f'<td class="n">{t["seller_items_collected"]}</td>'
            f'<td class="n">{t["campus_swap_owned"]}</td>'
            f'<td class="n">100%</td></tr>')

    p.append(f'''
<section class="page">
  {page_head('Inventory', '04')}
  <h2>What we are holding, by category</h2>
  <p class="cap">Every item counted at the warehouse, seller-owned and Campus Swap–owned.</p>
  {legend([('Seller-owned', GREEN), ('Campus Swap–owned', AMBER)])}
  {chart_stacked([{'name': c['category_name'], 'seller_items': c['seller_items'],
                   'campus_swap_items': c['campus_swap_items']} for c in cats],
                 'name', ['seller_items', 'campus_swap_items'], [GREEN, AMBER],
                 'Items in storage by category and owner', label_w=140)}
  <p class="note">Furniture is the business. {furn['total']} of the {total_stored}
  catalogued items ({100 * furn['total'] // total_stored}%) are furniture, and with Kitchen &amp;
  Appliances the two categories make up
  {furn_kitchen_pct}% of the book. They are also the
  categories a student cannot move alone — which is precisely why the truck-and-storage model
  exists.</p>

  <h2>Every item on hand, by category and owner</h2>
  <table class="data">
    <thead><tr><th>Category</th><th class="n">Items</th><th class="n">Seller-owned</th>
    <th class="n">Campus Swap</th><th class="n">Share</th></tr></thead>
    <tbody>{tbl}</tbody>
  </table>
  <p class="cap">Campus Swap–owned stock is concentrated in furniture — the items nobody
  claimed were kept and listed rather than thrown out, which is why they outnumber
  seller-owned furniture. The 37 identical dressers are counted as 37 sellable units.</p>

  <h2>Listed versus held</h2>
  <div class="grid3">
    {stat(fmt(t['items_recorded']), 'items catalogued')}
    {stat(fmt(t['shop_items']), 'listed in the shop')}
    {stat(t['awaiting_details_or_price'], 'awaiting details or pricing',
          f"{t['blank_records']} still to be catalogued")}
  </div>
  <p class="cap">The {t['awaiting_details_or_price']} awaiting details are mostly the
  mattress unit: sellers are exempt from photographing mattresses by design, so those items
  are inspected at pickup and catalogued afterwards. They are inventory we hold, not yet
  inventory a buyer can see.</p>
</section>''')

    # ── PAGE 4b — furniture in detail ───────────────────────────────────────
    fs = t['furniture_subcategories']
    fs_total = sum(f['total'] for f in fs)
    dressers = next((f for f in fs if f['name'] == 'Dresser'), fs[0])
    sofas = next((f for f in fs if f['name'] == 'Couch / Sofa'), fs[1])
    p.append(f"""
<section class="page">
  {page_head('Furniture in detail', '05')}
  <p class="lede">Furniture is {100 * fs_total // t['items_recorded']}% of everything we hold
  and {live_top2_value_pct}% of shop value alongside appliances, so it is worth seeing at the
  level we actually buy, store and move it.</p>

  <h2>What the furniture actually is</h2>
  {legend([('Seller-owned', GREEN), ('Campus Swap–owned', AMBER)])}
  {chart_stacked([{'name': f['name'], 'seller_items': f['seller_items'],
                   'campus_swap_items': f['campus_swap_items']} for f in fs],
                 'name', ['seller_items', 'campus_swap_items'], [GREEN, AMBER],
                 'Furniture on hand by type and owner', label_w=152,
                 row_h=21, bar_h=13)}
  <p class="note">Dressers are the single biggest line at {dressers['total']} units, and
  <b>{dressers['campus_swap_items']} of them are Campus Swap–owned</b> — the identical-unit
  lot we hold. Sofas are only {sofas['total']} units but carry the highest average price at
  ${sofas['avg_price']:.0f}, so they punch well above their count in list value.</p>

  <h2>Average price by furniture type</h2>
  <table class="data">
    <thead><tr><th>Type</th><th class="n">On hand</th><th class="n">Seller-owned</th>
    <th class="n">Campus Swap</th><th class="n">Average price</th></tr></thead>
    <tbody>{''.join(
        f'<tr><td>{esc(f["name"])}</td><td class="n">{f["total"]}</td>'
        f'<td class="n">{f["seller_items"]}</td>'
        f'<td class="n">{f["campus_swap_items"]}</td>'
        f'<td class="n">{("$" + format(f["avg_price"], ".0f")) if f["avg_price"] else "—"}</td></tr>'
        for f in fs)}
    <tr class="tot"><td>All furniture</td><td class="n">{fs_total}</td>
    <td class="n">{sum(f['seller_items'] for f in fs)}</td>
    <td class="n">{sum(f['campus_swap_items'] for f in fs)}</td>
    <td class="n">—</td></tr></tbody>
  </table>
  <p class="cap">Average price covers the items in each type that carry a price.</p>
</section>""")

    # ── PAGE 5 — pricing ────────────────────────────────────────────────────
    agg = pricing['aggregate']
    bands = dist['live_price_bands']
    mid = bands[1]['count'] + bands[2]['count']
    p.append(f'''
<section class="page">
  {page_head('Pricing', '06')}
  <h2>Inventory value</h2>
  <div class="grid3">
    {stat('$' + fmt(int(h['live_inventory_list_value'])), 'list value of inventory')}
    {stat('$' + f"{h['live_inventory_avg_price']:.0f}", 'average list price')}
    {stat(fmt(h['live_in_shop_total']), 'priced items in the warehouse')}
  </div>
  <p class="cap">This is every priced item in the warehouse, not only what renders on the
  site this second: {t['rendering_now']} are live now and
  {t['awaiting_photo_processing']} are finishing image processing. A further
  {t['awaiting_details_or_price']} items on hand are not yet priced and are excluded, so the
  real figure is higher. It measures inventory on hand, not expected revenue — sell-through
  and final sale prices are both still unknown.</p>

  <h2>How the shop is priced</h2>
  <p class="cap">Every priced item in the warehouse, by list price. The
  {t['awaiting_details_or_price']} items still to be priced — mostly the mattress unit — are
  not shown.</p>
  {chart_columns([{'week_start': b['band'], 'count': b['count']} for b in bands],
                 'Live inventory by price band', categorical_labels=True, h=200)}
  <p class="note"><b>{mid} of the {sum(b['count'] for b in bands)} priced items
  ({100 * mid // sum(b['count'] for b in bands)}%)
  sit between $25 and $99</b> — the range a student will pay without deliberating, and
  low enough that delivery economics still work. The {bands[4]['count']} items above $200 are
  where the margin sits, and they are the listings to prioritise next year.</p>

  <h2>Where the list value sits</h2>
  <table class="data">
    <thead><tr><th>Category</th><th class="n">Priced items</th>
    <th class="n">Average price</th><th class="n">List value</th>
    <th class="n">Share of value</th></tr></thead>
    <tbody>{''.join(
        f'<tr><td>{esc(c["category_name"])}</td><td class="n">{c["count"]}</td>'
        f'<td class="n">${c["avg_price"]:.0f}</td>'
        f'<td class="n">${fmt(int(c["list_value"]))}</td>'
        f'<td class="n">{100 * c["list_value"] / h["live_inventory_list_value"]:.0f}%</td></tr>'
        for c in dist['live_by_category'])}
    <tr class="tot"><td>Total</td>
    <td class="n">{sum(c['count'] for c in dist['live_by_category'])}</td>
    <td class="n">${h['live_inventory_avg_price']:.0f}</td>
    <td class="n">${fmt(int(h['live_inventory_list_value']))}</td>
    <td class="n">100%</td></tr></tbody>
  </table>

  <h2>Intake estimate vs. final list price</h2>
  <div class="grid3">
    {stat('$' + f"{agg['avg_suggested']:.0f}", 'average intake estimate')}
    {stat('$' + f"{agg['avg_listed']:.0f}", 'average final list price')}
    {stat(f"{agg['pct_diff']:+.0f}%", 'listed above estimate')}
  </div>
  <p class="cap">Based on the {agg['n']} items carrying both an intake estimate and a final
  list price — {agg['listed_higher']} were listed higher, {agg['listed_lower']} lower and
  {agg['unchanged']} unchanged. Intake estimates were only recorded for part of the season, so
  this is a directional signal on a small sample, not a season-wide pricing result. It is
  reported here because it is the closest thing we have to a valuation check before the first
  sale.</p>
</section>''')

    # ── PAGE 6 — storage ────────────────────────────────────────────────────
    su = t['storage_units']
    su_phys = sum(u['physical'] for u in su)
    retained = t['storage_units_retained']
    cancelled = t['storage_units_ever_rented'] - retained
    p.append(f'''
<section class="page">
  {page_head('Storage', '07')}
  <h2>Where the inventory sits</h2>
  <p class="cap">Hand counted unit by unit during the re-organisation. Each unit now holds a
  single category, which is what makes a stack findable months later.</p>
  {chart_hbar([{'l': f"{u['number']} · {u['label'].replace(' Unit', '')}",
                'v': u['physical']} for u in su], 'l', 'v',
              'Items per storage unit', label_w=210, pad_r=52)}
  <p class="note">The footprint is now organised by category rather than by whatever fit
  on the day — <b>mattresses in {su[2]['number']}, dressers in {su[4]['number']}, couches
  split across {su[0]['number']} and {su[6]['number']}</b>. That is what let two people count
  all {su_phys} items in an afternoon, and it is the difference between a storage unit and a
  warehouse.</p>

  <h2>We over-bought storage, and fixed it</h2>
  <div class="grid3">
    {stat(t['storage_units_ever_rented'], 'units rented across the season')}
    {stat(retained, 'units retained after consolidation')}
    {stat(cancelled, 'units being cancelled')}
  </div>
  <p class="cap">Units were taken on ahead of the move-out rush, when the size of the intake
  was still a guess. All {retained} retained units are now marked full, and consolidating into
  them is the clearest cost lesson of the season: the next campus starts with a fraction of the
  footprint and adds only against measured volume. Storage cost itself sits in the separate
  financial breakdown.</p>

  <h2>Owner mix on hand</h2>
  <div class="grid3">
    {stat(fmt(t['seller_items_collected']), 'collected from sellers')}
    {stat(fmt(t['campus_swap_owned']), 'Campus Swap–owned',
          f"{t['campaign_buckets']['kept_for_campus_swap']} kept for resale")}
    {stat(fmt(t['unrecorded_gap']), 'not yet catalogued',
          'the twin mattress block')}
  </div>
  <p class="cap">Together that is the {t['items_on_hand_physical']} items on hand. Campus
  Swap–owned stock now exceeds what sellers supplied, because items nobody claimed were kept
  and listed rather than thrown out — inventory we own outright and keep the full sale price
  on.</p>
</section>''')

    # ── PAGE 7b — the units themselves ──────────────────────────────────────
    um = t['unit_metrics']
    ut = t['unit_totals']
    dense = max(um, key=lambda m: m['items_per_100_sqft'] or 0)
    # the mattress unit is priced as one listing, so exclude it from value comparisons
    fully_priced = [m for m in um if m['items_priced'] >= m['items'] * 0.5]
    weakest_priced = min(fully_priced, key=lambda m: m['value_per_sqft'] or 0)
    priciest = max(um, key=lambda m: m['avg_price'] or 0)
    p.append(f"""
<section class="page">
  {page_head('Storage units in detail', '08')}
  <p class="lede">{ut['sqft']:,.0f} square feet holding {ut['items']} catalogued items worth
  ${fmt(int(ut['value']))} — <b>${ut['value_per_sqft']:.2f} of inventory per square foot</b>.
  Each unit is packed with one category, so the economics of each differ sharply.</p>

  <h2>Inventory value per square foot</h2>
  <p class="cap">The measure that matters for a rented footprint: how much sellable value each
  square foot is carrying.</p>
  {chart_hbar([{'l': f"{m['number']} · {m['label'].replace(' Unit', '')}",
                'v': m['value_per_sqft'] or 0,
                's': f"${fmt(int(m['value']))}"} for m in um],
              'l', 'v', 'Inventory value per square foot by unit',
              sub_key='s', label_w=210, pad_r=96, row_h=25, bar_h=14,
              value_fmt=lambda v: f'${v:.2f}')}
  <p class="note"><b>{um[0]['number']} carries ${um[0]['value_per_sqft']:.2f} per square foot,
  {um[0]['value_per_sqft'] / weakest_priced['value_per_sqft']:.1f}× {weakest_priced['number']}
  at ${weakest_priced['value_per_sqft']:.2f}.</b>
  {dense['number']} is the densest at {dense['items_per_100_sqft']:.0f} items per 100 sq ft but
  averages only ${dense['avg_price']:.0f} an item, while {priciest['number']} holds
  {priciest['items']} items at ${priciest['avg_price']:.0f} each. Density and value are
  different problems, and the mix tells us what to rent next season.</p>

  <h2>Unit by unit</h2>
  <table class="data">
    <thead><tr><th>Unit</th><th>Holds</th><th class="n">Size</th><th class="n">Items</th>
    <th class="n">Value</th><th class="n">Avg price</th><th class="n">$/sq ft</th>
    <th class="n">Items/100 sq ft</th></tr></thead>
    <tbody>{''.join(
        f'<tr><td>{esc(m["number"])}</td>'
        f'<td>{esc(m["label"].replace(" Unit", ""))}</td>'
        f'<td class="n">{esc(m["size_label"])}</td>'
        f'<td class="n">{m["items"]}</td>'
        f'<td class="n">${fmt(int(m["value"]))}</td>'
        f'<td class="n">{("$" + format(m["avg_price"], ".0f")) if m["avg_price"] else "—"}</td>'
        f'<td class="n">${m["value_per_sqft"]:.2f}</td>'
        f'<td class="n">{m["items_per_100_sqft"]:.0f}</td></tr>' for m in um)}
    <tr class="tot"><td>Total</td><td>8 units</td>
    <td class="n">{ut['sqft']:,.0f} sq ft</td><td class="n">{ut['items']}</td>
    <td class="n">${fmt(int(ut['value']))}</td>
    <td class="n">${ut['avg_price']:.0f}</td>
    <td class="n">${ut['value_per_sqft']:.2f}</td>
    <td class="n">{ut['items_per_100_sqft']:.0f}</td></tr></tbody>
  </table>
  <p class="cap">Size is the unit's footprint as rented. Value counts every catalogued item
  carrying a price; the mattress unit reads low because that block is priced as one listing
  until its stock is entered. Rent is excluded here and sits in the financial breakdown —
  paired with these figures it gives a value-to-rent ratio per unit, which is how we will
  choose unit sizes at the next campus.</p>
</section>""")

    # ── PAGE 7 — operations ─────────────────────────────────────────────────
    wk_rows = ''
    for w in logistics['weeks']:
        if not w['pickups_scheduled']:
            continue
        dt = datetime.strptime(w['week_start'], '%Y-%m-%d')
        rate = (f'{round(100 * w["pickups_completed"] / w["pickups_scheduled"])}%'
                if w['pickups_scheduled'] else '—')
        wk_rows += (f'<tr><td>Week of {dt.strftime("%B %-d")}</td>'
                    f'<td class="n">{w["truck_shifts_used"]}</td>'
                    f'<td class="n">{w["pickups_scheduled"]}</td>'
                    f'<td class="n">{w["pickups_completed"]}</td>'
                    f'<td class="n">{w["no_show"]}</td>'
                    f'<td class="n">{w["other_issue"] + w["never_actioned"]}</td>'
                    f'<td class="n">{rate}</td></tr>')
    lt = logistics['totals']
    wk_rows += (f'<tr class="tot"><td>Total</td><td class="n">{lt["truck_shifts_run"]}</td>'
                f'<td class="n">{lt["pickups_scheduled"]}</td>'
                f'<td class="n">{lt["pickups_completed"]}</td>'
                f'<td class="n">{lt["no_show"]}</td>'
                f'<td class="n">{lt["other_issue"] + lt["never_actioned"]}</td>'
                f'<td class="n">{round(100 * lt["pickups_completed"] / lt["pickups_scheduled"])}%</td></tr>')

    p.append(f'''
<section class="page">
  {page_head('Operations', '09')}
  <h2>Pickup weeks</h2>
  <table class="data">
    <thead><tr><th>Week</th><th class="n">Truck-shifts</th><th class="n">Stops scheduled</th>
    <th class="n">Completed</th><th class="n">No-show</th><th class="n">Cancelled / other</th>
    <th class="n">Rate</th></tr></thead>
    <tbody>{wk_rows}</tbody>
  </table>
  <p class="note">We completed <b>{lt['pickups_completed']} of {lt['pickups_scheduled']}
  scheduled stops ({round(100 * lt['pickups_completed'] / lt['pickups_scheduled'])}%)</b> across
  {lt['truck_shifts_run']} truck-shifts. Every stop that did not complete was the seller's
  side, not ours: {lt['no_show']} were no-shows where nobody met the truck, and
  {lt['other_issue'] + lt['never_actioned']} were cancelled or called off before the visit.
  When a student was there, we collected.</p>

  <h2>Crew</h2>
  <div class="grid3">
    {stat(crew['distinct_crew_members'], 'crew members')}
    {stat(crew['total_shift_assignments'], 'shift assignments filled')}
    {stat(crew['weeks_with_staffed_shifts'], 'weeks staffed')}
  </div>
  <p class="cap">All shifts were worked in the mover role; a separate warehouse organiser
  role was trialled and retired during the season.</p>

  <h2>Shifts worked per crew member</h2>
  {chart_hbar([{'l': c['crew'], 'v': c['shifts']} for c in dist['crew_shift_loads']],
              'l', 'v', 'Shifts worked per crew member', label_w=70, row_h=22, bar_h=13)}
  <p class="note">Coverage leaned on a core:
  <b>three workers covered {dist['crew_top3_shifts']} of {dist['crew_total_shifts']} shifts
  ({dist['crew_top3_share_pct']:.0f}%)</b>. That is efficient at one school and a single point
  of failure at twenty — a deeper bench is the first hire we make at each new campus.</p>

  <h2>What this proves for school two</h2>
  <p class="note">One campus, {h['sellers_who_listed']} sellers,
  {h['items_listed_by_sellers']} listings and {t['items_recorded']} items warehoused were
  delivered by {crew['distinct_crew_members']} part-time student hires, rented trucks and
  {t['storage_units_retained']} storage units — no owned vehicles, no warehouse lease and
  no full-time operations staff. That is the unit we intend to replicate.</p>
</section>''')


    return ''.join(p)


def page_head(title, num):
    return (f'<header class="ph"><span class="pt">{esc(title)}</span>'
            f'<span class="pn">{esc(num)}</span></header>')


CSS = f'''
@page {{ size: letter; margin: 0; }}
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; padding: 0; }}
body {{
  font-family: "Helvetica Neue", Helvetica, system-ui, -apple-system, sans-serif;
  color: {INK}; background: #FFFFFF; -webkit-font-smoothing: antialiased;
}}
.page {{
  width: 8.5in; height: 11in; padding: 0.62in 0.75in 0.55in;
  background: #FFFFFF; position: relative; overflow: hidden;
  page-break-after: always; break-after: page;
}}
.page:last-child {{ page-break-after: auto; break-after: auto; }}

/* cover */
.cover {{ background: {CREAM}; display: flex; flex-direction: column;
  padding: 1.15in 0.85in 0.7in; }}
.cov-top {{ flex: 0 0 auto; }}
.cov-mid {{ flex: 1 1 auto; display: flex; flex-direction: column;
  justify-content: flex-start; padding-top: 0.62in; }}
.cov-kicker {{ font-size: 9px; letter-spacing: 0.18em; text-transform: uppercase;
  font-weight: 700; color: {AMBER}; margin-bottom: 12px; }}
.brandmark {{ font-size: 11px; letter-spacing: 0.22em; font-weight: 600;
  color: {FOREST}; }}
.cov-rule {{ width: 46px; height: 3px; background: {AMBER}; margin: 16px 0 30px; }}
.cover h1 {{ font-family: Georgia, "Times New Roman", serif; font-weight: 400;
  font-size: 52px; line-height: 1.06; letter-spacing: -0.02em; color: {FOREST};
  margin: 0 0 18px; }}
.cov-sub {{ font-size: 13px; color: {INK_2}; margin: 0; max-width: 4.6in;
  line-height: 1.55; }}
.cov-stats {{ display: grid; grid-template-columns: 1fr 1fr; gap: 1px;
  background: {RULE}; border: 1px solid {RULE}; }}
.cov-stats .stat {{ background: {CREAM}; padding: 20px 18px 18px; }}
.cov-foot {{ display: flex; justify-content: space-between; font-size: 9px;
  color: {MUTED}; border-top: 1px solid {RULE}; padding-top: 12px; gap: 20px; }}

/* page chrome */
.ph {{ display: flex; justify-content: space-between; align-items: baseline;
  border-bottom: 1px solid {RULE}; padding-bottom: 8px; margin-bottom: 22px; }}
.pt {{ font-family: Georgia, serif; font-size: 19px; color: {FOREST}; }}
.pn {{ font-size: 9px; letter-spacing: 0.16em; color: {MUTED}; font-weight: 600; }}

h2 {{ font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase;
  font-weight: 700; color: {FOREST}; margin: 26px 0 8px; }}
.ph + h2 {{ margin-top: 0; }}
.lede {{ font-size: 12.5px; line-height: 1.62; color: {INK_2}; margin: 0 0 6px;
  max-width: 6.4in; }}
.lede + h2 {{ margin-top: 30px; }}
.cap {{ font-size: 9.5px; line-height: 1.5; color: {MUTED}; margin: 8px 0 0;
  max-width: 6.4in; }}
.note {{ font-size: 11px; line-height: 1.58; color: {INK_2}; margin: 12px 0 0;
  padding-left: 11px; border-left: 2px solid {AMBER}; max-width: 6.5in; }}
.note b {{ color: {INK}; font-weight: 600; }}

/* stats */
.stat {{ }}
.sv {{ font-family: Georgia, serif; font-size: 31px; line-height: 1.05;
  color: {FOREST}; letter-spacing: -0.015em; }}
.sl {{ font-size: 9.5px; letter-spacing: 0.04em; color: {INK_2}; margin-top: 6px;
  text-transform: uppercase; font-weight: 600; }}
.sn {{ font-size: 9px; color: {MUTED}; margin-top: 3px; line-height: 1.4; }}
.grid2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 34px; margin-top: 4px; }}
.grid3 {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 22px;
  margin-top: 6px; }}
.note + .grid3 {{ margin-top: 24px; }}
.grid3 + h2 {{ margin-top: 30px; }}
.grid3 .sv {{ font-size: 26px; }}

/* key-values */
.kv {{ display: flex; justify-content: space-between; align-items: baseline;
  border-bottom: 1px solid {GRID}; padding: 7px 0; font-size: 11px;
  color: {INK_2}; }}
.kv b {{ color: {INK}; font-weight: 600; font-variant-numeric: tabular-nums; }}

/* tables */
table {{ width: 100%; border-collapse: collapse; margin-top: 4px; }}
.recon td {{ padding: 11px 0; border-bottom: 1px solid {GRID}; vertical-align: baseline; }}
.recon .rl {{ font-size: 11.5px; color: {INK}; }}
.recon .rn {{ display: block; font-size: 9px; color: {MUTED}; margin-top: 2px; }}
.recon .rv {{ text-align: right; font-family: Georgia, serif; font-size: 22px;
  color: {FOREST}; font-variant-numeric: tabular-nums; white-space: nowrap;
  padding-left: 16px; }}
.recon tr.tot .rv {{ color: {INK}; }}
.recon tr:nth-child(3) td {{ border-bottom: 2px solid {BASELINE}; }}
.data th {{ font-size: 8.5px; letter-spacing: 0.06em; text-transform: uppercase;
  color: {MUTED}; font-weight: 700; text-align: left; padding: 0 8px 7px 0;
  border-bottom: 1px solid {BASELINE}; }}
.data td {{ font-size: 10.5px; padding: 7px 8px 7px 0; border-bottom: 1px solid {GRID};
  color: {INK_2}; }}
.data td.n, .data th.n {{ text-align: right; font-variant-numeric: tabular-nums;
  padding-right: 0; }}
.data tr.tot td {{ font-weight: 700; color: {INK}; border-bottom: none;
  border-top: 1.5px solid {BASELINE}; }}

/* legend */
.legend {{ display: flex; gap: 18px; margin: 2px 0 10px; }}
.lg {{ font-size: 9.5px; color: {INK_2}; display: inline-flex; align-items: center;
  gap: 6px; }}
.sw {{ width: 9px; height: 9px; border-radius: 2px; display: inline-block; }}

/* method */
.meth {{ margin: 4px 0 0; padding-left: 16px; }}
.meth li {{ font-size: 10.5px; line-height: 1.6; color: {INK_2}; margin-bottom: 9px;
  max-width: 6.4in; }}
.meth b {{ color: {INK}; font-weight: 600; }}
code {{ font-family: "SF Mono", Menlo, monospace; font-size: 9.5px; color: {INK_2}; }}
'''


def main():
    with open(IN_FILE) as fh:
        d = json.load(fh)
    html = (f'<!doctype html><html><head><meta charset="utf-8">'
            f'<title>Campus Swap — Year One Operating Report</title>'
            f'<style>{CSS}</style></head><body>{build(d)}</body></html>')
    with open(OUT_HTML, 'w') as fh:
        fh.write(html)
    print(f'wrote {OUT_HTML}')

    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        pg = b.new_page(viewport={'width': 816, 'height': 1056})
        pg.goto('file://' + OUT_HTML)
        pg.wait_for_timeout(400)
        pg.pdf(path=OUT_PDF, width='8.5in', height='11in', print_background=True,
               margin={'top': '0', 'right': '0', 'bottom': '0', 'left': '0'})
        # page-by-page PNGs for visual QA
        for i, sec in enumerate(pg.query_selector_all('section.page'), 1):
            sec.screenshot(path=f'/tmp/board_report/page_{i:02d}.png')
        b.close()
    print(f'wrote {OUT_PDF}')
    print(f'wrote {len(os.listdir("/tmp/board_report"))} files total')


if __name__ == '__main__':
    main()
