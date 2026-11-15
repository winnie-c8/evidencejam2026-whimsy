// Q3 gap map. Every box is a button. The map is one Tab stop; the arrow keys move between boxes
// (Home / End: row ends).
// - A studied box already opens its treatment's side panel on its own card (popovertarget); here it
//   gets its full spoken name: "Seeding / sowing, Plant & vegetation cover: 9 studies, Mixed, High certainty".
// - An empty box becomes a button for the one shared "Not studied" panel (#gm-gap), filled in from
//   its row, its column and the Not studied list (the pack's "searched for" sentence).
// - A card's fold-outs fill in the first time they open: "Certainty calculation" from the exact rule
//   text, "Citations" from the finding's own sources page, "Constraints" from the page's limitations.
// Without script, studied boxes still open their panels, and each fold-out still holds the exact
// rule text or a link (the sources page, the limitations).
(function () {
  var table = document.querySelector('#gapmap-wrap table.gapmap');
  if (!table) return;
  var RULES = {};
  try { RULES = JSON.parse(document.getElementById('gm-rules').textContent); } catch (e) { /* plain text stays */ }
  var gapPop = document.getElementById('gm-gap');
  var anyLim = document.querySelector('[data-check*="/limitations/"]');
  var QID = anyLim ? anyLim.getAttribute('data-check').split('/')[0] : '';
  var cols = [].map.call(table.tHead.rows[0].querySelectorAll('th[scope="col"]:not(.tot)'),
    function (th) { return th.textContent.trim(); });

  function txt(root, sel) {
    var n = root && root.querySelector(sel);
    return n ? n.textContent.replace(/\s+/g, ' ').trim() : '';
  }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function plural(n, one, many) { return n === 1 ? one : many; }

  // 1. Buttons and their spoken names.
  [].forEach.call(table.tBodies[0].rows, function (tr) {
    var row = txt(tr, 'th[scope="row"]');
    [].forEach.call(tr.querySelectorAll('td:not(.tot)'), function (td, i) {
      var b = td.querySelector('button');
      if (td.classList.contains('empty')) {
        td.removeAttribute('aria-label');
        b = el('button', 'gm-e', '–');
        b.type = 'button';
        b.setAttribute('popovertarget', 'gm-gap');
        b.setAttribute('aria-label', row + ', ' + cols[i] + ': Not studied');
        b.dataset.r = row;
        b.dataset.c = cols[i];
        td.textContent = '';
        td.appendChild(b);
      } else if (b) {
        var card = document.getElementById(b.dataset.open);
        var n = txt(card, '[data-check$="/studies"]');
        b.setAttribute('aria-label', row + ', ' + cols[i] + ': ' + n + (n === '1' ? ' study, ' : ' studies, ') +
          txt(card, '[data-check$="/direction"]') + ', ' + txt(card, '[data-check$="/certainty"]') + ' certainty');
      }
    });
  });

  // Each card: the split bar from its numbers (decorative; the words are the content), and the
  // Constraints fold-out (the page's own limitations; the table says which go with a studied box).
  [].forEach.call(document.querySelectorAll('.gmc-sp'), function (p) {
    var bar = el('span', 'agree');
    bar.setAttribute('aria-hidden', 'true');
    [].forEach.call(p.querySelectorAll('.sp'), function (sp) {
      var k = (sp.className.match(/\bk-([\w-]+)/) || [])[1], n = parseInt(txt(sp, '[data-check]'), 10);
      if (!k || !(n > 0)) return;
      var seg = el('i', 's-' + k);
      seg.style.flexGrow = n;
      bar.appendChild(seg);
    });
    if (bar.children.length) p.parentNode.insertBefore(bar, p);
  });
  [].forEach.call(document.querySelectorAll('.gmc .gmc-more'), function (row) {
    var d = el('details', 'gmx gmx-lim');
    d.dataset.lim = table.dataset.lim || '';
    d.appendChild(el('summary', '', 'Constraints'));
    var b = el('div', 'gmx-b'), go = el('p', 'go'), a = el('a', '', 'What this map can’t tell you →');
    a.href = '#limits-' + QID;
    go.appendChild(a);
    b.appendChild(go);
    d.appendChild(b);
    row.appendChild(d);
  });

  // Hovering a box, or selecting it (keyboard focus, or its panel open), lifts the box and its row
  // and column names a little, so it is obvious which pairing you are looking at. "hv" is the mouse,
  // "fx" the focus; CSS animates both the same way.
  var heads = table.tHead.rows[0].cells;
  function mark(td, cls, on) {
    if (!td || td.classList.contains('tot') || !td.parentNode.parentNode.isSameNode(table.tBodies[0])) return;
    td.classList.toggle(cls, on);
    var rh = td.parentNode.querySelector('th[scope="row"]'), ch = heads[td.cellIndex];
    if (rh) rh.classList.toggle(cls, on);
    if (ch) ch.classList.toggle(cls, on);
  }
  var hov = null, foc = null;
  table.addEventListener('mouseover', function (e) {
    var td = e.target.closest('td');
    if (td === hov) return;
    mark(hov, 'hv', false);
    hov = td && td.querySelector('button') ? td : null;
    mark(hov, 'hv', true);
  });
  table.addEventListener('mouseleave', function () { mark(hov, 'hv', false); hov = null; });
  table.addEventListener('focusin', function (e) {
    var td = e.target.closest('td');
    mark(foc, 'fx', false);
    foc = td;
    mark(foc, 'fx', true);
  });
  table.addEventListener('focusout', function (e) {
    if (!table.contains(e.relatedTarget)) { mark(foc, 'fx', false); foc = null; }
  });

  // 2. One Tab stop for the whole map (roving tabindex): only one box is in the Tab order, the
  //    first at the start, then whichever box was last focused. Tab enters and leaves the map
  //    once; the arrow keys move between boxes. Without script, the studied boxes stay Tab stops.
  var boxes = table.tBodies[0].querySelectorAll('td > button');
  var cur = boxes[0] || null;
  [].forEach.call(boxes, function (b) { b.tabIndex = b === cur ? 0 : -1; });
  table.addEventListener('focusin', function (e) {
    var b = e.target.closest('td > button');
    if (!b || b === cur) return;
    if (cur) cur.tabIndex = -1;
    b.tabIndex = 0;
    cur = b;
  });

  // Arrow keys between boxes.
  table.addEventListener('keydown', function (e) {
    var k = e.key;
    if (['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'].indexOf(k) < 0) return;
    var b = e.target.closest('td > button');
    if (!b) return;
    var td = b.parentNode, tr = td.parentNode, rows = table.tBodies[0].rows;
    var ri = tr.sectionRowIndex, ci = td.cellIndex;
    if (k === 'ArrowRight') ci++;
    else if (k === 'ArrowLeft') ci--;
    else if (k === 'ArrowDown') ri++;
    else if (k === 'ArrowUp') ri--;
    else if (k === 'Home') ci = 1;
    else ci = tr.cells.length - 2;           // End: the last box (the totals cell is not one)
    e.preventDefault();
    var c = rows[ri] && rows[ri].cells[ci], nb = c && c.querySelector('button');
    if (nb) nb.focus();
  });

  // 3. The pack's limitations, word for word, copied from the page (they live there once).
  function lims(box, list) {
    if (!box || box.dataset.filled) return;
    box.dataset.filled = '1';
    var ul = el('ul', 'gmx-lims');
    (list || box.dataset.lim || '').split(',').filter(Boolean).forEach(function (i) {
      var src = document.querySelector('[data-check="' + QID + '/limitations/' + i + '"]');
      var li = src && src.closest('li');
      if (!li) return;
      var c = li.cloneNode(true);
      [].forEach.call(c.querySelectorAll('[data-check]'), function (n) { n.removeAttribute('data-check'); });
      ul.appendChild(c);
    });
    if (ul.children.length) box.insertBefore(ul, box.firstChild);
  }

  // 4. An empty box: fill the shared Not studied panel just before it opens.
  var gapLis = [].slice.call(document.querySelectorAll('li.gap'));
  function findGap(r, c) {
    for (var i = 0; i < gapLis.length; i++) {
      var li = gapLis[i], o = li.querySelector('.o'), st = li.querySelector('strong');
      if (!o || o.textContent.trim() !== c) continue;
      if (li.textContent.replace(st ? st.textContent : '', '').replace(o.textContent, '').trim() === r) return li;
    }
    return null;
  }
  table.addEventListener('click', function (e) {
    var b = e.target.closest('button.gm-e');
    if (!b || !gapPop) return;
    var r = b.dataset.r, c = b.dataset.c, li = findGap(r, c);
    var h = gapPop.querySelector('.gmc-h');
    h.textContent = r + ' ';
    var arrow = el('span', '', '→');
    arrow.setAttribute('aria-hidden', 'true');
    h.appendChild(arrow);
    h.appendChild(el('span', 'sr-only', ', paired with'));
    h.appendChild(document.createTextNode(' ' + c));
    var note = li && document.querySelector('.searched[data-s="' + li.dataset.s + '"]');
    var tpl = note && note.getAttribute('data-template');
    var sf = gapPop.querySelector('.gmc-searched');
    sf.hidden = !tpl;
    if (tpl) sf.querySelector('span').textContent = '“' + tpl.split('{outcome}').join(c) + '”';
    gapPop.querySelector('.gmc-list').setAttribute('href', li ? '#' + li.id : '#not-studied');
    lims(gapPop.querySelector('.gmc-lims'));
  });
  if (gapPop) {
    gapPop.querySelector('.gmc-list').addEventListener('click', function () { gapPop.hidePopover(); });
  }

  // 5. "Certainty calculation": start → adjust → result, from the exact rule text.
  var RX = /^start (high|moderate|low|very low) \([^)]*\)(.*?)\s*->\s*(high|moderate|low|very low)$/;
  var LV = { 'very low': 1, low: 2, moderate: 3, high: 4 };
  var LW = { 1: 'Very low', 2: 'Low', 3: 'Moderate', 4: 'High' };
  function bars(n) {
    var s = el('span', 'bars b' + n);
    s.setAttribute('aria-hidden', 'true');
    return s;
  }
  function signed(n) { return n > 0 ? '+' + n : n < 0 ? '−' + (-n) : '0'; }
  function step(label, num, text, cls) {
    var li = el('li', cls || '');
    li.appendChild(el('span', 'lab', label));
    var nu = el('span', 'num');
    nu.appendChild(num);
    li.appendChild(nu);
    if (text) li.appendChild(text);
    return li;
  }
  function calc(d) {
    var box = d.querySelector('.gmc-calc'), m = txt(d, '.rule').match(RX);
    if (!box || !m) return;
    var start = LV[m[1]], fin = LV[m[3]], tot = start, one = false, moves = [];
    m[2].split(';').forEach(function (p) {
      p = p.trim();
      if (!p) return;
      var dm = p.match(/^([+-]\d+)/), dv = dm ? +dm[1] : 0, t = p;
      if (/single study/.test(p)) one = true;
      (RULES.steps || []).some(function (sp) {
        var x = p.match(new RegExp(sp[0]));
        if (x) { t = sp[1].replace('{0}', x[1] || ''); return true; }
        return false;
      });
      tot += dv;
      moves.push([dv, t]);
    });
    var note = '';
    if (tot !== fin) {
      note = tot > 4 && fin === 4 ? 'It can’t go above 4, so it stays at the top.'
        : tot < 1 && fin === 1 ? 'It can’t go below 1.'
          : fin === 3 && one ? 'One study never goes above Moderate.'
            : 'Adds up to ' + tot + '; the pack grades it ' + fin + '.';
    }
    box.appendChild(el('p', 'gmc-ck', 'How this finding got “' + LW[fin] + '”'));
    var ol = el('ol', 'gmc-flow');
    var n1 = el('span', '', start + ' ');
    n1.appendChild(bars(start));
    ol.appendChild(step('Start', n1, el('span', 't', (RULES.start || {})[m[1]] || '')));
    var adj = el('span', 't');
    if (!moves.length) adj.textContent = 'Nothing moved it up or down.';
    moves.forEach(function (mv) {
      var line = el('span', 'mv');
      if (mv[0] && moves.length > 1) line.appendChild(el('b', mv[0] > 0 ? 'up' : 'down', signed(mv[0]) + ' '));
      line.appendChild(document.createTextNode(mv[1]));
      adj.appendChild(line);
    });
    ol.appendChild(step('Adjust', el('span', tot - start > 0 ? 'up' : tot - start < 0 ? 'down' : '', signed(tot - start)), adj));
    var n3 = el('span', '', LW[fin] + ' ');
    n3.appendChild(bars(fin));
    ol.appendChild(step('Result', n3, note ? el('span', 't', note) : null, 'res'));
    box.appendChild(ol);
    var more = el('p', 'gmc-calc-more');
    var how = el('button', 'gmx-btn', 'How certainty is graded');
    how.type = 'button';
    how.setAttribute('popovertarget', 'how-grading');
    more.appendChild(how);
    box.appendChild(more);
    var cav = el('p', 'gmc-caveat');
    cav.appendChild(el('strong', '', 'The grade can overstate how sure we are. '));
    cav.appendChild(document.createTextNode('It starts from the strongest study, not an average, so one good ' +
      'experiment can lift a group of weaker studies.'));
    box.appendChild(cav);
  }

  // 6. "Citations": each paper with its year, its quotes word for word and a link to the paper,
  // read from the finding's own sources page (the answer page stays light). If that page can't be
  // fetched, the link to it is still there.
  function cites(d) {
    var b = d.querySelector('.gmx-b');
    fetch(d.dataset.src).then(function (r) {
      if (!r.ok) throw new Error(r.status);
      return r.text();
    }).then(function (html) {
      var doc = new DOMParser().parseFromString(html, 'text/html');
      var papers = [].slice.call(doc.querySelectorAll('section.paper'));
      if (!papers.length) return;
      var ul = el('ul', 'gmx-papers');
      papers.forEach(function (sec, k) {
        var head = txt(sec, 'h2').replace(/^Paper \d+ of \d+: /, '');
        var ym = head.match(/\s\((\d{4})\)$/);
        var title = ym ? head.slice(0, ym.index) : head;
        // each source: its quote word for word, and the sources page's notes on that claim (how it
        // was tested, what it found, ...), so nothing on that page is missing from the popup
        var quotes = [].map.call(sec.querySelectorAll('details.ev'), function (ev) {
          var frag = document.createDocumentFragment();
          var q = ev.querySelector('blockquote.quote');
          if (q) frag.appendChild(el('blockquote', 'quote', q.textContent.trim()));
          var dl = ev.querySelector('dl.camo');
          if (dl) {
            var c = document.importNode(dl, true);
            [].forEach.call(c.querySelectorAll('[data-check],[id]'), function (n) {
              n.removeAttribute('data-check');
              n.removeAttribute('id');
            });
            var ab = el('details', 'gmx-about');
            ab.appendChild(el('summary', '', 'About this source'));
            ab.appendChild(c);
            frag.appendChild(ab);
          }
          return frag;
        });
        var doi = sec.querySelector('p.src a[href^="https://doi.org/"]');
        var doiTxt = sec.querySelector('p.src .doi');
        var li = el('li');
        var pd = el('details', 'gmx-paper');
        if (k === 0) pd.open = true;
        var sm = el('summary');
        sm.appendChild(el('span', 'y', ym ? ym[1] : '–'));
        sm.appendChild(el('span', 't', title));
        sm.appendChild(el('span', 'n', quotes.length + ' ' + plural(quotes.length, 'quote', 'quotes')));
        pd.appendChild(sm);
        if (quotes[0]) pd.appendChild(quotes[0]);
        if (quotes.length > 1) {
          var qm = el('details', 'gmx-qmore');
          var qs = el('summary', '', (quotes.length - 1) + ' more ' + plural(quotes.length - 1, 'quote', 'quotes'));
          qm.appendChild(qs);
          quotes.slice(1).forEach(function (q) { qm.appendChild(q); });
          pd.appendChild(qm);
        }
        if (doi) {
          var a = el('a', 'gmx-btn', 'Open the paper ');
          a.href = doi.getAttribute('href');
          a.rel = 'noopener';
          var ar = el('span', '', '↗');
          ar.setAttribute('aria-hidden', 'true');
          a.appendChild(ar);
          var p = el('p', 'gmx-acts');
          p.appendChild(a);
          if (doiTxt) p.appendChild(el('small', 'doi', doiTxt.textContent.trim()));
          pd.appendChild(p);
        }
        li.appendChild(pd);
        ul.appendChild(li);
      });
      var go = b.querySelector('.go');
      b.insertBefore(el('p', 'gmx-note', 'Each quote is one sentence copied word for word from the paper. ' +
        '“Authors’ wording” is how strongly the paper words its claim; it is separate from the certainty grade.'), go);
      b.insertBefore(ul, go);
      // everything from the sources page is now here, so no need to open it (the link stays in the
      // page for readers without script, and for the checkers)
      if (go) go.style.display = 'none';
    }).catch(function () { /* the sources-page link stays */ });
  }

  // Full screen shows only the map's box, and anything outside it (the side panels, the "How
  // certainty is graded" box, the legend) would sit behind it. So while the map is full screen they
  // move inside it, and go back to their places afterwards. Links that leave the map (to the Not
  // studied list) end full screen first.
  var wrap = document.getElementById('gapmap-wrap');
  var legend = document.getElementById('gm-legend');
  var moved = [];
  document.addEventListener('fullscreenchange', function () {
    var on = document.fullscreenElement === wrap;
    if (on && !moved.length) {
      var parts = [].slice.call(document.querySelectorAll('.rowpop, #how-grading'));
      if (legend) parts.unshift(legend);
      parts.forEach(function (n) {
        if (n.matches && n.matches(':popover-open')) n.hidePopover();
        var mark = document.createComment('gm');
        n.parentNode.insertBefore(mark, n);
        moved.push([n, mark]);
        if (n === legend) wrap.insertBefore(n, wrap.firstChild);
        else wrap.appendChild(n);
      });
    } else if (!on && moved.length) {
      moved.forEach(function (m) {
        if (m[0].matches && m[0].matches(':popover-open')) m[0].hidePopover();
        m[1].parentNode.insertBefore(m[0], m[1]);
        m[1].remove();
      });
      moved = [];
    }
  });
  if (gapPop) {
    gapPop.querySelector('.gmc-list').addEventListener('click', function () {
      if (document.fullscreenElement) document.exitFullscreen();
    });
  }

  // Fold-outs are <details>: fill each one the first time it opens.
  document.addEventListener('toggle', function (e) {
    var d = e.target;
    if (!d.matches || !d.matches('details.gmx') || !d.open || d.dataset.done) return;
    d.dataset.done = '1';
    if (d.classList.contains('gmx-calc')) calc(d);
    else if (d.classList.contains('gmx-src')) cites(d);
    else if (d.classList.contains('gmx-lim')) lims(d.querySelector('.gmx-b'), d.dataset.lim);
  }, true);
})();
