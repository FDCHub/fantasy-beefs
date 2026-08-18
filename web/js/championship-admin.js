/* ============================================================================
 * FantasyStakes — commissioner championship controls
 *
 * The certified RC2 championship writes already exist and are commissioner-only
 * on the server. This module is the surface for them and nothing more: it holds
 * no economics, derives no amount, and decides no lifecycle state. Every figure
 * it shows came from `/championship/results` or `/championship/config`, and
 * every refusal it shows is the server's own reason code, printed verbatim.
 *
 * WHY REFUSALS ARE SHOWN RATHER THAN TRANSLATED. The backend refuses with stable
 * codes — FS_CHAMPIONSHIP_NOT_ACTIVATED, FS_CHAMPIONSHIP_FIELD_CHANGED_AFTER_
 * ACTIVATION, FS_CORRECTION_POOL_CLASS_NOT_CORRECTABLE and their siblings — each
 * of which names a specific, actionable condition. Restating them in friendlier
 * words here would create a second vocabulary that drifts from the one in the
 * logs and the runbook, so the code and the server's sentence are surfaced
 * together.
 *
 * IRREVERSIBLE ACTIONS ASK FIRST. Freeze closes the scoring window and settle
 * distributes a fixed pot that RC2 will never claw back. Both are two-step: the
 * sheet states what will happen and what cannot be undone, and only an explicit
 * confirm submits.
 * ========================================================================== */

import { escapeHtml, note, sectionHeading } from './components.js';
import { formatCredits } from './credits.js';

/** The certified RC2 championship routes. Named, never assembled ad hoc. */
export const CHAMPIONSHIP_ROUTES = Object.freeze({
  config: 'GET /league/{league_id}/championship/config',
  setConfig: 'PUT /league/{league_id}/championship/config',
  activate: 'POST /league/{league_id}/championship/activate',
  freeze: 'POST /league/{league_id}/championship/freeze',
  settle: 'POST /league/{league_id}/championship/settle',
  results: 'GET /league/{league_id}/championship/results',
  corrections: 'GET /league/{league_id}/championship/corrections',
  correct: 'POST /league/{league_id}/championship/corrections',
});

export const COMPETITION_TYPES = Object.freeze(['versus', 'prop_pool']);

/**
 * Which championship actions the server could accept in this state.
 *
 * ADVISORY ONLY. The server is the authority and refuses on its own terms; this
 * exists so the surface does not offer a button whose only possible outcome is a
 * 409. A disabled control here never substitutes for the backend guard.
 */
export function availableActions(results, config) {
  const lifecycle = (results && results.lifecycle) || 'LIVE';
  const activated = Boolean(config && config.configured && config.frozen);
  return Object.freeze({
    editConfig: !(config && config.frozen),
    activate: !activated,
    freeze: lifecycle === 'LIVE',
    settle: lifecycle === 'FINAL',
    correct: lifecycle === 'FROZEN' || lifecycle === 'FINAL',
    lifecycle,
  });
}

/** One-line human summary of the lifecycle, with the outstanding count. */
export function lifecycleSummary(results) {
  const lifecycle = (results && results.lifecycle) || 'LIVE';
  const open = (results && results.unresolved) ? results.unresolved.length : 0;
  switch (lifecycle) {
    case 'PAID':
      return 'PAID — the championship pot has been distributed.';
    case 'FINAL':
      return 'FINAL — every eligible result is authoritative. The pot can be settled.';
    case 'FROZEN':
      return `FROZEN — scoring is closed, ${open} eligible result`
        + `${open === 1 ? '' : 's'} still outstanding. The pot cannot be settled yet.`;
    default:
      return 'LIVE — the championship chase is running and has not been frozen.';
  }
}

/** The server's refusal, shown as it was given. */
export function refusalNote(detail) {
  if (!detail) return '';
  return `<p class="fs-adm__refusal" role="alert">${escapeHtml(String(detail))}</p>`;
}

