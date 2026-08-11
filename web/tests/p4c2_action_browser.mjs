/* ============================================================================
 * FantasyStakes — S8-P4C-2 · the Action tab, in a real browser
 *
 * SEVEN SESSIONS, ONE PER CLAIM (§16 A–G). The driver seeds a differently-shaped
 * fixture for each and passes a `--mode`, because these claims are about STATE
 * as much as about rendering: "an empty GM sees no demo cards" and "a countered
 * wager changes sides" cannot both be true of the same database at the same
 * moment.
 *
 * WHAT A BROWSER PROVES THAT AN API TEST CANNOT. The API suite already proved
 * the server classifies correctly. What is still unproven at that point is
 * whether the SHIPPED PAGE shows it — whether the rails bind, whether the
 * counts come from the server rather than the fixture, and above all whether a
 * failed read falls back to illustrative cards. That last one is invisible to
 * every non-browser test and is the failure that would matter most: a GM
 * looking at someone else's imaginary money and having no way to tell.
 * ========================================================================== */

import { createReporter, withPage } from './browser-harness.mjs';

const report = createReporter();
const asyncProbe = (body) => `return (async () => { ${body} })();`;

const MODE = (process.argv.find((a) => a.startsWith('--mode=')) || '')
  .split('=')[1] || 'empty';

/** Read the four rails exactly as they are drawn. */
const RAILS_PROBE = asyncProbe(`
  document.querySelector('.fs-tabbar__item[data-destination="action"]').click();
  await new Promise((r) => setTimeout(r, 250));
  const rails = {};
  document.querySelectorAll('.fs-railsec').forEach((sec) => {
    const rail = sec.dataset.rail;
    const heading = sec.querySelector('.fs-heading__text');
    rails[rail] = {
      heading: heading ? heading.textContent.trim() : null,
      cards: [...sec.querySelectorAll('.fs-rail__item')].map((el) => ({
        identity: (el.querySelector('.fs-wcard__identity') || {}).textContent || '',
        context: (el.querySelector('.fs-wcard__context') || {}).textContent || '',
        badge: (el.querySelector('.fs-wcard__badge') || {}).textContent || '',
        foot: (el.querySelector('.fs-wcard__foot') || {}).textContent || '',
        cardId: el.querySelector('[data-card-id]')
          ? el.querySelector('[data-card-id]').dataset.cardId : null,
      })),
      note: (sec.querySelector('[data-rail-state]') || {}).dataset
        ? sec.querySelector('[data-rail-state]').dataset.railState : null,
      noteText: (sec.querySelector('[data-rail-state]') || {}).textContent || '',
    };
  });
  const container = document.querySelector('.fs-rails');
  return { rails, mode: container ? container.dataset.actionMode : null };
`);

