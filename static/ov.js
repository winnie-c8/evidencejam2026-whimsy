// Q1 "Overview & Constraints". When the section reaches the top of the screen it stays put, and
// as you keep scrolling the dotted wave is drawn from left to right with a soft edge (eased, so it
// glides). When the wave reaches the overview, that text fades and rises in with the bottom pin;
// when it reaches the constraints, they come in with the top pin. Then the page scrolls on.
// Only from 900px wide and without reduced motion (the page adds .anim then); otherwise everything
// is simply shown. Tabbing into the text shows everything at once.
(function () {
  var sec = document.getElementById('overview');
  if (!sec || !sec.classList.contains('anim')) return;
  var track = sec.parentNode, wave = sec.querySelector('.ov-wave');
  // each block with the pin that comes in with it
  var groups = [[sec.querySelector('.ov-left'), sec.querySelector('.pin-bottom')],
                [sec.querySelector('.ov-right'), sec.querySelector('.pin-top')]];
  var DRAW = 1.1;            // screen heights of scrolling to draw the whole wave
  var cur = 0, target = 0, running = false;
  function size() { track.style.height = (sec.offsetHeight + innerHeight * DRAW) + 'px'; }
  function goal() {
    var top = parseFloat(getComputedStyle(sec).top) || 0;
    var span = track.offsetHeight - sec.offsetHeight;
    // 0 until the section is pinned under the header, 1 at the end of the track
    target = span > 0 ? Math.min(1, Math.max(0, (top - track.getBoundingClientRect().top) / span)) : 1;
  }
  function draw() {
    cur += (target - cur) * 0.12;                       // ease toward the scroll position
    if (Math.abs(target - cur) < 0.001) cur = target;
    wave.style.setProperty('--p', cur.toFixed(4));
    var w = wave.getBoundingClientRect(), edge = w.left + cur * w.width;
    groups.forEach(function (g) {
      var r = g[0].getBoundingClientRect(), shown = edge >= r.left + r.width * 0.25;
      g.forEach(function (el) { if (el) el.classList.toggle('on', shown); });
    });
    if (cur !== target) requestAnimationFrame(draw); else running = false;
  }
  function onScroll() {
    if (sec.classList.contains('done')) return;
    goal();
    if (!running) { running = true; requestAnimationFrame(draw); }
  }
  sec.addEventListener('focusin', function () { sec.classList.add('done'); });   // keyboard: show all
  addEventListener('scroll', onScroll, { passive: true });
  addEventListener('resize', function () { size(); onScroll(); });
  size();
  onScroll();
})();
