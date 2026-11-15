// Home page only: the layered tree in the top-left corner turns as you scroll the page.
// The drawing (static/tree.svg, inlined into index.html as a <template>) is split into one flat
// card per shape; the cards sit at different depths, so turning them shows the layers.
// Pause, half-turn, pause, half-turn over the whole page. Decorative: hidden from screen
// readers, and it stays still for people who ask for reduced motion.
(function () {
  var box = document.getElementById('treeStage');
  var tpl = document.getElementById('treeSvg');
  if (!box || !tpl) return;
  var stage = box.firstElementChild;
  var src = tpl.content.querySelector('svg');
  var SPREAD = 360, HOLD = 1.2, TURN = 3.5, W = 386, H = 526;

  var kids = Array.prototype.slice.call(src.querySelector('g[clip-path]').children);
  var keep = [];
  kids.forEach(function (e, i) {
    if (e.tagName === 'rect') return;                                  // white background
    if (e.tagName === 'path' && e.getAttribute('stroke')) return;      // thin branch lines
    keep.push(i);
  });

  // one card per shape; ids get a per-card suffix so the page has no duplicate ids
  var cards = keep.map(function (idx, k) {
    var text = src.outerHTML.replace(/(id="|url\(#)([^")]+)/g, function (_, a, id) { return a + id + '-t' + k; });
    var div = document.createElement('div');
    div.className = 'tree-layer';
    div.innerHTML = text;
    var g = div.querySelector('g[clip-path]');
    Array.prototype.slice.call(g.children).forEach(function (e, i) { if (i !== idx) g.removeChild(e); });
    stage.appendChild(div);
    return { div: div, z: -SPREAD / 2 + SPREAD * k / (keep.length - 1) };
  });

  var total = 2 * (HOLD + TURN);
  function angleAt(p) {
    var t = Math.min(Math.max(p, 0), 0.9999) * total;
    var half = Math.floor(t / (HOLD + TURN)), u = t - half * (HOLD + TURN);
    if (u < HOLD) return 180 * half;
    var x = (u - HOLD) / TURN;
    return 180 * half + 180 * (0.5 - 0.5 * Math.cos(Math.PI * x));
  }
  function draw(a) {
    for (var i = 0; i < cards.length; i++)
      cards[i].div.style.transform = 'perspective(1700px) rotateY(' + a + 'deg) translateZ(' + cards[i].z + 'px)';
  }
  function fit() {   // scale the drawing to the box it sits in
    // 0.8: room for the layers that swing out past the edges as the tree turns
    var s = 0.8 * Math.min(box.clientWidth / W, box.clientHeight / H) || 0;
    stage.style.transform = 'translate(-50%, -50%) scale(' + s + ')';
  }

  var still = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)');
  var target = 0, current = 0, running = false;
  function readScroll() {
    if (still && still.matches) { target = 0; return; }
    var range = document.documentElement.scrollHeight - innerHeight;
    target = angleAt(range > 0 ? scrollY / range : 0);
  }
  function tick() {   // ease toward the scroll position so it glides; stop when it gets there
    current += (target - current) * 0.12;
    if (Math.abs(target - current) < 0.01) current = target;
    draw(current);
    running = current !== target;
    if (running) requestAnimationFrame(tick);
  }
  function kick() { readScroll(); if (!running) { running = true; requestAnimationFrame(tick); } }

  addEventListener('scroll', kick, { passive: true });
  addEventListener('resize', function () { fit(); kick(); });
  fit(); readScroll(); current = target; draw(current);
})();

// Home page left menu: the item for the section being read is marked (.on) and its underline
// (--p) fills as you read through it; the CSS greys the others. Without this script nothing is greyed.
(function () {
  var nav = document.querySelector('.home-menu');
  if (!nav) return;
  var items = Array.prototype.slice.call(nav.querySelectorAll('li[data-sec]')).map(function (li) {
    return { li: li, sec: document.getElementById(li.getAttribute('data-sec')) };
  }).filter(function (it) { return it.sec; });
  var queued = false;

  function spy() {
    var line = innerHeight * 0.4, on = null, prog = 0;
    var atEnd = scrollY + innerHeight >= document.documentElement.scrollHeight - 2;
    items.forEach(function (it) {
      var r = it.sec.getBoundingClientRect();
      if (r.top <= line) { on = it; prog = (line - r.top) / Math.max(r.height, 1); }
    });
    if (atEnd && items.length) { on = items[items.length - 1]; prog = 1; }
    items.forEach(function (it) {
      it.li.classList.toggle('on', it === on);
      it.li.style.setProperty('--p', it === on ? Math.min(Math.max(prog, 0), 1).toFixed(3) : '0');
    });
    nav.classList.toggle('has-on', !!on);
  }

  function update() { queued = false; spy(); }
  function ask() { if (!queued) { queued = true; requestAnimationFrame(update); } }
  addEventListener('scroll', ask, { passive: true });
  addEventListener('resize', ask);
  update();
})();
