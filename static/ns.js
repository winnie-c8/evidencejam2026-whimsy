// Not studied dropdown (Figma frames 4-6): topic and outcome pickers that take several values
// each, shown as removable chips. A pairing is listed when its topic is one of the chosen topics
// (or none is chosen) and its outcome is one of the chosen outcomes (or none is chosen).
// Without script every pairing is listed and the pickers stay hidden. A link to #gap-<slug>
// clears the choices first so the row is visible.
(function () {
  document.querySelectorAll('details.ns').forEach(function (d) {
    var f = d.querySelector('.ns-f');
    var lis = [].slice.call(d.querySelectorAll('li.gap'));
    var notes = [].slice.call(d.querySelectorAll('.searched[data-s]'));
    var more = d.querySelector('.ns-more'), none = d.querySelector('.ns-none');
    var cnt = d.querySelector('.ns-n'), word = d.querySelector('.ns-w'), badge = d.querySelector('.ns-c');
    var sub = d.querySelector('.ns-sub'), subAll = sub ? sub.textContent : '';
    var shown = +d.dataset.shown || 12, all = false;
    var pickers = f ? [].slice.call(f.querySelectorAll('.ns-pick')) : [];
    if (f) f.hidden = false;

    var P = pickers.map(function (p) {
      var panel = document.getElementById(p.dataset.panel);
      var o = {
        key: p.dataset.k, name: p.dataset.name, el: p, panel: panel,
        open: p.querySelector('.ns-open'), chips: p.querySelector('.ns-chips'),
        opts: [].slice.call(panel.querySelectorAll('button[data-v]')), sel: []
      };
      o.open.addEventListener('click', function () { toggle(o, panel.hidden); });
      p.querySelector('.ns-box').addEventListener('click', function (e) {
        if (e.target === e.currentTarget || e.target === o.chips) toggle(o, panel.hidden);
      });
      o.opts.forEach(function (b) {
        b.addEventListener('click', function () {
          // the chosen option leaves the grid (it becomes a chip): keep focus on a neighbour
          var vis = visible(o), i = vis.indexOf(b);
          var next = vis[i + 1] || vis[i - 1];
          pick(o, b.dataset.v);
          (next || o.open).focus();
        });
      });
      o.chips.addEventListener('click', function (e) {
        var c = e.target.closest('button[data-v]');
        if (!c) return;
        pick(o, c.dataset.v);
        o.open.focus();
      });
      [p, panel].forEach(function (x) {
        x.addEventListener('keydown', function (e) {
          if (e.key === 'Escape' && !panel.hidden) { e.preventDefault(); toggle(o, false); o.open.focus(); }
        });
      });
      // Arrow keys: Down on the box opens the grid; inside it, arrows move between options
      // (Up/Down in reading order, Left/Right a column apart), Home/End jump to the ends.
      o.open.addEventListener('keydown', function (e) {
        if (e.key !== 'ArrowDown') return;
        e.preventDefault();
        toggle(o, true);
        var vis = visible(o);
        if (vis[0]) vis[0].focus();
      });
      panel.addEventListener('keydown', function (e) {
        var vis = visible(o), i = vis.indexOf(document.activeElement);
        if (i < 0) return;
        var per = Math.ceil(vis.length / cols(o)), j = null;
        if (e.key === 'ArrowDown') j = i + 1;
        else if (e.key === 'ArrowUp') j = i - 1;
        else if (e.key === 'ArrowRight') j = i + per;
        else if (e.key === 'ArrowLeft') j = i - per;
        else if (e.key === 'Home') j = 0;
        else if (e.key === 'End') j = vis.length - 1;
        if (j === null) return;
        e.preventDefault();
        if (j < 0 && e.key === 'ArrowUp') { o.open.focus(); return; }
        vis[Math.max(0, Math.min(vis.length - 1, j))].focus();
      });
      return o;
    });

    function visible(o) {
      return o.opts.filter(function (b) { return !b.hidden; });
    }

    function cols(o) {  // columns actually drawn (fewer on a phone than the CSS asks for)
      var xs = {};
      visible(o).forEach(function (b) { xs[Math.round(b.getBoundingClientRect().left)] = 1; });
      return Math.max(1, Object.keys(xs).length);
    }

    function toggle(o, show) {
      P.forEach(function (x) {
        var on = x === o && show;
        x.panel.hidden = !on;
        x.open.setAttribute('aria-expanded', on ? 'true' : 'false');
        x.el.classList.toggle('on', on);
      });
    }

    function pick(o, v) {
      var i = o.sel.indexOf(v);
      if (i < 0) o.sel.push(v); else o.sel.splice(i, 1);
      all = false;
      draw(o);
      run();
    }

    function label(o, v) {
      for (var i = 0; i < o.opts.length; i++) if (o.opts[i].dataset.v === v) return o.opts[i].textContent;
      return '';
    }

    function draw(o) {
      o.opts.forEach(function (b) { b.hidden = o.sel.indexOf(b.dataset.v) >= 0; });
      o.chips.textContent = '';
      o.sel.forEach(function (v) {
        var t = label(o, v), b = document.createElement('button');
        b.type = 'button';
        b.className = 'ns-chip';
        b.dataset.v = v;
        b.setAttribute('aria-label', 'Remove ' + t);
        b.textContent = t + ' ';
        var x = document.createElement('span');
        x.setAttribute('aria-hidden', 'true');
        x.textContent = '×';
        b.appendChild(x);
        o.chips.appendChild(b);
      });
      o.el.classList.toggle('has', o.sel.length > 0);
    }

    function chosen(k) {
      for (var i = 0; i < P.length; i++) if (P[i].key === k) return P[i].sel;
      return [];
    }

    function run() {
      var s = chosen('s'), o = chosen('o'), any = s.length || o.length, n = 0;
      var cap = any || all ? Infinity : shown;
      lis.forEach(function (li) {
        var ok = (!s.length || s.indexOf(li.dataset.s) >= 0) && (!o.length || o.indexOf(li.dataset.o) >= 0);
        if (ok) n++;
        li.hidden = !ok || n > cap;
      });
      notes.forEach(function (x) { x.hidden = s.indexOf(x.dataset.s) < 0; });
      if (none) none.hidden = n > 0;
      cnt.textContent = n;
      if (badge) badge.textContent = n;
      word.textContent = n === 1 ? 'pairing' : 'pairings';
      if (sub) {
        sub.textContent = any ? P.map(function (p) {
          return p.name + ': ' + (p.sel.length ? p.sel.map(function (v) { return label(p, v); }).join(', ') : 'any');
        }).join(' · ') : subAll;
      }
      var rest = n - shown;
      more.hidden = any || all || rest < 1;
      more.textContent = '+ ' + rest + ' more';
    }

    more.addEventListener('click', function () { all = true; run(); });
    document.addEventListener('click', function (e) {
      if (f && !f.contains(e.target)) P.forEach(function (o) { if (!o.panel.hidden) toggle(o, false); });
    });

    function hash() {
      var t = location.hash && document.getElementById(decodeURIComponent(location.hash.slice(1)));
      if (t && d.contains(t) && t.matches('li.gap')) {
        P.forEach(function (o) { o.sel = []; draw(o); });
        toggle(null, false);
        all = true;
        run();
      }
    }
    addEventListener('hashchange', hash);
    run();
    hash();
  });
})();
