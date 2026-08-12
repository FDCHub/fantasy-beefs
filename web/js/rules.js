/* ============================================================================
 * FantasyStakes — UI/UX Rev 4.2 · Rules & Settings
 * Sprint 7 Package 4
 *
 * The league's operating manual and the commissioner's control surface — not an
 * app preferences page. Four regions, in order:
 *
 *     A · the five rule groups
 *     B · league configuration
 *     C · commissioner surfaces
 *     D · the legal line
 *
 * NO STRIP, NO DISCLAIMER. This tab summarises no position, so it carries no
 * four-cell strip, and the Credits disclaimer appears only under one.
 *
 * THE LEGAL LINE LIVES HERE, ONCE. Rev 4.2 moves product and copyright identity
 * out of the global masthead and to the bottom of this tab. It is subordinate
 * to the operating content and it is not repeated anywhere else in the app —
 * a defensive banner on every screen was the treatment this supersedes.
 * ========================================================================== */

import { PanelComposer, escapeHtml, note, sectionHeading, tabHeader } from './components.js';
import { LEGAL_LINE, RULE_GROUPS, SETTINGS, SETTINGS_SEAM } from './data/rules-data.js';
import {
  SETTINGS_MODE_AUTHORITATIVE,
  SETTINGS_MODE_UNAVAILABLE,
  poolEntryEditable,
  settingsMode,
  settingsRows,
} from './settings-model.js';
import { explainRefusal, updatePoolEntry } from './settings-command.js';
import { LEAGUE_IDENTITY } from './demo-state.js';
import { leagueName } from './league-model.js';
import { bindCommissioner, commissionerArea } from './commissioner.js';
import { bindLifecycle, lifecycleArea } from './lifecycle.js';

/** Locked Rev 4.2 header copy. */
export const RULES_TITLE = 'RULES & SETTINGS';
export const RULES_SUBTITLE = 'The league’s operating manual';

/* ── A · Rules ──────────────────────────────────────────────────────────────*/

/**
 * One rule group as a compact, tappable row.
 *
 * The chevron is the disclosure affordance; the row opens the shared sheet
 * rather than expanding in place, because a rules sheet is long-form reading
 * and the tab behind it is a directory.
 */
function ruleRow(group) {
  return (
    `<button type="button" class="fs-rulerow" data-rule="${escapeHtml(group.id)}">` +
    '<span class="fs-rulerow__main">' +
    `<span class="fs-rulerow__title">${escapeHtml(group.title)}</span>` +
    `<span class="fs-rulerow__blurb">${escapeHtml(group.blurb)}</span>` +
    '</span>' +
    `<span class="fs-rulerow__count">${group.rules.length}</span>` +
    '<span class="fs-rulerow__chev">›</span>' +
    '</button>'
  );
}

function rulesRegion() {
  return (
    '<section class="fs-rulesec" data-region="rules">' +
    sectionHeading('LEAGUE RULES') +
    `<div class="fs-rules" id="fs-rule-groups">${RULE_GROUPS.map(ruleRow).join('')}</div>` +
    '</section>'
  );
}

/**
 * One rule group's sheet.
 *
 * Each rule states its governing source. That is not decoration: a rules sheet
 * that cannot be traced to a specification is a place where policy gets
 * invented, and showing the source makes the invention visible.
 *
 * @param {object} group
 * @returns {{title: string, sub: string, body: string}}
 */
export function ruleSheet(group) {
  return {
    title: group.title,
    sub: group.blurb,
    body:
      group.rules.map((rule) => (
        '<section class="fs-rule">' +
        `<div class="fs-rule__head">${escapeHtml(rule.heading)}</div>` +
        `<div class="fs-rule__body">${escapeHtml(rule.body)}</div>` +
        `<div class="fs-rule__src">${escapeHtml(rule.source)}</div>` +
        '</section>'
      )).join('') +
      '<div class="fs-note">Where this sheet and a governing specification ' +
      'disagree, the specification is right.</div>',
  };
}

/* ── B · Settings ───────────────────────────────────────────────────────────*/

function settingRow(setting) {
  const exact = typeof setting.exactCents === 'number'
    ? ` data-exact-cents="${setting.exactCents}"`
    : '';
  return (
    `<button type="button" class="fs-setrow" data-setting="${escapeHtml(setting.id)}">` +
    `<span class="fs-setrow__label">${escapeHtml(setting.label)}</span>` +
    `<span class="fs-setrow__value fs-money"${exact}>${escapeHtml(setting.value)}</span>` +
    '<span class="fs-setrow__chev">›</span>' +
    '</button>'
  );
}

