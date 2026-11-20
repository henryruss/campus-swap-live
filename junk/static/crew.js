/* My jobs: a small map under each job's Navigate button (Google Maps JS).
   A job picked from address suggestions has its lat/lng already; one typed by hand gets looked
   up once with Places text search. A map is only drawn when it's on screen (a Coming up row
   gets its map when it's opened), and never pans: the pin is CSS at the center. */
(function () {
  'use strict';
  var STYLES = [
    { featureType: 'poi', stylers: [{ visibility: 'off' }] },
    { featureType: 'transit', stylers: [{ visibility: 'off' }] },
    { elementType: 'geometry', stylers: [{ saturation: -40 }] },
    { featureType: 'road', elementType: 'labels.icon', stylers: [{ visibility: 'off' }] }
  ];
  var ready = false;

  function where(el) {
    var lat = parseFloat(el.dataset.lat), lng = parseFloat(el.dataset.lng);
    if (!isNaN(lat) && !isNaN(lng)) return Promise.resolve({ lat: lat, lng: lng });
    var q = (el.dataset.address || '').trim();
    if (!q || !google.maps.places || !google.maps.places.Place) return Promise.resolve(null);
    return google.maps.places.Place.searchByText({ textQuery: q, fields: ['location'], maxResultCount: 1 })
      .then(function (r) {
        var p = r && r.places && r.places[0];
        return p && p.location ? { lat: p.location.lat(), lng: p.location.lng() } : null;
      })
      .catch(function () { return null; });
  }

  function draw(el) {
    if (!ready || el.dataset.drawn) return;
    var row = el.closest('details');
    if (row && !row.open) return;
    el.dataset.drawn = '1';
    where(el).then(function (pos) {
      if (!pos) return;                       // no map rather than a wrong one
      el.hidden = false;
      new google.maps.Map(el.querySelector('.jr-cj-canvas'), {
        center: pos, zoom: 15, styles: STYLES, disableDefaultUI: true, gestureHandling: 'none',
        clickableIcons: false, keyboardShortcuts: false
      });
    });
  }

  // Watch each job's card (the map itself starts hidden, and hidden things never intersect).
  var seen = 'IntersectionObserver' in window ? new IntersectionObserver(function (entries) {
    entries.forEach(function (e) {
      var m = e.isIntersecting && e.target.querySelector('[data-mini-map]');
      if (m) draw(m);
    });
  }, { rootMargin: '200px' }) : null;

  function watchAll() {
    document.querySelectorAll('[data-mini-map]').forEach(function (el) {
      if (seen) seen.observe(el.closest('.jr-cj') || el.parentNode); else draw(el);
    });
  }
  document.addEventListener('toggle', function (e) {
    if (e.target.matches && e.target.matches('details') && e.target.open) {
      var m = e.target.querySelector('[data-mini-map]');
      if (m) draw(m);
    }
  }, true);

  window.__jrCrewMaps = function () {
    Promise.all([google.maps.importLibrary('maps'), google.maps.importLibrary('places')])
      .then(function () { ready = true; watchAll(); })
      .catch(function () { /* the Navigate button still works */ });
  };
})();
