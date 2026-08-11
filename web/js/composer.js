/* ============================================================================
 * FantasyStakes — UI/UX Rev 4.2 · unified Versus composer
 * Sprint 7 Package 2
 *
 * ONE composer. A whole-card tap opens it with no market selected; a market
 * tap opens the same composer with that market selected. There is no
 * intermediate market-selection sheet — choosing a market is a control inside
 * the composer, not a screen in front of it.
 *
 * Fixed order, top to bottom:
 *
 *     identity → ML / Spread / O-U → VIEW MATCHUP PREVIEW → LOCKED | DYNAMIC
 *     → selected-mode explanation → YOUR STAKE $0 → economics → send
 *
 * The stake opens at $0 untouched. Send stays disabled until the market, the
 * mode, the minimum and the funding rules are all satisfied — the same rules,
 * in the same order, that the engine applies.
 * ========================================================================== */

import { escapeHtml } from './components.js';
import { formatCredits } from './credits.js';
import { matchup } from './data/league-data.js';
import { previewSheet } from './preview.js';
import { matchupMarketCells } from './wagercard.js';
import {
  MARKETS,
  MODE_COPY,
  MODE_DYNAMIC,
  MODE_LOCKED,
  composerEconomics,
  createComposerState,
  dynamicCeilingNote,
  lockedFreezeNote,
  marketById,
  parseStakeInput,
  selectMarket,
  selectMode,
  setStakeCents,
  validateComposer,
} from './wager-model.js';

/**
 * Live composer state. Held here rather than in the DOM so pushing the Matchup
 * Preview on top and closing it again cannot lose it.
 * @type {{state: object, matchup: object}|null}
 */
let session = null;

/** @returns {object|null} the current composer state, for tests and callers. */
/* ── The production command hook ────────────────────────────────────────── */

/**
 * How the composer reaches the live issue command.
 *
 * INSTALLED BY THE SHELL, not reached for from in here. The composer would
 * otherwise need to know the acting league, the acting team and how to refresh
 * the Action tab — three pieces of session knowledge that belong to the shell,
 * and that a sheet has no business discovering for itself.
 *
 * Null in `demo`: the component suites render and validate the composer without
 * a server, and a hook that defaulted to issuing would make every isolated
 * render one click away from posting real escrow.
 */
let ISSUE_HOOK = null;

/**
 * @param {null|{leagueId: number, actingTeamId: number, issue: Function,
 *               refresh: Function}} hook
 */
export function setIssueHook(hook) {
  ISSUE_HOOK = hook;
}

/** @returns {boolean} whether a live issue command is installed. */
export function issueBound() {
  return ISSUE_HOOK !== null;
}

export function currentSession() {
  return session;
}

/** Discard the session — called when the sheet stack empties. */
export function endSession() {
  session = null;
}

/**
 * Begin composing a challenge.
 *
 * @param {{matchupId: string, marketId?: string|null, availableCents: number}} spec
 */
export function beginSession(spec) {
  const m = matchup(spec.matchupId);

  // THE AUTHORITATIVE TARGET LIST, or none. `opponents` are `ActionState` rows
  // — real team ids the server served. In demo it is empty, and the composer
  // then has no live target and no issue hook, so the two halves are never
  // half-present.
  const opponents = Array.isArray(spec.opponents) ? spec.opponents : [];

  // S8-P4C-2R: NO NAME BRIDGE. A caller MAY hand in an already-authoritative
  // `opponentTeamId`, but it is honoured only if it appears in the served list
  // — an id that does not is treated as absent rather than trusted. Nothing
  // resolves a target from display text.
  const preselected = opponents.some((o) => o.team_id === spec.opponentTeamId)
    ? spec.opponentTeamId : null;

  session = {
    matchup: m,
    opponents,
    // The acting team's own name, from `/auth/me`. Null in demo.
    actingTeamName: spec.actingTeamName || null,
    state: createComposerState({
      // `id` and `name` remain the ILLUSTRATIVE entry context — the League card
      // this was opened from, which is still a fixture until P4C-3. `teamId` is
      // the only field carrying authority, and it comes from the served list.
      opponent: { id: m.id, name: m.name, teamId: preselected },
      marketId: spec.marketId ?? null,
      mode: MODE_LOCKED,
      availableCents: spec.availableCents,
    }),
  };
  return session;
}

