/* Q1 graph: drag boxes and arrows (arrows stay attached), pin a box's highlight, filter and
   sort the arrows, and open an arrow's evidence in a side panel. Without this script the
   graph still works: each arrow is a plain link to its evidence section further down.

   The routing below mirrors route_all() in build/graph_svg.py; keep the two in step. */
(function () {
  'use strict';
  var svg = document.getElementById('q1g');
  if (!svg || !svg.getScreenCTM || !window.fetch) return;

  function num(name) { return +svg.getAttribute('data-' + name); }
  var DOWN = svg.getAttribute('data-flow') === 'down';
  var STRIP = num('strip'), VTAIL = num('vtail'), MOD_INSET = num('mod-inset');
  var HEAD_GAP = num('head-gap'), TIER = num('tier');
  var PORT_PAD = num('port-pad'), OUT_W = num('out-w');
  var VB = svg.viewBox.baseVal;
  var DIRS = { r: [1, 0], l: [-1, 0], b: [0, 1], t: [0, -1] };
  var INTO = { l: [1, 0], r: [-1, 0], t: [0, 1], b: [0, -1] };
  var FLOWDIR = DOWN ? [0, 1] : [1, 0];
  var MAIN_IN = DOWN ? 'tb' : 'lr';
  var PERP = DOWN ? [1, 0] : [0, 1];
  var RANK = { high: 0, moderate: 1, low: 2, very_low: 3 };

  function P(u, v) { return DOWN ? [v, u] : [u, v]; }
  function f1(v) { var s = v.toFixed(1); return s === '-0.0' ? '0.0' : s; }
  function each(list, fn) { Array.prototype.forEach.call(list, fn); }
  function major(dx, dy) {   // the main direction of a vector, as a unit step along x or y
    return Math.abs(dx) >= Math.abs(dy) ? [dx < 0 ? -1 : 1, 0] : [0, dy < 0 ? -1 : 1];
  }

  // ---------------------------------------------------------------- model, read from the SVG

  var boxes = {};
  each(svg.querySelectorAll('g.node'), function (el) {
    var m = /translate\(([-\d.]+),([-\d.]+)\)/.exec(el.getAttribute('transform'));
    var kind = /\bk-(\w+)/.exec(el.getAttribute('class'));
    var b = { el: el, id: el.getAttribute('data-id'), x: +m[1], y: +m[2], kind: kind ? kind[1] : '',
              w: +el.getAttribute('data-w'), h: +el.getAttribute('data-h'),
              name: el.textContent.replace(/\s+/g, ' ').trim() };
    b.homeX = b.x; b.homeY = b.y;
    boxes[b.id] = b;
  });

  var arrows = [];
  var byId = {};
  each(svg.querySelectorAll('a.edge, a.gap-link'), function (el) {
    var rect = el.querySelector('.lbl rect');
    var cert = /\bc-(high|moderate|low|very_low)\b/.exec(el.getAttribute('class'));
    var n = el.getAttribute('data-n');
    var a = { el: el, id: el.getAttribute('data-id'), s: el.getAttribute('data-s'),
              lw: +rect.getAttribute('width'), lh: +rect.getAttribute('height'),
              paths: el.querySelectorAll('path.hit, path.vis'), rect: rect,
              texts: el.querySelectorAll('.lbl text'), ring: el.querySelector('circle.ring'),
              cert: cert ? cert[1] : null,               // null: a "no evidence" gap
              rank: cert ? RANK[cert[1]] : 4, studies: n ? +n : 0,
              via: null, laneOff: 0 };                   // set when the reader drags the arrow
    a.textOff = Array.prototype.map.call(a.texts, function (t) {
      return [+t.getAttribute('x') - +rect.getAttribute('x'), +t.getAttribute('y') - +rect.getAttribute('y')];
    });
    if (el.hasAttribute('data-te')) {
      a.te = el.getAttribute('data-te');
      a.lt = +el.getAttribute('data-lt');
    } else {
      a.t = el.getAttribute('data-t');
      var lane = el.getAttribute('data-lane');
      a.lane = lane ? lane.split(' ').map(Number) : null;
    }
    arrows.push(a);
    byId[a.id] = a;
  });
  var members = Array.prototype.slice.call(svg.querySelectorAll('path.member'));

  // ---------------------------------------------------------------- routing

  function right(b) { return b.x + b.w; }
  function bottom(b) { return b.y + b.h; }
  function cx(b) { return b.x + b.w / 2; }
  function cy(b) { return b.y + b.h / 2; }

  function sides(s, t) {
    if (DOWN) {
      if (t.y - bottom(s) >= 60) return ['b', 't'];
      if (s.y - bottom(t) >= 60) return ['t', 'b'];
      return cx(t) >= cx(s) ? ['r', 'l'] : ['l', 'r'];
    }
    if (t.x - right(s) >= 60) return ['r', 'l'];
    if (s.x - right(t) >= 60) return ['l', 'r'];
    return cy(t) >= cy(s) ? ['b', 't'] : ['t', 'b'];
  }

  function modSide(s, a) {
    if (DOWN) {
      if (a[1] - bottom(s) >= 40) return 'b';
      if (s.y - a[1] >= 40) return 't';
      return a[0] >= cx(s) ? 'r' : 'l';
    }
    if (a[0] - right(s) >= 40) return 'r';
    if (s.x - a[0] >= 40) return 'l';
    return a[1] >= cy(s) ? 'b' : 't';
  }

  function laneActive(s, t, sd, lane) {
    if (!lane) return false;
    if (DOWN) return sd[0] === 'b' && sd[1] === 't' && bottom(s) + 40 <= lane[0] && lane[1] + 40 <= t.y - STRIP;
    return sd[0] === 'r' && sd[1] === 'l' && right(s) + 40 <= lane[0] && lane[1] + 40 <= t.x - STRIP;
  }

  function sCurve(a, da, b, db) {
    var dist = da[1] === 0 ? Math.abs(b[0] - a[0]) : Math.abs(b[1] - a[1]);
    var k = Math.max(24, 0.5 * dist);
    return [[a[0] + da[0] * k, a[1] + da[1] * k], [b[0] - db[0] * k, b[1] - db[1] * k]];
  }

  function bezier(p, t) {
    var u = 1 - t;
    return [u * u * u * p[0][0] + 3 * u * u * t * p[1][0] + 3 * u * t * t * p[2][0] + t * t * t * p[3][0],
            u * u * u * p[0][1] + 3 * u * u * t * p[1][1] + 3 * u * t * t * p[2][1] + t * t * t * p[3][1]];
  }

  function fmtPath(start, segs) {
    var out = 'M' + f1(start[0]) + ',' + f1(start[1]);
    segs.forEach(function (sg) {
      out += ' ' + sg[0] + sg[1].map(function (p) { return f1(p[0]) + ',' + f1(p[1]); }).join(' ');
    });
    return out;
  }

  var sortByCertainty = false;   // "Sort by certainty": most certain arrows first at each box

  function routeAll() {
    var info = {};
    var plain = arrows.filter(function (a) { return !a.te; });
    var mods = arrows.filter(function (a) { return a.te; });

    plain.forEach(function (a) {
      var s = boxes[a.s], t = boxes[a.t], sd = sides(s, t);
      var lane = laneActive(s, t, sd, a.lane) ? [a.lane[0], a.lane[1], a.lane[2] + a.laneOff] : null;
      info[a.id] = { sides: sd, lane: lane };
    });

    function roughAnchor(te) {
      var ti = info[te], tg = byId[te];
      if (ti.lane) return P(ti.lane[0] + MOD_INSET, ti.lane[2]);
      if (tg.via) return tg.via;
      var s = boxes[tg.s], t = boxes[tg.t];
      return [(cx(s) + cx(t)) / 2, (cy(s) + cy(t)) / 2];
    }
    mods.forEach(function (m) {
      info[m.id] = { side: modSide(boxes[m.s], m.via || roughAnchor(m.te)) };
    });

    var ends = {};
    function addEnd(nid, side, other, id, role) {
      var key = nid + '\u0000' + side;
      (ends[key] = ends[key] || { nid: nid, side: side, list: [] }).list.push([other, id, role]);
    }
    plain.forEach(function (a) {
      var i = info[a.id], s = boxes[a.s], t = boxes[a.t], so = i.sides[0], ti = i.sides[1];
      var oOut, oIn;
      if (i.lane) { oOut = oIn = i.lane[2]; }
      else if (a.via) { oOut = oIn = (so === 'l' || so === 'r') ? a.via[1] : a.via[0]; }
      else if (so === 'l' || so === 'r') { oOut = cy(t); oIn = cy(s); }
      else { oOut = cx(t); oIn = cx(s); }
      addEnd(a.s, so, oOut, a.id, 'out');
      addEnd(a.t, ti, oIn, a.id, 'in');
    });
    mods.forEach(function (m) {
      var side = info[m.id].side, ra = m.via || roughAnchor(m.te);
      addEnd(m.s, side, (side === 'l' || side === 'r') ? ra[1] : ra[0], m.id, 'out');
    });
    function byCertainty(p, q) {
      var ap = byId[p[1]], aq = byId[q[1]];
      return (ap.rank - aq.rank) || (aq.studies - ap.studies);
    }
    Object.keys(ends).forEach(function (key) {
      var e = ends[key], b = boxes[e.nid], n = e.list.length;
      e.list.sort(function (p, q) {
        return (sortByCertainty ? byCertainty(p, q) : 0) || p[0] - q[0] ||
          (p[1] < q[1] ? -1 : p[1] > q[1] ? 1 : 0);
      });
      // top-down, arrows coming in from above get a slot as wide as their badge (one row of badges)
      var slots = e.list.map(function (it) { return it[2] === 'in' ? byId[it[1]].lw + PORT_PAD : OUT_W; });
      var total = slots.reduce(function (s, v) { return s + v; }, 0);
      var spaced = DOWN && (e.side === 't' || e.side === 'b') && total <= b.w;
      var cum = (b.w - total) / 2;
      e.list.forEach(function (it, k) {
        var f = (k + 1) / (n + 1), p;
        if (spaced) { f = (cum + slots[k] / 2) / b.w; cum += slots[k]; }
        if (e.side === 'l') p = [b.x, b.y + b.h * f];
        else if (e.side === 'r') p = [right(b), b.y + b.h * f];
        else if (e.side === 't') p = [b.x + b.w * f, b.y];
        else p = [b.x + b.w * f, bottom(b)];
        info[it[1]][it[2]] = p;
        if (it[2] === 'in') info[it[1]].tier = k % 2;
      });
    });

    var out = {};
    plain.forEach(function (a) {
      var i = info[a.id], so = i.sides[0], ti = i.sides[1];
      var p0 = i.out, p3 = i['in'], d0 = DIRS[so], d3 = INTO[ti];
      var tail = MAIN_IN.indexOf(ti) >= 0 ? STRIP : VTAIL;
      var tp = [p3[0] - d3[0] * tail, p3[1] - d3[1] * tail];
      var segs = [], cur = p0, cd = d0, c;
      if (i.lane) {
        var la = P(i.lane[0], i.lane[2]), lb = P(i.lane[1], i.lane[2]);
        c = sCurve(cur, cd, la, FLOWDIR);
        segs.push(['C', [c[0], c[1], la]]);
        segs.push(['L', [lb]]);
        cur = lb; cd = FLOWDIR;
      } else if (a.via) {
        var tan = major(tp[0] - p0[0], tp[1] - p0[1]);
        c = sCurve(cur, cd, a.via, tan);
        segs.push(['C', [c[0], c[1], a.via]]);
        cur = a.via; cd = tan;
      }
      c = sCurve(cur, cd, tp, d3);
      var main = [cur, c[0], c[1], tp];
      segs.push(['C', [c[0], c[1], tp]]);
      segs.push(['L', [p3]]);
      var tier = DOWN ? (i.tier || 0) : 0, lx, ly;
      if (ti === 'l' && !DOWN) { lx = p3[0] - HEAD_GAP - a.lw; ly = p3[1] - a.lh / 2; }
      else if (ti === 'r' && !DOWN) { lx = p3[0] + HEAD_GAP; ly = p3[1] - a.lh / 2; }
      else if (ti === 't' && DOWN) { lx = p3[0] - a.lw / 2; ly = p3[1] - HEAD_GAP - a.lh - tier * TIER; }
      else if (ti === 'b' && DOWN) { lx = p3[0] - a.lw / 2; ly = p3[1] + HEAD_GAP + tier * TIER; }
      else if (DOWN) { lx = (p0[0] + p3[0]) / 2 - a.lw / 2; ly = (p0[1] + p3[1]) / 2 - a.lh - 6; }
      else { lx = p3[0] + 8; ly = (p0[1] + p3[1]) / 2 - a.lh / 2; }
      var anchor = i.lane ? P(i.lane[0] + MOD_INSET, i.lane[2]) : (a.via || bezier(main, 0.5));
      out[a.id] = { d: fmtPath(p0, segs), label: [lx, ly], anchor: anchor };
    });
    mods.forEach(function (m) {
      var p0 = info[m.id].out, d0 = DIRS[info[m.id].side], an = out[m.te].anchor;
      var ax = an[0], ay = an[1], segs = [], start = p0, sd = d0, label;
      if (m.via) {   // dragged: pass through the reader's point, label there
        var tan = major(ax - p0[0], ay - p0[1]), c = sCurve(p0, d0, m.via, tan);
        segs.push(['C', [c[0], c[1], m.via]]);
        start = m.via; sd = tan;
        label = [m.via[0] - m.lw / 2, m.via[1] - m.lh / 2];
      }
      var k1 = Math.max(40, 0.5 * (sd[1] === 0 ? Math.abs(ax - start[0]) : Math.abs(ay - start[1])));
      var dp = DOWN ? ax - start[0] : ay - start[1];
      var k2 = Math.max(40, 0.5 * Math.abs(dp)), sign = dp >= 0 ? 1 : -1;
      var pts = [start, [start[0] + sd[0] * k1, start[1] + sd[1] * k1],
                 [ax - PERP[0] * sign * k2, ay - PERP[1] * sign * k2], [ax, ay]];
      segs.push(['C', pts.slice(1)]);
      if (!label) {
        var lc = bezier(pts, m.lt);
        label = [lc[0] - m.lw / 2, lc[1] - m.lh / 2];
      }
      out[m.id] = { d: fmtPath(p0, segs), ring: [ax, ay], label: label };
    });
    return out;
  }

  function memberPath(m, c) {
    if (DOWN) {
      var sx = cx(m) < cx(c) ? right(m) - 10 : m.x + 10;
      var ex = Math.min(Math.max(sx, c.x + 10), right(c) - 10);
      return 'M' + f1(sx) + ',' + f1(bottom(m)) + ' V' + f1(c.y - 14) + ' H' + f1(ex) + ' V' + f1(c.y);
    }
    var bx = Math.min(m.x, c.x) - 14;
    return 'M' + f1(m.x) + ',' + f1(cy(m)) + ' H' + f1(bx) + ' V' + f1(cy(c)) + ' H' + f1(c.x);
  }

  var routes = null;
  function draw() {
    routes = routeAll();
    Object.keys(boxes).forEach(function (id) {
      var b = boxes[id];
      b.el.setAttribute('transform', 'translate(' + f1(b.x) + ',' + f1(b.y) + ')');
    });
    arrows.forEach(function (a) {
      var r = routes[a.id];
      each(a.paths, function (p) { p.setAttribute('d', r.d); });
      a.rect.setAttribute('x', f1(r.label[0]));
      a.rect.setAttribute('y', f1(r.label[1]));
      each(a.texts, function (t, i) {
        t.setAttribute('x', f1(r.label[0] + a.textOff[i][0]));
        t.setAttribute('y', f1(r.label[1] + a.textOff[i][1]));
      });
      if (a.ring && r.ring) {
        a.ring.setAttribute('cx', f1(r.ring[0]));
        a.ring.setAttribute('cy', f1(r.ring[1]));
      }
    });
    members.forEach(function (p) {
      var c = boxes[p.getAttribute('data-c')], m = boxes[p.getAttribute('data-m')];
      if (c && m) p.setAttribute('d', memberPath(m, c));
    });
  }

  // ---------------------------------------------------------------- highlight what is related

  var hoverKey = null;   // a box id or arrow element under the pointer / keyboard focus
  var pinned = null;     // a box id whose arrows stay highlighted (click the box again to clear)
  var selected = null;   // the arrow whose card is open
  var sel = null;        // the picked box (a treatment or condition), or null

  function relatedTo(target) {
    var on = { arrows: [], nodes: {} };
    if (typeof target === 'string') {
      on.nodes[target] = true;
      arrows.forEach(function (a) {
        var t = a.te ? byId[a.te] : null;
        if (a.s === target || a.t === target || (t && (t.s === target || t.t === target))) {
          on.arrows.push(a.el);
          on.nodes[a.s] = true;
          if (a.t) on.nodes[a.t] = true;
        }
      });
    } else {
      var a = byId[target.getAttribute('data-id')];
      on.arrows.push(a.el);
      on.nodes[a.s] = true;
      if (a.t) on.nodes[a.t] = true;
      if (a.te) {
        var te = byId[a.te];
        on.arrows.push(te.el);
        on.nodes[te.s] = on.nodes[te.t] = true;
      }
    }
    return on;
  }

  function highlight() {
    var target = sel || pinned || hoverKey || selected;
    svg.classList.toggle('hl', !!target);
    each(svg.querySelectorAll('.on'), function (el) { el.classList.remove('on'); });
    Object.keys(boxes).forEach(function (id) { boxes[id].el.classList.toggle('pinned', id === pinned); });
    if (!target) return;
    var on = relatedTo(target);
    on.arrows.forEach(function (el) { el.classList.add('on'); });
    Object.keys(on.nodes).forEach(function (id) { if (boxes[id]) boxes[id].el.classList.add('on'); });
    members.forEach(function (p) {
      if (on.nodes[p.getAttribute('data-c')] && on.nodes[p.getAttribute('data-m')]) p.classList.add('on');
    });
  }

  function pointedAt(el) {
    var node = el.closest && el.closest('g.node');
    if (node) return node.getAttribute('data-id');
    return (el.closest && el.closest('a.edge, a.gap-link')) || null;
  }
  svg.addEventListener('pointerover', function (ev) {
    if (drag) return;
    hoverKey = pointedAt(ev.target);
    highlight();
  });
  svg.addEventListener('pointerleave', function () {
    if (drag) return;
    hoverKey = null;
    highlight();
  });
  svg.addEventListener('focusin', function (ev) { hoverKey = pointedAt(ev.target); highlight(); });
  svg.addEventListener('focusout', function () { hoverKey = null; highlight(); });

  // ---------------------------------------------------------------- tooltip: an arrow's full counts

  var tip = document.createElement('div');
  tip.className = 'gtip';
  tip.hidden = true;
  tip.setAttribute('aria-hidden', 'true');   // the arrow's accessible name already says all of this
  document.body.appendChild(tip);

  function fillTip(link) {
    var name = (link.getAttribute('aria-label') || '').replace(/\s*Opens (evidence|details)\.\s*$/, '');
    var cut = name.indexOf(': ');
    tip.textContent = '';
    var head = document.createElement('strong');
    head.textContent = cut > 0 ? name.slice(0, cut) : name;
    tip.appendChild(head);
    var rest = cut > 0 ? name.slice(cut + 2) : '';
    tip.appendChild(document.createTextNode(rest.charAt(0).toUpperCase() + rest.slice(1)));
    var split = link.getAttribute('data-split');
    if (split) {
      tip.appendChild(document.createElement('br'));
      tip.appendChild(document.createTextNode('Studies by direction: ' + split));
    }
  }
  function placeTip(x, y) {
    tip.hidden = false;
    var w = tip.offsetWidth, h = tip.offsetHeight;
    var left = Math.min(x + 14, window.innerWidth - w - 8), top = y + 18;
    if (top + h > window.innerHeight - 8) top = y - h - 12;
    tip.style.left = Math.max(8, left) + 'px';
    tip.style.top = Math.max(8, top) + 'px';
  }
  var tipFor = null;
  function boxTip(node) {           // a greyed box says why
    tip.textContent = node.getAttribute('data-why');
    tipFor = node;
  }
  svg.addEventListener('pointermove', function (ev) {
    var node = !drag && ev.target.closest && ev.target.closest('g.node[data-why]');
    if (node) { if (node !== tipFor) boxTip(node); placeTip(ev.clientX, ev.clientY); return; }
    var link = !drag && ev.pointerType !== 'touch' && ev.target.closest && ev.target.closest('a.edge, a.gap-link');
    if (!link) { tip.hidden = true; tipFor = null; return; }
    if (link !== tipFor) { fillTip(link); tipFor = link; }
    placeTip(ev.clientX, ev.clientY);
  });
  svg.addEventListener('pointerleave', function () { tip.hidden = true; tipFor = null; });
  svg.addEventListener('focusin', function (ev) {
    var node = ev.target.closest && ev.target.closest('g.node[data-why]');
    if (node) {
      boxTip(node);
      var nb = node.getBoundingClientRect();
      placeTip(nb.left, nb.bottom - 10);
      return;
    }
    var link = ev.target.closest && ev.target.closest('a.edge, a.gap-link');
    if (!link) return;
    fillTip(link);
    tipFor = link;
    var r = link.querySelector('.lbl rect') || link;
    var b = r.getBoundingClientRect();
    placeTip(b.left, b.bottom - 10);
  });
  svg.addEventListener('focusout', function () { tip.hidden = true; tipFor = null; });

  // ---------------------------------------------------------------- dragging boxes and arrows

  var drag = null;          // {kind: 'box'|'arrow', ...} from pointerdown until pointerup
  var suppressClick = false;
  var pending = false;
  function redraw() {
    if (pending) return;
    pending = true;
    requestAnimationFrame(function () { pending = false; draw(); });
  }
  function toSvg(ev) {
    var pt = svg.createSVGPoint();
    pt.x = ev.clientX; pt.y = ev.clientY;
    var p = pt.matrixTransform(svg.getScreenCTM().inverse());
    return [p.x, p.y];
  }
  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

  svg.addEventListener('dragstart', function (ev) { ev.preventDefault(); });   // no link drag image
  svg.addEventListener('pointerdown', function (ev) {
    if (ev.button !== 0) return;
    var p = toSvg(ev);
    var node = ev.target.closest && ev.target.closest('g.node');
    var link = !node && ev.target.closest && ev.target.closest('a.edge, a.gap-link');
    if (node) {
      var b = boxes[node.getAttribute('data-id')];
      drag = { kind: 'box', b: b, dx: p[0] - b.x, dy: p[1] - b.y, start: p, moved: false, id: ev.pointerId };
    } else if (link) {
      var a = byId[link.getAttribute('data-id')];
      // an arrow on a lane slides sideways; any other arrow bends through the pointer
      var onLane = routes && a.lane && !a.te && laneActiveNow(a);
      drag = { kind: 'arrow', a: a, start: p, moved: false, id: ev.pointerId, lane: onLane, off: a.laneOff };
    } else {
      return;
    }
    if (ev.pointerType === 'mouse') ev.preventDefault();   // no text selection / link dragging
  });
  function laneActiveNow(a) {
    var s = boxes[a.s], t = boxes[a.t];
    return laneActive(s, t, sides(s, t), a.lane);
  }
  svg.addEventListener('pointermove', function (ev) {
    if (!drag || ev.pointerId !== drag.id) return;
    var p = toSvg(ev);
    if (!drag.moved) {
      if (Math.abs(p[0] - drag.start[0]) + Math.abs(p[1] - drag.start[1]) < 5) return;
      drag.moved = true;
      var el = drag.kind === 'box' ? drag.b.el : drag.a.el;
      if (drag.kind === 'box') svg.appendChild(el);   // on top while it moves
      el.classList.add('dragging');
      if (svg.setPointerCapture) svg.setPointerCapture(ev.pointerId);
      hoverKey = drag.kind === 'box' ? drag.b.id : drag.a.el;
      highlight();
    }
    if (drag.kind === 'box') {
      var b = drag.b;
      b.x = clamp(p[0] - drag.dx, 0, VB.width - b.w);
      b.y = clamp(p[1] - drag.dy, 0, VB.height - b.h);
    } else if (drag.lane) {
      drag.a.laneOff = drag.off + (DOWN ? p[0] - drag.start[0] : p[1] - drag.start[1]);
    } else {
      drag.a.via = [clamp(p[0], 0, VB.width), clamp(p[1], 0, VB.height)];
    }
    redraw();
  });
  function endDrag(ev) {
    if (!drag || ev.pointerId !== drag.id) return;
    var d = drag;
    drag = null;
    if (d.moved) {
      (d.kind === 'box' ? d.b.el : d.a.el).classList.remove('dragging');
      suppressClick = true;              // the click that follows a drag doesn't open the panel
      setTimeout(function () { suppressClick = false; }, 0);
    } else if (d.kind === 'box' && ev.type === 'pointerup') {
      boxClick(d.b.id);
    }
  }
  svg.addEventListener('pointerup', endDrag);
  svg.addEventListener('pointercancel', endDrag);


  // ---------------------------------------------------------------- Q1 flow view (#85)
  // Pick a box (thick blue outline; its arrows go full strength). Then click a box it has an
  // arrow to, or any arrow: that arrow's findings card opens under the flow diagram. The
  // six-sided box (and "See the N claims", and the count in the blue bar) open the
  // two-treatments card. Esc closes the card; a second Esc unpicks the box.

  var figure = svg.closest('figure');
  var main = document.getElementById('main') || document.body;
  svg.classList.add('pale');
  var status = document.createElement('p');
  status.className = 'sr-only';
  status.setAttribute('role', 'status');
  figure.parentNode.insertBefore(status, figure.nextSibling);

  var slot = document.getElementById('card-slot');
  if (!slot) {                        // the graph page: cards open under the diagram too
    slot = document.createElement('div');
    slot.id = 'card-slot';
    figure.parentNode.insertBefore(slot, status.nextSibling);
  }
  slot.hidden = true;

  // ----- the findings card, laid out from the data in its section

  var LIMS = [];
  try { LIMS = JSON.parse((document.getElementById('card-lims') || {}).textContent || '[]'); } catch (e) { LIMS = []; }
  var SYMS = { increase: '↑', decrease: '↓', mixed: '⇅', no_effect: '–', unclear: '?' };
  var START_WHY = { 4: 'The best studies were experiments with an untreated control.', 3: 'The best studies were other controlled studies.',
                    2: 'The best studies only observed, with no experiment.', 1: 'The best evidence was a model or a case study.' };
  var NUMW = ['No', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine', 'Ten', 'Eleven', 'Twelve'];
  var LV = { 'very low': 1, low: 2, moderate: 3, high: 4 };
  var LW = { 1: 'Very low', 2: 'Low', 3: 'Moderate', 4: 'High' };
  var STEPS = [[/^-1 single study$/, 'Only one study.'], [/^-1 studies disagree$/, 'The studies disagree.'],
               [/^-1 most claims report no comparator$/, 'Most claims have no comparison.'],
               [/^\+1 (\d+) studies agree$/, '{0} studies agree.'],
               [/^\+1 mechanistic and difference-making evidence$/, 'It shows how it works, not just that it works.']];
  var RULE = /^start (high|moderate|low|very low) \([^)]*\)(.*?)\s*->\s*(high|moderate|low|very low)$/;

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text) e.textContent = text;
    return e;
  }
  function foundWhat(d, target) {
    var t = target.toLowerCase();
    var noun = t.indexOf('growth') >= 0 ? 'growth' : t.indexOf('survival') >= 0 ? 'survival' : '';
    if (d === 'increase') return 'found ' + (noun === 'growth' ? 'more growth' : noun ? 'higher survival' : 'an increase');
    if (d === 'decrease') return 'found ' + (noun === 'growth' ? 'less growth' : noun ? 'lower survival' : 'a decrease');
    return { mixed: 'mixed', no_effect: 'no change', unclear: 'unclear' }[d] || d;
  }
  function bars(n) { var b = el('span', 'bars b' + n); b.setAttribute('aria-hidden', 'true'); return b; }
  function fold(cls, title, body) {
    var d = el('details', 'fc-d ' + cls);
    var s = el('summary');
    s.appendChild(el('span', '', title));
    var pm = el('span', 'pm');
    pm.setAttribute('aria-hidden', 'true');
    s.appendChild(pm);
    d.appendChild(s);
    var inn = el('div', 'fc-in');
    d.appendChild(inn);
    if (body) inn.appendChild(body);
    return d;
  }
  function fig(label, nodes) {
    var f = el('div', 'fig');
    f.appendChild(el('p', 'fig-l', label));
    var v = el('p', 'fig-v');
    nodes.forEach(function (n) { if (typeof n === 'string') v.appendChild(document.createTextNode(n)); else if (n) v.appendChild(n); });
    f.appendChild(v);
    return f;
  }
  function ladder(rule) {
    var m = RULE.exec(rule.replace(/\s+/g, ' ').trim());
    if (!m) return null;
    var ol = el('ol', 'ladder');
    function row(cls, k, n, b, t) {
      var li = el('li', cls);
      li.appendChild(el('span', 'lad-k', k));
      var nn = el('span', 'lad-n', n);
      if (b) nn.appendChild(b);
      li.appendChild(nn);
      li.appendChild(el('span', 'lad-t', t));
      ol.appendChild(li);
    }
    var start = LV[m[1]], tot = start;
    row('lad-s', 'Start', String(start), bars(start), START_WHY[start]);
    var parts = m[2].split(';').map(function (p) { return p.trim(); }).filter(Boolean);
    parts.forEach(function (p) {
      var d = +((/^([+-]\d+)/.exec(p) || [0, 0])[1]);
      tot += d;
      var text = p;
      for (var i = 0; i < STEPS.length; i++) {
        var x = STEPS[i][0].exec(p);
        if (x) { text = STEPS[i][1].replace('{0}', NUMW[+x[1]] || x[1] || ''); break; }
      }
      row('lad-a', 'Adjust', (d > 0 ? '+' : d < 0 ? '\u2212' : '') + Math.abs(d), null, text);
    });
    if (!parts.length) row('lad-a', 'Adjust', '0', null, 'Nothing moves it up or down.');
    var fin = LV[m[3]];
    var why = tot > 4 && fin === 4 ? 'It can\u2019t go above 4, so it stays at the top.'
      : tot < 1 && fin === 1 ? 'It can\u2019t go below 1, so it stays at the bottom.'
      : tot !== fin ? 'A single study never goes above 3.' : 'Start plus the adjustments.';
    row('lad-r', 'Result', LW[fin], bars(fin), why);
    var wrap = el('div');
    wrap.appendChild(el('p', 'fc-lab', 'How this finding got \u201c' + LW[fin] + '\u201d'));
    wrap.appendChild(ol);
    return wrap;
  }
  // "How certainty is graded" and "Constraints of this grade", inside every Certainty calculation
  var GRADING = "<details class=\"fc-d sub\"><summary><span>How certainty is graded</span><span class=\"pm\" aria-hidden=\"true\"></span></summary><div class=\"fc-in\"><ul class=\"levels\"><li><span class=\"bars b4\" aria-hidden=\"true\"></span> High</li><li><span class=\"bars b3\" aria-hidden=\"true\"></span> Moderate</li><li><span class=\"bars b2\" aria-hidden=\"true\"></span> Low</li><li><span class=\"bars b1\" aria-hidden=\"true\"></span> Very low</li></ul><p class=\"lv-h\"><span class=\"num\" aria-hidden=\"true\">1</span> Start from the best study</p><ul class=\"pts\"><li>Experiment with an untreated control <b>4</b></li><li>Other controlled study <b>3</b></li><li>Observation only <b>2</b></li><li>Model or case study <b>1</b></li></ul><p class=\"lv-h\"><span class=\"num\" aria-hidden=\"true\">2</span> Then move up or down</p><ul class=\"pts\"><li>Only one study <b>−1</b></li><li>Studies disagree <b>−1</b></li><li>Most claims have no comparison <b>−1</b></li><li>Three or more studies agree <b>+1</b></li><li>Shows how it works <b>+1</b></li></ul><p>It always stays between 1 and 4. A single study never goes above 3.</p></div></details><details class=\"fc-d sub warn\"><summary><span>Constraints of this grade</span><span class=\"pm\" aria-hidden=\"true\"></span></summary><div class=\"fc-in\"><p>The grade can overstate how sure we are. It starts from the strongest study, not an average. One good experiment can lift a whole group of weaker studies to “High”.</p></div></details>";
  function fillGrading(slotEl) { slotEl.innerHTML = GRADING; }

  function buildCard(sec) {
    var root = sec.querySelector('.efind') || sec;
    var data = root.querySelector('.fc-figs');
    var dir = data.querySelector('.dir');
    var q = function (end) { return data.querySelector('[data-check$="/' + end + '"]'); };
    var cert = q('certainty'), studies = q('studies'), claims = q('claims');
    var target = sec.getAttribute('data-tl') || '';
    var figs = el('div', 'fc-figs');
    figs.appendChild(fig('Finding', [dir]));
    figs.appendChild(fig('Certainty', [data.querySelector('.bars'), ' ', cert]));
    var sf = fig('Studies', [studies]);
    var sub = el('p', 'fig-s');
    sub.appendChild(document.createTextNode((+studies.textContent === 1 ? 'study' : 'studies') + ' · '));
    sub.appendChild(claims);
    sub.appendChild(document.createTextNode(+claims.textContent === 1 ? ' claim' : ' claims'));
    sf.querySelector('.fig-v').appendChild(sub);
    figs.appendChild(sf);
    root.replaceChild(figs, data);

    // the split bar, each part labelled; the counts are the pack's own spans
    var split = root.querySelector('.fc-split');
    if (split) {
      var parts = Array.prototype.map.call(split.querySelectorAll('[data-d]'), function (s) {
        return [s.getAttribute('data-d'), s.querySelector('[data-check]')];
      });
      var total = parts.reduce(function (t, p) { return t + +p[1].textContent; }, 0);
      var wrap = el('div', 'split');
      var bar = el('p', 'split-bar');
      parts.forEach(function (p) {
        var seg = el('span', 'seg vote-' + p[0]);
        seg.style.flexGrow = p[1].textContent;
        var sym = el('span', '', (SYMS[p[0]] || '') + ' ');
        sym.setAttribute('aria-hidden', 'true');
        seg.appendChild(sym);
        seg.appendChild(p[1]);
        seg.appendChild(document.createTextNode(' ' + foundWhat(p[0], target)));
        bar.appendChild(seg);
      });
      var d = /dir-([a-z-]+)/.exec(dir.className)[1].replace('-', '_');
      var word = dir.textContent.replace(/^\W+\s*/, '').trim().toLowerCase();
      var mine = parts.filter(function (p) { return p[0] === d; })[0];
      var note = 'How the ' + total + ' ' + (total === 1 ? 'study' : 'studies') + ' split.';
      if (d === 'mixed') note += ' They don’t agree, so the overall answer is “studies disagree”.';
      else if (mine) {
        var n = +mine[1].textContent;
        note += ' The overall answer is “' + word + '” because ' +
          (total === 1 ? 'the one study' : n === total ? 'all ' + n : 2 * n > total ? 'most of them (' + n + ' of ' + total + ')'
            : 'the most common result (' + n + ' of ' + total + ')') + ' ' + foundWhat(d, target) + '.';
      }
      if (parts.some(function (p) { return p[0] === 'mixed'; })) {
        note += ' “Mixed” means that study’s own results pointed different ways.';
      }
      wrap.appendChild(bar);
      wrap.appendChild(el('p', 'split-note', note));
      root.replaceChild(wrap, split);
    }

    // Certainty calculation, Citations, Constraints: each closed at first
    var btns = el('div', 'fc-btns');
    var rule = root.querySelector('p.rule');
    var calc = el('div');
    var lad = ladder(rule.textContent);
    if (lad) calc.appendChild(lad);
    var rh = el('div', 'fc-rule-h', 'The data\u2019s rule, word for word: ');
    rh.appendChild(rule);
    calc.appendChild(rh);
    var gs = el('div', 'grading-slot');
    calc.appendChild(gs);
    btns.appendChild(fold('calc', 'Certainty calculation', calc));
    var src = root.querySelector('.fc-src');
    var link = src.querySelector('a.srclink');
    var cites = el('div');
    var tiles = el('div', 'tiles');
    tiles.setAttribute('aria-live', 'polite');
    cites.appendChild(tiles);
    cites.appendChild(src);
    var cd = fold('cites', 'Citations (' + claims.textContent + ')', cites);
    cd.addEventListener('toggle', function () { if (cd.open && !tiles.firstChild && link) loadTiles(link, tiles); });
    btns.appendChild(cd);
    var ul = el('ul', 'fc-lims');
    (sec.getAttribute('data-lims') || '').split(' ').forEach(function (i) {
      var l = LIMS[+i];
      if (!l) return;
      var li = el('li');
      li.appendChild(el('strong', '', l[0] + ': '));
      li.appendChild(document.createTextNode(l[1]));
      ul.appendChild(li);
    });
    var cons = el('div');
    cons.appendChild(ul);
    var more = el('p', 'fc-more');
    var a = el('a', '', 'All the constraints of this answer');
    a.href = '#overview';
    more.appendChild(a);
    cons.appendChild(more);
    btns.appendChild(fold('cons', 'Constraints', cons));
    root.appendChild(btns);
  }

  // Citations: one tile per paper, from the finding's sources page. Click a paper: its first
  // quote word for word, the rest behind "N more quotes", and the paper's DOI link.
  var cache = {};
  function loadTiles(link, box) {
    var url = link.getAttribute('href');
    box.textContent = 'Loading the citations…';
    var got = cache[url] || (cache[url] = fetch(url).then(function (r) {
      if (!r.ok) throw new Error(r.status);
      return r.text();
    }));
    got.then(function (text) {
      var doc = new DOMParser().parseFromString(text, 'text/html');
      var papers = doc.querySelectorAll('section.paper');
      if (!papers.length) throw new Error('no papers');
      box.textContent = '';
      var nq = doc.querySelectorAll('section.paper details.ev').length;
      box.appendChild(el('p', 'fc-lab', papers.length + (papers.length === 1 ? ' paper' : ' papers') + ' \u00b7 ' + nq + (nq === 1 ? ' quote' : ' quotes')));
      var list = el('ul', 'tile-list');
      each(papers, function (p, k) {
        var h = p.querySelector('h2').textContent.replace(/^Paper \d+ of \d+:\s*/, '');
        var ym = /\((\d{4})\)\s*$/.exec(h);
        var title = h.replace(/\s*\(\d{4}\)\s*$/, '').replace(/<\/?i>/g, '');
        var evs = p.querySelectorAll('details.ev');
        var li = el('li', 'tile');
        var b = el('button', 'tile-b');
        b.type = 'button';
        b.setAttribute('aria-expanded', 'false');
        b.appendChild(el('span', 'tile-y', ym ? ym[1] : 'Year not given'));
        b.appendChild(el('span', 'tile-t', title));
        b.appendChild(el('span', 'tile-n', evs.length + (evs.length === 1 ? ' quote' : ' quotes')));
        var panel = el('div', 'tile-q');
        panel.hidden = true;
        panel.id = 'tq-' + Math.random().toString(36).slice(2, 9);
        b.setAttribute('aria-controls', panel.id);
        var first = evs[0].querySelector('blockquote');
        if (first) panel.appendChild(document.importNode(first, true));
        var acts = el('div', 'tile-acts');
        if (evs.length > 1) {
          var rest = el('div');
          for (var i = 1; i < evs.length; i++) {
            var bq = evs[i].querySelector('blockquote');
            if (bq) rest.appendChild(document.importNode(bq, true));
          }
          acts.appendChild(fold('sub', (evs.length - 1) + ' more ' + (evs.length === 2 ? 'quote' : 'quotes'), rest));
        }
        var doi = p.querySelector('p.src a[href^="https://doi.org/"]');
        if (doi) {
          var go = el('a', '', 'Open the paper \u2197');
          go.href = doi.getAttribute('href');
          go.rel = 'noopener';
          acts.appendChild(go);
        }
        panel.appendChild(acts);
        b.addEventListener('click', function () {
          var open = b.getAttribute('aria-expanded') !== 'true';
          b.setAttribute('aria-expanded', String(open));
          panel.hidden = !open;
          li.classList.toggle('open', open);
        });
        li.appendChild(b);
        li.appendChild(panel);
        list.appendChild(li);
      });
      box.appendChild(list);
      link.firstChild.textContent = 'Open all the citations on their own page';
    }).catch(function () {
      delete cache[url];
      box.textContent = 'The citations could not be loaded here. Use the link below to read them.';
    });
  }

  // ----- open and close a card

  var current = null, openedFrom = null, slotHome = null, pickedRow = null;
  function openCard(sec, arrow, from, anchor) {
    if (current && current !== sec) putBack(current);
    if (!slotHome) { slotHome = document.createComment('slot'); slot.parentNode.insertBefore(slotHome, slot); }
    if (anchor) anchor.parentNode.insertBefore(slot, anchor.nextSibling);
    else slotHome.parentNode.insertBefore(slot, slotHome.nextSibling);
    if (pickedRow) pickedRow.classList.remove('picked');
    pickedRow = from && from.closest && from.closest('.brow, tr');
    if (pickedRow) pickedRow.classList.add('picked');
    current = sec;
    slot.appendChild(sec);
    slot.hidden = false;
    if (selected) selected.classList.remove('sel');
    selected = arrow || null;
    if (selected) selected.classList.add('sel');
    openedFrom = from || arrow || null;
    highlight();
    var h = sec.querySelector('h3');
    if (h) h.focus({ preventScroll: true });
    sec.scrollIntoView({ block: 'nearest' });
    return true;
  }
  function putBack(sec) { if (sec._home && sec._home.parentNode) sec._home.parentNode.insertBefore(sec, sec._home.nextSibling); }
  function closeCard() {
    if (!current) return;
    putBack(current);
    current = null;
    slot.hidden = true;
    if (pickedRow) { pickedRow.classList.remove('picked'); pickedRow = null; }
    if (selected) selected.classList.remove('sel');
    selected = null;
    highlight();
    var back = openedFrom;
    openedFrom = null;
    if (back && back.focus) back.focus();
  }
  function cardFor(id) {
    var t = id && document.getElementById(id);
    return t && t.closest('section.edge-panel');
  }
  function openArrow(a) {
    var sec = cardFor(a.getAttribute('href').slice(1));
    return sec ? openCard(sec, a, a) : false;
  }

  // ----- pick a box

  var combos = [];
  each(document.querySelectorAll('.combo-panel'), function (sec) {
    combos.push({ node: sec.getAttribute('data-node'), card: sec });
  });
  function comboNode(id) { return combos.filter(function (c) { return c.node === id; })[0] || null; }
  function arrowFrom(s, t) {
    for (var i = 0; i < arrows.length; i++) if (arrows[i].s === s && arrows[i].t === t && !arrows[i].te) return arrows[i];
    return null;
  }

  function applySel() {
    Object.keys(boxes).forEach(function (id) {
      var on = sel === id;
      boxes[id].el.classList.toggle('chosen', on);
      boxes[id].el.setAttribute('aria-pressed', String(on));
    });
    highlight();
  }
  function boxClick(id) {
    var b = boxes[id];
    var cn = comboNode(id);
    if (cn) { openCard(cn.card, null, b.el); return; }
    if (sel === id) {
      sel = null;
      status.textContent = b.name + ' unpicked.';
    } else if (sel && arrowFrom(sel, id)) {
      var a = arrowFrom(sel, id);
      openCard(cardFor(a.el.getAttribute('href').slice(1)), a.el, b.el);
      return;
    } else {
      sel = id;
      pinned = null;
      status.textContent = b.name + ' picked: its arrows are shown at full strength. Pick a box it points to, or an arrow, to read what the studies found.';
    }
    applySel();
  }

  Object.keys(boxes).forEach(function (id) {
    var e = boxes[id].el;
    e.setAttribute('tabindex', '0');
    e.setAttribute('role', 'button');
    e.setAttribute('aria-pressed', 'false');
    e.setAttribute('aria-label', boxes[id].name + (comboNode(id) ? ': opens the two-treatments card' : ''));
    e.addEventListener('keydown', function (ev) {
      if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); boxClick(id); }
    });
  });

  svg.addEventListener('click', function (ev) {
    if (suppressClick) { ev.preventDefault(); return; }
    var a = ev.target.closest && ev.target.closest('a.edge, a.gap-link');
    if (!a || ev.ctrlKey || ev.metaKey || ev.shiftKey || ev.altKey) return;
    if (openArrow(a)) ev.preventDefault();
  });

  document.addEventListener('keydown', function (ev) {
    if (ev.key !== 'Escape') return;
    if (howto && howto.open) return;          // the dialog closes itself
    if (current) closeCard();
    else if (sel) { sel = null; applySel(); status.textContent = 'Nothing picked.'; }
  });

  // links that open the two-treatments card ("See the 5 claims", the count in the blue bar)
  each(document.querySelectorAll('a[href^="#combo-"]'), function (a) {
    a.addEventListener('click', function (ev) {
      var sec = document.getElementById(a.getAttribute('href').slice(1));
      if (!sec) return;
      ev.preventDefault();
      openCard(sec, null, a);
      sec.scrollIntoView({ block: 'start' });
    });
  });

  // ----- Bars and Table views (Figma "Bars view", "Table view"), drawn from the diagram itself

  var DWORD = { increase: 'Increases', decrease: 'Decreases', mixed: 'Studies disagree', no_effect: 'No change found', unclear: 'Unclear' };
  var DSYM = { increase: '↑', decrease: '↓', mixed: '⇅', no_effect: '–', unclear: '?' };
  var CW = { high: 'High', moderate: 'Moderate', low: 'Low', very_low: 'Very low' };
  var CN = { high: 4, moderate: 3, low: 2, very_low: 1 };
  function rowsInto(t) {
    var out = [];
    arrows.forEach(function (a) {
      if (a.te || a.t !== t) return;
      var d = /\bd-(\w+)/.exec(a.el.getAttribute('class'));
      var src = boxes[a.s];
      out.push({ a: a, gap: !a.cert, dir: d ? d[1] : null, cert: a.cert, n: a.studies,
                 name: src.name + (src.kind === 'combination' ? ', used together' : '') });
    });
    return out.sort(function (p, q) { return (p.gap - q.gap) || (p.a.rank - q.a.rank) || (q.n - p.n); });
  }
  function dirSpan(d) {
    var sp = el('span', 'dir dir-' + d.replace('_', '-'));
    var sy = el('span', '', DSYM[d] + ' ');
    sy.setAttribute('aria-hidden', 'true');
    sp.appendChild(sy);
    sp.appendChild(document.createTextNode(DWORD[d] || d));
    return sp;
  }
  function openRow(r, from, anchor) {
    var sec = cardFor(r.a.el.getAttribute('href').slice(1));
    if (sec) openCard(sec, r.a.el, from, anchor);
  }
  var outcomes = Object.keys(boxes).filter(function (id) { return boxes[id].kind === 'outcome'; });
  var conds = Object.keys(boxes).filter(function (id) { return boxes[id].kind === 'condition'; });

  function barsView() {
    var v = el('section', 'q1v');
    v.id = 'view-bars';
    v.setAttribute('aria-label', 'Bars view');
    v.appendChild(el('p', 'view-note', 'Each bar is one treatment or condition. The longer the bar, the higher the certainty. Pick a bar to open its findings.'));
    var key = el('ul', 'ckey');
    [['vote-increase', '↑ Increases'], ['vote-decrease', '↓ Decreases'], ['vote-mixed', '⇅ Studies disagree'], ['k-gap', 'Not studied']].forEach(function (k) {
      var li = el('li');
      li.appendChild(el('i', k[0]));
      li.appendChild(document.createTextNode(k[1]));
      key.appendChild(li);
    });
    v.appendChild(key);
    outcomes.forEach(function (t) {
      var wrap = el('div', 'bwrap');
      wrap.appendChild(el('h3', 'ch', boxes[t].name));
      var ul = el('ul', 'bchart');
      rowsInto(t).forEach(function (r) {
        var li = el('li', 'brow' + (r.gap ? ' is-gap' : ''));
        var b = el('button');
        b.type = 'button';
        b.appendChild(el('span', 'bl', r.name));
        var track = el('span', 'bt');
        var bar = el('span', 'bb' + (r.gap ? '' : ' vote-' + r.dir), r.gap ? '? Not studied' : DSYM[r.dir] + ' ' + DWORD[r.dir]);
        if (!r.gap) bar.style.width = (CN[r.cert] * 20.5) + '%';
        track.appendChild(bar);
        if (!r.gap) {
          track.appendChild(el('span', 'bn', r.n + (r.n === 1 ? ' study' : ' studies')));
          var cs = el('span', 'sr-only', ', ' + CW[r.cert] + ' certainty');
          track.appendChild(cs);
        }
        b.appendChild(track);
        b.addEventListener('click', function () { openRow(r, li, wrap); });
        li.appendChild(b);
        ul.appendChild(li);
      });
      wrap.appendChild(ul);
      var ax = el('div', 'brow bax');
      ax.setAttribute('aria-hidden', 'true');
      ax.appendChild(el('span', 'bl'));
      var sc = el('span', 'bax-s');
      ['1 Very low', '2 Low', '3 Moderate', '4 High'].forEach(function (w) { sc.appendChild(el('b', '', w)); });
      sc.appendChild(el('small', '', 'CERTAINTY \u2192'));
      ax.appendChild(sc);
      wrap.appendChild(ax);
      v.appendChild(wrap);
    });
    return v;
  }

  function oneTable(t, firstCol) {
    var wrap = el('div', 'vtable');
    var tb = el('table');
    tb.appendChild(el('caption', '', 'Affects on ' + boxes[t].name.charAt(0).toLowerCase() + boxes[t].name.slice(1)));
    var thead = el('thead');
    var hr = el('tr');
    [firstCol, 'Findings', 'Certainty', '# of studies'].forEach(function (h) { var th = el('th', '', h); th.scope = 'col'; hr.appendChild(th); });
    thead.appendChild(hr);
    tb.appendChild(thead);
    var body = el('tbody');
    rowsInto(t).forEach(function (r) {
      var tr = el('tr', r.gap ? 'is-gap' : '');
      var th = el('th');
      th.scope = 'row';
      var a = el('a', '', r.name);
      a.href = r.a.el.getAttribute('href');
      th.appendChild(a);
      tr.appendChild(th);
      var td1 = el('td');
      if (r.gap) td1.textContent = '? Not studied'; else td1.appendChild(dirSpan(r.dir));
      tr.appendChild(td1);
      var td2 = el('td');
      if (r.gap) td2.textContent = '—';
      else { td2.appendChild(bars(CN[r.cert])); td2.appendChild(document.createTextNode(' ' + CW[r.cert])); }
      tr.appendChild(td2);
      tr.appendChild(el('td', '', String(r.gap ? 0 : r.n)));
      var go = function (ev) { ev.preventDefault(); openRow(r, tr, wrap); };
      a.addEventListener('click', go);
      tr.addEventListener('click', function (ev) { if (ev.target !== a) go(ev); });
      body.appendChild(tr);
    });
    tb.appendChild(body);
    wrap.appendChild(tb);
    return wrap;
  }
  function tableView2() {
    var v = el('section', 'q1v');
    v.id = 'view-table';
    v.setAttribute('aria-label', 'Table view');
    v.appendChild(el('p', 'view-note', 'Every arrow on the flow diagram as a row, with the same numbers. Pick a row to open what the studies found.'));
    outcomes.forEach(function (t, i) { v.appendChild(oneTable(t, i ? 'Treatment or condition' : 'Treatment or condition')); });
    if (conds.length) {
      var inner = el('div');
      conds.forEach(function (t) { inner.appendChild(oneTable(t, 'Treatment or condition')); });
      var f = fold('vmore', 'What the treatments change: ' + conds.length + ' more tables', inner);
      v.appendChild(f);
    }
    return v;
  }

  // ----- toolbar: Flow / Bars / Table, and How to read the flow diagram

  var bar = document.querySelector('.flow-bar');
  var tableView = document.querySelector('section.gtable');
  var together = document.querySelectorAll('.together');
  if (bar) {
    bar.hidden = false;
    var vBars = barsView(), vTable = tableView2();
    figure.parentNode.insertBefore(vBars, figure);
    figure.parentNode.insertBefore(vTable, figure);
    if (tableView) tableView.hidden = true;     // the plain table stays in the page for no-script readers
    var setView = function (v) {
      figure.hidden = v !== 'flow';
      each(together, function (t) { t.hidden = v !== 'flow'; });
      vBars.hidden = v !== 'bars';
      vTable.hidden = v !== 'table';
      if (current && slotHome) slotHome.parentNode.insertBefore(slot, slotHome.nextSibling);   // the open card stays open
      each(bar.querySelectorAll('[data-view]'), function (b) { b.setAttribute('aria-pressed', String(b.getAttribute('data-view') === v)); });
    };
    each(bar.querySelectorAll('[data-view]'), function (b) {
      b.addEventListener('click', function () { setView(b.getAttribute('data-view')); });
    });
    setView(location.hash === '#table' ? 'table' : 'flow');
  }
  var howto = document.getElementById('howto');
  var howBtn = document.querySelector('.howto-btn');
  if (howto && howBtn && howto.showModal) {
    howBtn.addEventListener('click', function () { howto.showModal(); });
    howto.querySelector('[data-close]').addEventListener('click', function () { howto.close(); });
    howto.addEventListener('close', function () { howBtn.focus(); });
    howto.addEventListener('click', function (ev) { if (ev.target === howto) howto.close(); });   // click outside
  } else if (howBtn) {
    howBtn.hidden = true;
  }

  // every card remembers where it lives, so it can go back there when another one opens
  function initCards() {
  each(document.querySelectorAll('section.edge-panel'), function (sec) {
    sec._home = document.createComment('card');
    sec.parentNode.insertBefore(sec._home, sec);
    var head = document.createElement('div');
    head.className = 'fc-head';
    var kick = sec.querySelector('.fc-kicker');
    if (!kick) {
      kick = document.createElement('p');
      kick.className = 'fc-kicker';
      kick.textContent = sec.classList.contains('gap-panel') ? 'Not studied' : 'Findings';
    }
    head.appendChild(kick);
    var x = document.createElement('button');
    x.type = 'button';
    x.className = 'x';
    x.innerHTML = '✕<span class="sr-only"> Close this card</span>';
    x.addEventListener('click', closeCard);
    head.appendChild(x);
    sec.insertBefore(head, sec.firstChild);
    var h3 = sec.querySelector('h3');
    if (h3) h3.setAttribute('tabindex', '-1');
    each(sec.querySelectorAll('.back-graph'), function (el) { el.parentNode.removeChild(el); });
    if (sec.querySelector('.fc-figs')) buildCard(sec);
    each(sec.querySelectorAll('.grading-slot'), fillGrading);
  });
  var store = document.getElementById('cards');
  if (store) store.hidden = true;
  }

  initCards();
  routes = routeAll();

  // Arriving at an arrow (#e-...), a finding inside one (#f-..., e.g. from the short answer)
  // or the two-treatments card (#combo-...): open it under the flow diagram.
  function openFromHash() {
    var h = location.hash && decodeURIComponent(location.hash.slice(1));
    var sec = h && cardFor(h);
    if (!sec) return;
    var start = svg.querySelector('a[href="#' + sec.id + '"]');
    var node = sec.getAttribute('data-node');
    openCard(sec, start, start || (node && boxes[node] && boxes[node].el));
  }
  openFromHash();
  window.addEventListener('hashchange', openFromHash);
}());
