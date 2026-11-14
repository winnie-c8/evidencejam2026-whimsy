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
    var r = el.querySelector('rect');
    var kind = /\bk-(\w+)/.exec(el.getAttribute('class'));
    var b = { el: el, id: el.getAttribute('data-id'), x: +m[1], y: +m[2], kind: kind ? kind[1] : '',
              w: +r.getAttribute('width'), h: +r.getAttribute('height'),
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
      e.list.forEach(function (it, k) {
        var f = (k + 1) / (n + 1), p;
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
  var selected = null;   // the arrow whose evidence is open in the panel

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
    var target = pinned || hoverKey || selected;
    svg.classList.toggle('hl', !!target);
    each(svg.querySelectorAll('.on'), function (el) { el.classList.remove('on'); });
    Object.keys(boxes).forEach(function (id) { boxes[id].el.classList.toggle('pinned', id === pinned); });
    if (!target) return;
    var on = relatedTo(target);
    on.arrows.forEach(function (el) { el.classList.add('on'); });
    Object.keys(on.nodes).forEach(function (id) { if (boxes[id]) boxes[id].el.classList.add('on'); });
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
      pinned = pinned === d.b.id ? null : d.b.id;   // a click on a box pins / unpins its arrows
      highlight();
      updateState();
    }
  }
  svg.addEventListener('pointerup', endDrag);
  svg.addEventListener('pointercancel', endDrag);

  // ---------------------------------------------------------------- tools above the graph

  var figure = svg.closest('figure');
  var caption = figure.querySelector('figcaption');
  var stateLine = document.createElement('span');
  stateLine.className = 'fig-state';
  stateLine.setAttribute('role', 'status');
  caption.appendChild(document.createTextNode(' '));
  caption.appendChild(stateLine);

  var tools = document.createElement('div');
  tools.className = 'graph-tools';
  tools.innerHTML =
    '<p>Drag a box or an arrow to move it; arrows stay attached. Click a box to keep its arrows ' +
    'highlighted (click it again to clear). Select an arrow to read its evidence in a side panel.</p>' +
    '<div class="tool-row"><span id="show-label">Show only:</span>' +
    '<div class="seg" role="group" aria-labelledby="show-label">' +
    '<button type="button" data-show="all" aria-pressed="true">All certainties</button>' +
    '<button type="button" data-show="high" aria-pressed="false">High certainty</button>' +
    '<button type="button" data-show="moderate" aria-pressed="false">Moderate certainty</button>' +
    '<button type="button" data-show="low" aria-pressed="false">Low or very low certainty</button></div></div>' +
    '<div class="tool-row">' +
    '<button type="button" class="direct" aria-pressed="false">Direct effects only</button>' +
    '<button type="button" class="sort" aria-pressed="false">Sort by certainty</button>' +
    '<button type="button" class="reset">Reset layout</button></div>';
  figure.parentNode.insertBefore(tools, figure);

  var certFilter = 'all';
  var directOnly = false;
  var SHOW = { high: ['high'], moderate: ['moderate'], low: ['low', 'very_low'] };
  var SHOW_WORDS = { high: 'high-certainty', moderate: 'moderate-certainty', low: 'low- or very-low-certainty' };

  function isCondition(id) { return boxes[id] && boxes[id].kind === 'condition'; }

  // Hide arrows the filters leave out. Every box stays. A moderation arrow that is shown keeps
  // the arrow it changes visible (faded), so it never points at nothing.
  function applyFilters() {
    var keep = SHOW[certFilter];
    var shown = 0;
    arrows.forEach(function (a) {
      var certOk = !keep || (a.cert !== null && keep.indexOf(a.cert) >= 0);
      var directOk = !directOnly || (!isCondition(a.s) && !(a.t && isCondition(a.t)));
      var on = certOk && directOk;
      a.el.classList.toggle('filtered', !on);
      a.el.classList.remove('context');
      if (on) shown++;
    });
    arrows.forEach(function (a) {
      if (a.te && !a.el.classList.contains('filtered') && byId[a.te].el.classList.contains('filtered')) {
        byId[a.te].el.classList.remove('filtered');
        byId[a.te].el.classList.add('context');
      }
    });
    return shown;
  }

  // The caption says what the graph is showing right now.
  function updateState() {
    var shown = applyFilters();
    var parts = [];
    if (certFilter !== 'all' || directOnly) {
      parts.push(shown + ' of ' + arrows.length + ' arrows: ' +
        (directOnly ? 'direct treatment → outcome' : '') +
        (directOnly && certFilter !== 'all' ? ', ' : '') +
        (certFilter !== 'all' ? SHOW_WORDS[certFilter] : '') + ' only; every box stays');
    } else {
      parts.push('all ' + arrows.length + ' arrows');
    }
    if (sortByCertainty) {
      parts.push('sorted by certainty (most certain ' + (DOWN ? 'on the left' : 'at the top') + ' of each box)');
    }
    if (pinned) parts.push('highlighting the arrows of “' + boxes[pinned].name + '” (click the box again to clear)');
    stateLine.textContent = 'Now showing: ' + parts.join('; ') + '.';
  }

  each(tools.querySelectorAll('[data-show]'), function (btn) {
    btn.addEventListener('click', function () {
      certFilter = btn.getAttribute('data-show');
      each(tools.querySelectorAll('[data-show]'), function (b) { b.setAttribute('aria-pressed', String(b === btn)); });
      updateState();
    });
  });
  var directBtn = tools.querySelector('.direct');
  directBtn.addEventListener('click', function () {
    directOnly = !directOnly;
    directBtn.setAttribute('aria-pressed', String(directOnly));
    updateState();
  });
  var sortBtn = tools.querySelector('.sort');
  sortBtn.addEventListener('click', function () {
    sortByCertainty = !sortByCertainty;
    sortBtn.setAttribute('aria-pressed', String(sortByCertainty));
    draw();
    updateState();
  });
  tools.querySelector('.reset').addEventListener('click', function () {
    Object.keys(boxes).forEach(function (id) { boxes[id].x = boxes[id].homeX; boxes[id].y = boxes[id].homeY; });
    arrows.forEach(function (a) { a.via = null; a.laneOff = 0; });
    draw();
  });

  // a click on empty space clears a pinned box
  svg.addEventListener('click', function (ev) {
    if (suppressClick) { ev.preventDefault(); return; }
    var a = ev.target.closest && ev.target.closest('a.edge, a.gap-link');
    if (a) {
      if (ev.ctrlKey || ev.metaKey || ev.shiftKey || ev.altKey) return;
      if (openPanel(a)) ev.preventDefault();
      return;
    }
    if (!(ev.target.closest && ev.target.closest('g.node')) && pinned) {
      pinned = null;
      highlight();
      updateState();
    }
  });

  // ---------------------------------------------------------------- side panel

  var main = document.getElementById('main') || document.body;
  var panel = document.createElement('aside');
  panel.className = 'drawer';
  panel.hidden = true;
  panel.setAttribute('role', 'dialog');
  panel.setAttribute('aria-modal', 'false');
  panel.setAttribute('aria-labelledby', 'drawer-title');
  panel.innerHTML = '<div class="drawer-head"><h2 id="drawer-title" tabindex="-1"></h2>' +
    '<button type="button" class="drawer-close">Close<span class="sr-only"> evidence panel</span></button></div>' +
    '<div class="drawer-body"></div>';
  main.appendChild(panel);
  var panelTitle = panel.querySelector('h2');
  var panelBody = panel.querySelector('.drawer-body');
  var cache = {};

  function stripIds(root) {
    each(root.querySelectorAll('[id]'), function (el) { el.removeAttribute('id'); });
    if (root.removeAttribute) root.removeAttribute('id');
  }

  // A bar of how the studies split by direction (the pack's own counts, in the words below it).
  var VOTE = { increase: ['↑', 'Increase'], decrease: ['↓', 'Decrease'], mixed: ['⇅', 'Mixed'],
               no_effect: ['–', 'No effect'], unclear: ['?', 'Unclear'] };
  function voteBar(root) {
    var parts = [];
    each(root.querySelectorAll('[data-check*="/study_directions/"]'), function (el) {
      var dir = el.getAttribute('data-check').split('/').pop();
      var n = +el.textContent;
      if (n > 0 && VOTE[dir]) parts.push([dir, n]);
    });
    if (!parts.length) return null;
    var total = parts.reduce(function (s, p) { return s + p[1]; }, 0);
    var wrap = document.createElement('div');
    wrap.className = 'votes-wrap';
    var h = document.createElement('p');
    h.className = 'votes-head';
    h.textContent = 'How the ' + total + ' ' + (total === 1 ? 'study splits' : 'studies split') + ' by direction:';
    var bar = document.createElement('div');
    bar.className = 'votebar';
    bar.setAttribute('aria-hidden', 'true');   // the same counts are written out just below
    parts.forEach(function (p) {
      var seg = document.createElement('span');
      seg.className = 'vote-' + p[0];
      seg.style.flexGrow = p[1];
      seg.textContent = VOTE[p[0]][0] + ' ' + p[1];
      bar.appendChild(seg);
    });
    wrap.appendChild(h);
    wrap.appendChild(bar);
    return wrap;
  }

  function loadSources(link, slot) {
    var url = link.getAttribute('href');
    var got = cache[url] || (cache[url] = fetch(url).then(function (r) {
      if (!r.ok) throw new Error(r.status);
      return r.text();
    }));
    got.then(function (text) {
      var doc = new DOMParser().parseFromString(text, 'text/html');
      var src = doc.querySelector('.sources');
      if (!src) throw new Error('no sources');
      var n = src.querySelectorAll('details.ev').length;
      stripIds(src);
      slot.innerHTML = '';
      var h = document.createElement('h3');
      h.textContent = n === 1 ? 'The quoted source' : 'The ' + n + ' quoted sources';
      slot.appendChild(h);
      var note = doc.querySelector('.note');
      if (note) slot.appendChild(document.importNode(note, true));
      slot.appendChild(document.importNode(src, true));
      link.firstChild.textContent = 'Open these sources on their own page';
    }).catch(function () {
      delete cache[url];
      slot.textContent = 'The sources could not be loaded here. Use the link above to read them.';
    });
  }

  function openPanel(a) {
    var sec = document.getElementById(a.getAttribute('href').slice(1));
    if (!sec) return false;
    var clone = sec.cloneNode(true);
    var h3 = clone.querySelector('h3');
    panelTitle.textContent = h3 ? h3.textContent : '';
    if (h3) h3.parentNode.removeChild(h3);
    each(clone.querySelectorAll('.back-graph'), function (el) { el.parentNode.removeChild(el); });
    each(clone.querySelectorAll('details.cert'), function (d) { d.open = true; });
    stripIds(clone);
    var votes = clone.querySelector('.votes');
    var bar = voteBar(clone);
    if (votes && bar) votes.parentNode.parentNode.insertBefore(bar, votes.parentNode);
    panelBody.innerHTML = '';
    while (clone.firstChild) panelBody.appendChild(clone.firstChild);
    var link = panelBody.querySelector('a.srclink');
    if (link) {
      var slot = document.createElement('div');
      slot.className = 'drawer-sources';
      slot.setAttribute('aria-live', 'polite');
      slot.textContent = 'Loading the quoted sources…';
      panelBody.appendChild(slot);
      loadSources(link, slot);
    }
    if (selected) selected.classList.remove('sel');
    selected = a;
    a.classList.add('sel');
    panel.hidden = false;
    panel.scrollTop = 0;
    document.documentElement.classList.add('drawer-open');
    panelTitle.focus();
    highlight();
    return true;
  }

  function closePanel() {
    if (panel.hidden) return;
    panel.hidden = true;
    document.documentElement.classList.remove('drawer-open');
    var back = selected;
    if (selected) selected.classList.remove('sel');
    selected = null;
    highlight();
    if (back) back.focus();
  }

  panel.querySelector('.drawer-close').addEventListener('click', closePanel);
  document.addEventListener('keydown', function (ev) {
    if (ev.key === 'Escape' && !panel.hidden) closePanel();
  });

  routes = routeAll();
  updateState();

  // Arriving from "On the graph" (q1-graph.html#e-...): show that arrow in the panel.
  if (/^#e-/.test(location.hash)) {
    var start = svg.querySelector('a[href="' + location.hash.replace(/"/g, '') + '"]');
    if (start) {
      figure.scrollIntoView();
      openPanel(start);
    }
  }
}());