/**
 * Select the authoritative opponent, by team id.
 *
 * BY ID, FROM THE SERVED LIST, and refused otherwise. This is the only way a
 * composer session acquires a real target, which is what makes "the command
 * cannot be steered by display text" a structural property rather than a habit.
 *
 * @param {number} teamId
 */
export function selectOpponent(teamId) {
  if (!session) throw new Error('no composer session');
  const found = session.opponents.find((o) => o.team_id === teamId);
  if (!found) {
    throw new Error(`team ${teamId} is not an authoritative opponent`);
  }
  session.state = {
    ...session.state,
    opponent: {
      ...session.state.opponent,
      teamId: found.team_id,
      authoritativeName: found.team_name,
    },
  };
  return session.state;
}

/** Whether this session can name a real target. @returns {boolean} */
export function hasAuthoritativeOpponent() {
  return Boolean(session && session.state.opponent.teamId !== null
                 && session.state.opponent.teamId !== undefined);
}

/**
 * The composer's sheet spec. Re-invoked whenever the sheet stack returns to
 * this level, so it always renders from current state.
 *
 * @returns {{title: string, sub: string, body: string, onMount: Function}}
 */
export function composerSheet() {
  if (!session) throw new Error('no composer session');
  const { matchup: m, state } = session;

  // THE TITLE FOLLOWS THE AUTHORITATIVE TARGET once one is chosen. Leaving the
  // fixture's opponent name in the title while the command addressed a
  // different team is precisely the confusion this repair removes.
  const opponentName = state.opponent.authoritativeName || m.name;

  // AND THE GM'S OWN NAME COMES FROM THE SESSION in production. `m.you.name` is
  // the fixture's GM; a signed-in GM was being shown someone else's team name
  // above a control that would spend their money.
  const yourName = session.actingTeamName || m.you.name;

  // THE SUBTITLE ASSERTED A RECORD, A RANK AND A WEEK, all three from the
  // illustrative League fixture. None is Action's to source — record and rank
  // are League's and the week is Week's, both P4C-3 — so in production the line
  // says only what it is for. Demo keeps the locked Rev 4.2 line exactly.
  const sub = session.opponents.length
    ? 'Pick your market'
    : `${m.record} · ${m.rank} · Week 5 · pick your market`;

  return {
    title: `${yourName} vs ${opponentName}`,
    sub,
    body:
      opponentSelector(state) +
      marketSelector(m, state) +
      previewButton() +
      modeSelector(state) +
      modeExplanation(state) +
      stakeField(state) +
      economicsBlock(m, state) +
      sendControl(state),
    onMount: bindComposer,
  };
}

/* ── Sections ───────────────────────────────────────────────────────────── */

/**
 * Who the wager is against — the authoritative selector.
 *
 * DRAWN ONLY IN PRODUCTION. In demo there are no served opponents, so this
 * renders nothing and the locked Rev 4.2 composer is unchanged: the fixture
 * opens against one matchup and stays that way.
 *
 * IN PRODUCTION IT IS REQUIRED. The League card that opened this composer is
 * still illustrative until P4C-3, so it carries no authority to hand over — and
 * rather than let its display name stand in for one, the composer asks. `Send`
 * stays disabled until a real team is chosen.
 */
function opponentSelector(state) {
  if (!session.opponents.length) return '';
  const chosen = state.opponent.teamId;
  return (
    '<div class="fs-oppsel" data-opponent-block>' +
    '<div class="fs-oppsel__label">Who are you challenging?</div>' +
    session.opponents.map((o) => (
      '<button type="button" class="fs-btn fs-oppsel__btn'
      + (o.team_id === chosen ? ' is-selected' : '') + '" '
      + `data-composer-opponent="${o.team_id}" `
      + `aria-pressed="${o.team_id === chosen}">`
      + `${escapeHtml(o.team_name)}</button>`
    )).join('') +
    '</div>'
  );
}

function marketSelector(m, state) {
  const cells = matchupMarketCells(m);
  return (
    '<div class="fs-field">' +
    '<div class="fs-field__label">MARKET</div>' +
    '<div class="fs-seg fs-seg--market" role="group" aria-label="Market">' +
    MARKETS.map((market) => {
      const cell = cells.find((c) => c.id === market.id);
      const selected = state.marketId === market.id;
      return (
        `<button type="button" class="fs-seg__opt${selected ? ' is-selected' : ''}" ` +
        `data-composer-market="${escapeHtml(market.id)}" aria-pressed="${selected}">` +
        `<span class="fs-seg__label">${escapeHtml(market.label)}</span>` +
        `<span class="fs-seg__value">${escapeHtml(cell.value)}</span>` +
        '</button>'
      );
    }).join('') +
    '</div></div>'
  );
}

