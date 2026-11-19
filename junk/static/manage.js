/* Junk removal — manager calendar.
   - Navigation (arrows, Today, Week/Month) and saves swap the calendar in place: no page reloads.
   - Job modal is a server-rendered fragment, with Google Places suggestions + a map on the address field.
   - Drag and drop works in week and month view, and to/from the Unscheduled panel. */
(function () {
  'use strict';

  var app = document.getElementById('jr-app');
  if (!app) return;
  var formUrl = app.dataset.formUrl;
  var moveUrl = app.dataset.moveUrl;
  var csrf = (document.querySelector('meta[name="csrf-token"]') || {}).content || '';
  var modal = document.getElementById('jr-modal');
  var modalBody = modal.querySelector('[data-modal-body]');
  var toastEl = document.getElementById('jr-toast');

  var dragging = false;
  var refreshQueued = false;
  var lastDragEnd = 0;

  function cal() { return document.querySelector('[data-cal]'); }
  function returnTo() { var c = cal(); return (c && c.dataset.returnTo) || '/junk/manage'; }

  // ─── toast ────────────────────────────────────────────
  var toastTimer;
  function toast(msg) {
    toastEl.textContent = msg;
    toastEl.classList.add('is-on');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { toastEl.classList.remove('is-on'); }, 2600);
  }

  // ─── in-place navigation ──────────────────────────────
  var cache = new Map();   // url -> {at, promise}; cleared on any write
  var CACHE_MS = 20000;

  function fetchPage(url) {
    var hit = cache.get(url);
    if (hit && Date.now() - hit.at < CACHE_MS) return hit.promise;
    var promise = fetch(url, { credentials: 'same-origin' }).then(function (r) {
      if (!r.ok) throw new Error(r.status);
      return r.text();
    });
    cache.set(url, { at: Date.now(), promise: promise });
    promise.catch(function () { cache.delete(url); });
    return promise;
  }

  function parse(html) { return new DOMParser().parseFromString(html, 'text/html'); }

  // Everything that scrolls on its own inside the calendar, keyed so the same box can be
  // found again in the re-rendered calendar.
  var SCROLLERS = ['.jr-month', '.jr-list--unscheduled', '.jr-day .jr-list'];

  function eachScroller(root, fn) {
    SCROLLERS.forEach(function (sel, i) {
      root.querySelectorAll(sel).forEach(function (el) { fn(el, i + '|' + (el.dataset.date || '')); });
    });
  }

  function saveScroll(root) {
    var saved = {};
    eachScroller(root, function (el, key) { if (el.scrollTop) saved[key] = el.scrollTop; });
    return saved;
  }

  function restoreScroll(root, saved) {
    eachScroller(root, function (el, key) { if (saved[key]) el.scrollTop = saved[key]; });
  }

  // Swap the calendar for the one in `doc`. Returns false if the page isn't a calendar
  // (e.g. the session expired and we got the sign-in page). `keepScroll` is for re-rendering
  // the same view after a save: every scrolled day, list and month grid stays where it was.
  function applyDoc(doc, keepScroll) {
    var fresh = doc.querySelector('[data-cal]');
    var current = cal();
    if (!fresh || !current) return false;
    var saved = keepScroll ? saveScroll(current) : null;
    current.replaceWith(document.adoptNode(fresh));
    if (saved) restoreScroll(fresh, saved);
    if (doc.title) document.title = doc.title;
    var flashes = doc.querySelectorAll('.jr-flash');
    if (flashes.length) toast(flashes[flashes.length - 1].textContent.trim());
    initCal();
    return true;
  }

  function navigate(url, push, keepScroll) {
    fetchPage(url).then(function (html) {
      if (!applyDoc(parse(html), keepScroll)) { window.location.href = url; return; }
      if (push) history.pushState({ jr: true }, '', url);
    }).catch(function () { window.location.href = url; });
  }

  function currentUrl() { return window.location.pathname + window.location.search; }

  function refresh() {
    if (dragging) { refreshQueued = true; return; }
    cache.clear();
    navigate(currentUrl(), false, true);
  }

  window.addEventListener('popstate', function () { cache.clear(); navigate(currentUrl(), false); });

  function plainClick(e) { return e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey; }

  // Prefetch on hover so the click feels instant.
  document.addEventListener('mouseover', function (e) {
    var a = e.target.closest && e.target.closest('a[data-nav]');
    if (a) fetchPage(a.getAttribute('href'));
  });

  // ─── Address: Google Places (New) suggestions + a map preview ──
  // Our own dropdown (styled like the rest of the modal) fed by AutocompleteSuggestion.
  // Picking one fills the address and its lat/lng; typing by hand clears the lat/lng.
  var mapsReady = false;
  window.__jrPlacesReady = function () {
    Promise.all([google.maps.importLibrary('places'), google.maps.importLibrary('maps')])
      .then(function () { mapsReady = true; attachAddress(); })
      .catch(function () { /* the field still works as plain text */ });
  };

  var PIN = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 21s-7-6.2-7-11.5A7 7 0 0 1 19 9.5C19 14.8 12 21 12 21Z"/><circle cx="12" cy="9.5" r="2.5"/></svg>';
  // Quiet basemap: no business pins or transit, softer color. No hardcoded colors.
  var MAP_STYLES = [
    { featureType: 'poi', stylers: [{ visibility: 'off' }] },
    { featureType: 'transit', stylers: [{ visibility: 'off' }] },
    { elementType: 'geometry', stylers: [{ saturation: -40 }] },
    { featureType: 'road', elementType: 'labels.icon', stylers: [{ visibility: 'off' }] }
  ];

  function stripUSA(s) { return (s || '').replace(/, USA$/, ''); }

  function attachAddress() {
    if (!mapsReady) return;
    var root = modalBody.querySelector('[data-addr]');
    if (!root || root.dataset.bound) return;
    root.dataset.bound = '1';

    var P = google.maps.places;
    var input = root.querySelector('[data-addr-input]');
    var list = root.querySelector('[data-addr-list]');
    var latEl = root.querySelector('[data-addr-lat]');
    var lngEl = root.querySelector('[data-addr-lng]');
    var mapBox = root.querySelector('[data-addr-map]');
    var canvas = root.querySelector('[data-addr-canvas]');
    var openLink = root.querySelector('[data-addr-open]');
    var token = null, preds = [], active = -1, seq = 0, timer = null, map = null;

    function setOpen(open) {
      list.hidden = !open;
      input.setAttribute('aria-expanded', open ? 'true' : 'false');
      if (!open) { active = -1; input.removeAttribute('aria-activedescendant'); }
    }

    function highlighted(textObj) {
      // Bold the parts of the suggestion that match what was typed.
      var frag = document.createDocumentFragment();
      var text = textObj.text, at = 0;
      (textObj.matches || []).forEach(function (m) {
        if (m.startOffset > at) frag.appendChild(document.createTextNode(text.slice(at, m.startOffset)));
        var b = document.createElement('b');
        b.textContent = text.slice(m.startOffset, m.endOffset);
        frag.appendChild(b);
        at = m.endOffset;
      });
      if (at < text.length) frag.appendChild(document.createTextNode(text.slice(at)));
      return frag;
    }

    function render() {
      list.innerHTML = '';
      if (!preds.length) { setOpen(false); return; }
      preds.forEach(function (p, i) {
        var li = document.createElement('li');
        li.className = 'jr-addr-opt';
        li.id = 'jr-addr-opt-' + i;
        li.setAttribute('role', 'option');
        li.innerHTML = PIN;
        var txt = document.createElement('span');
        txt.className = 'jr-addr-txt';
        var main = document.createElement('span');
        main.className = 'jr-addr-main';
        main.appendChild(highlighted(p.mainText || p.text));
        txt.appendChild(main);
        if (p.secondaryText) {
          var sec = document.createElement('span');
          sec.className = 'jr-addr-sec';
          sec.textContent = stripUSA(p.secondaryText.text);
          txt.appendChild(sec);
        }
        li.appendChild(txt);
        li.addEventListener('mousedown', function (e) { e.preventDefault(); });  // keep focus
        li.addEventListener('click', function () { choose(p); });
        li.addEventListener('mousemove', function () { if (active !== i) setActive(i); });
        list.appendChild(li);
      });
      var attr = document.createElement('li');
      attr.className = 'jr-addr-attr';
      attr.setAttribute('aria-hidden', 'true');
      attr.textContent = 'Powered by Google';
      list.appendChild(attr);
      setOpen(true);
    }

    function setActive(i) {
      active = i;
      Array.prototype.forEach.call(list.querySelectorAll('.jr-addr-opt'), function (li, j) {
        li.classList.toggle('is-active', j === i);
      });
      if (i >= 0) input.setAttribute('aria-activedescendant', 'jr-addr-opt-' + i);
      else input.removeAttribute('aria-activedescendant');
    }

    function suggest() {
      var q = input.value.trim();
      if (q.length < 3) { preds = []; render(); return; }
      if (!token) token = new P.AutocompleteSessionToken();
      var mine = ++seq;
      P.AutocompleteSuggestion.fetchAutocompleteSuggestions({
        input: q, includedRegionCodes: ['us'], sessionToken: token
      }).then(function (res) {
        if (mine !== seq || document.activeElement !== input) return;
        preds = res.suggestions.map(function (s) { return s.placePrediction; })
          .filter(Boolean).slice(0, 5);
        render();
      }).catch(function () { preds = []; render(); });
    }

    function choose(pred) {
      seq++;  // drop any suggestion request still in flight
      preds = [];
      setOpen(false);
      input.value = stripUSA(pred.text.text);
      var place = pred.toPlace();
      place.fetchFields({ fields: ['formattedAddress', 'location'], sessionToken: token })
        .catch(function () { return place.fetchFields({ fields: ['formattedAddress', 'location'] }); })
        .then(function () {
          token = null;  // one session = suggestions + one pick
          if (place.formattedAddress) input.value = stripUSA(place.formattedAddress);
          if (place.location) {
            latEl.value = place.location.lat();
            lngEl.value = place.location.lng();
          }
          showMap();
          input.dispatchEvent(new Event('change', { bubbles: true }));  // autosave the pick
        }).catch(function () { token = null; });
    }

    function clearPin() {
      latEl.value = '';
      lngEl.value = '';
      mapBox.hidden = true;
    }

    function showMap() {
      var lat = parseFloat(latEl.value), lng = parseFloat(lngEl.value);
      if (isNaN(lat) || isNaN(lng)) { mapBox.hidden = true; return; }
      var pos = { lat: lat, lng: lng };
      mapBox.hidden = false;
      openLink.href = 'https://www.google.com/maps/search/?api=1&query=' +
        encodeURIComponent(input.value.trim() || (lat + ',' + lng));
      if (!map) {
        // The pin is drawn by CSS at the center; the map never pans, so it stays exact.
        map = new google.maps.Map(canvas, {
          center: pos, zoom: 16, styles: MAP_STYLES,
          disableDefaultUI: true, zoomControl: true, gestureHandling: 'none',
          clickableIcons: false, keyboardShortcuts: false
        });
      } else {
        map.setCenter(pos);
        map.setZoom(16);
      }
    }

    input.addEventListener('input', function () {
      clearPin();
      clearTimeout(timer);
      timer = setTimeout(suggest, 140);
    });
    input.addEventListener('focus', function () { if (preds.length) render(); });
    input.addEventListener('blur', function () { setOpen(false); });
    input.addEventListener('keydown', function (e) {
      if (list.hidden) return;
      var n = preds.length;
      if (e.key === 'ArrowDown') { e.preventDefault(); setActive((active + 1) % n); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); setActive(active <= 0 ? n - 1 : active - 1); }
      else if (e.key === 'Enter') { e.preventDefault(); choose(preds[active >= 0 ? active : 0]); }
      else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); setOpen(false); }
    });

    showMap();  // an existing job with a located address
  }

  // ─── autosave ─────────────────────────────────────────
  // An existing job saves as you type: ~0.7 s after the last keystroke, or right away when a
  // field is left, the date changes or an address is picked. Saves run one at a time, in order.
  // Named `edits`, not `save`: the drag code below has a save() function, and a variable with
  // the same name overwrote it (every drop threw, leaving Sortable stuck mid-drag).
  var edits = { timer: null, dirty: false, changed: false, chain: null };

  function resetSave() {
    clearTimeout(edits.timer);
    edits = { timer: null, dirty: false, changed: false, chain: null };
  }

  function saveState(text) {
    var el = modalBody.querySelector('[data-save-state]');
    if (el) el.textContent = text;
  }

  // Resolves true once everything typed so far is saved, false if a save failed.
  function saveNow() {
    clearTimeout(edits.timer);
    var form = modalBody.querySelector('form[data-autosave]');
    if (!form || !edits.dirty) return edits.chain || Promise.resolve(true);
    edits.dirty = false;
    var body = new FormData(form);
    var state = edits;
    var run = (state.chain || Promise.resolve(true)).then(function () {
      saveState('Saving…');
      return fetch(form.action, {
        method: 'POST', body: body, credentials: 'same-origin',
        headers: { 'X-Autosave': '1', 'Accept': 'application/json' },
      }).then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (data) {
          if (!r.ok || !data.ok) throw new Error(data.error || '');
        });
      }).then(function () {
        state.changed = true;
        cache.clear();
        if (state === edits) saveState('Saved');
        return true;
      }).catch(function (err) {
        if (state === edits) { state.dirty = true; saveState(''); }
        toast(err.message || 'Couldn’t save. Check your connection.');
        return false;
      });
    });
    state.chain = run;
    return run;
  }

  function queueSave(delay) {
    edits.dirty = true;
    clearTimeout(edits.timer);
    edits.timer = setTimeout(saveNow, delay);
  }

  modal.addEventListener('input', function (e) {
    if (e.target.closest('form[data-autosave]')) queueSave(700);
  });
  modal.addEventListener('change', function (e) {
    if (e.target.closest('form[data-autosave]')) queueSave(0);
  });

  // ─── modal ────────────────────────────────────────────
  function hideModal() {
    modal.hidden = true;
    document.body.classList.remove('jr-modal-open');
    modalBody.innerHTML = '';
  }

  // Closing finishes any pending save first. If it fails, the modal stays open so nothing is
  // lost. If anything was saved, the calendar re-renders (keeping its scroll).
  function closeModal() {
    if (modal.hidden) return;
    saveNow().then(function (ok) {
      if (!ok || modal.hidden) return;
      var changed = edits.changed;
      resetSave();
      hideModal();
      if (changed) refresh();
    });
  }

  function openForm(params) {
    resetSave();
    var qs = new URLSearchParams(params);
    qs.set('return_to', returnTo());
    modalBody.innerHTML = '';
    modalBody.classList.add('is-loading');
    modal.hidden = false;
    document.body.classList.add('jr-modal-open');
    fetch(formUrl + '?' + qs.toString(), { credentials: 'same-origin' })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); })
      .then(function (html) {
        modalBody.innerHTML = html;
        modalBody.classList.remove('is-loading');
        attachAddress();
        if (!params.id && window.matchMedia('(hover: hover)').matches) {
          var first = modalBody.querySelector('input[name="customer_name"]');
          if (first) first.focus();
        }
      })
      .catch(function () {
        hideModal();
        toast('Couldn’t open that job. Try again.');
      });
  }

  modal.addEventListener('click', function (e) {
    if (e.target.closest('[data-close]')) closeModal();
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && !modal.hidden) closeModal();
  });

  // Modal forms (add, done, delete) post in the background, then swap the calendar.
  // Enter in an autosaving form just saves.
  document.addEventListener('submit', function (e) {
    var form = e.target;
    if (form.dataset.confirm && !window.confirm(form.dataset.confirm)) {
      e.preventDefault();
      return;
    }
    if (!form.closest('#jr-modal')) return;
    e.preventDefault();
    if (form.hasAttribute('data-autosave')) { saveNow(); return; }
    // Mark done saves anything pending first; delete throws pending edits away.
    if (form.hasAttribute('data-delete')) { clearTimeout(edits.timer); edits.dirty = false; }
    var buttons = modal.querySelectorAll('button[type="submit"]');
    buttons.forEach(function (b) { b.disabled = true; });
    saveNow().then(function (ok) {
      if (!ok) throw new Error('save');
      return fetch(form.action, { method: 'POST', body: new FormData(form), credentials: 'same-origin' });
    })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); })
      .then(function (html) {
        cache.clear();
        var doc = parse(html);
        var err = doc.querySelector('.jr-flash--error');
        if (err) {   // keep the modal open so nothing typed is lost
          toast(err.textContent.trim());
          buttons.forEach(function (b) { b.disabled = false; });
          return;
        }
        resetSave();
        hideModal();
        if (!applyDoc(doc, true)) window.location.reload();
      })
      .catch(function (err) {
        if (err.message !== 'save') toast('Couldn’t save. Try again.');
        buttons.forEach(function (b) { b.disabled = false; });
      });
  });

  // ─── clicks ───────────────────────────────────────────
  document.addEventListener('click', function (e) {
    if (Date.now() - lastDragEnd < 300) return;

    var nav = e.target.closest('a[data-nav]');
    if (nav && plainClick(e)) {
      e.preventDefault();
      navigate(nav.getAttribute('href'), true);
      return;
    }
    if (!modal.hidden || !e.target.closest('[data-cal]')) return;

    if (e.target.closest('[data-new-job]')) {
      openForm({});
      return;
    }
    var card = e.target.closest('.jr-card');
    if (card) {
      openForm({ id: card.dataset.jobId });
      return;
    }
    var mcell = e.target.closest('.jr-mcell');
    if (mcell) {   // month: anywhere in a week row opens that week
      navigate(mcell.parentElement.dataset.weekHref, true);
      return;
    }
    var day = e.target.closest('.jr-day');
    if (day && !e.target.closest('.jr-day-head')) {
      openForm({ date: day.dataset.date });
    }
  });

  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Enter' || !modal.hidden) return;
    var card = e.target.closest && e.target.closest('.jr-card');
    if (card) openForm({ id: card.dataset.jobId });
  });

  // ─── drag and drop ────────────────────────────────────
  // Where the pointer really is. Sortable samples the drop target on a timer, so a fast
  // flick across several days can be released before it notices the final column.
  var pointer = { x: 0, y: 0 };
  var highlighted = null;
  var dragEl = null;

  function isDone(card) { return card && card.classList.contains('jr-card--done'); }

  // Over a day → that day. Anywhere off the calendar (the panel, the toolbar, outside the
  // window) → the Unscheduled panel, except for a done job, which must keep its date (null:
  // releasing there cancels the drag).
  function dropZoneAt(x, y) {
    var el = document.elementFromPoint(x, y);
    var day = el && el.closest('.jr-drop');
    if (day) return day;
    return isDone(dragEl) ? null : cal().querySelector('.jr-side');
  }

  function setHighlight(zone) {
    if (zone === highlighted) return;
    if (highlighted) highlighted.classList.remove('is-drop-target');
    highlighted = zone;
    if (zone) zone.classList.add('is-drop-target');
  }

  function track(e) {
    var t = e.touches ? e.touches[0] : e;
    if (!t) return;
    pointer.x = t.clientX;
    pointer.y = t.clientY;
    if (!dragging) return;
    var zone = dropZoneAt(pointer.x, pointer.y);
    setHighlight(zone);
    if (!dragEl) return;
    // Off the calendar: no slot opens anywhere. The card leaves the calendar, the panel's
    // "Drag a job here" box lights up, and the job lands in the Unscheduled list on release.
    var overSide = !!(zone && zone.classList.contains('jr-side'));
    dragEl.classList.toggle('is-parked', overSide);
    if (overSide) return;
    // Snap: move the slot into the day under the pointer right away, rather than waiting
    // for Sortable's next ~50ms sample. Sortable takes over ordering within that day.
    var list = listForZone(zone);
    if (list && dragEl.parentNode !== list) insertAtPointer(list, dragEl);
  }
  document.addEventListener('pointermove', track, { passive: true });
  document.addEventListener('mousemove', track, { passive: true });
  document.addEventListener('touchmove', track, { passive: true });

  function cardsIn(list) {
    return Array.prototype.slice.call(list.querySelectorAll(':scope > .jr-card'));
  }

  function listForZone(zone) {
    if (!zone) return null;
    return zone.classList.contains('jr-side')
      ? zone.querySelector('.jr-list--unscheduled')
      : zone.querySelector('.jr-list');
  }

  function insertAtPointer(list, card) {
    if (list.classList.contains('jr-list--unscheduled')) { list.appendChild(card); return; }
    var before = null;
    cardsIn(list).some(function (c) {
      if (c === card) return false;
      var r = c.getBoundingClientRect();
      if (pointer.y < r.top + r.height / 2) { before = c; return true; }
      return false;
    });
    list.insertBefore(card, before);
  }

  function save(card, to) {
    var date = to.dataset.date || null;
    var countEl = cal().querySelector('[data-unscheduled-count]');
    if (countEl) countEl.textContent = cardsIn(cal().querySelector('.jr-list--unscheduled')).length || '';
    card.classList.add('is-saving');
    fetch(moveUrl, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
      body: JSON.stringify({
        job_id: Number(card.dataset.jobId),
        date: date,
        ordered_ids: date ? cardsIn(to).map(function (c) { return Number(c.dataset.jobId); }) : []
      })
    })
      .then(function (r) {
        if (!r.ok) throw new Error(r.status);
        refresh();   // re-render from the server so every view agrees
      })
      .catch(function () {
        toast('The calendar changed. Refreshing…');
        refresh();
      });
  }

  function initCal() {
    var c = cal();
    if (!c) return;
    document.body.dataset.view = c.dataset.view;
    if (typeof Sortable === 'undefined') return;
    var unscheduled = c.querySelector('.jr-list--unscheduled');

    c.querySelectorAll('.jr-list').forEach(function (list) {
      Sortable.create(list, {
        // The panel list never opens a slot; drops there are placed by onEnd.
        group: list === unscheduled ? { name: 'jobs', put: false } : 'jobs',
        sort: list !== unscheduled,       // Unscheduled is ordered by age, not by hand
        draggable: '.jr-card',
        animation: 160,
        easing: 'cubic-bezier(0.2, 0.7, 0.2, 1)',
        forceFallback: true,              // same lifted-card look on every browser
        fallbackOnBody: true,
        fallbackClass: 'is-drag',
        fallbackTolerance: 4,             // a click with a tiny wobble is still a click
        ghostClass: 'is-ghost',
        delay: 200,
        delayOnTouchOnly: true,           // phones: press-and-hold to drag, so scrolling still works
        touchStartThreshold: 5,
        emptyInsertThreshold: 12,
        scroll: true,
        bubbleScroll: true,
        scrollSensitivity: 80,
        onStart: function (evt) {
          dragEl = evt.item;
          dragging = true;
          document.body.classList.add('jr-dragging');
        },
        onEnd: function (evt) {
          var zone = dropZoneAt(pointer.x, pointer.y);
          dragging = false;
          dragEl = null;
          document.body.classList.remove('jr-dragging');
          lastDragEnd = Date.now();
          setHighlight(null);
          var card = evt.item;
          var to = evt.to;
          card.classList.remove('is-parked');

          // Only a done job released off the calendar has no zone: cancel, put it back.
          if (!zone) {
            refreshQueued = false;
            refresh();
            return;
          }

          // Trust the pointer over Sortable's last sample.
          var actual = listForZone(zone);
          var corrected = false;
          if (actual && actual !== to) {
            insertAtPointer(actual, card);
            to = actual;
            corrected = true;
          }

          if (!corrected && evt.from === to && evt.oldIndex === evt.newIndex) {
            if (refreshQueued) { refreshQueued = false; refresh(); }
            return;
          }
          if (evt.from === unscheduled && to === unscheduled) return;
          refreshQueued = false;
          save(card, to);
        }
      });
    });
  }

  initCal();
})();

