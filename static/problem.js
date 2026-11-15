// Home page "Problem" opening, revealed as you scroll (normal scrolling, nothing pinned):
// 1. at first only the sentence shows;
// 2. the flowers drift in one by one over the first few hundred pixels of scrolling;
// 3. once every flower is in, "spread across: hundreds of papers" (it sits below the flowers);
// 4. then the paper band, slice by slice to the end of the screen, once it comes up the screen.
// Decorative only: the text is in the page from the start. Nothing moves for people who ask for
// reduced motion (the page adds .anim only otherwise), and without this script all is shown.
(function () {
  var sec = document.getElementById('problem');
  if (!sec || !sec.classList.contains('anim')) return;
  var box = sec.querySelector('.pb-flowers'), band = sec.querySelector('.pb-papers');
  var flowers = [].slice.call(box.querySelectorAll('img'));
  var strips = [].slice.call(band.querySelectorAll('img'));
  var words = [sec.querySelector('.pb-spread'), sec.querySelector('.pb-many')];
  var STEP = 22;        // px of scrolling per flower: 14 flowers in about 300px
  var GAP = 45;         // ms between paper slices: the whole band in about a second
  // top of the bunch first, as if drifting down (each flower's centre y is in its clip-path)
  flowers.sort(function (a, b) {
    return parseFloat(a.style.clipPath.split(' ').pop()) - parseFloat(b.style.clipPath.split(' ').pop());
  });
  function on(el, yes) { if (el) el.classList.toggle('on', yes); }
  // how far an element has come up the screen: 0 with its top at the bottom edge, 1 at `upto`
  function seen(el, upto) {
    var h = innerHeight;
    return Math.min(1, Math.max(0, (h - el.getBoundingClientRect().top) / (h * (1 - upto))));
  }
  var wordsAt = null, done = false, played = false;   // scroll position when the words came in; the band follows from there
  // px a part has risen past 90% of the screen height (0 until it is on screen)
  function risen(el) { return Math.max(0, innerHeight * 0.9 - el.getBoundingClientRect().top); }
  function frame() {
    var d = Math.max(0, scrollY), shown = 0;
    // flowers follow your scrolling, but only once the bunch is on screen (phones)
    var df = Math.min(d, risen(box));
    flowers.forEach(function (f, i) { var y = df >= 10 + STEP * i; on(f, y); if (y) shown++; });
    var wordsIn = shown === flowers.length && risen(words[0]) > 0;
    words.forEach(function (w) { on(w, wordsIn); });
    if (!wordsIn) wordsAt = null; else if (wordsAt === null) wordsAt = scrollY;
    // then the paper band: once the words are in and the band is on screen, it plays through to
    // its last slice on its own, left to right (it no longer waits for more scrolling, so the stack
    // always reaches the end of the screen), and stays built
    if (!played && wordsAt !== null && risen(band) > 0) {
      played = true;
      strips.forEach(function (s, i) { s.style.transitionDelay = (i * GAP) + 'ms'; s.classList.add('on'); });
      // the paper band is complete: let the next part of the page (Our Mission) come in
      setTimeout(function () {
        if (!done) { done = true; dispatchEvent(new Event('papers-done')); }
      }, strips.length * GAP + 400);
    }
  }
  var queued = false;
  function onScroll() { if (!queued) { queued = true; requestAnimationFrame(function () { queued = false; frame(); }); } }
  addEventListener('scroll', onScroll, { passive: true });
  addEventListener('resize', onScroll);
  frame();
})();