/* ── Configuration ──────────────────────────────────────────────────────── */

export function configSection(config) {
  if (!config) return sectionHeading('Championship contributions') + note('Unavailable.');
  const frozen = Boolean(config.frozen);
  const rows =
    '<dl class="fs-adm__kv">'
    + '<dt>Yahoo Championship Contribution</dt>'
    + `<dd>${escapeHtml(formatCredits(config.yahoo_championship_contribution_cents))}</dd>`
    + '<dt>FantasyStakes Championship Contribution</dt>'
    + `<dd>${escapeHtml(formatCredits(config.fantasystakes_championship_contribution_cents))}</dd>`
    + '</dl>';
  return (
    sectionHeading('Championship contributions')
    + rows
    + note(frozen
      ? 'Frozen at activation. Contributions cannot be changed for this season.'
      : 'Editable until the championship is activated. The two contributions are '
        + 'independent; the FantasyStakes contribution defaults to the Yahoo amount.')
    + (frozen ? '' : '<button type="button" class="fs-adm__btn" '
      + 'data-fs-champ-action="edit-config">Edit FantasyStakes contribution</button>')
  );
}

export function configSheet(config) {
  const current = config
    ? config.fantasystakes_championship_contribution_cents : 8000;
  return {
    title: 'FantasyStakes Championship Contribution',
    sub: 'Per GM, whole Credits. Freezes at activation.',
    body:
      '<form class="fs-adm__form" data-fs-champ-form="config">'
      + '<label class="fs-adm__label" for="fs-champ-contrib">Contribution (Credits)</label>'
      + '<input class="fs-adm__input" id="fs-champ-contrib" name="contribution" '
      + `type="number" min="1" max="1000" step="1" value="${escapeHtml(String(Math.round(current / 100)))}">`
      + note('This is the whole of each GM’s FantasyStakes Championship '
             + 'Contribution and the only source of the FantasyStakes '
             + 'Championship Pot. It cannot be changed once the championship is '
             + 'activated.')
      + '<button type="submit" class="fs-adm__btn fs-adm__btn--primary">Save contribution</button>'
      + '</form>',
  };
}

/* ── Irreversible actions ───────────────────────────────────────────────── */

export function confirmSheet(action, results) {
  const specs = {
    activate: {
      title: 'Activate the FantasyStakes Championship',
      sub: 'Funds the fixed pot and freezes both contributions.',
      warning: 'Each GM is advanced their FantasyStakes Championship '
        + 'Contribution and it is committed to the fixed pot. The funded field '
        + 'and both contributions freeze permanently for this season.',
    },
    freeze: {
      title: 'Freeze the championship',
      sub: 'Closes the scoring window and the funded field.',
      warning: 'Championship scoring ends here. Postseason FantasyStakes play '
        + 'may still move Credits but will no longer change Championship Score. '
        + 'This cannot be undone.',
    },
    settle: {
      title: 'Settle the FantasyStakes Championship',
      sub: 'Distributes the fixed pot 60 / 30 / 10.',
      warning: 'The pot is paid to the final podium. After this, an '
        + 'authoritative correction is refused and there is no clawback and no '
        + 'second distribution. This cannot be undone.',
    },
  };
  const spec = specs[action];
  if (!spec) return null;
  const pot = results && results.pot_cents !== null
    && results.pot_cents !== undefined
    ? note(`Fixed pot: ${formatCredits(results.pot_cents)}.`) : '';
  return {
    title: spec.title,
    sub: spec.sub,
    body:
      `<p class="fs-adm__warn">${escapeHtml(spec.warning)}</p>`
      + pot
      + (action === 'settle' ? note(lifecycleSummary(results)) : '')
      + '<button type="button" class="fs-adm__btn fs-adm__btn--danger" '
      + `data-fs-champ-confirm="${escapeHtml(action)}">`
      + `${escapeHtml(spec.title)}</button>`,
  };
}

/* ── Authoritative corrections ──────────────────────────────────────────── */

