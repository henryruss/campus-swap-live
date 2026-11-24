/* My jobs: size each mini map's picture to its box. The box is at least square and runs down
   the card when the details are long, so its height is only known once the page is laid out.
   Asking Google for exactly that size means nothing is cropped (its logo has to stay whole).
   Sizes snap to 8px so a refresh asks for the same picture and the browser's cache has it.
   A Coming up row's map is sized when the row opens; if Google can't draw one, it goes away. */
(function () {
  'use strict';

  var MAX = 320;                                        // Static Maps: 640px at scale 2

  function size(img) {
    var box = img.parentNode, w = box.clientWidth, h = box.clientHeight;
    if (!w || !h) return;                               // in a closed row: wait for it to open
    var snap = function (v) { return Math.min(MAX, Math.max(8, Math.round(v / 8) * 8)); };
    var src = img.dataset.map + '&size=' + snap(w) + 'x' + snap(h);
    if (img.getAttribute('src') !== src) img.src = src;
  }
  function sizeAll(root) { (root || document).querySelectorAll('img[data-map]').forEach(size); }

  document.addEventListener('error', function (e) {
    var img = e.target;
    if (!img.matches || !img.matches('img[data-map]')) return;
    var box = img.parentNode;
    box.hidden = true;
    box.parentNode.classList.remove('has-map');
  }, true);
  document.addEventListener('toggle', function (e) {
    if (e.target.matches && e.target.matches('details') && e.target.open) sizeAll(e.target);
  }, true);
  // A phone turned sideways changes the column widths.
  var lastW = window.innerWidth, t;
  window.addEventListener('resize', function () {
    if (window.innerWidth === lastW) return;
    lastW = window.innerWidth; clearTimeout(t); t = setTimeout(function () { sizeAll(); }, 200);
  });
  sizeAll();

  // Copy address. The clipboard API needs https (or localhost); the phone dev host is plain
  // http, so fall back to the old select-and-copy. Inside a Coming up row's summary, the tap
  // mustn't also open or close the row.
  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text);
    return new Promise(function (ok, fail) {
      var ta = document.createElement('textarea');
      ta.value = text; ta.setAttribute('readonly', '');
      ta.style.position = 'fixed'; ta.style.opacity = '0';
      document.body.appendChild(ta); ta.select(); ta.setSelectionRange(0, text.length);
      var done = false;
      try { done = document.execCommand('copy'); } catch (e) {}
      document.body.removeChild(ta);
      if (done) { ok(); } else { fail(); }
    });
  }
  document.addEventListener('click', function (e) {
    var btn = e.target.closest && e.target.closest('[data-copy]');
    if (!btn) return;
    e.preventDefault(); e.stopPropagation();
    copyText(btn.dataset.copy).then(function () {
      btn.classList.add('is-copied');
      btn.setAttribute('aria-label', 'Copied');
      clearTimeout(btn._t);
      btn._t = setTimeout(function () {
        btn.classList.remove('is-copied');
        btn.setAttribute('aria-label', 'Copy address');
      }, 1500);
    }).catch(function () {});
  });

  // ─── The checklist (Slice 3a) ───
  // Every change posts, and the server answers with the job's checklist re-rendered; it's
  // swapped in place. Photos show at once as previews, shrink on the phone (bad signal at the
  // curb), go up one at a time, and stay put with "Retry" if one doesn't make it.
  var csrf = (document.querySelector('meta[name="csrf-token"]') || {}).content || '';
  var MAX_SIDE = 1600;

  // The checklist in a manager's job window (calendar) stays editable on a finished job; on My
  // jobs a finished job is read-only for everyone. The server re-renders it to match.
  function where(sec) { return sec && sec.closest && sec.closest('[data-ck-wrap]') ? { 'X-JR-Job-Window': '1' } : {}; }
  function send(url, body, sec) {
    var opts = { method: 'POST', headers: Object.assign({ 'X-CSRFToken': csrf, 'Accept': 'application/json' }, where(sec)), credentials: 'same-origin' };
    if (body instanceof FormData) { opts.body = body; }
    else { opts.body = JSON.stringify(body); opts.headers['Content-Type'] = 'application/json'; }
    return fetch(url, opts).then(function (r) {
      return r.json().catch(function () { return { ok: false }; }).then(function (d) { d.http = r.status; return d; });
    });
  }

  // A short note at the bottom (the calendar has one; elsewhere, nothing).
  function toast(msg) {
    var t = document.getElementById('jr-toast');
    if (!t) return;
    t.textContent = msg;
    t.classList.add('is-on');
    clearTimeout(t._jr);
    t._jr = setTimeout(function () { t.classList.remove('is-on'); }, 2400);
  }

  function showError(sec, msg) {
    var el = sec && sec.querySelector('[data-ck-err]');
    if (!el) return;
    el.textContent = msg || '';
    el.hidden = !msg;
  }

  // A new photo goes at the end of its item's photos.
  function place(host, tile) { host.appendChild(tile); }

  // Swap in the new checklist, keeping any photos still on their way up, and update the job's
  // status line. When the last item gets its answer, the job folds up: done, waiting on review.
  function swap(sec, reply) {
    var html = reply && reply.html, error = reply && !reply.ok ? reply.error : null;
    if (!html) { showError(sec, error || "That didn't save. Check your signal and try again."); return sec; }
    var tmp = document.createElement('div');
    tmp.innerHTML = html.trim();
    var fresh = tmp.firstElementChild;
    sec.querySelectorAll('.jr-ck-thumb.is-pending, .jr-ck-thumb.is-failed').forEach(function (tile) {
      var host = fresh.querySelector('[data-photos="' + tile.dataset.kind + '"]');
      if (host) place(host, tile);
    });
    var card = sec.closest('[data-job-card]');
    var wasDone = sec.querySelector('.jr-ck-count.is-done');
    sec.replaceWith(fresh);
    showError(fresh, error);
    var wrap = fresh.closest('[data-ck-wrap]');           // the manager's job modal: keep its look in step
    if (wrap && reply.review) {
      var old = wrap.querySelector('[data-ck-review]');
      tmp.innerHTML = reply.review.trim();
      if (old) old.replaceWith(tmp.firstElementChild);
    }
    if (card && reply.status) {
      var st = card.querySelector('[data-job-status]');
      if (st) { tmp.innerHTML = reply.status.trim(); st.replaceWith(tmp.firstElementChild); }
    }
    if (card && reply.complete && !wasDone && card.open && !fresh.querySelector('.jr-ck-thumb.is-pending')) {
      setTimeout(function () { fold(card); }, 700);   // a beat to see the last check land
    }
    return fresh;
  }

  // Close a job's row without the page jumping: keep its head where it was on screen.
  function fold(card) {
    var head = card.querySelector('summary');
    var before = head.getBoundingClientRect().top;
    card.open = false;
    keepPlace(head, before);
    if (head.getBoundingClientRect().top < 0) head.scrollIntoView({ block: 'start', behavior: 'smooth' });
  }

  function shrink(file) {
    if (!window.createImageBitmap) return Promise.resolve(file);
    return createImageBitmap(file, { imageOrientation: 'from-image' }).then(function (bmp) {
      var k = Math.min(1, MAX_SIDE / Math.max(bmp.width, bmp.height));
      var c = document.createElement('canvas');
      c.width = Math.round(bmp.width * k); c.height = Math.round(bmp.height * k);
      c.getContext('2d').drawImage(bmp, 0, 0, c.width, c.height);
      return new Promise(function (ok) { c.toBlob(function (b) { ok(b || file); }, 'image/jpeg', 0.85); });
    }).catch(function () { return file; });
  }

  var queue = Promise.resolve();
  function upload(tile) {
    tile.classList.remove('is-failed');
    tile.classList.add('is-pending');
    var old = tile.querySelector('.jr-ck-retry');
    if (old) old.remove();
    queue = queue.then(function () {
      var sec = tile.closest('[data-checklist]');
      if (!sec) return;
      return shrink(tile._file).then(function (blob) {
        var fd = new FormData();
        fd.append('kind', tile.dataset.kind);
        fd.append('photo', blob, 'photo.jpg');
        return send(sec.dataset.photoUrl, fd, sec);
      }).then(function (d) {
        sec = tile.closest('[data-checklist]');
        if (d.ok) { tile.remove(); URL.revokeObjectURL(tile._url); swap(sec, d); return; }
        failed(tile);
        if (d.html) swap(sec, d); else showError(sec, d.error || "That photo didn't go up.");
      }, function () {
        failed(tile);
        showError(tile.closest('[data-checklist]'), "That photo didn't go up. Check your signal and tap Retry.");
      });
    });
  }
  function failed(tile) {
    tile.classList.remove('is-pending');
    tile.classList.add('is-failed');
    var b = document.createElement('button');
    b.type = 'button'; b.className = 'jr-ck-retry'; b.textContent = 'Retry';
    b.addEventListener('click', function (e) { e.preventDefault(); upload(tile); });
    tile.appendChild(b);
  }

  // Add photos: a fresh file picker on every tap. (Reusing one input, iPhone needs two taps to
  // open it again after its menu is cancelled.) It's put on the page only while it's open.
  // iPhone: after its photo menu is dismissed by tapping the page, it takes ~0.8s to finish
  // closing, and quietly ignores any request to open a menu until then (seen in the tap log,
  // 2026-11-22). So a tap that comes while the last menu is still closing waits for it to
  // finish (iOS says so with a "cancel"), then opens. A request that soon after a real tap
  // still counts as that tap.
  var picker = null, closing = false;
  var DESKTOP = window.matchMedia && window.matchMedia('(hover: hover) and (pointer: fine)').matches;
  function pickPhotos(btn) {
    var sec = btn.closest('[data-checklist]');
    if (DESKTOP && sec.dataset.snapUrl) { ways.open(btn); return; }
    openPicker(btn);
  }
  function openPicker(btn) {
    var sec = btn.closest('[data-checklist]'), kind = btn.dataset.photoAdd;
    var input = document.createElement('input');
    input.type = 'file';
    input.accept = 'image/*';
    input.multiple = kind !== 'dump';                  // one receipt
    input.className = 'jr-ck-picker';
    input.addEventListener('change', function () {
      var files = [].slice.call(input.files || []);
      done(input);
      var host = sec.isConnected ? sec : document.querySelector('[data-photo-url="' + sec.dataset.photoUrl + '"]');
      if (host && files.length) addPhotos(host, kind, files);
    });
    input.addEventListener('cancel', function () { done(input); });
    document.body.appendChild(input);
    var waitFor = closing && picker;                   // the last menu hasn't finished closing
    picker = input;
    closing = true;
    if (!waitFor) { input.click(); return; }
    // The wait is iOS's (a few hundred ms), so the square shows it heard the tap right away.
    btn.classList.add('is-opening');
    var started = Date.now();
    (function wait() {
      if (!waitFor.isConnected || Date.now() - started > 900) {
        if (waitFor.isConnected) waitFor.remove();
        btn.classList.remove('is-opening');
        if (picker === input) input.click();
        return;
      }
      setTimeout(wait, 30);
    })();
  }
  // ─── On a computer: a QR code for your phone, or upload from this computer ───
  // The phone page adds photos straight to the job; while the code is showing, this checks
  // back every few seconds and swaps them into the card.
  var ways = (function () {
    var el = null, btn = null, timer = null, seen = 0;
    var ICON_PC = '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4" width="18" height="12" rx="1.5"/><path d="M8 20h8M12 16v4"/></svg>';
    function count(sec) { return sec ? sec.querySelectorAll('[data-photos="' + btn.dataset.photoAdd + '"] .jr-ck-thumb:not(.is-pending)').length : 0; }
    function section() {   // the card's checklist (it's swapped out after every change)
      return document.querySelector('[data-checklist][data-snap-url="' + btn._snap + '"]');
    }
    function build() {
      el = document.createElement('div');
      el.className = 'jr-ck-ways';
      el.setAttribute('role', 'dialog');
      el.setAttribute('aria-label', 'Add photos');
      el.hidden = true;
      document.body.appendChild(el);
      el.addEventListener('click', function (e) {
        var w = e.target.closest('[data-way]');
        if (!w) return;
        if (w.dataset.way === 'pc') { var b = btn; close(); openPicker(b); }
      });
      document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && !el.hidden) close(); });
      document.addEventListener('mousedown', function (e) {
        if (!el.hidden && !el.contains(e.target) && !(btn && btn.contains(e.target))) close();
      });
      window.addEventListener('resize', place);
      window.addEventListener('scroll', place, { passive: true });
    }
    function place() {
      if (!el || el.hidden || !btn || !btn.isConnected) return;
      var r = btn.getBoundingClientRect(), w = el.offsetWidth, h = el.offsetHeight;
      var left = Math.max(12, Math.min(r.left, window.innerWidth - w - 12));
      var top = r.bottom + 8 + h > window.innerHeight - 12 ? Math.max(12, r.top - 8 - h) : r.bottom + 8;
      el.style.left = left + 'px'; el.style.top = top + 'px';
    }
    function open(b) {
      if (!el) build();
      if (!el.hidden && btn === b) { close(); return; }
      close();
      btn = b;
      btn._snap = b.closest('[data-checklist]').dataset.snapUrl;
      el.innerHTML = '<div class="jr-ck-qr" data-qr><p>Making a code…</p></div>' +
                     '<button type="button" class="jr-ck-way" data-way="pc">' + ICON_PC + 'Upload from this computer</button>';
      el.hidden = false;
      place();
      el.querySelector('[data-way]').focus();
      phone();
    }
    function phone() {
      var sec = section();
      if (!sec) { close(); return; }
      var box = el.querySelector('[data-qr]');
      fetch(sec.dataset.snapUrl + '?kind=' + encodeURIComponent(btn.dataset.photoAdd), { credentials: 'same-origin' })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (el.hidden) return;
          if (!d.ok) { box.innerHTML = '<p>' + (d.error || "That didn't work.") + '</p>'; return; }
          box.innerHTML = d.svg + '<p>Scan with your phone’s camera to take photos. They show up here.</p>' +
                          '<p class="jr-ck-qr-got" data-got hidden></p>';
          place();
          seen = count(section());
          var startedAt = seen;
          clearInterval(timer);
          timer = setInterval(function () {
            var s0 = section();
            if (!s0 || document.hidden) return;
            fetch(s0.dataset.pollUrl, { credentials: 'same-origin', headers: where(s0) }).then(function (r) { return r.json(); }).then(function (reply) {
              var s1 = section();
              if (!s1 || !reply.html) return;
              var tmp = document.createElement('div');
              tmp.innerHTML = reply.html.trim();
              var n = tmp.querySelectorAll('[data-photos="' + btn.dataset.photoAdd + '"] .jr-ck-thumb').length;
              if (n === seen) return;
              seen = n;
              swap(s1, reply);
              var got = el.querySelector('[data-got]');
              if (got && n > startedAt) {
                got.hidden = false;
                got.textContent = (n - startedAt) + (n - startedAt === 1 ? ' photo' : ' photos') + ' added';
              }
            }).catch(function () {});
          }, 2500);
        })
        .catch(function () { box.innerHTML = '<p>The code didn’t load. Check your connection.</p>'; });
    }
    function close() {
      clearInterval(timer); timer = null;
      if (el) el.hidden = true;
    }
    return { open: open };
  })();

  function done(input) {                               // its menu has closed: picked or cancelled
    input.remove();
    if (picker === input) { picker = null; closing = false; }
  }

  function addPhotos(sec, kind, files) {
    var host = sec.querySelector('[data-photos="' + kind + '"]');
    if (!host) return;
    files.forEach(function (file) {
      var tile = document.createElement('span');
      tile.className = 'jr-ck-thumb is-pending';
      tile.dataset.kind = kind;
      tile._file = file;
      tile._url = URL.createObjectURL(file);
      var a = document.createElement('a');
      var img = document.createElement('img');
      img.src = tile._url; img.alt = 'Photo uploading';
      a.appendChild(img); tile.appendChild(a);
      place(host, tile);
      upload(tile);
    });
  }

  function answer(sec, body) {
    sec.classList.add('is-busy');
    send(sec.dataset.checkUrl, body, sec).then(function (d) {
      swap(sec, d);
    }, function () {
      sec.classList.remove('is-busy');
      showError(sec, "That didn't save. Check your signal and try again.");
    });
  }

  document.addEventListener('click', function (e) {
    var t = e.target.closest ? e.target : null;
    if (!t) return;
    // Something wrong? Send the note; the box comes back saying it's flagged.
    var flagBtn = t.closest('[data-flag-send]');
    if (flagBtn) {
      var box = flagBtn.closest('[data-flag]');
      flagBtn.disabled = true;
      send(box.dataset.flagUrl, { note: box.querySelector('[data-flag-note]').value }).then(function (d) {
        if (!d.ok || !d.html) {
          flagBtn.disabled = false;
          box.querySelector('[data-flag-state]').textContent = d.error || "That didn't send. Try again.";
          return;
        }
        var tmp = document.createElement('div');
        tmp.innerHTML = d.html.trim();
        var card = box.closest('[data-job-card]');
        box.replaceWith(tmp.firstElementChild);
        var st = card && card.querySelector('[data-job-status]');
        if (st && d.status) { tmp.innerHTML = d.status.trim(); st.replaceWith(tmp.firstElementChild); }
      }, function () {
        flagBtn.disabled = false;
        box.querySelector('[data-flag-state]').textContent = "That didn't send. Check your signal and try again.";
      });
      return;
    }
    // The manager's job modal: the checklist is to look at; Edit opens the working one.
    var edit = t.closest('[data-ck-edit], [data-ck-done]');
    if (edit) {
      var w = edit.closest('[data-ck-wrap]');
      w.classList.toggle('is-editing', edit.hasAttribute('data-ck-edit'));
      if (edit.hasAttribute('data-ck-edit')) w.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      return;
    }
    var add = t.closest('[data-photo-add]');
    if (add) { pickPhotos(add); return; }
    var check = t.closest('[data-check]');
    if (check) {
      answer(check.closest('[data-checklist]'), { item: check.dataset.check, answer: check.dataset.answer });
      return;
    }
    var shot = t.closest('a[data-gallery]');
    if (shot && !e.metaKey && !e.ctrlKey) {
      e.preventDefault();
      var all = [].slice.call(document.querySelectorAll('a[data-gallery="' + shot.dataset.gallery + '"]'));
      viewer.open(all, all.indexOf(shot));
      return;
    }
    var rm = t.closest('[data-photo-remove]');
    if (rm) {
      e.preventDefault();
      if (!window.confirm('Remove this photo?')) return;
      var sec = rm.closest('[data-checklist]');
      send(rm.dataset.photoRemove, {}, sec).then(function (d) { swap(sec, d); },
        function () { showError(sec, "That didn't save. Check your signal and try again."); });
    }
  });

  // ─── Closing a row near the bottom of the page ───
  // The page gets shorter, the browser pulls the scroll back, and everything jumps. A spacer at
  // the bottom takes up the slack so the row's head stays put; it melts away as you scroll up.
  var spacer = null, spacerBase = 0;
  function keepPlace(head, before) {
    var drift = head.getBoundingClientRect().top - before;
    if (drift <= 0.5) return;
    if (!spacer) {
      spacer = document.createElement('div');
      spacer.setAttribute('aria-hidden', 'true');
      document.body.appendChild(spacer);
    }
    spacer.style.height = (spacer.offsetHeight + drift) + 'px';
    window.scrollBy(0, drift);
    spacerBase = window.scrollY;
  }
  window.addEventListener('scroll', function () {
    if (!spacer || !spacer.offsetHeight) return;
    var shrink = spacerBase - window.scrollY;                  // scrolled up by this much
    if (shrink > 0) {
      spacer.style.height = Math.max(0, spacer.offsetHeight - shrink) + 'px';
      spacerBase = window.scrollY;
    }
  }, { passive: true });
  document.addEventListener('click', function (e) {
    var head = e.target.closest && e.target.closest('details[data-job-card] > summary');
    if (!head || !head.parentNode.open || e.target.closest('[data-copy]')) return;
    var before = head.getBoundingClientRect().top;
    requestAnimationFrame(function () { keepPlace(head, before); });
  });

  // ─── Photo viewer ───
  var viewer = (function () {
    var el = document.querySelector('[data-pv]');
    if (!el) return { open: function (links, i) { window.open(links[i].href, '_blank'); } };
    var img = el.querySelector('[data-pv-img]'), count = el.querySelector('[data-pv-count]');
    var moveBtn = el.querySelector('[data-pv-move]'), panel = el.querySelector('[data-pv-panel]');
    var jobsList = el.querySelector('[data-pv-jobs]');
    var links = [], at = 0, lastFocus = null;
    function show() {
      img.src = links[at].href;
      count.textContent = (at + 1) + ' of ' + links.length;
      moveBtn.hidden = !links[at].dataset.move;
      panel.hidden = true;
    }
    function step(d) {
      if (links.length < 2 || !panel.hidden) return;
      at = (at + d + links.length) % links.length;
      show();
    }
    // Move: the jobs within a week of this one, nearest first; pick one and the photo goes there.
    function pickJob() {
      var link = links[at];
      jobsList.innerHTML = '<li class="jr-pv-none">Loading…</li>';
      panel.hidden = false;
      fetch(link.dataset.targets, { credentials: 'same-origin' }).then(function (r) { return r.json(); }).then(function (d) {
        jobsList.innerHTML = '';
        if (!d.jobs || !d.jobs.length) { jobsList.innerHTML = '<li class="jr-pv-none">No other jobs within a week of this one.</li>'; return; }
        d.jobs.forEach(function (j) {
          var li = document.createElement('li'), b = document.createElement('button');
          b.type = 'button'; b.className = 'jr-pv-job'; b.dataset.jobId = j.id;
          var n = document.createElement('strong'); n.textContent = j.name;
          var m = document.createElement('span'); m.textContent = [j.day, j.street].filter(Boolean).join(' · ') + (j.done ? ' · done' : '');
          b.appendChild(n); b.appendChild(m); li.appendChild(b); jobsList.appendChild(li);
        });
      }).catch(function () { jobsList.innerHTML = '<li class="jr-pv-none">That didn’t load. Try again.</li>'; });
    }
    function moveTo(jobId, label) {
      var link = links[at], wrap = link.closest('[data-ck-wrap]');
      var sec = wrap ? wrap.querySelector('[data-checklist]') : link.closest('[data-checklist]');
      send(link.dataset.move, { job_id: jobId }, sec).then(function (d) {
        if (!d.ok) { jobsList.innerHTML = '<li class="jr-pv-none">' + (d.error || 'That didn’t work.') + '</li>'; return; }
        close();
        if (sec) swap(sec, d);
        toast('Photo moved to ' + label);
      }, function () { jobsList.innerHTML = '<li class="jr-pv-none">That didn’t save. Check your connection.</li>'; });
    }
    function open(list, i) {
      links = list; at = Math.max(0, i);
      el.classList.toggle('is-single', links.length < 2);
      lastFocus = document.activeElement;
      el.hidden = false;
      document.documentElement.style.overflow = 'hidden';
      show();
      el.querySelector('[data-pv-close]').focus();
    }
    function close() {
      el.hidden = true;
      img.removeAttribute('src');
      document.documentElement.style.overflow = '';
      if (lastFocus) lastFocus.focus();
    }
    el.addEventListener('click', function (e) {
      var nav = e.target.closest('[data-pv-step]');
      if (nav) { step(+nav.dataset.pvStep); return; }
      if (e.target.closest('[data-pv-move]')) { pickJob(); return; }
      if (e.target.closest('[data-pv-cancel]')) { panel.hidden = true; return; }
      var job = e.target.closest('[data-job-id]');
      if (job) { moveTo(job.dataset.jobId, job.querySelector('strong').textContent); return; }
      if (e.target.closest('[data-pv-panel]')) return;
      if (e.target.closest('[data-pv-close]') || e.target === el || e.target.matches('[data-pv-fig]')) close();
    });
    document.addEventListener('keydown', function (e) {   // first, so Escape doesn't also close the job modal
      if (el.hidden) return;
      e.stopImmediatePropagation();
      if (e.key === 'Escape') { if (!panel.hidden) panel.hidden = true; else close(); }
      else if (e.key === 'ArrowRight') step(1);
      else if (e.key === 'ArrowLeft') step(-1);
    }, true);
    var x0 = null, y0 = 0;
    el.addEventListener('touchstart', function (e) {
      if (e.touches.length === 1) { x0 = e.touches[0].clientX; y0 = e.touches[0].clientY; }
    }, { passive: true });
    el.addEventListener('touchend', function (e) {
      if (x0 === null) return;
      var dx = e.changedTouches[0].clientX - x0, dy = e.changedTouches[0].clientY - y0;
      x0 = null;
      if (Math.abs(dx) > 40 && Math.abs(dx) > Math.abs(dy) * 1.5) step(dx < 0 ? 1 : -1);
    });
    return { open: open };
  })();
})();
