// Home page: parts marked .rv (the Our Mission block, each question's heading and text, and its
// photos) fade and rise in as they scroll into view. Our Mission (data-after="papers") waits
// until the paper band above it has filled in (static/problem.js fires "papers-done").
// The page adds .rv-js to <html> only when the reader has not asked for reduced motion;
// without it (or without script) everything is simply shown. Focus shows a part at once.
(function () {
  var root = document.documentElement;
  if (!root.classList.contains('rv-js')) return;
  var els = [].slice.call(document.querySelectorAll('.rv'));
  var papers = !document.querySelector('#problem.anim');   // no paper animation: nothing to wait for
  addEventListener('papers-done', function () { papers = true; check(); });
  function show(el) { el.classList.add('on'); }
  function ready(el) { return el.dataset.after !== 'papers' || papers; }
  function inView(el) {
    var r = el.getBoundingClientRect();
    return r.top < innerHeight * 0.88 && r.bottom > 0;
  }
  function check() {
    els.forEach(function (el, i) {
      if (!el.classList.contains('on') && ready(el) && inView(el)) {
        // photos in one cluster come in one after another
        var sib = el.parentNode.classList.contains('hphotos') ? [].indexOf.call(el.parentNode.children, el) : 0;
        el.style.transitionDelay = (sib * 0.18) + 's';
        show(el);
      }
    });
  }
  document.addEventListener('focusin', function (e) {
    var el = e.target.closest && e.target.closest('.rv');
    if (el) show(el);
    els.forEach(function (x) { if (x.contains(e.target)) show(x); });
  });
  var queued = false;
  function onScroll() { if (!queued) { queued = true; requestAnimationFrame(function () { queued = false; check(); }); } }
  addEventListener('scroll', onScroll, { passive: true });
  addEventListener('resize', onScroll);
  check();
})();
