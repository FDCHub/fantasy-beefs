/* ============================================================================
 * FantasyStakes — WP3C · Rev 4.3 gameplay surfaces · browser suite
 *
 * Run directly:   node web/tests/wp3c_browser.mjs
 * Or through:     python test_wp3c_rev43_gameplay.py
 *
 * MEASURED GEOMETRY AND REAL INTERACTION against the running application. These
 * are the claims the component suite cannot make: that the preview row really
 * renders above the markets on screen, that the counter sheet really replaces
 * the browser prompt, that the Account disclosures really hide and really come
 * back, and that the WP3C type scale survived the cascade.
 * ========================================================================== */

import { GO_RULES, createReporter, withPage } from './browser-harness.mjs';

const { check, section, finish } = createReporter();

const VIEWPORTS = [
  { width: 320, height: 568, label: 'small phone' },
  { width: 375, height: 667, label: 'standard phone' },
  { width: 390, height: 844, label: 'modern phone' },
  { width: 430, height: 932, label: 'large phone' },
];

await withPage({ port: 9455 }, async ({ evaluate, setViewport }) => {

  /* ── What the server actually says ────────────────────────────────────── */

  const served = await evaluate(`return (async () => {
    const me = await (await fetch('/auth/me', { credentials: 'same-origin' })).json();
    const league = me.capabilities.acting_league_id;
    const get = async (p) => {
      const r = await fetch(p, { credentials: 'same-origin' });
      return r.ok ? await r.json() : null;
    };
    const ctx = await get('/league/' + league + '/context/me');
    const action = await get('/league/' + league + '/action/me');
    return {
      league,
      phase: ctx ? ctx.phase : null,
      week: ctx ? ctx.current_week : null,
      opponents: action ? action.opponents : [],
      eligible: action
        ? action.opponents.filter((o) => o.versus_eligible !== false).length : 0,
      versusPhase: action ? action.versus_phase : null,
      determinable: action ? action.versus_field_determinable : null,
    };
  })();`);

  section('§6 · The Versus subject contract is served, not inferred');

  check('the session reads an authoritative league',
    typeof served.league === 'number', String(served.league));
  check('the Action read carries a Versus phase',
    served.versusPhase === 'regular' || served.versusPhase === 'postseason',
    String(served.versusPhase));
  check('and states whether the field is determinable',
    typeof served.determinable === 'boolean', String(served.determinable));
  check('every opponent carries an eligibility marker',
    served.opponents.every((o) => typeof o.versus_eligible === 'boolean'),
    `${served.opponents.length} opponents`);
  check('in the regular season every member is eligible',
    served.versusPhase !== 'regular'
    || served.eligible === served.opponents.length,
    `${served.eligible} of ${served.opponents.length}`);

  /* ── Play ─────────────────────────────────────────────────────────────── */

  section('§4/§5 · Play renders real data and no fabricated content');

  const play = await evaluate(`
    document.querySelector('.fs-tabbar__item[data-destination="league"]').click();
    const panel = document.getElementById('panel-league');
    const cards = [...panel.querySelectorAll('[data-card-action="challenge"]')];
    return {
      text: panel.textContent,
      cardIds: cards.map((c) => Number(c.dataset.cardId)),
      headings: [...panel.querySelectorAll('.fs-heading__text')]
        .map((el) => el.textContent),
      sub: panel.querySelector('.fs-tabhead__sub').textContent,
      stripLabels: [...panel.querySelectorAll('.fs-strip__label')]
        .map((el) => el.textContent),
      hasAside: Boolean(panel.querySelector('.fs-tabhead__aside')),
      disclaimers: panel.querySelectorAll('.fs-disclaimer').length,
    };
  `);

  check('every discovery card is a team the SERVER named',
    play.cardIds.every((id) => served.opponents.some((o) => o.team_id === id)),
    `cards ${JSON.stringify(play.cardIds)}`);
  check('and only the eligible ones are offered',
    play.cardIds.length === served.eligible,
    `${play.cardIds.length} cards for ${served.eligible} eligible`);
  check('no invented opponent name appears',
    !/CULV Destroyers|Gridiron Goodfellas|Skipolini|Bada Bing|Sunday Gravy|Racconti|Contabile|Provenza/
      .test(play.text));
  check('no invented record, rank or projection appears',
    !/\b7–0\b|\bProjected\b|Biggest dog on the board/.test(play.text));
  check('no FIRST KICKOFF countdown', !/FIRST KICKOFF/i.test(play.text)
    && play.hasAside === false);
  check('no standings rank in the summary strip',
    !/·\s*\d(st|nd|rd|th)\b/.test(play.text));
  check('no heading carries a directional arrow',
    play.headings.every((h) => !h.includes('↕')), play.headings.join(' | '));
  check('the four-cell strip is retained with its locked labels',
    ['Net Won', 'Wallet', 'Min Left', 'Available']
      .every((l) => play.stripLabels.includes(l)),
    play.stripLabels.join(' | '));
  check('the Credits disclaimer appears once', play.disclaimers === 1);
  check('the context line states the served week and phase',
    served.week === null || play.sub.includes(`Week ${served.week}`),
    play.sub);

  /* ── §7 · the Versus card hierarchy, measured ─────────────────────────── */

  section('§7 · VIEW MATCHUP PREVIEW renders above the markets');

  if (play.cardIds.length > 0) {
    const card = await evaluate(`
      const c = document.querySelector('#panel-league [data-card-action="challenge"]');
      const preview = c.querySelector('[data-preview-opponent]');
      const markets = [...c.querySelectorAll('.fs-market')];
      const identity = c.querySelector('.fs-wcard__identity');
      const cb = c.getBoundingClientRect();
      const pb = preview.getBoundingClientRect();
      return {
        identityAbovePreview:
          identity.getBoundingClientRect().bottom <= pb.top + 1,
        previewAboveMarkets:
          pb.bottom <= markets[0].getBoundingClientRect().top + 1,
        previewFullWidth: Math.abs(pb.width - cb.width) <= 32,
        previewTarget: Math.round(pb.height),
        previewText: preview.textContent.trim(),
        marketLabels: markets.map((m) =>
          m.querySelector('.fs-market__label').textContent),
        marketTargets: markets.map((m) =>
          Math.round(m.getBoundingClientRect().height)),
        allButtons: markets.every((m) => m.tagName === 'BUTTON'),
        clipped: c.scrollHeight > c.clientHeight + 1,
      };
    `);
    check('identity comes first', card.identityAbovePreview === true);
    check('the preview row sits ABOVE the market cells',
      card.previewAboveMarkets === true);
    check('it is full width', card.previewFullWidth === true);
    check('it reads VIEW MATCHUP PREVIEW',
      card.previewText === 'VIEW MATCHUP PREVIEW', card.previewText);
    check('it meets the 44px target', card.previewTarget >= 44,
      `${card.previewTarget}px`);
    check('the markets are ML | SPR | O/U',
      card.marketLabels.join(' | ') === 'ML | SPR | O/U',
      card.marketLabels.join(' | '));
    check('every market cell is a real button at 44px',
      card.allButtons === true && card.marketTargets.every((h) => h >= 44),
      card.marketTargets.join(','));
    check('the card does not clip its own content', card.clipped === false);
  } else {
    check('this league offers no Versus subjects — card hierarchy not exercised',
      true, 'reported, not skipped silently');
  }

  /* ── §8 · the Matchup Preview ─────────────────────────────────────────── */

  section('§8 · Matchup Preview is analysis, in the locked order');

  if (play.cardIds.length > 0) {
    const preview = await evaluate(`
      document.querySelector('#panel-league [data-preview-opponent]').click();
      const sheet = document.getElementById('fs-sheet');
      const open = document.getElementById('fs-overlay').classList.contains('is-open');
      if (!open) return { open: false, titles: [], html: sheet.innerHTML.slice(0, 200) };
      const titles = [...sheet.querySelectorAll('.fs-prev__title')]
        .map((el) => el.textContent);
      const close = sheet.querySelector('[data-fs-close]');
      const s = sheet.getBoundingClientRect();
      const c = close ? close.getBoundingClientRect() : null;
      const titleEl = sheet.querySelector('.fs-sheet__title');
      return {
        open,
        title: titleEl ? titleEl.textContent : null,
        titles,
        hasMarketCells: Boolean(sheet.querySelector('.fs-market, [data-market]')),
        fromRight: c ? s.right - c.right : null,
        fromLeft: c ? c.left - s.left : null,
        fromTop: c ? c.top - s.top : null,
      };
    `);
    check('the preview opens from the discovery card', preview.open === true
      && /Matchup Preview/.test(preview.title));
    check('the section order is the locked one',
      preview.titles.join(' → ')
        === 'MATCHUP → WHY THE LINE LOOKS THIS WAY → THE READ → LINEUPS',
      preview.titles.join(' → '));
    check('it duplicates no betting market',
      preview.hasMarketCells === false
      && !preview.titles.includes('SPORTSBOOK VIEW'));
    check('the close control is upper-left (owner ruling, superseding §9/§25)',
      preview.fromLeft >= 0 && preview.fromLeft < preview.fromRight
      && preview.fromTop >= 0,
      `${preview.fromLeft.toFixed(1)}px from left`);

    const closed = await evaluate(`
      document.querySelector('#fs-sheet [data-fs-close]').click();
      return { open: document.getElementById('fs-overlay').classList.contains('is-open'),
               onPlay: document.getElementById('panel-league')
                 .classList.contains('is-active') };
    `);
    check('closing it returns to the Versus card',
      closed.open === false && closed.onPlay === true);
  }

  /* ── §13/§15 · Status ─────────────────────────────────────────────────── */

  section('§13 · Status keeps four sections in one typography');

  const status = await evaluate(`
    document.querySelector('.fs-tabbar__item[data-destination="action"]').click();
    const panel = document.getElementById('panel-action');
    const rails = [...panel.querySelectorAll('[data-rail]')];
    return {
      header: panel.querySelector('.fs-tabhead__title').textContent,
      railIds: rails.map((r) => r.dataset.rail),
      headingSizes: rails.map((r) => Math.round(parseFloat(
        getComputedStyle(r.querySelector('.fs-heading__text')).fontSize))),
      horizontal: rails.every((r) => {
        const rail = r.querySelector('.fs-rail');
        return rail && getComputedStyle(rail).overflowX === 'auto';
      }),
    };
  `);

  check('four sections, in the locked order',
    status.railIds.join(',') === 'action,waiting,live,completed',
    status.railIds.join(','));
  check('all four headings share ONE type size (§13)',
    new Set(status.headingSizes).size === 1, status.headingSizes.join(','));
  check('and that size is the §5 section step',
    status.headingSizes[0] >= 18 && status.headingSizes[0] <= 20,
    `${status.headingSizes[0]}px`);
  check('each keeps its horizontally scrolling row',
    status.horizontal === true);
  check('the header states the served week and phase, not a literal',
    served.week === null || status.header.includes(`WEEK ${served.week}`),
    status.header);
  check('and it still calls the content ACTION (§13)',
    /ACTION$/.test(status.header), status.header);

  section('§15 · Counter uses product UI, and no browser prompt survives');

  const noPrompt = await evaluate(`
    // If any surface still called window.prompt, this would trap it. It is
    // replaced rather than merely unused, so a regression is caught here rather
    // than by a suite hanging on a modal it cannot dismiss.
    let called = 0;
    window.prompt = () => { called += 1; return null; };
    window.confirm = () => { called += 1; return false; };
    window.alert = () => { called += 1; };
    const respond = document.querySelector('#panel-action [data-respond="counter"]');
    if (!respond) {
      const card = document.querySelector('#panel-action [data-card-action]');
      if (card) card.click();
    }
    const counter = document.querySelector('#fs-sheet [data-respond="counter"]');
    if (counter) counter.click();
    const sheet = document.getElementById('fs-sheet');
    return {
      offered: Boolean(counter),
      called,
      hasField: Boolean(sheet.querySelector('#fs-cstake-input')),
      hasSend: Boolean(sheet.querySelector('#fs-cstake-send')),
      hasCancel: Boolean(sheet.querySelector('#fs-cstake-cancel')),
      title: sheet.querySelector('.fs-sheet__title')
        ? sheet.querySelector('.fs-sheet__title').textContent : null,
    };
  `);

  if (noPrompt.offered) {
    check('countering opens a product sheet, not a browser dialog',
      noPrompt.called === 0 && noPrompt.hasField === true,
      `${noPrompt.called} native dialogs`);
    check('the sheet is titled for the task',
      /Counter/.test(noPrompt.title || ''), String(noPrompt.title));
    check('it offers a deliberate send and a cancel',
      noPrompt.hasSend === true && noPrompt.hasCancel === true);

    const validated = await evaluate(`
      const input = document.getElementById('fs-cstake-input');
      input.value = '25.50';
      document.getElementById('fs-cstake-send').click();
      const fractional = document.getElementById('fs-cstake-error').textContent;
      input.value = '';
      document.getElementById('fs-cstake-send').click();
      const empty = document.getElementById('fs-cstake-error').textContent;
      return { fractional, empty };
    `);
    check('a fractional stake is refused in product language, not rounded',
      /whole number of Credits/.test(validated.fractional), validated.fractional);
    check('an empty stake is refused too', validated.empty.length > 0);

    await evaluate(`
      document.getElementById('fs-cstake-cancel').click();
      return true;
    `);
  } else {
    check('no counterable wager in this session — counter UI not exercised',
      noPrompt.called === 0, 'and no native dialog was reached either');
  }

  /* ── §18–§20 · Account ────────────────────────────────────────────────── */

  section('§18/§20 · Account answers its four questions, detail behind disclosure');

  const account = await evaluate(`
    document.querySelector('.fs-tabbar__item[data-destination="ledger"]').click();
    const panel = document.getElementById('panel-ledger');
    const sections = [...panel.querySelectorAll('[data-disclosure]')];
    const settle = panel.querySelector('#fs-current-settle');
    const anchor = panel.querySelector('.fs-anchor');
    return {
      sub: panel.querySelector('.fs-tabhead__sub').textContent,
      stripLabels: [...panel.querySelectorAll('.fs-strip__label')]
        .map((el) => el.textContent),
      settleVisible: settle
        ? settle.getBoundingClientRect().height > 0 : false,
      settleInsideDisclosure: settle ? Boolean(settle.closest('[data-disclosure]')) : null,
      sectionCount: sections.length,
      allCollapsed: sections.every((s) =>
        s.querySelector('.fs-lsec__body').getBoundingClientRect().height === 0),
      allAriaFalse: sections.every((s) =>
        s.querySelector('[data-lsec-toggle]').getAttribute('aria-expanded') === 'false'),
      toggleTargets: sections.map((s) =>
        Math.round(s.querySelector('[data-lsec-toggle]').getBoundingClientRect().height)),
      anchorText: anchor ? anchor.textContent : null,
      anchorCount: panel.querySelectorAll('.fs-anchor').length,
    };
  `);

  // UIRECON WAVE 1 — `Weekly Min Left` is labelled `Min Left`; same cell, same
  // source. The four questions the strip answers are unchanged.
  check('the top-level strips answer what I have and what is in play',
    ['Available', 'In Play', 'Held', 'Min Left']
      .every((l) => account.stripLabels.includes(l)),
    account.stripLabels.join(' | '));
  check('Current Settle is visible without expanding anything (§20)',
    account.settleVisible === true
    && account.settleInsideDisclosure === false);
  check('the three accounting sections are disclosures',
    account.sectionCount === 3, String(account.sectionCount));
  check('and they start collapsed', account.allCollapsed === true);
  check('with accessible expanded state', account.allAriaFalse === true);
  check('every disclosure toggle meets the 44px target',
    account.toggleTargets.every((h) => h >= 44), account.toggleTargets.join(','));
  check('the trust anchor is exact, and appears once (§19)',
    account.anchorText === 'Real odds. Fantasy stakes. Ledger keeps score.'
    && account.anchorCount === 1, String(account.anchorText));
  check('the subtitle states the served week and phase',
    served.week === null || account.sub.includes(`Week ${served.week}`),
    account.sub);

  const reopened = await evaluate(`
    const section = document.querySelector('#panel-ledger [data-disclosure]');
    const toggle = section.querySelector('[data-lsec-toggle]');
    toggle.click();
    const openHeight = section.querySelector('.fs-lsec__body').getBoundingClientRect().height;
    const rows = section.querySelectorAll('[data-exact-cents]').length;
    const aria = toggle.getAttribute('aria-expanded');
    toggle.click();
    const closedAgain = section.querySelector('.fs-lsec__body').getBoundingClientRect().height;
    return { openHeight, rows, aria, closedAgain };
  `);
  check('opening a disclosure reveals its detail — nothing was deleted (§20)',
    reopened.openHeight > 0 && reopened.rows > 0,
    `${reopened.rows} figures`);
  check('and announces itself', reopened.aria === 'true');
  check('closing it collapses again', reopened.closedAgain === 0);

  /* ── §22 · Rules ──────────────────────────────────────────────────────── */

  section('§22 · Rules & Settings carries no stale terminology');

  const rules = await evaluate(`
    ${GO_RULES}
    const panel = document.getElementById('panel-rules');
    // Open every rule group and every settings row so the SHEET copy is
    // scanned too — most of the terminology lives there, not on the panel.
    let text = panel.textContent;
    for (const row of [...panel.querySelectorAll('[data-rule], [data-setting]')]) {
      row.click();
      text += ' ' + document.getElementById('fs-sheet').textContent;
      const close = document.querySelector('#fs-sheet [data-fs-close]');
      if (close) close.click();
    }
    return { text, labels: [...panel.querySelectorAll('.fs-setrow__label')]
      .map((el) => el.textContent) };
  `);

  for (const stale of ['BAB', 'Economy Stop', 'fourteen', '14 weeks',
    'capped at', '$140 max', 'Buy-In', 'five certified stops']) {
    check(`no stale term on screen: ${stale}`, !rules.text.includes(stale));
  }
  check('no internal module or file path is drawn',
    !/\.py\b|web\/js\//.test(rules.text),
    (rules.text.match(/\S*(\.py\b|web\/js\/)\S*/) || [''])[0]);
  check('the allocation row is named for the governing term',
    rules.labels.includes('Season-Opening Allocation'),
    rules.labels.join(' | '));
  for (const required of ['largest margin', 'Points For', '60 / 30 / 10',
    'official third place', 'championship track']) {
    check(`states: ${required}`, rules.text.includes(required));
  }

  /* ── §30 · readability, measured after the cascade ────────────────────── */

  section('§30 · The WP3B scale, applied to WP3C surfaces');

  const type = await evaluate(`
    const px = (sel) => {
      const el = document.querySelector(sel);
      return el ? Math.round(parseFloat(getComputedStyle(el).fontSize)) : null;
    };
    document.querySelector('.fs-tabbar__item[data-destination="league"]').click();
    return {
      playTitle: px('#panel-league .fs-tabhead__title'),
      playHeading: px('#panel-league .fs-heading__text'),
      cardIdentity: px('#panel-league .fs-wcard__identity'),
      previewRow: px('#panel-league .fs-previewrow'),
      marketLabel: px('#panel-league .fs-market__label'),
    };
  `);
  check(`Play's title is 22–24px (${type.playTitle})`,
    type.playTitle >= 22 && type.playTitle <= 24);
  check(`its section headings are 18–20px (${type.playHeading})`,
    type.playHeading >= 18 && type.playHeading <= 20);
  if (type.cardIdentity !== null) {
    check(`card primary text is 16–17px (${type.cardIdentity})`,
      type.cardIdentity >= 16 && type.cardIdentity <= 17);
    check(`market labels are at least 14px (${type.marketLabel})`,
      type.marketLabel >= 14);
  }

  /* ── Every viewport ───────────────────────────────────────────────────── */

  for (const vp of VIEWPORTS) {
    section(`${vp.width}×${vp.height} — ${vp.label}`);
    await setViewport(vp.width, vp.height);

    const m = await evaluate(`
      const out = { clipped: [], docW: document.documentElement.scrollWidth,
                    innerW: window.innerWidth };
      for (const id of ['standings', 'league', 'action', 'week', 'ledger']) {
        document.querySelector('.fs-tabbar__item[data-destination="' + id + '"]').click();
        const p = document.getElementById('panel-' + id);
        [...p.querySelectorAll('.fs-wcard, .fs-pool, .fs-poolrow, .fs-st__row')]
          .filter((el) => el.scrollHeight > el.clientHeight + 1)
          .forEach((el) => out.clipped.push(id + '/' + el.className.split(' ')[0]));
      }
      document.querySelector('.fs-tabbar__item[data-destination="league"]').click();
      const grid = document.getElementById('fs-pools-grid');
      out.poolCols = grid
        ? new Set([...grid.querySelectorAll('.fs-pool')]
          .map((c) => Math.round(c.getBoundingClientRect().left))).size
        : null;
      return out;
    `);

    check(`${vp.width}: the page does not scroll horizontally`,
      m.docW <= m.innerW, `${m.docW} vs ${m.innerW}`);
    if (m.poolCols !== null) {
      check(`${vp.width}: Play Pools stay a 2-column grid (§11)`,
        m.poolCols === 2, `${m.poolCols} columns`);
    }
    if (vp.width >= 375) {
      check(`${vp.width}: no card on any primary tab clips`,
        m.clipped.length === 0, m.clipped.join(', '));
    } else {
      // WP3C §41 — 320x568 is below the certified set and belongs to WP3E. It
      // is measured for information so the carry-forward carries a number.
      check(`${vp.width}: measured below the certified set — ${m.clipped.length} clipping`,
        true, m.clipped.length ? m.clipped.join(', ') : 'none');
    }
  }

  await setViewport(390, 844);
});

finish('WP3C REV 4.3 GAMEPLAY — BROWSER');