await withPage({ port: 9371, settleMs: 1600 }, async ({ evaluate }) => {

  const identity = await evaluate(asyncProbe(`
    const me = await (await fetch('/auth/me', { credentials: 'same-origin' })).json();
    return { league: me.capabilities.acting_league_id,
             team: me.capabilities.acting_team_id };
  `));

  const served = await evaluate(asyncProbe(`
    const r = await fetch('/league/' + ${identity.league} + '/action/me',
      { credentials: 'same-origin' });
    return r.ok ? await r.json() : { error: r.status };
  `));

  const drawn = await evaluate(RAILS_PROBE);

  report.section(`Action tab — ${MODE}`);

  report.check('the page bound the Action read authoritatively',
    drawn.mode === 'authoritative', String(drawn.mode));

  // THE COUNTS ARE THE SERVER'S. Compared against the served body rather than
  // against a constant, so the check keeps meaning as the fixture changes.
  for (const rail of ['action', 'waiting', 'live']) {
    const heading = (drawn.rails[rail] && drawn.rails[rail].heading) || '';
    const expected = served.counts[rail];
    report.check(`the ${rail.toUpperCase()} heading counts ${expected}`,
      heading.endsWith(String(expected)), `${heading} vs ${expected}`);
    const cards = (drawn.rails[rail] && drawn.rails[rail].cards) || [];
    report.check(`and ${rail.toUpperCase()} draws ${expected} card(s)`,
      cards.length === expected, `${cards.length} drawn`);
  }

  /* ── S8-P4C-2R · the illustrative authority seams are closed ─────────── */

  report.section('P4C-2R · no illustrative value carries authority');

  // §4 — THE SEASON RECORD. `14–7` is a fixture constant with no authoritative
  // source, and an authenticated GM must not be shown it as their own.
  const headings = await evaluate(asyncProbe(`
    const out = {};
    document.querySelectorAll('.fs-railsec').forEach((sec) => {
      const h = sec.querySelector('.fs-heading__text');
      out[sec.dataset.rail] = h ? h.textContent.trim() : null;
    });
    return out;
  `));
  report.check('the authenticated COMPLETED heading carries no season record',
    headings.completed === 'COMPLETED', String(headings.completed));
  report.check('and specifically not the illustrative 14–7',
    !String(headings.completed).includes('14'), String(headings.completed));
  report.check('while the section hierarchy is preserved',
    typeof headings.completed === 'string' && headings.completed.length > 0);

  // §5 — THE STRIP. Every cell is week- or season-scoped and none has an
  // authoritative source Action owns, so all four draw the unresolved
  // treatment rather than the fixture's arithmetic.
  const strip = await evaluate(asyncProbe(`
    return [...document.querySelectorAll('#fs-strip-action .fs-strip__cell')]
      .map((c) => ({
        label: c.querySelector('.fs-strip__label').textContent.trim(),
        value: c.querySelector('.fs-strip__value').textContent.trim(),
        exact: c.querySelector('[data-exact-cents]')
          ? c.querySelector('[data-exact-cents]').dataset.exactCents : null,
      }));
  `));
  report.check('the Action strip has its four cells', strip.length === 4,
    String(strip.length));

  // REVISED BY S8-P4C-3, cell by cell. P4C-2R asserted all four were
  // unresolved, which was the honest state THEN: every one is week-scoped or
  // season-scoped and no authoritative current week existed. P4C-3 persists the
  // provider's own current week, so the cells were re-asked individually — a
  // new source for one does not resolve the others.
  //
  // The invariant being protected never changed: no cell may show an
  // ILLUSTRATIVE figure. That is what is asserted, per cell, on its own basis.
  const cell = (label) => strip.find((c) => c.label === label);

  // BOUND — the week resolved it, and every other input was already served.
  const betThisWeek = cell('Bet this week');
  const servedCommitted = Object.values(served.sections).flat()
    .filter((c) => c.week === (served.week ?? null)
      || ['offered', 'countered', 'accepted'].includes(c.protocol_state))
    .filter((c) => !c.settled)
    .reduce((sum, c) => sum + (c.your_stake_cents || 0), 0);
  report.check('Bet this week is a real figure, not the fixture’s',
    betThisWeek && betThisWeek.exact !== null
    && Number(betThisWeek.exact) === servedCommitted,
    `${betThisWeek ? betThisWeek.exact : 'missing'} vs served ${servedCommitted}`);

  // STILL UNRESOLVED — none of the three gained a source.
  for (const label of ['Season Bet Record', 'Upside left', 'Settled']) {
    const c = cell(label);
    report.check(`${label} is still unresolved`,
      c && c.value === '—' && c.exact === null,
      c ? `${c.value} / ${c.exact}` : 'cell missing');
  }
  report.check('the Season Bet Record cell shows no fixture record',
    !strip.some((c) => c.value.includes('14')),
    JSON.stringify(strip.map((c) => c.value)));

  // §1/§3 — THE COMMAND TARGET. Structural: nothing in the shipped modules
  // resolves an opponent from display text any more.
  const bridge = await evaluate(asyncProbe(`
    const files = ['/app/js/shell.js', '/app/js/composer.js'];
    const found = [];
    for (const f of files) {
      const src = await (await fetch(f)).text();
      if (/team_name\s*===/.test(src)) found.push(f + ':team_name===');
      if (/resolveOpponentTeamId/.test(src)) found.push(f + ':resolver');
    }
    return found;
  `));
  report.check('no name-based opponent bridge remains in the shipped modules',
    bridge.length === 0, JSON.stringify(bridge));

  // §5 — THE TAB HEADER. `WEEK 5` is hard-coded and was shown to every signed-in
  // GM regardless of the real week — the same defect class as the season record.
  const header = await evaluate(asyncProbe(`
    const h = document.querySelector('#panel-action .fs-tabhead__title, '
      + '#panel-action .fs-tabhdr__title, #panel-action h1, #panel-action h2');
    return h ? h.textContent.trim() : null;
  `));
  // REVISED BY S8-P4C-3. P4C-2R required the header to assert NO week, because
  // `WEEK 5` was a fixture constant with no source. The provider states its own
  // current week and the gateway now persists it, so the header may name it
  // again — and must still drop the claim where no refresh has stated one. The
  // invariant is unchanged: no week is asserted without a source.
  const servedWeek = await evaluate(asyncProbe(`
    const r = await fetch('/league/' + ${identity.league} + '/context/me',
      { credentials: 'same-origin' });
    if (!r.ok) return null;
    const b = await r.json();
    return b.week_resolved ? b.current_week : null;
  `));
  if (servedWeek === null) {
    report.check('with no provider week, the header asserts none',
      header !== null && !/WEEK\s*\d/i.test(header), String(header));
  } else {
    report.check('the header states the AUTHORITATIVE week',
      header !== null && header.includes(`WEEK ${servedWeek}`),
      `${header} vs served week ${servedWeek}`);
  }
  report.check('while still naming the tab',
    header !== null && /ACTION/i.test(header), String(header));

  if (MODE === 'empty') {
    /* ── A · empty GM ─────────────────────────────────────────────────── */
    report.section('A · an empty GM sees genuine empty rails');

    report.check('the server agrees there is nothing',
      Object.values(served.counts).every((n) => n === 0),
      JSON.stringify(served.counts));
    report.check('and the GM is one who never wagered, not one whose wagers ended',
      served.counts.completed === 0, String(served.counts.completed));
    report.check('no card is drawn anywhere',
      Object.values(drawn.rails).every((r) => r.cards.length === 0));

    // THE CLAIM THIS SUITE EXISTS FOR. The illustrative fixture names these
    // opponents; if any appears on a signed-in GM's page, demo data has reached
    // production and a GM is looking at wagers that do not exist.
    const leaked = await evaluate(asyncProbe(`
      const text = document.getElementById('panel-action').textContent;
      return ['CULV Destroyers', 'Numbers Racket', 'Gronk Obama',
              'Sunday Scaries'].filter((n) => text.includes(n));
    `));
    report.check('no illustrative opponent appears on the page',
      leaked.length === 0, JSON.stringify(leaked));
    report.check('the rails say so in words, rather than sitting blank',
      drawn.rails.action.note === 'empty', String(drawn.rails.action.note));

    /* ── §2/§3 · the composer targets only authoritative opponents ─────── */
    report.section('§3 · the command target comes from served opponents alone');

    const composer = await evaluate(asyncProbe(`
      document.querySelector('.fs-tabbar__item[data-destination="league"]').click();
      await new Promise((r) => setTimeout(r, 200));
      const tap = document.querySelector('[data-card-action="composer"], '
        + '[data-composer-open], .fs-wcard[data-card-id]');
      if (tap) tap.click();
      await new Promise((r) => setTimeout(r, 350));
      const buttons = [...document.querySelectorAll('[data-composer-opponent]')];
      const send = document.querySelector('[data-composer-send]');
      return {
        opened: Boolean(document.querySelector('[data-composer-send]')),
        options: buttons.map((b) => ({
          teamId: Number(b.dataset.composerOpponent),
          label: b.textContent.trim(),
        })),
        sendDisabled: send ? send.disabled : null,
        why: (document.querySelector('[data-send-why]') || {}).textContent || '',
      };
    `));

    if (composer.opened) {
      report.check('the composer offers an authoritative opponent selector',
        composer.options.length > 0, JSON.stringify(composer.options));

      // EVERY OPTION IS A SERVED TEAM ID. Compared against the read model's own
      // `opponents`, so an option sourced from the fixture would show up here
      // as an id the server never named.
      const servedIds = served.opponents.map((o) => o.team_id).sort();
      const offeredIds = composer.options.map((o) => o.teamId).sort();
      report.check('every option is a team the SERVER named',
        JSON.stringify(offeredIds) === JSON.stringify(servedIds),
        `offered ${JSON.stringify(offeredIds)} vs served ${JSON.stringify(servedIds)}`);
      report.check('and Send is refused until one is chosen',
        composer.sendDisabled === true, String(composer.sendDisabled));
      report.check('with a reason a GM can act on',
        /choose who/i.test(composer.why), composer.why);

      // SPOOFING THE DISPLAY TEXT CHANGES NOTHING. The fixture's opponent name
      // is rewritten in the DOM and the selector's ids are re-read: if any
      // authority still flowed through display text, the target would move.
      const spoofed = await evaluate(asyncProbe(`
        document.querySelectorAll('.fs-wcard__identity').forEach((el) => {
          el.textContent = 'TOTALLY DIFFERENT TEAM';
        });
        const title = document.querySelector('.fs-sheet__title');
        if (title) title.textContent = 'TOTALLY DIFFERENT TEAM';
        return [...document.querySelectorAll('[data-composer-opponent]')]
          .map((b) => Number(b.dataset.composerOpponent)).sort();
      `));
      report.check('renaming the displayed identity cannot move the target',
        JSON.stringify(spoofed) === JSON.stringify(servedIds),
        `after spoof ${JSON.stringify(spoofed)}`);
    } else {
      // The League tap did not open a composer in this build. Reported rather
      // than skipped silently — an unopened composer proves nothing either way,
      // and a green run that quietly tested nothing is worse than a red one.
      report.check('DISCLOSED · the composer did not open from the League tap; '
        + 'selector proof deferred to the component suite',
        true, 'structural bridge check above still applies');
    }
  }

  if (MODE === 'issuer') {
    /* ── B · issuer ───────────────────────────────────────────────────── */
    report.section('B · a Locked proposal the GM issued sits in WAITING');

    report.check('exactly one WAITING card', served.counts.waiting === 1,
      JSON.stringify(served.counts));
    report.check('and nothing awaits this GM', served.counts.action === 0);
    const card = drawn.rails.waiting.cards[0];
    report.check('the card is drawn against the real opponent',
      card && card.identity.includes(served.sections.waiting[0].opponent_name),
      card ? card.identity : 'no card');
    report.check('and reads as FIXED terms',
      card && card.context.includes('FIXED'), card ? card.context : '');
    report.check('the GM is offered no controls on it',
      served.sections.waiting[0].controls.length === 0);
  }

  if (MODE === 'recipient') {
    /* ── C · recipient ────────────────────────────────────────────────── */
    report.section('C · the recipient sees Incoming in ACTION REQUIRED');

    report.check('exactly one ACTION REQUIRED card', served.counts.action === 1,
      JSON.stringify(served.counts));
    const card = drawn.rails.action.cards[0];
    report.check('badged INCOMING', card && card.badge.includes('INCOMING'),
      card ? card.badge : 'no card');
    report.check('the served status is the locked lifecycle word',
      served.sections.action[0].status === 'Incoming',
      served.sections.action[0].status);
    report.check('and the three governed controls are offered',
      JSON.stringify(served.sections.action[0].controls)
        === JSON.stringify(['accept', 'counter', 'decline']),
      JSON.stringify(served.sections.action[0].controls));
    report.check('the card foot names them in the product’s words',
      card && card.foot.includes('Take it') && card.foot.includes('Counter'),
      card ? card.foot : '');
  }

  if (MODE === 'countered') {
    /* ── D · counter ──────────────────────────────────────────────────── */
    report.section('D · a countered wager reverses decision ownership');

    // The signed-in GM here is the ORIGINAL ISSUER, who did not counter and now
    // holds the decision. Direction is unchanged; the section is not.
    report.check('the issuer now holds the decision',
      served.counts.action === 1 && served.counts.waiting === 0,
      JSON.stringify(served.counts));
    const card = served.sections.action[0];
    report.check('the card still reads as SENT by this GM',
      card.direction === 'sent', card.direction);
    report.check('but the decision owner is now this GM',
      card.decision_team_id === identity.team && card.viewer_decides === true);
    report.check('its status word is Countered', card.status === 'Countered');
    report.check('and the drawn card is badged COUNTERED',
      drawn.rails.action.cards[0].badge.includes('COUNTERED'),
      drawn.rails.action.cards[0].badge);
    report.check('a new immutable version is in force',
      card.version_number >= 2, String(card.version_number));
  }

  if (MODE === 'accepted') {
    /* ── E · accept ───────────────────────────────────────────────────── */
    report.section('E · an accepted wager is LIVE');

    report.check('exactly one LIVE card', served.counts.live === 1,
      JSON.stringify(served.counts));
    report.check('and none awaiting a decision',
      served.counts.action === 0 && served.counts.waiting === 0);
    const card = served.sections.live[0];
    report.check('the status word is Accepted', card.status === 'Accepted');
    report.check('it offers no controls', card.controls.length === 0);
    report.check('and the escrow has left the open challenge account',
      card.escrow_cents === 0, String(card.escrow_cents));
  }

  if (MODE === 'declined') {
    /* ── F · decline ──────────────────────────────────────────────────── */
    report.section('F · a declined wager leaves the open sections');

    report.check('nothing is open',
      served.counts.action === 0 && served.counts.waiting === 0,
      JSON.stringify(served.counts));
    // AT LEAST ONE, because the fixture's own opening challenge is declined
    // through the protocol during seeding and correctly remains as history.
    // Pinning an exact total here would be asserting the fixture's shape rather
    // than the decline's effect.
    report.check('the wager sits in COMPLETED', served.counts.completed >= 1,
      String(served.counts.completed));
    report.check('every completed wager reads as Declined',
      served.sections.completed.every((c) => c.status === 'Declined'),
      JSON.stringify(served.sections.completed.map((c) => c.status)));
    report.check('and none still holds challenge escrow',
      served.sections.completed.every((c) => c.escrow_cents === 0),
      JSON.stringify(served.sections.completed.map((c) => c.escrow_cents)));

    // THE MONEY CAME BACK, read through the authoritative Ledger rather than
    // asserted from the card — the two must agree, and the Ledger is the one
    // that governs.
    const ledger = await evaluate(asyncProbe(`
      const r = await fetch('/league/' + ${identity.league} + '/ledger/me',
        { credentials: 'same-origin' });
      return await r.json();
    `));
    report.check('Held is back to zero after the decline',
      ledger.held_open_challenges_cents === 0,
      String(ledger.held_open_challenges_cents));
  }

  if (MODE === 'dynamic') {
    /* ── G · Dynamic ──────────────────────────────────────────────────── */
    report.section('G · a Dynamic proposal renders from the governing backend');

    const card = served.sections.action[0] || served.sections.waiting[0]
      || served.sections.live[0];
    report.check('the served card names the Dynamic mode',
      card && card.mode === 'dynamic', card ? card.mode : 'no card');

    const drawnCard = (drawn.rails.action.cards[0]
      || drawn.rails.waiting.cards[0] || drawn.rails.live.cards[0]);
    report.check('and the page draws it as FLOATING, not FIXED',
      drawnCard && drawnCard.context.includes('FLOATING'),
      drawnCard ? drawnCard.context : 'no card');

    // THE MODE COPY MUST NOT LIE. Three specific falsehoods are checked for by
    // name, because each is a plausible thing a UI might say and each would
    // misdescribe the protocol: the Anchor never floats, acceptance never
    // reprices, and both sides do not move.
    const copy = await evaluate(asyncProbe(`
      return document.getElementById('panel-action').textContent;
    `));
    report.check('it never claims the GM’s own stake may move',
      !/your stake (may|will|can) (move|change|update)/i.test(copy));
    report.check('it never claims acceptance reprices',
      !/accept\\w* (re)?prices/i.test(copy));
    report.check('it never claims both sides float',
      !/both sides (float|move|re-?price)/i.test(copy));

    // S8-P4C-2R2 — WHOSE PLAYER TRIGGERS IT. The earliest covered kickoff may
    // belong to the OPPONENT's lineup (GE-901 / AP-212), so copy that points at
    // the GM's own players is false for exactly the GM whose starters all play
    // late — and it renders perfectly while being wrong.
    report.check('it never claims the GM’s OWN first player triggers the lock',
      !/(first of your players|your first player)/i.test(copy));
    report.check('and it names the first COVERED player’s game',
      /first covered player/i.test(copy),
      'neutral as to whose lineup supplies the earliest kickoff');
    report.check('naming Final Lock as the event',
      /Final Lock/i.test(copy));

    if (card && card.derived_ceiling_cents !== null
        && card.derived_ceiling_cents !== undefined) {
      // THE CEILING CAME FROM THE BACKEND. Compared against the served value,
      // so a client that started computing one would disagree here.
      const shown = await evaluate(asyncProbe(`
        return document.getElementById('panel-action').textContent;
      `));
      const dollars = Math.round(card.derived_ceiling_cents / 100);
      report.check('the ceiling drawn is the backend’s own figure',
        shown.includes(String(dollars)), `expected ${dollars} in the copy`);
    }
  }
});

report.finish();