function settingsRegion() {
  return (
    `<section class="fs-rulesec" data-region="settings" ` +
    `data-state="${escapeHtml(settingsMode())}">` +
    sectionHeading('LEAGUE SETTINGS',
                   settingsMode() === SETTINGS_MODE_UNAVAILABLE ? '' : 'read-only') +
    (settingsMode() === SETTINGS_MODE_UNAVAILABLE
      ? note('League settings could not be read for this session. The figures '
             + 'below are not shown rather than shown wrongly — a league’s '
             + 'rules are not something to guess at.', { pending: true })
      : `<div class="fs-settings" id="fs-settings">` +
        `${settingsRows().map(settingRow).join('')}</div>`) +
    // Stated on the surface, not only in the model: a row that looks editable
    // and is not should say why.
    // S8-P4 CORRECTION. This said no governed configuration command existed.
    // One does now — Standard Pool Bet, per the B2 ruling — so the sentence
    // became false, and false in the place a commissioner reads to find out
    // what they may change. The other three rows are still read-only, and the
    // reason is the ruling rather than a missing route.
    '<div class="fs-note">Current league configuration. The Standard Pool Bet ' +
    'is set by the commissioner and freezes once the first Pool week of the ' +
    'season is collected. '
    + 'The economy stop, Skunk amount and payout split are fixed ' +
    'for the season — changing any of them would re-price obligations GMs have ' +
    'already funded.</div>' +
    '</section>'
  );
}

/**
 * @param {object} setting
 * @returns {{title: string, sub: string, body: string}}
 */
export function settingSheet(setting) {
  const exact = typeof setting.exactCents === 'number'
    ? ` data-exact-cents="${setting.exactCents}"`
    : '';
  return {
    title: setting.label,
    sub: 'League configuration',
    onMount: SETTING_SHEET_MOUNT,
    body:
      '<div class="fs-prev__row"><span class="fs-prev__label">Current</span>' +
      `<span class="fs-prev__value fs-money"${exact}>${escapeHtml(setting.value)}</span></div>` +
      `<div class="fs-rule__body">${escapeHtml(setting.detail)}</div>` +
      `<div class="fs-rule__src">${escapeHtml(setting.source)}</div>` +
      settingControl(setting),
  };
}

/**
 * The per-row control.
 *
 * EXACTLY ONE ROW IS MUTABLE, and the server says which. `editable` comes from
 * the settings response, and `poolEntryEditable()` additionally requires the
 * acting session to hold commissioner authority — but neither decides
 * anything: the command is refused server-side for anyone without league
 * authority, and after the season's first collection freezes it. The control
 * is drawn disabled rather than offered and then refused, which is a courtesy,
 * not a permission.
 *
 * @param {object} setting a row from `settingsRows()`
 * @returns {string}
 */
function settingControl(setting) {
  if (settingsMode() !== SETTINGS_MODE_AUTHORITATIVE) {
    return `<div class="fs-note is-warn">Read-only. `
      + `${escapeHtml(SETTINGS_SEAM.needs)}. `
      + 'This surface implements no configuration path of its own.</div>';
  }

  if (setting.id !== 'pool-bet') {
    // Fixed for the season — the B2 ruling, not a missing implementation.
    return '<div class="fs-note">Fixed for the season. Changing it would '
      + 're-price obligations GMs have already funded, so no command exists '
      + 'to change it mid-season.</div>';
  }

  if (setting.frozen) {
    return '<div class="fs-note is-warn">Frozen for this season — the first '
      + 'Pool week has been collected, and the entry is fixed from that point. '
      + 'The server refuses a change whatever this surface shows.</div>';
  }

  if (!poolEntryEditable(COMMISSIONER_CAPABILITY)) {
    return '<div class="fs-note">Set by the league commissioner. Your session '
      + 'does not hold commissioner authority for this league.</div>';
  }

  return (
    '<form class="fs-setform" id="fs-pool-entry-form">' +
    '<label class="fs-setform__label" for="fs-pool-entry">Standard Pool Bet</label>' +
    // `min`/`max`/`step` come from the SERVER's governed bounds. They are a
    // convenience for the input, not the enforcement: an out-of-bounds value
    // is refused by `betting/pool_funding.configure_pool_weekly_entry`, and
    // nothing here clamps silently.
    `<input class="fs-setform__input" id="fs-pool-entry" type="number" ` +
    `min="${setting.minCents / 100}" max="${setting.maxCents / 100}" ` +
    `step="0.01" value="${setting.exactCents / 100}" ` +
    `data-min-cents="${setting.minCents}" data-max-cents="${setting.maxCents}">` +
    '<button type="submit" class="fs-btn fs-btn--gold fs-setform__save" ' +
    'id="fs-pool-entry-save">Save</button>' +
    '<p class="fs-setform__error" id="fs-pool-entry-error" role="alert" ' +
    'aria-live="polite"></p>' +
    '</form>'
  );
}

