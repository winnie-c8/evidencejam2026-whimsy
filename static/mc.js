// Q2 chart hover help: hovering a result word, a certainty meter or a mark on the age track
// shows its "How to read this" row (the hidden .mc-tt inside it) in one floating box. The box
// stays while the pointer is on it, and Esc or scrolling closes it. Without script nothing shows;
// the same rows are in the "How to read this" card.
(function () {
  var box = document.createElement('div');
  box.className = 'mc-tipbox';
  box.setAttribute('role', 'tooltip');
  box.hidden = true;
  document.body.appendChild(box);
  var cur = null;

  function show(t) {
    var src = t.querySelector(':scope > .mc-tt');
    if (!src) return;
    cur = t;
    box.innerHTML = src.innerHTML;
    box.style.setProperty('--c', getComputedStyle(t).getPropertyValue('--c'));
    box.hidden = false;
    var r = t.getBoundingClientRect(), w = box.offsetWidth, h = box.offsetHeight;
    var vw = document.documentElement.clientWidth;
    var x = Math.min(Math.max(8, r.left + r.width / 2 - w / 2), vw - w - 8);
    var y = r.top - h - 8;
    if (y < 8) y = r.bottom + 8;
    box.style.left = Math.max(8, x) + 'px';
    box.style.top = y + 'px';
  }

  function hide() { box.hidden = true; cur = null; }

  // mousemove (not mouseover): after a scroll closes the box, moving the pointer shows it again
  document.addEventListener('mousemove', function (e) {
    var t = e.target.closest('.mc-tip');
    if (t) { if (t !== cur) show(t); return; }
    if (!e.target.closest('.mc-tipbox')) hide();
  });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') hide(); });

  // Chart | Table switch: show it, start on the chart, swap views on click.
  var sw = document.querySelector('.mc-switch');
  if (sw) {
    var btns = [].slice.call(sw.querySelectorAll('button[data-view]'));
    var setView = function (id) {
      btns.forEach(function (b) {
        var on = b.getAttribute('data-view') === id;
        b.setAttribute('aria-pressed', on ? 'true' : 'false');
        document.getElementById(b.getAttribute('data-view')).hidden = !on;
      });
    };
    btns.forEach(function (b) {
      b.addEventListener('click', function () { setView(b.getAttribute('data-view')); });
    });
    sw.hidden = false;
    setView('mc-view-chart');
  }

  // A click anywhere on a chart row or table row opens that finding's popup (the outcome name
  // is the keyboard button; this covers the result word, certainty and age marks).
  document.addEventListener('click', function (e) {
    var row = e.target.closest('.mc-row, .mc-trow');
    if (row && !e.target.closest('button, a')) {
      var b = row.querySelector('.mc-name');
      if (b) { hide(); b.click(); }
      return;
    }
    // in the one-finding popup the card is always open: its header must not fold it away
    var s = e.target.closest('.cardpop details.fd > summary');
    if (s && !e.target.closest('a, button')) e.preventDefault();
  });
  addEventListener('scroll', hide, { passive: true });
})();
