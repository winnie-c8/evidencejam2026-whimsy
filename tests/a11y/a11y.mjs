// Browser checks for the built site, run in CI (not part of build.sh).
//
//   cd tests/a11y && npm ci && npx playwright install chromium
//   node a11y.mjs ../../site            # or PW_CHANNEL=chrome to use your installed Chrome
//
// For every page in site/:
//   1. axe-core (WCAG 2.1 A + AA rules): 0 violations. Judges run axe-core and Lighthouse.
//   2. Phone width (375 px): the page must not scroll sideways (wide tables may scroll
//      inside their own container).
// On the graph page, every arrow must be keyboard-focusable.
// Exit 0 = PASS, 1 = problems found.

import { spawn } from 'node:child_process';
import { readdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { chromium } from 'playwright';
import AxeBuilder from '@axe-core/playwright';

const site = resolve(process.argv[2] || '../../site');
const port = 8000 + Math.floor(Math.random() * 1000);
const base = `http://127.0.0.1:${port}`;
const pages = readdirSync(site).filter((f) => f.endsWith('.html')).sort();
const problems = [];

const server = spawn('python3', ['-m', 'http.server', String(port), '--bind', '127.0.0.1', '-d', site], { stdio: 'ignore' });
const stop = () => server.kill();

async function waitForServer() {
  for (let i = 0; i < 50; i++) {
    try { if ((await fetch(base + '/index.html')).ok) return; } catch { /* not up yet */ }
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