/**
 * Whether the acting session holds commissioner authority for this league.
 *
 * Set by the shell from /auth/me before the panel is built. Presentation only.
 */
let COMMISSIONER_CAPABILITY = false;

/** @param {boolean} value from /auth/me capabilities */
export function setCommissionerCapability(value) {
  COMMISSIONER_CAPABILITY = Boolean(value);
}

/**
 * The settings sheet's mount hook.
 *
 * Set by the shell, which is the only thing that knows the acting league and
 * how to re-render after a save. Left null in demo mode, where there is no
 * league to write to and the form is never drawn.
 * @type {((host: HTMLElement, api: object) => void)|null}
 */
let SETTING_SHEET_MOUNT = null;

/** @param {((host: HTMLElement, api: object) => void)|null} fn */
export function setSettingSheetMount(fn) {
  SETTING_SHEET_MOUNT = fn;
}

/* ── D · Legal ──────────────────────────────────────────────────────────────*/

function legalFooter() {
  return `<div class="fs-legal" id="fs-legal">${escapeHtml(LEGAL_LINE)}</div>`;
}

/* ── Panel ──────────────────────────────────────────────────────────────────*/

/**
 * @returns {string}
 */
export function buildRulesPanel() {
  const composer = new PanelComposer('rules');

  composer.add(tabHeader({
    title: RULES_TITLE,
    // THE REAL LEAGUE, when one is bound. `LEAGUE_IDENTITY.name` is the
    // fixture's `CULV APPRECIATION SOCIETY` and was shown as the heading of a
    // signed-in GM's own settings.
    sub: leagueName() ?? LEAGUE_IDENTITY.name,
    asideLabel: RULES_SUBTITLE,
  }));

  // No strip and no disclaimer: this tab summarises no position.
  //
  // WP4 PUTS THE LIFECYCLE BETWEEN CONFIGURATION AND REPORTING. League setup
  // reads as the continuation of LEAGUE SETTINGS above it, and the week's
  // operations are the thing a commissioner comes to this tab to DO — placing
  // them after twelve GM ledger cards would bury the routine act behind the
  // occasional one. The commissioner area's own locked order is untouched.
  composer.add(
    '<div class="fs-rulescroll">' +
    rulesRegion() +
    settingsRegion() +
    lifecycleArea() +
    commissionerArea() +
    legalFooter() +
    '</div>',
  );

  return composer.toHTML();
}

/**
 * @param {HTMLElement} panel
 * @param {{openSheet: Function}} api
 */
export function bindRules(panel, api) {
  panel.querySelectorAll('[data-rule]').forEach((el) => {
    el.addEventListener('click', () => {
      const group = RULE_GROUPS.find((g) => g.id === el.dataset.rule);
      if (group) api.openSheet(ruleSheet(group));
    });
  });

  panel.querySelectorAll('[data-setting]').forEach((el) => {
    el.addEventListener('click', () => {
      const setting = settingsRows().find((s) => s.id === el.dataset.setting);
      if (setting) api.openSheet(settingSheet(setting));
    });
  });

  bindCommissioner(panel, api);
  bindLifecycle(panel);
}

/**
 * Bind the Standard Pool Bet form, wherever it is rendered.
 *
 * The form lives inside the settings SHEET, which is created after the panel
 * is bound, so this is called from the sheet's own mount rather than from
 * `bindRules`.
 *
 * @param {HTMLElement} host the sheet element
 * @param {{leagueId: number, onSaved: (settings: object) => void}} ctx
 */
export function bindPoolEntryForm(host, ctx) {
  const form = host.querySelector('#fs-pool-entry-form');
  if (!form) return;

  const input = form.querySelector('#fs-pool-entry');
  const save = form.querySelector('#fs-pool-entry-save');
  const error = form.querySelector('#fs-pool-entry-error');
  let inFlight = false;

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (inFlight) return;

    // Dollars in, exact cents out. Rounded ONCE here, at the input boundary,
    // because a float dollar figure cannot be sent to a cents API without
    // deciding where the rounding happens — and nothing downstream may round.
    const cents = Math.round(Number(input.value) * 100);
    error.textContent = '';

    if (!Number.isFinite(cents)) {
      error.textContent = 'Enter an amount.';
      return;
    }

    inFlight = true;
    save.disabled = true;
    save.textContent = 'Saving…';
    try {
      // NOT CLAMPED. An out-of-bounds value is sent and the server's refusal
      // is shown, so the bound stays in the setter that owns it.
      const settings = await updatePoolEntry(ctx.leagueId, cents);
      ctx.onSaved(settings);
    } catch (refusal) {
      error.textContent = explainRefusal(refusal);
    } finally {
      inFlight = false;
      save.disabled = false;
      save.textContent = 'Save';
    }
  });
}