// ─── dev-only touch debug readout ─────────────────────────
// Open any calendar URL with ?touchdebug=1 (on a dev server; it needs the dev switch on the
// page, so it can never run in production). ?touchdebug=0 turns it off.
(function () {
  if (!document.querySelector('.jr-dev')) return;
  var q = new URLSearchParams(location.search).get('touchdebug');
  try {
    if (q === '1') sessionStorage.setItem('jrTouchDebug', '1');
    if (q === '0') sessionStorage.removeItem('jrTouchDebug');
    if (sessionStorage.getItem('jrTouchDebug') !== '1') return;
  } catch (e) { if (q !== '1') return; }

  var hud = document.createElement('pre');
  hud.style.cssText = 'position:fixed;top:4px;right:4px;z-index:99999;margin:0;padding:6px 8px;' +
    'max-width:70vw;font:10px/1.35 ui-monospace,monospace;white-space:pre-wrap;pointer-events:none;' +
    'background:rgba(0,0,0,.78);color:#fff;border-radius:6px';
  document.body.appendChild(hud);

  var s = { moves: 0, blocked: 0, lastBlocked: false, startOn: '-', drops: 0 };
  function name(el) {
    if (!el || !el.tagName) return String(el);
    return el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') +
      (el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\s+/).join('.') : '');
  }
  window.addEventListener('touchstart', function (e) {
    var t = e.touches[0];
    s.startOn = name(document.elementFromPoint(t.clientX, t.clientY));
    s.moves = 0; s.blocked = 0;
  }, { passive: true });
  // Bubbles to window after Sortable's document listener has had its say.
  window.addEventListener('touchmove', function (e) {
    s.moves++;
    if (e.defaultPrevented) s.blocked++;
    s.lastBlocked = e.defaultPrevented;
  }, { passive: true });
  window.addEventListener('touchend', function () {
    if (document.body.classList.contains('jr-dragging')) s.drops++;
  }, { passive: true });

  function draw() {
    var b = document.body, cs = getComputedStyle(b), hs = getComputedStyle(document.documentElement);
    hud.textContent = [
      'touch: ' + s.moves + ' moves, ' + s.blocked + ' blocked (last ' + s.lastBlocked + ')',
      'finger landed on: ' + s.startOn,
      'Sortable.active: ' + !!(window.Sortable && Sortable.active) + '  ghost: ' + !!(window.Sortable && Sortable.ghost),
      'body: ' + (b.className || '-') + '  user-select:' + (b.style.userSelect || '-'),
      'overflow body/html: ' + cs.overflowY + '/' + hs.overflowY,
      'modal hidden: ' + (document.getElementById('jr-modal') || {}).hidden,
      'scrollY: ' + Math.round(scrollY) + ' / ' + (document.documentElement.scrollHeight - innerHeight),
      'leftover drag cards: ' + document.querySelectorAll('body > .jr-card').length,
    ].join('\n');
  }
  setInterval(draw, 300);
  draw();
})();
