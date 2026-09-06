/* ============================================================================
 * FantasyStakes — /launch publish verification
 *
 * Runs against the SAME server the preview checker uses, which applies the real
 * `site/_headers` — the Content-Security-Policy included. That is the whole
 * point: the memo arrived as a self-contained file with an inline style block
 * and inline style attributes, both of which `style-src 'self'` refuses. If the
 * extraction were wrong the page would render unstyled and the CSP violation
 * would arrive on Log.entryAdded, which is captured below.
 *
 * Run:  node tools/marketing/launch_check.mjs
 * ========================================================================== */

import { withBrowser, goto, evaluate } from './chrome.mjs';

const APP = 'https://app.fantasystakesapp.com';

const VIEWPORTS = [
  { width: 375, height: 812, mobile: true, label: '375 iPhone SE' },
  { width: 390, height: 844, mobile: true, label: '390 iPhone 14' },
  { width: 430, height: 932, mobile: true, label: '430 iPhone Pro Max' },
  { width: 768, height: 1024, mobile: true, label: '768 tablet' },
  { width: 1440, height: 900, mobile: false, label: '1440 desktop' },
];

let failures = 0;
const check = (ok, label, detail = '') => {
  if (!ok) failures += 1;
  console.log('  [' + (ok ? 'PASS' : 'FAIL') + '] ' + label + (detail ? ' — ' + detail : ''));
};
const section = (t) => { console.log('\n' + t); console.log('-'.repeat(t.length)); };

