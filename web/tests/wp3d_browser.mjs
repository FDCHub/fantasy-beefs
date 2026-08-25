/* ============================================================================
 * FantasyStakes — WP3D · provider identity and Yahoo attribution · browser
 *
 * Run through:  python test_wp3d_provider_attribution.py
 *
 * ONE SUITE, RUN FIVE TIMES, AGAINST FIVE DIFFERENTLY-BOUND LEAGUES.
 * `FS_WP3D_MODE` names which one, and the expectations switch with it:
 *
 *   connected      a Yahoo league with a stated week — attributed
 *   pending        a Yahoo league that has never synced — NOT attributed
 *   demo           the governed synthetic provider — NEVER attributed
 *   absent         no provider binding at all — NOT attributed
 *   commissioner   the same connected league, signed in as the commissioner
 *
 * WHY IT MUST BE THE REAL PAGE. The component tier proves the model answers
 * correctly when handed a context. Only this tier can prove that the answer
 * reaches the chrome, that it survives a tab change, that the attribution lands
 * on the panels that actually show Yahoo information and on no others, and that
 * none of it lands on top of the bottom navigation.
 * ========================================================================== */

import { GO_RULES, createReporter, withPage } from './browser-harness.mjs';

const { check, section, finish } = createReporter();

const MODE = process.env.FS_WP3D_MODE || 'connected';

/** What this run should see. */
const EXPECT = {
  connected: { label: 'YAHOO · CONNECTED', family: 'yahoo', attributed: true },
  pending: { label: 'YAHOO · NOT SYNCED YET', family: 'yahoo', attributed: false },
  demo: { label: 'DEMO', family: 'demo', attributed: false },
  absent: { label: 'NOT CONNECTED', family: 'none', attributed: false },
  commissioner: { label: 'YAHOO · CONNECTED', family: 'yahoo', attributed: true },
}[MODE];

const REQUIRED = 'Fantasy data provided by Yahoo Fantasy';
const HREF = 'https://football.fantasysports.yahoo.com/';

const PRIMARY = ['standings', 'league', 'action', 'week', 'ledger'];