function previewButton() {
  return (
    '<button type="button" class="fs-btn fs-btn--ghost fs-preview-open" data-composer-preview>' +
    'VIEW MATCHUP PREVIEW' +
    '</button>'
  );
}

function modeSelector(state) {
  return (
    '<div class="fs-field">' +
    '<div class="fs-field__label">TERMS</div>' +
    '<div class="fs-seg fs-seg--mode" role="group" aria-label="Terms">' +
    [MODE_LOCKED, MODE_DYNAMIC].map((mode) => {
      const selected = state.mode === mode;
      return (
        `<button type="button" class="fs-seg__opt${selected ? ' is-selected' : ''}" ` +
        `data-composer-mode="${mode}" aria-pressed="${selected}">` +
        `<span class="fs-seg__label">${MODE_COPY[mode].label}</span>` +
        '</button>'
      );
    }).join('') +
    '</div></div>'
  );
}

function modeExplanation(state) {
  const copy = MODE_COPY[state.mode];
  return (
    '<div class="fs-modenote" data-mode-note>' +
    `<div class="fs-modenote__head">${escapeHtml(copy.headline)}</div>` +
    `<div class="fs-modenote__body">${escapeHtml(copy.body)}</div>` +
    '</div>'
  );
}

function stakeField(state) {
  const dollars = state.stakeCents === 0 ? '0' : (state.stakeCents / 100).toFixed(2).replace(/\.00$/, '');
  return (
    '<div class="fs-stake">' +
    '<label class="fs-stake__label" for="fs-stake-input">YOUR STAKE</label>' +
    '<div class="fs-stake__row">' +
    '<span class="fs-stake__cur">$</span>' +
    `<input class="fs-stake__input" id="fs-stake-input" data-composer-stake ` +
    `inputmode="decimal" autocomplete="off" value="${escapeHtml(dollars)}" ` +
    'aria-describedby="fs-stake-hint">' +
    '</div>' +
    '<div class="fs-stake__hint" id="fs-stake-hint" data-stake-hint></div>' +
    '</div>'
  );
}

function economicsBlock(m, state) {
  return `<div class="fs-econ" data-econ>${economicsRows(m, state)}</div>`;
}

/**
 * The economics rows. Rendered separately so typing updates them without
 * re-rendering the field the GM is typing into.
 */
function economicsRows(m, state) {
  const line = { odds: m.ml };
  const econ = composerEconomics(state, line);
  const rows = [
    { label: 'Your stake', cents: econ.yourStakeCents },
    { label: 'Opponent stake', cents: econ.opponentStakeCents },
    { label: 'Pot', cents: econ.potCents, anchor: true },
    { label: 'You win', cents: econ.winCents, tone: 'is-positive' },
    { label: 'You lose', cents: econ.loseCents, tone: 'is-negative' },
  ];

  const note = state.mode === MODE_DYNAMIC ? dynamicCeilingNote(econ) : lockedFreezeNote();

  return (
    rows.map((row) => (
      `<div class="fs-econ__row${row.anchor ? ' is-anchor' : ''}">` +
      `<span class="fs-econ__label">${escapeHtml(row.label)}</span>` +
      `<span class="fs-econ__value fs-money ${row.tone || ''}" data-exact-cents="${row.cents}">` +
      `${escapeHtml(formatCredits(row.cents))}</span>` +
      '</div>'
    )).join('') +
    `<div class="fs-econ__note">${escapeHtml(note)}</div>`
  );
}

function sendControl(state) {
  const verdict = validateComposer(state);
  // A LIVE SEND NEEDS A REAL TARGET. Checked here rather than inside
  // `validateComposer`, which is shared with the demo composer that has no
  // target to choose and would otherwise be permanently invalid.
  const needsTarget = Boolean(session.opponents.length)
    && (state.opponent.teamId === null || state.opponent.teamId === undefined);
  const ok = verdict.ok && !needsTarget;
  const message = needsTarget
    ? 'Choose who you are challenging.'
    : (verdict.ok ? '' : (verdict.hint || verdict.reasons[0]));
  return (
    '<div class="fs-send" data-send-block>' +
    `<div class="fs-send__why" data-send-why>${escapeHtml(message)}</div>` +
    `<button type="button" class="fs-btn fs-btn--gold fs-send__btn" data-composer-send ` +
    `${ok ? '' : 'disabled'}>Send Challenge</button>` +
    '</div>'
  );
}

