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