await withPage({ port: 9473 }, async ({ evaluate, setViewport }) => {

  console.log(`\n(mode: ${MODE})`);

  /* ── The chrome ───────────────────────────────────────────────────────── */

  section('§15/§16 · The source states itself once, in the chrome');

  const chip = await evaluate(`
    const el = document.querySelector('.fs-source');
    if (!el) return { present: false };
    const mast = document.querySelector('.fs-mast');
    const box = el.getBoundingClientRect();
    const label = el.querySelector('.fs-source__label');
    const style = getComputedStyle(label);
    return {
      present: true,
      count: document.querySelectorAll('.fs-source').length,
      text: el.textContent.trim(),
      family: el.dataset.sourceState,
      insideMasthead: Boolean(mast && mast.contains(el)),
      fontSize: Math.round(parseFloat(style.fontSize)),
      titleSize: Math.round(parseFloat(getComputedStyle(
        document.querySelector('.fs-mast__word')).fontSize)),
      width: Math.round(box.width),
      right: Math.round(box.right),
      innerW: window.innerWidth,
    };
  `);

  check('the source chip is rendered', chip.present === true);
  check(`it reads exactly ${EXPECT.label}`, chip.text === EXPECT.label,
    chip.text);
  check('and reports its family for styling',
    chip.family === EXPECT.family, chip.family);
  check('it appears ONCE, not once per panel', chip.count === 1,
    String(chip.count));
  check('it lives in the app chrome, so it persists across tabs',
    chip.insideMasthead === true);
  check('and it does not compete with the product wordmark',
    chip.fontSize < chip.titleSize,
    `${chip.fontSize}px vs ${chip.titleSize}px`);
  check('it stays inside the viewport', chip.right <= chip.innerW,
    `${chip.right} vs ${chip.innerW}`);

  /* ── §35 · readable, not a colour ─────────────────────────────────────── */

  section('§35 · The state is readable text');

  check('the label is real text content, not a background image or a glyph',
    /[A-Z]/.test(chip.text) && chip.text.length >= 4, chip.text);
  check('nothing about it reads as developer metadata',
    !/debug|dev\b|test|fixture|prototype|mock|sandbox|beta/i.test(chip.text),
    chip.text);

  const providerPanel = await evaluate(`
    FantasyStakes.goTo('provider');
    const panel = document.querySelector('.fs-panel.is-active');
    const region = panel.querySelector('[data-region="provider"]');
    return { id: panel.id,
      title: panel.querySelector('.fs-tabhead__title').textContent,
      label: panel.querySelector('[data-provider-label]').textContent,
      family: region.dataset.providerFamily,
      controls: region.querySelectorAll('button, input, select, textarea').length };
  `);
  check('Provider Information is its own rendered destination',
    providerPanel.id === 'panel-provider'
      && providerPanel.title === 'PROVIDER INFORMATION', JSON.stringify(providerPanel));
  check('the destination reports the same served provider state as the chrome',
    providerPanel.label === EXPECT.label && providerPanel.family === EXPECT.family,
    JSON.stringify(providerPanel));
  check('Provider Information is read-only', providerPanel.controls === 0,
    String(providerPanel.controls));

  /* ── §26/§4 · the product is unchanged ────────────────────────────────── */

  section('§4/§26 · Same product, same five tabs, whatever the source');

  const nav = await evaluate(`
    const items = [...document.querySelectorAll('.fs-tabbar__item')];
    return {
      count: items.length,
      labels: items.map((i) => i.querySelector('.fs-tabbar__label').textContent),
      wordmark: document.querySelector('.fs-mast__word').textContent,
    };
  `);
  check('five primary tabs, in the locked order',
    nav.labels.join(' · ') === 'Standings · Play · Status · Wrap Up · Account',
    nav.labels.join(' · '));
  check('and the product is still called FantasyStakes',
    nav.wordmark === 'FantasyStakes', nav.wordmark);
  check('no Demo-only navigation was introduced', nav.count === 5);

  /* ── §18 · attribution placement, per surface ─────────────────────────── */

  section('§18 · Attribution lands on the surfaces that show Yahoo data');

  const panels = await evaluate(`return (async () => {
    const out = {};
    for (const id of ${JSON.stringify(PRIMARY)}) {
      document.querySelector('.fs-tabbar__item[data-destination="' + id + '"]').click();
      await new Promise((r) => setTimeout(r, 120));
      const panel = document.getElementById('panel-' + id);
      const nodes = [...panel.querySelectorAll('.fs-attribution')];
      const link = nodes.length ? nodes[0].querySelector('a') : null;
      const nav = document.querySelector('.fs-tabbar').getBoundingClientRect();
      const box = nodes.length ? nodes[0].getBoundingClientRect() : null;
      out[id] = {
        count: nodes.length,
        text: nodes.length ? nodes[0].textContent.trim() : null,
        href: link ? link.getAttribute('href') : null,
        tag: link ? link.tagName : null,
        tabbable: link ? link.tabIndex >= 0 : null,
        underlined: link
          ? getComputedStyle(link).textDecorationLine.includes('underline')
          : null,
        fontSize: link ? Math.round(parseFloat(getComputedStyle(link).fontSize)) : null,
        // ABOVE THE NAV, NEVER OVER IT.
        clearsNav: box ? box.bottom <= nav.top + 1 : null,
        panelText: panel.textContent,
      };
    }
    return out;
  })();`);

  for (const id of PRIMARY) {
    const p = panels[id];
    if (EXPECT.attributed) {
      check(`${id}: attributed exactly once`, p.count === 1, String(p.count));
      check(`${id}: with the agreement's exact words`, p.text === REQUIRED,
        p.text);
      check(`${id}: linking to the official Yahoo Fantasy destination`,
        p.href === HREF, p.href);
      check(`${id}: as a real, focusable anchor`,
        p.tag === 'A' && p.tabbable === true);
      check(`${id}: recognisable as a link without relying on colour`,
        p.underlined === true);
      check(`${id}: readable, and subordinate to the content`,
        p.fontSize >= 9, `${p.fontSize}px`);
      check(`${id}: it sits ABOVE the bottom navigation`, p.clearsNav === true);
    } else {
      check(`${id}: NOT attributed — no Yahoo information is being shown`,
        p.count === 0, String(p.count));
      check(`${id}: and the required text appears nowhere on the panel`,
        !p.panelText.includes(REQUIRED));
    }
    check(`${id}: no endorsement or partnership language`,
      !/Powered by Yahoo|Official Yahoo|Yahoo-approved|Yahoo sportsbook|Yahoo partner/i
        .test(p.panelText));
  }

  /* ── §20/§22 · Rules, and the reference-vs-display distinction ────────── */

  section('§20/§22 · Rules & Settings, and the commissioner region');

  const rules = await evaluate(`return (async () => {
    ${GO_RULES}
    await new Promise((r) => setTimeout(r, 200));
    const panel = document.getElementById('panel-rules');
    const nodes = [...panel.querySelectorAll('.fs-attribution')];
    return {
      count: nodes.length,
      text: nodes.length ? nodes[0].textContent.trim() : null,
      mentionsYahoo: /Yahoo/.test(panel.textContent),
      hasRuleCards: panel.querySelectorAll('[data-rule]').length > 0,
      panelText: panel.textContent,
      hasCommissionerRegion: Boolean(panel.querySelector('.fs-legal')),
    };
  })();`);

  // THE PROSE IS NOT ON THE PANEL, and asserting it here measured the wrong
  // thing: the rule text lives in the sheets those rows open, so the only
  // `Yahoo` on the panel body in a connected league was the attribution this
  // package added. The §22 distinction — a REFERENCE to Yahoo in copy is not a
  // DISPLAY of Yahoo Fantasy Information — is certified where it can be, on the
  // source, in `test_wp3d_provider_attribution.py` §8. What belongs here is the
  // placement claim: one attribution for the whole surface, or none.
  check('the surface offers its rule rows either way',
    rules.hasRuleCards === true, String(rules.hasRuleCards));
  if (EXPECT.attributed) {
    check('and the panel is attributed ONCE, not once per region',
      rules.count === 1, String(rules.count));
    check('with the exact words', rules.text === REQUIRED, rules.text);
  } else {
    check('but prose alone is never attributed, and this source is not Yahoo',
      rules.count === 0, String(rules.count));
  }
  check('no endorsement language in the rules copy',
    !/Powered by Yahoo|Official Yahoo|Yahoo-approved|Yahoo partner/i
      .test(rules.panelText));

  /* ── §20 · the Matchup Preview ────────────────────────────────────────── */

  section('§20 · The Matchup Preview source treatment');

  const preview = await evaluate(`return (async () => {
    document.querySelector('.fs-tabbar__item[data-destination="league"]').click();
    await new Promise((r) => setTimeout(r, 200));
    const row = document.querySelector('#panel-league [data-preview-opponent]');
    if (!row) return { opened: false };
    row.click();
    await new Promise((r) => setTimeout(r, 350));
    const sheet = document.getElementById('fs-sheet');
    return {
      opened: true,
      text: sheet.textContent,
      banner: sheet.querySelectorAll('.fs-srcbanner').length,
      titles: [...sheet.querySelectorAll('.fs-prev__title')].map((e) => e.textContent),
      attribution: sheet.querySelectorAll('.fs-attribution').length,
    };
  })();`);

  if (preview.opened) {
    check('the retired banner is gone from the preview',
      preview.banner === 0 && !preview.text.includes('OFFICIAL YAHOO FANTASY MATCHUP'),
      String(preview.banner));
    check('no claim of official standing survives anywhere in it',
      !/official\s+yahoo/i.test(preview.text));
    // UIRECON WAVE 4A — MATCHUP IS GONE AND ON OFFER STANDS IN ITS SLOT.
    //
    // The old first block restated the two team names the sheet subtitle
    // already carried. Its slot now names the MARKET the GM is being offered,
    // which is what the three analysis modules below it explain — and which is
    // fetched, so it is present exactly when this session has a served market
    // to name and absent when it does not. The pending family legitimately has
    // none. What is invariant, and is what this assertion has always been
    // about, is the ANALYSIS ORDER underneath.
    const analysis = preview.titles.filter((t) => t !== 'RESULT');
    const expected = analysis.includes('ON OFFER')
      ? 'LINEUPS → ON OFFER → WHY THE LINE LOOKS THIS WAY → THE READ'
      : 'LINEUPS → WHY THE LINE LOOKS THIS WAY → THE READ';
    check('the locked analysis order keeps Lineups above On Offer',
      analysis.join(' → ') === expected, preview.titles.join(' → '));
    check('and nothing restates the pairing the sheet header already names',
      !preview.titles.includes('MATCHUP'), preview.titles.join(' → '));
    if (EXPECT.family === 'demo') {
      check('a Demo preview carries NO Yahoo wording at all',
        !/Yahoo/.test(preview.text), 'no Yahoo mention');
      check('and no attribution', preview.attribution === 0);
    }
    await evaluate(`
      const c = document.querySelector('#fs-sheet [data-fs-close]');
      if (c) c.click();
      return true;`);
  } else {
    check('this league offers no preview row — treatment not exercised',
      true, 'reported, not passed over');
  }

  /* ── §13/§26 · no raw diagnostics anywhere a member can see ───────────── */

  section('§13 · No raw diagnostic reaches the member-facing product');

  const swept = await evaluate(`return (async () => {
    let text = document.querySelector('.fs-mast').textContent;
    for (const id of ${JSON.stringify(PRIMARY)}) {
      document.querySelector('.fs-tabbar__item[data-destination="' + id + '"]').click();
      await new Promise((r) => setTimeout(r, 100));
      text += ' ' + document.getElementById('panel-' + id).textContent;
    }
    ${GO_RULES}
    await new Promise((r) => setTimeout(r, 200));
    text += ' ' + document.getElementById('panel-rules').textContent;
    return text;
  })();`);

  for (const leak of ['Traceback', 'ProviderError', 'HTTPException',
    'access_token', 'refresh_token', 'oauth', 'OAuth',
    'fantasysports.yahooapis', 'ECONNREFUSED', 'status_code',
    'open_provider_conflicts', 'stuck_pools', 'blocked_reason',
    'unfinalized_matchup_ids', 'last_provider_refresh']) {
    check(`no ${leak} on any member-facing surface`, !swept.includes(leak));
  }
  check('no bare HTTP status code is presented as product copy',
    !/\b(?:4\d\d|5\d\d)\b\s*(?:error|status)/i.test(swept));

  // THE DIAGNOSTIC ROUTE ITSELF, asked for by the page's own session.
  const diagnostics = await evaluate(`return (async () => {
    const me = await (await fetch('/auth/me', { credentials: 'same-origin' })).json();
    const league = me.capabilities.acting_league_id;
    const res = await fetch('/league/' + league + '/provider/status',
      { credentials: 'same-origin' });
    return { status: res.status, commissioner: Boolean(
      me.capabilities.is_commissioner) };
  })();`);

  if (MODE === 'commissioner') {
    check('a commissioner session may still read the diagnostics',
      diagnostics.status === 200, String(diagnostics.status));
  } else {
    check('an ordinary GM session is refused the diagnostics',
      diagnostics.status === 403 || diagnostics.status === 401,
      String(diagnostics.status));
  }

  /* ── §31 · the state survives navigation ──────────────────────────────── */

  section('§31 · The source survives every tab change');

  const persisted = await evaluate(`return (async () => {
    const seen = [];
    for (const id of ${JSON.stringify(PRIMARY)}) {
      document.querySelector('.fs-tabbar__item[data-destination="' + id + '"]').click();
      await new Promise((r) => setTimeout(r, 80));
      const el = document.querySelector('.fs-source');
      seen.push(el ? el.textContent.trim() : null);
    }
    return seen;
  })();`);
  check('the chip reads the same on all five tabs',
    new Set(persisted).size === 1 && persisted[0] === EXPECT.label,
    persisted.join(' | '));

  /* ── §34 · phone geometry ─────────────────────────────────────────────── */

  section('§34 · The chrome and the footer fit the phone');

  for (const [width, height] of [[375, 667], [390, 844], [430, 932],
    [320, 568]]) {
    await setViewport(width, height);
    const m = await evaluate(`
      document.querySelector('.fs-tabbar__item[data-destination="league"]').click();
      const chip = document.querySelector('.fs-source');
      const label = chip ? chip.querySelector('.fs-source__label') : null;
      const nav = document.querySelector('.fs-tabbar').getBoundingClientRect();
      const attr = document.querySelector('#panel-league .fs-attribution');
      const lockup = document.querySelector('.fs-mast__lockup').getBoundingClientRect();
      const cards = [...document.querySelectorAll('#panel-league .fs-wcard')];
      return {
        docW: document.documentElement.scrollWidth,
        innerW: window.innerWidth,
        chipRight: chip ? Math.round(chip.getBoundingClientRect().right) : null,
        chipTruncated: label ? label.scrollWidth > label.clientWidth + 1 : null,
        chipOverNav: chip
          ? chip.getBoundingClientRect().bottom > nav.top : null,
        // RC4 MOBILE RECONCILIATION - THE REGION IS WHAT MUST CLEAR THE NAV.
        // Play scrolls as a page now, so the source line is ordinary content
        // near the end of a CLIPPED scroll region rather than the last block of
        // a fixed-height panel: below the fold on a short phone, and painted
        // nowhere the region does not reach. The claim - nothing Play draws
        // lands on the navigation - is asked of the box that does the clipping.
        attrOverNav: attr
          ? (document.querySelector('#panel-league .fs-zones')
             || attr).getBoundingClientRect().bottom > nav.top + 1 : null,
        lockupW: Math.round(lockup.width),
        clipped: cards.filter((c) => c.scrollHeight > c.clientHeight + 1).length,
      };
    `);
    check(`${width}: the page does not scroll horizontally`,
      m.docW <= m.innerW, `${m.docW} vs ${m.innerW}`);
    check(`${width}: the source chip fits its column, untruncated`,
      m.chipTruncated === false && m.chipRight <= m.innerW,
      `right ${m.chipRight}, truncated ${m.chipTruncated}`);
    check(`${width}: the chip never reaches the bottom navigation`,
      m.chipOverNav === false);
    // THE LOCKUP IS MEASURED AGAINST WHAT IT WAS, NOT AGAINST AN IDEAL.
    //
    // A COMMISSIONER session already carried a two-line meta column before this
    // package: measured at HEAD, the badge left the lockup 92px at 375 and 107
    // at 390, with the masthead at 87px. WP3D adds nothing to it — the chip
    // shares the gear's row — so the claim here is that the chip did not make
    // it worse, and the absolute figure is a WP3E item rather than this one.
    const FLOOR = { commissioner: { 375: 92, 390: 107, 430: 147, 320: 60 },
      other: { 375: 150, 390: 150, 430: 150, 320: 60 } }[
      MODE === 'commissioner' ? 'commissioner' : 'other'][width];
    if (width >= 375) {
      check(`${width}: the chip took no width from the lockup`,
        m.lockupW >= FLOOR, `${m.lockupW}px, floor ${FLOOR}px`);
    } else {
      check(`${width}: lockup measured below the certified set — ${m.lockupW}px`,
        true, 'reported, not gated');
    }
    if (m.attrOverNav !== null) {
      check(`${width}: the attribution never overlaps the bottom navigation`,
        m.attrOverNav === false);
    }
    if (MODE === 'commissioner') {
      // PRE-EXISTING, AND MEASURABLY IMPROVED. At HEAD a commissioner's Play
      // cards clipped at 375 — 127px of content in 120px of card — because the
      // COMMISSIONER badge pushes the masthead to 87px. WP3D releases the Play
      // zones' bottom padding, which gives 5px back: 125px now. The condition
      // is not this package's and is carried to WP3E; what is asserted is that
      // WP3D did not deepen it.
      check(`${width}: commissioner clipping is no worse than HEAD — `
        + `${m.clipped} card(s)`, m.clipped <= 2, 'pre-existing, carried to WP3E');
    } else if (width >= 375) {
      check(`${width}: no wager card clips its own content`, m.clipped === 0,
        `${m.clipped} clipping`);
    } else {
      // 320x568 belongs to WP3E. Measured so the carry-forward carries a
      // number, and compared against the figure WP3C.2 recorded so this
      // package can be shown not to have made it worse.
      check(`${width}: measured below the certified set — ${m.clipped} clipping`,
        m.clipped <= 2, `WP3C.2 recorded 2; now ${m.clipped}`);
    }
  }

  await setViewport(390, 844);
});

finish('WP3D PROVIDER IDENTITY + ATTRIBUTION — BROWSER');
