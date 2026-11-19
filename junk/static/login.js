/* "Continue with Google" as a small popup over this page (Google Identity Services code flow).
   If Google's script hasn't loaded, the button's href does a full-page redirect instead. */
(function () {
  var btn = document.querySelector('[data-google-popup]');
  if (!btn) return;
  var errBox = document.querySelector('[data-google-error]');
  var csrf = document.querySelector('meta[name="csrf-token"]');
  var client = null;

  function showError(msg) {
    if (!errBox) return;
    errBox.textContent = msg;
    errBox.hidden = false;
  }

  function setBusy(busy) {
    btn.classList.toggle('is-busy', busy);
    btn.setAttribute('aria-busy', busy ? 'true' : 'false');
  }

  function onCode(resp) {
    if (!resp || !resp.code) { setBusy(false); return; }
    fetch(btn.dataset.codeUrl, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf ? csrf.content : '' },
      body: JSON.stringify({ code: resp.code, next: btn.dataset.next || '' })
    }).then(function (r) { return r.json().catch(function () { return { ok: false }; }); })
      .then(function (data) {
        if (data.ok) { window.location.assign(data.redirect); return; }
        setBusy(false);
        showError(data.error || 'Google sign-in didn’t go through. Try again, or use your password.');
      })
      .catch(function () {
        setBusy(false);
        showError('Couldn’t reach the server. Try again.');
      });
  }

  function getClient() {
    if (client) return client;
    if (!(window.google && google.accounts && google.accounts.oauth2)) return null;
    client = google.accounts.oauth2.initCodeClient({
      client_id: btn.dataset.clientId,
      scope: 'openid email profile',
      ux_mode: 'popup',
      callback: onCode,
      error_callback: function () { setBusy(false); }  // closed the popup, or it was blocked
    });
    return client;
  }

  btn.addEventListener('click', function (e) {
    var c = getClient();
    if (!c) return;  // fall through to the full-page redirect
    e.preventDefault();
    if (errBox) errBox.hidden = true;
    setBusy(true);
    c.requestCode();
  });
})();