/**
 * The correction form.
 *
 * IT CANNOT EXPRESS AN AMOUNT, AND THAT IS THE POINT. The commissioner names the
 * contest and states the corrected RESULT; the server derives the Credits from
 * posted ledger state. There is no cents field, no score field and no delta
 * field anywhere in this form — a correction that let somebody type a number
 * would be an edit of the championship rather than a restatement of a contest.
 */
export function correctionSheet() {
  return {
    title: 'Authoritative correction',
    sub: 'Restate one eligible regular-season contest.',
    body:
      '<form class="fs-adm__form" data-fs-champ-form="correction">'
      + '<label class="fs-adm__label" for="fs-corr-type">Competition</label>'
      + '<select class="fs-adm__input" id="fs-corr-type" name="competition_type">'
      + '<option value="versus">FantasyStakes matchup</option>'
      + '<option value="prop_pool">FantasyStakes prop pool</option>'
      + '</select>'

      + '<label class="fs-adm__label" for="fs-corr-ref">Contest id</label>'
      + '<input class="fs-adm__input" id="fs-corr-ref" name="contest_ref" '
      + 'type="number" min="1" step="1" required>'

      + '<fieldset class="fs-adm__fieldset" data-fs-corr="versus">'
      + '<legend class="fs-adm__label">Corrected matchup result</legend>'
      + '<label><input type="radio" name="outcome" value="winner" checked> '
      + 'A GM won</label>'
      + '<label><input type="radio" name="outcome" value="push"> Push</label>'
      + '<label class="fs-adm__label" for="fs-corr-winner">Winning team id</label>'
      + '<input class="fs-adm__input" id="fs-corr-winner" name="winner_team_id" '
      + 'type="number" min="1" step="1">'
      + '</fieldset>'

      + '<fieldset class="fs-adm__fieldset" data-fs-corr="prop_pool" hidden>'
      + '<legend class="fs-adm__label">Corrected winning GMs</legend>'
      + '<label class="fs-adm__label" for="fs-corr-winners">Team ids, comma separated</label>'
      + '<input class="fs-adm__input" id="fs-corr-winners" name="winner_team_ids" '
      + 'type="text" inputmode="numeric" placeholder="e.g. 3, 7">'
      + '</fieldset>'

      + '<label class="fs-adm__label" for="fs-corr-reason">Reason</label>'
      + '<textarea class="fs-adm__input" id="fs-corr-reason" name="reason" '
      + 'rows="3" minlength="3" maxlength="500" required></textarea>'

      + note('The Credits are derived by the server from the contest’s own '
             + 'posted economics. Only eligible regular-season contests can be '
             + 'corrected: postseason contests and legacy single-GM wagers are '
             + 'refused, and a correction after the pot is paid is refused '
             + 'before anything moves.')
      + '<button type="submit" class="fs-adm__btn fs-adm__btn--danger">'
      + 'Review correction</button>'
      + '</form>',
  };
}

/** Second step: restate what was entered and require an explicit confirm. */
export function correctionConfirmSheet(draft) {
  const outcome = draft.competition_type === 'versus'
    ? (draft.outcome === 'push'
      ? 'Push — each GM’s own stake returns to them.'
      : `Team ${draft.winner_team_id} won.`)
    : `Winning GMs: ${(draft.winner_team_ids || []).join(', ') || '(none)'}`;
  return {
    title: 'Confirm correction',
    sub: 'This is recorded permanently and cannot be edited.',
    body:
      '<dl class="fs-adm__kv">'
      + '<dt>Competition</dt>'
      + `<dd>${escapeHtml(draft.competition_type === 'versus' ? 'FantasyStakes matchup' : 'FantasyStakes prop pool')}</dd>`
      + '<dt>Contest</dt>'
      + `<dd>${escapeHtml(String(draft.contest_ref))}</dd>`
      + '<dt>Corrected result</dt>'
      + `<dd>${escapeHtml(outcome)}</dd>`
      + '<dt>Reason</dt>'
      + `<dd>${escapeHtml(draft.reason)}</dd>`
      + '</dl>'
      + '<p class="fs-adm__warn">The correction is appended to the audit trail '
      + 'and the championship standing is recomputed from it. Corrections are '
      + 'never edited or deleted.</p>'
      + '<button type="button" class="fs-adm__btn fs-adm__btn--danger" '
      + 'data-fs-champ-confirm="correction">Submit correction</button>',
  };
}