/* ── Binding ────────────────────────────────────────────────────────────── */

function bindComposer(host, api) {
  host.querySelectorAll('[data-composer-market]').forEach((el) => {
    el.addEventListener('click', () => {
      session.state = selectMarket(session.state, el.dataset.composerMarket);
      api.rerender();
    });
  });

  host.querySelectorAll('[data-composer-opponent]').forEach((el) => {
    el.addEventListener('click', () => {
      selectOpponent(Number(el.dataset.composerOpponent));
      api.rerender();
    });
  });

  host.querySelectorAll('[data-composer-mode]').forEach((el) => {
    el.addEventListener('click', () => {
      session.state = selectMode(session.state, el.dataset.composerMode);
      api.rerender();
    });
  });

  const preview = host.querySelector('[data-composer-preview]');
  if (preview) {
    // Pushed on top: the composer stays underneath with its state intact.
    preview.addEventListener('click', () => api.push(() => previewSheet(session.matchup)));
  }

  const input = host.querySelector('[data-composer-stake]');
  if (input) {
    input.addEventListener('input', () => {
      const parsed = parseStakeInput(input.value);
      if (parsed.error) {
        showStakeError(host, parsed.error);
        return;
      }
      session.state = setStakeCents(session.state, parsed.cents);
      refreshDerived(host);
    });
  }

  const send = host.querySelector('[data-composer-send]');
  if (send && ISSUE_HOOK) {
    send.addEventListener('click', async () => {
      const { state } = session;
      // DISABLED FOR THE DURATION, so a second click cannot issue a second
      // funded challenge. Escrow posts at issue now: a double-send is two real
      // stakes, not two harmless rows.
      send.disabled = true;
      const why = host.querySelector('[data-send-why]');
      if (why) why.textContent = 'Sending…';
      try {
        await ISSUE_HOOK.issue({
          challengerTeamId: ISSUE_HOOK.actingTeamId,
          // THE SELECTED AUTHORITATIVE TEAM ID, and nothing else. No name, no
          // fixture id, no lookup — the value came from the served opponent
          // list at the moment the GM chose it.
          challengedTeamId: state.opponent.teamId,
          week: ISSUE_HOOK.week,
          wagerType: marketById(state.marketId).persisted,
          amountCents: state.stakeCents,
          mode: state.mode,
        });
        // THE AUTHORITATIVE REFRESH IS THE SUCCESS PATH. Nothing here writes a
        // card or moves a figure — the tab re-reads and draws what is true.
        await ISSUE_HOOK.refresh();
        api.close();
      } catch (error) {
        send.disabled = false;
        if (why) why.textContent = ISSUE_HOOK.explain(error);
      }
    });
  }

  refreshDerived(host);
}

/**
 * Update everything that follows from the stake, in place.
 *
 * In place, deliberately: re-rendering the whole sheet on each keystroke would
 * tear out the input the GM is typing into and drop the caret.
 */
function refreshDerived(host) {
  const { matchup: m, state } = session;

  const econ = host.querySelector('[data-econ]');
  if (econ) econ.innerHTML = economicsRows(m, state);

  const verdict = validateComposer(state);
  const needsTarget = Boolean(session.opponents.length)
    && (state.opponent.teamId === null || state.opponent.teamId === undefined);

  const send = host.querySelector('[data-composer-send]');
  if (send) send.disabled = !verdict.ok || needsTarget;

  const why = host.querySelector('[data-send-why]');
  if (why) {
    why.textContent = needsTarget
      ? 'Choose who you are challenging.'
      : (verdict.ok ? '' : (verdict.hint || verdict.reasons[0]));
  }

  const hint = host.querySelector('[data-stake-hint]');
  if (hint) {
    hint.textContent = state.touched ? '' : 'Wagers fund from Weekly Min first, then Wallet.';
    hint.classList.remove('is-error');
  }
}

function showStakeError(host, message) {
  const hint = host.querySelector('[data-stake-hint]');
  if (hint) {
    hint.textContent = message;
    hint.classList.add('is-error');
  }
  const send = host.querySelector('[data-composer-send]');
  if (send) send.disabled = true;
}