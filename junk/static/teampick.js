/* The team picker: a button that opens a floating search + scrolling list of people.
   Used by "+ Add…" in the job modal and by "View someone's jobs" on My jobs.

   Markup (see _job_crew.html):
     [data-pick]
       button[data-pick-open]
       [data-pick-pop] hidden
         input[data-pick-q]
         .jr-teampick-list > .jr-teampick-opt …   (an <a href> navigates; anything else is
                                                  handled by whoever listens for its click)
         [data-pick-none]

   The list is position: fixed, placed against the button (flipping above when there's no room
   below), so a modal or card never grows a scrollbar for it. Type to narrow by the start of any
   word of a name; scroll for the rest; tap, or arrows + Enter, to pick. */
(function () {
  'use strict';
  var pick = null;   // { pop, btn, q, active }

  function opts() { return pick ? [].slice.call(pick.pop.querySelectorAll('.jr-teampick-opt:not([hidden])')) : []; }

  function place() {
    if (!pick) return;
    var vv = window.visualViewport;
    var vh = vv ? vv.height : window.innerHeight, vw = window.innerWidth, top0 = vv ? vv.offsetTop : 0;
    var r = pick.btn.getBoundingClientRect();
    var w = Math.min(300, vw - 24);
    var pop = pick.pop, list = pop.querySelector('.jr-teampick-list');
    pop.style.width = w + 'px';
    pop.style.left = Math.max(12, Math.min(r.left, vw - w - 12)) + 'px';
    var below = top0 + vh - r.bottom - 12, above = r.top - top0 - 12;
    var up = below < 220 && above > below;
    var room = Math.min(360, up ? above : below) - 6;
    list.style.maxHeight = Math.max(88, Math.min(260, room - 50)) + 'px';   // ~6 rows; 50: the search box
    pop.style.top = up ? '' : (r.bottom + 6) + 'px';
    pop.style.bottom = up ? (window.innerHeight - r.top + 6) + 'px' : '';
  }

  function setActive(i) {
    var list = opts();
    list.forEach(function (o, j) { o.classList.toggle('is-active', j === i); });
    pick.active = list.length ? i : -1;
    if (list[i]) list[i].scrollIntoView({ block: 'nearest' });
  }

  function filter() {
    var words = pick.q.value.toLowerCase().trim().split(/\s+/).filter(Boolean);
    var any = false;
    pick.pop.querySelectorAll('.jr-teampick-opt').forEach(function (o) {
      var hay = ' ' + o.dataset.name.replace(/[^\w@.]+/g, ' ');
      var ok = words.every(function (w) { return hay.indexOf(' ' + w) !== -1; });   // word starts
      o.hidden = !ok; any = any || ok;
    });
    pick.pop.querySelector('[data-pick-none]').hidden = any;
    setActive(words.length && any ? 0 : -1);
  }

  function open(btn) {
    close();
    var pop = btn.closest('[data-pick]').querySelector('[data-pick-pop]');
    pick = { pop: pop, btn: btn, q: pop.querySelector('[data-pick-q]'), active: -1 };
    pop.hidden = false;
    btn.setAttribute('aria-expanded', 'true');
    place();
    // Desktop: type right away. Phones: no keyboard until they tap the search, so the whole
    // list is there to scroll.
    if (window.matchMedia('(hover: hover) and (pointer: fine)').matches) pick.q.focus();
  }

  function close() {
    if (!pick) return;
    pick.pop.hidden = true;
    pick.btn.setAttribute('aria-expanded', 'false');
    pick.q.value = '';
    pick.pop.querySelectorAll('.jr-teampick-opt').forEach(function (o) { o.hidden = false; o.classList.remove('is-active'); });
    pick.pop.querySelector('[data-pick-none]').hidden = true;
    pick = null;
  }

  document.addEventListener('click', function (e) {
    var btn = e.target.closest('[data-pick-open]');
    if (btn) { if (pick && pick.btn === btn) close(); else open(btn); return; }
    if (!pick) return;
    var opt = e.target.closest('.jr-teampick-opt');
    if (opt) { setTimeout(close, 0); return; }        // let the option's own handler run first
    if (!e.target.closest('[data-pick-pop]')) close();
  }, true);
  document.addEventListener('input', function (e) { if (pick && e.target === pick.q) filter(); });
  document.addEventListener('keydown', function (e) {
    if (!pick || e.target !== pick.q) return;
    var n = opts().length;
    if (e.key === 'ArrowDown') { e.preventDefault(); if (n) setActive((pick.active + 1) % n); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); if (n) setActive((pick.active - 1 + n) % n); }
    else if (e.key === 'Enter') {
      e.preventDefault();
      var o = opts()[pick.active] || (n === 1 && opts()[0]);
      if (o) (o.querySelector('a[href]') || o).click();   // a link row follows its link
    }
    else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); var b = pick.btn; close(); b.focus(); }
  }, true);
  // The keyboard coming up (phones), a resize or a scroll moves the button: follow it.
  window.addEventListener('resize', place);
  if (window.visualViewport) window.visualViewport.addEventListener('resize', place);
  document.addEventListener('scroll', place, true);

  window.jrTeamPick = { close: close };
})();