/**
 * Turn the form draft into the certified request body.
 *
 * Produces exactly the contract `POST /championship/corrections` accepts. No
 * amount is present because none can be: the shape has no field for one.
 */
export function correctionRequest(draft) {
  const body = {
    competition_type: draft.competition_type,
    contest_ref: Number(draft.contest_ref),
    reason: draft.reason,
    correction_key: draft.correction_key,
  };
  body.corrected_result = draft.competition_type === 'versus'
    ? (draft.outcome === 'push'
      ? { outcome: 'push' }
      : { outcome: 'winner', winner_team_id: Number(draft.winner_team_id) })
    : { winner_team_ids: (draft.winner_team_ids || []).map(Number) };
  return body;
}

/* ── Correction history ─────────────────────────────────────────────────── */

/**
 * The append-only audit trail, readable by every league member.
 *
 * Shows the delta the SERVER derived, alongside the contest and revision that
 * produced it, so a GM can see not merely that a figure changed but which
 * contest changed it and why.
 */
export function correctionHistorySection(payload) {
  const rows = (payload && payload.corrections) || [];
  if (!rows.length) {
    return sectionHeading('Championship corrections')
      + note('No authoritative corrections have been recorded this season.');
  }
  const body = rows.map((r) => (
    '<tr class="fs-adm__corr-row">'
    + `<td>${escapeHtml(r.competition_type === 'versus' ? 'Matchup' : 'Prop pool')} `
    + `${escapeHtml(String(r.contest_ref))}</td>`
    + `<td class="fs-st__num">Wk ${escapeHtml(String(r.scoring_week))}</td>`
    + `<td class="fs-st__num">${escapeHtml(String(r.team_id))}</td>`
    + `<td class="fs-st__num">rev ${escapeHtml(String(r.revision))}</td>`
    + `<td class="fs-st__num">${escapeHtml(formatCredits(r.delta_cents))}</td>`
    + `<td>${escapeHtml(r.reason)}</td>`
    + '</tr>'
  )).join('');
  return (
    sectionHeading('Championship corrections')
    + '<table class="fs-adm__corr"><thead><tr>'
    + '<th>Contest</th><th>Week</th><th>GM</th><th>Rev</th><th>Delta</th><th>Reason</th>'
    + '</tr></thead><tbody>' + body + '</tbody></table>'
    + note('Append-only. Every row records the change the server derived from '
           + 'the contest’s own economics.')
  );
}

/** The whole commissioner championship area. */
export function championshipAdminSection(results, config) {
  const actions = availableActions(results, config);
  const button = (action, label, enabled) => (
    `<button type="button" class="fs-adm__btn${enabled ? '' : ' is-disabled'}" `
    + `data-fs-champ-action="${escapeHtml(action)}"${enabled ? '' : ' disabled'}>`
    + `${escapeHtml(label)}</button>`
  );
  return (
    '<section class="fs-adm fs-adm--championship">'
    + sectionHeading('FantasyStakes Championship')
    + note(lifecycleSummary(results))
    + configSection(config)
    + sectionHeading('Lifecycle')
    + '<div class="fs-adm__actions">'
    + button('activate', 'Activate championship', actions.activate)
    + button('freeze', 'Freeze championship', actions.freeze)
    + button('settle', 'Settle pot (60 / 30 / 10)', actions.settle)
    + button('correct', 'Record correction', actions.correct)
    + '</div>'
    + '</section>'
  );
}