await withBrowser(async ({ cdp, origin }) => {
  const problems = [];
  cdp.on((m) => {
    if (m.method === 'Runtime.exceptionThrown') {
      problems.push('exception: ' + m.params.exceptionDetails.text);
    }
    if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') {
      problems.push('console.error: ' + m.params.args.map((a) => a.value).join(' '));
    }
    if (m.method === 'Log.entryAdded' && m.params.entry.level === 'error') {
      problems.push(m.params.entry.source + ': ' + m.params.entry.text
        + ' <' + (m.params.entry.url || 'no url') + '>');
    }
  });

  section('Serving and status');
  const res = await fetch(origin + '/launch');
  check(res.status === 200, '/launch returns HTTP 200', 'HTTP ' + res.status);
  const css = await fetch(origin + '/styles/launch.css');
  check(css.status === 200, '/styles/launch.css returns HTTP 200', 'HTTP ' + css.status);
  check((css.headers.get('content-type') || '').includes('text/css'),
    'stylesheet is served as text/css', css.headers.get('content-type') || 'none');

  await cdp.send('Emulation.setDeviceMetricsOverride',
    { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
  await goto(cdp, origin + '/launch', 700);

  section('The stylesheet actually applied (CSP proof)');
  /* Reading a COMPUTED colour is the real proof. If the CSP had refused the
     stylesheet the body would fall back to the UA default white, and every
     assertion below would fail rather than quietly passing on markup alone. */
  const bg = await evaluate(cdp,
    'return getComputedStyle(document.body).backgroundColor;');
  const ink = await evaluate(cdp, 'return getComputedStyle(document.body).color;');
  check(!/rgba\(0, 0, 0, 0\)|rgb\(255, 255, 255\)/.test(bg),
    'body background comes from launch.css', bg);
  check(ink === 'rgb(246, 242, 232)', 'body ink is the locked --ink', ink);
  const heroBorder = await evaluate(cdp,
    'return getComputedStyle(document.querySelector(".hero")).borderBottomColor;');
  check(heroBorder === 'rgb(39, 56, 78)', 'hero rule is the locked --line', heroBorder);
  const ctaBg = await evaluate(cdp,
    'return getComputedStyle(document.querySelector(".cta")).backgroundColor;');
  check(ctaBg === 'rgb(216, 174, 88)', 'CTA is the locked gold', ctaBg);

  section('The extracted inline styles reproduce exactly');
  const divider = await evaluate(cdp,
    'const d = document.querySelector(".league-econ-divider");'
    + 'const s = getComputedStyle(d);'
    + 'return [s.borderTopStyle, s.borderTopWidth, s.borderTopColor, s.marginTop, s.marginBottom].join(" | ");');
  check(divider === 'dotted | 1px | rgba(255, 255, 255, 0.35) | 14px | 14px',
    'league divider matches the inline rule it replaced', divider);
  /* AT A NARROW WIDTH AUTO MARGINS RESOLVE TO 0px, because there is no free
     space to distribute - so a mobile viewport cannot tell a working
     `margin:auto` from a missing one. Measured at 1440, where the 820px lead
     sits in a 1040px wrap and real centring has to produce 110px a side. */
  await cdp.send('Emulation.setDeviceMetricsOverride',
    { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  await goto(cdp, origin + '/launch', 500);
  const centered = await evaluate(cdp,
    'const e = document.querySelector(".lead-centered");'
    + 'const s = getComputedStyle(e);'
    + 'return s.marginLeft + " | " + s.marginRight;');
  check(centered === '110px | 110px', 'centered lead still auto-centres', centered);
  await cdp.send('Emulation.setDeviceMetricsOverride',
    { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
  await goto(cdp, origin + '/launch', 500);
  const fb = await evaluate(cdp,
    'return getComputedStyle(document.querySelector(".feedback-note")).marginTop;');
  check(fb === '12px', 'feedback note keeps its 12px offset', fb);

  section('Locked content survived');
  const counts = await evaluate(cdp,
    'return JSON.stringify({'
    + 'cta: document.querySelectorAll("a.cta").length,'
    + 'cards: document.querySelectorAll(".card").length,'
    + 'steps: document.querySelectorAll(".step").length,'
    + 'econ: document.querySelectorAll(".econ-row").length,'
    + 'inline: document.querySelectorAll("[style]").length,'
    + 'title: document.title });');
  const c = JSON.parse(counts);
  check(c.cta === 2, 'two game-entry CTAs present', String(c.cta));
  check(c.steps === 5, 'five how-you-play steps', String(c.steps));
  check(c.econ === 6, 'six economy rows', String(c.econ));
  check(c.inline === 0, 'no inline style attributes remain', String(c.inline));
  check(c.title.startsWith('FantasyStakes'), 'locked title', c.title);

  section('CTA destinations');
  const hrefs = JSON.parse(await evaluate(cdp,
    'return JSON.stringify([...document.querySelectorAll("a.cta")].map(a => a.href));'));
  hrefs.forEach((h, i) => check(h === APP || h === APP + '/',
    'CTA ' + (i + 1) + ' points at the game application', h));
  const allHrefs = JSON.parse(await evaluate(cdp,
    'return JSON.stringify([...document.querySelectorAll("[href],[src]")]'
    + '.map(e => e.getAttribute("href") || e.getAttribute("src")));'));
  const bad = allHrefs.filter((h) => /sandbox:|localhost|127\.0\.0\.1|railway|file:|staging|:8080/i.test(h || ''));
  check(bad.length === 0, 'no sandbox, local, staging or Railway URLs', bad.join(', ') || 'none');

  section('Mobile rendering — no horizontal overflow');
  for (const v of VIEWPORTS) {
    await cdp.send('Emulation.setDeviceMetricsOverride',
      { width: v.width, height: v.height, deviceScaleFactor: 1, mobile: v.mobile });
    await goto(cdp, origin + '/launch', 500);
    const overflow = await evaluate(cdp,
      'return JSON.stringify({ scroll: document.documentElement.scrollWidth,'
      + ' client: document.documentElement.clientWidth });');
    const o = JSON.parse(overflow);
    check(o.scroll <= o.client + 1, v.label + ' — no horizontal scroll',
      'scrollWidth ' + o.scroll + ' vs ' + o.client);
  }

  /* The single-column collapse the memo's own media query specifies. */
  await cdp.send('Emulation.setDeviceMetricsOverride',
    { width: 375, height: 812, deviceScaleFactor: 1, mobile: true });
  await goto(cdp, origin + '/launch', 500);
  const cols = await evaluate(cdp,
    'return getComputedStyle(document.querySelector(".grid.three")).gridTemplateColumns;');
  check(cols.split(' ').length === 1, 'three-up grid collapses to one column at 375', cols);
  const tap = await evaluate(cdp,
    'return Math.round(document.querySelector("a.cta").getBoundingClientRect().height);');
  check(tap >= 44, 'CTA meets the 44px tap target', tap + 'px');

  section('Existing site still renders');
  for (const p of ['/', '/terms/', '/privacy/', '/contact/']) {
    await goto(cdp, origin + p, 500);
    const ok = await evaluate(cdp,
      'return JSON.stringify({ t: document.title,'
      + ' h1: (document.querySelector("h1") || {}).textContent || "",'
      + ' bg: getComputedStyle(document.body).backgroundColor });');
    const r = JSON.parse(ok);
    check(Boolean(r.t) && r.h1.trim().length > 0 && r.bg !== 'rgba(0, 0, 0, 0)',
      p + ' still renders with styling', r.t);
  }

  section('Console and CSP');
  check(problems.length === 0, 'no CSP violation, console error or exception',
    problems.slice(0, 3).join(' // ') || 'clean');
});

console.log('\n' + '='.repeat(70));
console.log(failures === 0 ? 'ALL LAUNCH CHECKS PASSED' : 'FAILURES: ' + failures);
console.log('='.repeat(70));
process.exit(failures === 0 ? 0 : 1);
