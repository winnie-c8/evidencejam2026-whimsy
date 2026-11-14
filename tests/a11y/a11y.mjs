// Browser checks for the built site, run in CI (not part of build.sh).
//
//   cd tests/a11y && npm ci && npx playwright install chromium
//   node a11y.mjs ../../site            # or PW_CHANNEL=chrome to use your installed Chrome
//
// For every page in site/:
//   1. axe-core (WCAG 2.1 A + AA rules): 0 violations. Judges run axe-core and Lighthouse.
//   2. Phone width (375 px): the page must not scroll sideways (wide tables may scroll
//      inside their own container).
// Keyboard: on every answer page (and one source page), Tab reaches every visible control,
//   starting with the skip link, and each one shows a visible focus outline.
// On the graph page, every arrow must be keyboard-focusable.
// Exit 0 = PASS, 1 = problems found.

import { spawn } from 'node:child_process';
import { readdirSync, readFileSync } from 'node:fs';
import { createServer } from 'node:net';
import { join, relative, resolve, sep } from 'node:path';
import { chromium } from 'playwright';
import AxeBuilder from '@axe-core/playwright';

const site = resolve(process.argv[2] || '../../site');
const problems = [];

// Every .html under site/, including subfolders.
function htmlFiles(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((d) => {
    const p = join(dir, d.name);
    if (d.isDirectory()) return htmlFiles(p);
    return d.name.endsWith('.html') ? [relative(site, p).split(sep).join('/')] : [];
  });
}
const pages = htmlFiles(site).sort();

// Ask the OS for a free port, so we never test some other server that happens to be running.
const port = await new Promise((res, rej) => {
  const s = createServer();
  s.once('error', rej);
  s.listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => res(p)); });
});
const base = `http://127.0.0.1:${port}`;

const server = spawn('python3', ['-m', 'http.server', String(port), '--bind', '127.0.0.1', '-d', site], { stdio: 'ignore' });
const stop = () => server.kill();

async function waitForServer() {
  // Up AND serving this site: the served index.html must be byte-identical to ours.
  const expected = readFileSync(join(site, 'index.html'), 'utf8');
  for (let i = 0; i < 50; i++) {
    try {
      const r = await fetch(base + '/index.html');
      if (r.ok) {
        if ((await r.text()) === expected) return;
        throw new Error(`port ${port} is serving a different site`);
      }
    } catch (e) { if (String(e.message).includes('different site')) throw e; }
    await new Promise((r) => setTimeout(r, 100));
  }
  throw new Error('http.server did not start');
}

try {
  await waitForServer();
  const browser = await chromium.launch(process.env.PW_CHANNEL ? { channel: process.env.PW_CHANNEL } : {});

  const desktop = await (await browser.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
  for (const p of pages) {
    await desktop.goto(`${base}/${p}`);
    const res = await new AxeBuilder({ page: desktop })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
      .analyze();
    for (const v of res.violations) {
      const where = v.nodes.slice(0, 3).map((n) => n.target.join(' ')).join(', ');
      problems.push(`${p}: axe ${v.id} (${v.impact}) x${v.nodes.length}: ${v.help}. e.g. ${where}`);
    }
    console.log(`[a11y] ${p}: axe ${res.violations.length} violation types, ${res.passes.length} rules passed`);
  }

  const phone = await (await browser.newContext({ viewport: { width: 375, height: 800 } })).newPage();
  // Twice per page: with the machine's default fonts, and with a wide font forced,
  // because Linux's default fonts are wider than macOS's (a page that fits on a Mac
  // can still scroll sideways on the judges' Linux machine).
  const WIDE = '*{font-family:Verdana,"DejaVu Sans",sans-serif !important}';
  for (const p of pages) {
    for (const wide of [false, true]) {
      await phone.goto(`${base}/${p}`);
      if (wide) await phone.addStyleTag({ content: WIDE });
      const w = await phone.evaluate(() => document.documentElement.scrollWidth);
      if (w > 376) problems.push(`${p}: scrolls sideways at 375 px wide${wide ? ' with a wide font' : ''} (page is ${w} px)`);
    }
  }

  // Keyboard only, on the answer pages: press Tab through the whole page. Every stop must
  // show a visible focus outline, the skip link must come first, and Tab must reach the end
  // of the page (no keyboard trap). Source pages share the same template, so one is enough.
  const kbPages = pages.filter((p) => !p.startsWith('sources-')).concat(pages.filter((p) => p.startsWith('sources-')).slice(0, 1));
  for (const p of kbPages) {
    await desktop.goto(`${base}/${p}`);
    // Controls on screen now (a link inside a closed <details> is only reachable once it is opened).
    const total = await desktop.evaluate(() => [...document.querySelectorAll(
      'a[href], summary, button, input, select, textarea, [tabindex]:not([tabindex="-1"])')]
      .filter((e) => e.checkVisibility()).length);
    const seen = new Set();
    let first = null, noOutline = [], steps = 0;
    for (; steps < total + 5; steps++) {
      await desktop.keyboard.press('Tab');
      const s = await desktop.evaluate(() => {
        const el = document.activeElement;
        if (!el || el === document.body) return null;
        const cs = getComputedStyle(el);
        const visible = (cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0) || cs.boxShadow !== 'none';
        // A unique tag per element, so two controls with the same text are not taken for one.
        if (!el.dataset.kbStop) el.dataset.kbStop = String((window.__kbStops = (window.__kbStops || 0) + 1));
        const key = el.dataset.kbStop;
        return { key, visible, text: (el.textContent || el.getAttribute('aria-label') || '').trim().slice(0, 50) };
      });
      if (!s) break;                      // focus left the page: Tab reached the end
      if (seen.has(s.key)) break;         // wrapped round
      seen.add(s.key);
      if (first === null) first = s.text;
      if (!s.visible) noOutline.push(s.text);
    }
    if (first !== 'Skip to content') problems.push(`${p}: first Tab stop is "${first}", not the skip link`);
    // Every link and summary on the page must be a Tab stop (none skipped, no trap before the end).
    if (seen.size < total) problems.push(`${p}: Tab reached only ${seen.size} of ${total} controls`);
    for (const t of noOutline.slice(0, 5)) problems.push(`${p}: no visible focus outline on "${t}"`);
    console.log(`[a11y] ${p}: keyboard ${seen.size} Tab stops, ${noOutline.length} without a visible outline`);
  }

  if (pages.includes('q1-graph.html')) {
    await desktop.goto(`${base}/q1-graph.html`);
    const unfocusable = await desktop.evaluate(() => {
      const bad = [];
      for (const a of document.querySelectorAll('svg a.edge, svg a.gap-link')) {
        a.focus();
        if (document.activeElement !== a) bad.push(a.id);
      }
      return { total: document.querySelectorAll('svg a.edge, svg a.gap-link').length, bad };
    });
    if (unfocusable.total === 0) problems.push('q1-graph.html: no graph arrows found to focus');
    for (const id of unfocusable.bad) problems.push(`q1-graph.html: arrow #${id} cannot get keyboard focus`);
  }

  await browser.close();
} catch (e) {
  problems.push(`a11y check crashed: ${e.message}`);
} finally {
  stop();
}

for (const p of problems) console.log(`[a11y] FAIL ${p}`);
console.log(problems.length ? `[a11y] FAIL: ${problems.length} problems` : `[a11y] PASS: ${pages.length} pages`);
process.exit(problems.length ? 1 : 0);
