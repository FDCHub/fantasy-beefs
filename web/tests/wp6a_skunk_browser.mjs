/* ============================================================================
 * FantasyStakes — WP6A · SKUNK OF THE WEEK, from the browser
 *
 * The callout is the week's headline result, and the POINT DIFFERENTIAL is its
 * key number. Both claims are about what a GM actually sees on a phone, so both
 * are measured here rather than asserted from markup: the differential's
 * rendered type size is compared against the final score's, and the whole card
 * is measured at 375, 390 and 430.
 *
 * THE SESSION IS AN ORDINARY GM. That is deliberate — the ruling says GMs see
 * the result but cannot invoke economic lifecycle actions, and this suite
 * asserts both halves against the same page.
 * ========================================================================== */

import { createReporter, withPage } from './browser-harness.mjs';

const report = createReporter();
const probe = (body) => `return (async () => { ${body} })();`;

await withPage({ port: 9411, settleMs: 2000 }, async ({ evaluate, setViewport }) => {

  /* ── What the server says happened ────────────────────────────────────── */

  const served = await evaluate(probe(`
    const me = await (await fetch('/auth/me', { credentials: 'same-origin' })).json();
    const league = me.capabilities.acting_league_id;
    const ctx = await (await fetch('/league/' + league + '/context/me',
      { credentials: 'same-origin' })).json();
    const skunk = await (await fetch(
      '/league/' + league + '/week/' + ctx.current_week + '/skunk',
      { credentials: 'same-origin' })).json();
    return {
      league, week: ctx.current_week,
      commissionerOf: me.capabilities.commissioner_league_ids || [],
      skunk,
    };
  `));

  report.section('The server serves the week’s Skunk to an ordinary GM');

  report.check('the session is NOT a commissioner of this league',
    !served.commissionerOf.includes(served.league),
    `commissioner of ${JSON.stringify(served.commissionerOf)}`);
  report.check('and the Skunk read still succeeds for them',
    served.skunk && served.skunk.assessed === true,
    JSON.stringify(served.skunk).slice(0, 120));
  report.check('it names one skunked GM',
    (served.skunk.entries || []).length === 1,
    String((served.skunk.entries || []).length));

  const entry = served.skunk.entries[0];

  /* ── The callout ──────────────────────────────────────────────────────── */

  report.section('SKUNK OF THE WEEK renders in The Week');

  const card = await evaluate(probe(`
    document.querySelector('.fs-tabbar__item[data-destination="week"]').click();
    await new Promise((r) => setTimeout(r, 400));
    const panel = document.getElementById('panel-week');
    const el = panel.querySelector('.fs-skunk');
    if (!el) return { present: false };
    const margin = el.querySelector('[data-skunk-margin]');
    const marginValue = el.querySelector('.fs-skunk__marginvalue');
    const final = el.querySelector('[data-skunk-final]');
    const fee = el.querySelector('[data-skunk-fee]');
    const eyebrow = el.querySelector('.fs-skunk__eyebrow');
    const line = el.querySelector('[data-skunk-line]');
    return {
      present: true,
      week: el.dataset.skunkWeek,
      eyebrow: eyebrow.textContent.trim(),
      line: line.textContent.replace(/\\s+/g, ' ').trim(),
      marginText: marginValue.textContent.trim(),
      marginLabel: margin.textContent.replace(/\\s+/g, ' ').trim(),
      finalText: final.textContent.trim(),
      feeText: fee.textContent.trim(),
      feeCents: fee.dataset.exactCents,
      // THE HIERARCHY, MEASURED. The ruling puts the differential above the raw
      // score, so the differential must actually be drawn larger.
      marginFontPx: parseFloat(getComputedStyle(marginValue).fontSize),
      finalFontPx: parseFloat(getComputedStyle(final).fontSize),
      lineFontPx: parseFloat(getComputedStyle(line).fontSize),
      // Ordering within the card.
      order: [...el.children].map((c) => (c.className || '').split(' ')[0]),
      // It must not have become a fourth module.
      modules: [...panel.querySelectorAll('[data-module]')]
        .map((m) => m.dataset.module),
      isModule: el.hasAttribute('data-module'),
      beforeYahoo: el.compareDocumentPosition(
        panel.querySelector('[data-module="yahoo"]')) & Node.DOCUMENT_POSITION_FOLLOWING,
    };
  `));

  report.check('the callout is present on The Week', card.present === true);
  report.check('it is scoped to the week on screen',
    card.week === String(served.week), `${card.week} vs week ${served.week}`);
  report.check('the eyebrow is SKUNK OF THE WEEK',
    card.eyebrow === 'SKUNK OF THE WEEK', card.eyebrow);
  report.check('it names the skunked GM and the opponent, in that order',
    card.line === `${entry.team_name} got skunked by ${entry.opponent_team_name}`,
    card.line);

  /* ── The key number ───────────────────────────────────────────────────── */

  report.section('The POINT DIFFERENTIAL is the key number');

  report.check('the margin shown is the served differential, to the same value',
    Number(card.marginText) === Number(entry.margin.toFixed(2)),
    `${card.marginText} vs served ${entry.margin}`);
  report.check('it keeps the fractional scoring rather than rounding it away',
    card.marginText.includes('.') && Number(card.marginText) % 1 !== 0,
    card.marginText);
  report.check('and it is labelled as a point margin',
    /point margin/i.test(card.marginLabel), card.marginLabel);
  // THE EMPHASIS CLAIM, AS A MEASUREMENT. "Stronger visual emphasis than the
  // raw final score" is only true if the rendered type is actually larger.
  report.check('the differential is drawn LARGER than the final score',
    card.marginFontPx > card.finalFontPx,
    `${card.marginFontPx}px vs ${card.finalFontPx}px`);
  report.check('and larger than the naming line above it',
    card.marginFontPx > card.lineFontPx,
    `${card.marginFontPx}px vs ${card.lineFontPx}px`);
  report.check('the margin sits above the final score in the card',
    card.order.indexOf('fs-skunk__margin') < card.order.indexOf('fs-skunk__final'),
    card.order.join(' → '));

  /* ── The score and the fee ────────────────────────────────────────────── */

  report.section('The final score and the $10 effect');

  const dp = (v) => {
    const s = String(Number(v.toFixed(2)));
    return s.includes('.') ? s.split('.')[1].length : 0;
  };
  const places = Math.max(dp(entry.margin), dp(entry.score), dp(entry.opponent_score));
  const expectedFinal = `Final: ${entry.opponent_score.toFixed(places)}–${entry.score.toFixed(places)}`;

  report.check('the final score is winner–loser, at the served precision',
    card.finalText === expectedFinal, `${card.finalText} vs ${expectedFinal}`);
  report.check('the $10 Skunk effect is stated',
    /\$10 Skunk/.test(card.feeText), card.feeText);
  report.check('and it carries the exact cents behind the display figure',
    Number(card.feeCents) === entry.cents && Number(card.feeCents) === 1000,
    `${card.feeCents} vs served ${entry.cents}`);

  /* ── It did not become a fourth module ────────────────────────────────── */

  report.section('The locked three-module dashboard is unchanged');

  report.check('The Week still has exactly three modules',
    card.modules.length === 3, card.modules.join(','));
  report.check('and they are still Yahoo, Bets and Pools',
    card.modules.join(',') === 'yahoo,bets,pools', card.modules.join(','));
  report.check('the callout is not itself a module',
    card.isModule === false);
  report.check('it leads the scroll, above the Yahoo module',
    Boolean(card.beforeYahoo));

  /* ── A GM sees it but cannot cause it ─────────────────────────────────── */

  report.section('A GM sees the result but holds no lifecycle control');

  const authority = await evaluate(probe(`
    const csrf = document.cookie.split('; ').find((c) => c.startsWith('fs_csrf='));
    const headers = {};
    if (csrf) headers['X-FS-CSRF'] = decodeURIComponent(csrf.split('=')[1]);
    const r = await fetch('/league/${served.league}/week/${served.week}/close', {
      method: 'POST', credentials: 'same-origin', headers,
    });
    return { status: r.status, csrfSent: Boolean(csrf),
             lifecycleControls: document.querySelectorAll('[data-lifecycle-action]').length };
  `));

  report.check('the CSRF token was read and sent', authority.csrfSent === true);
  report.check('a GM cannot run Week Close — the only way to cause a Skunk',
    authority.status === 403, `status ${authority.status}`);
  report.check('and no lifecycle control is drawn for them anywhere',
    authority.lifecycleControls === 0, String(authority.lifecycleControls));

  /* ── Mobile ───────────────────────────────────────────────────────────── */

  report.section('375 / 390 / 430 px');

  const measure = probe(`
    document.querySelector('.fs-tabbar__item[data-destination="week"]').click();
    await new Promise((r) => setTimeout(r, 400));
    const panel = document.getElementById('panel-week');
    const el = panel.querySelector('.fs-skunk');
    if (!el) return { missing: true };
    const scroll = panel.querySelector('.fs-wkscroll');
    const nav = document.getElementById('fs-tabbar').getBoundingClientRect();
    const box = el.getBoundingClientRect();
    return {
      missing: false,
      clipped: el.scrollHeight > el.clientHeight + 1
            || el.scrollWidth > el.clientWidth + 1,
      right: Math.round(box.right),
      docOverflow: document.documentElement.scrollWidth - window.innerWidth,
      bodyOverflow: document.body.scrollWidth - window.innerWidth,
      scrollOverflow: scroll.scrollWidth - scroll.clientWidth,
      escaping: [...el.querySelectorAll('*')]
        .filter((c) => c.getBoundingClientRect().right > window.innerWidth + 0.5).length,
      marginVisible: el.querySelector('.fs-skunk__marginvalue')
        .getBoundingClientRect().width > 0,
      navBottom: Math.round(nav.bottom),
      modules: panel.querySelectorAll('[data-module]').length,
    };
  `);

  for (const [width, height] of [[375, 667], [390, 844], [430, 932]]) {
    await setViewport(width, height);
    const m = await evaluate(measure);

    if (m.missing) {
      report.check(`${width}px: the callout renders`, false, 'absent');
      continue;
    }
    report.check(`${width}px: the callout does not clip its own content`,
      m.clipped === false);
    report.check(`${width}px: the page does not scroll horizontally`,
      m.docOverflow <= 0 && m.bodyOverflow <= 0,
      `doc ${m.docOverflow}px, body ${m.bodyOverflow}px`);
    report.check(`${width}px: the week column does not overflow`,
      m.scrollOverflow <= 0, `${m.scrollOverflow}px`);
    report.check(`${width}px: nothing in the callout escapes the viewport`,
      m.escaping === 0 && m.right <= width, `${m.escaping} past ${width}px`);
    report.check(`${width}px: the margin figure is visible`,
      m.marginVisible === true);
    report.check(`${width}px: the three modules survive`,
      m.modules === 3, String(m.modules));
    report.check(`${width}px: the bottom navigation has not sunk`,
      m.navBottom <= height + 1, `nav bottom ${m.navBottom} of ${height}`);
  }
});

report.finish();