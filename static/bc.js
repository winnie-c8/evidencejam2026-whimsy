// Q2 finding cards (Figma "Bottom card · one cause"): the three buttons under the figures
// (Certainty calculation, Citations, Constraints) each open their section below; the two
// fold-outs in the certainty section ("How certainty is graded", "Constraints of this grade")
// and the Constraints section are copied in from one <template> per page. Without script all
// three sections show, the fold-out buttons stay hidden and Constraints links to the overview.
(function () {
  function fill(el, id) {
    var t = document.getElementById(id);
    if (t && !el.dataset.filled) { el.textContent = ''; el.appendChild(t.content.cloneNode(true)); el.dataset.filled = '1'; }
  }

  document.querySelectorAll('article.bc').forEach(function (card) {
    var cons = card.querySelector('.bc-cons[data-tpl]');
    if (cons) fill(cons, cons.dataset.tpl);
    var folds = card.querySelector('.bc-folds');
    if (folds) folds.hidden = false;
    // start closed: the card shows its figures and split; the buttons open the rest
    card.querySelectorAll('.bc-btns .bc-tog').forEach(function (b) {
      b.setAttribute('aria-expanded', 'false');
      document.getElementById(b.getAttribute('aria-controls')).hidden = true;
    });
  });

  document.addEventListener('click', function (e) {
    var b = e.target.closest('article.bc .bc-tog');
    if (b) {
      var sec = document.getElementById(b.getAttribute('aria-controls'));
      var open = b.getAttribute('aria-expanded') !== 'true';
      if (open && b.dataset.tpl) fill(sec, b.dataset.tpl);
      b.setAttribute('aria-expanded', open ? 'true' : 'false');
      sec.hidden = !open;
      return;
    }
    // a link out of a popup ("Constraints" in How to read the chart) closes the popup first
    var a = e.target.closest('[popover] a[data-close]');
    if (a && a.closest('[popover]').hidePopover) a.closest('[popover]').hidePopover();
  });
})();
