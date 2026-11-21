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
})();
