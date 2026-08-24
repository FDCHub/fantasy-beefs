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

import { attributionFooter } from './attribution.js';
import {
  CREDITS_DISCLAIMER, PanelComposer, accordion, bindAccordions, escapeHtml,
  note, sectionHeading, tabHeader,
} from './components.js';
import { LEGAL_LINE, RULE_GROUPS, SETTINGS, SETTINGS_SEAM } from './data/rules-data.js';
import {
  SETTINGS_MODE_AUTHORITATIVE,
  SETTINGS_MODE_UNAVAILABLE,
  allocationAmountText,
  poolEntryEditable,
  settingsMode,
  settingsRows,
  vcAllocation,
} from './settings-model.js';
import { explainRefusal, updatePoolEntry } from './settings-command.js';
import { LEAGUE_IDENTITY } from './demo-state.js';
import { leagueName } from './league-model.js';
import { bindCommissioner, commissionerArea } from './commissioner.js';
import { bindLifecycle, lifecycleArea } from './lifecycle.js';
import { sourceState } from './provider-state.js';

/** Locked Final POR Rules destination copy. */
export const RULES_TITLE = 'RULES';
export const RULES_SUBTITLE = 'How FantasyStakes is played';

/* ── A · Rules ──────────────────────────────────────────────────────────────*/

/**
 * One rule group in the shared disclosure shell.
 */
function ruleRow(group) {
  const body = group.rules.map((rule) => (
    '<section class="fs-rule">'
    + `<div class="fs-rule__head">${escapeHtml(rule.heading)}</div>`
    + `<div class="fs-rule__body">${escapeHtml(rule.body)}</div>`
    + `<div class="fs-rule__src">${escapeHtml(rule.source)}</div>`
    + '</section>'
  )).join('');
  return accordion({
    key: `rule-${group.id}`,
    title: group.title,
    sub: group.blurb,
    meta: String(group.rules.length),
    bodyHtml: body,
  });
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

/**
 * FINAL POR §23's VC ALLOCATION table.
 *
 * THREE COLUMNS, AND THE THIRD IS THE POINT. `VC ALLOCATION | AMOUNT | RATIO TO
 * WEEKLY MINIMUM` — the ratio is what makes the table readable as an economy
 * rather than as seven unrelated amounts, because every figure in this product
 * is ultimately priced off the Weekly Minimum. It is the SERVER's ratio: §16.2
 * forbids reimplementing the economic formula in the browser, and a division
 * here would be a second definition of the relationship.
 *
 * A REAL <table>, NOT A GRID OF DIVS. Three labelled columns of related figures
 * is what a table is for, and a screen reader announcing "Prop Pool Entry, $1,
 * 0.1 times" is only possible if the header cells are header cells.
 *
 * @returns {string}
 */
function vcAllocationTable(view) {
  const row = (r) => (
    `<tr class="fs-vcrow" data-alloc="${escapeHtml(r.id)}" ` +
    `data-state="${escapeHtml(r.state)}">` +
    `<th scope="row" class="fs-vcrow__label">${escapeHtml(r.label)}</th>` +
    `<td class="fs-vcrow__amount fs-money">${escapeHtml(allocationAmountText(r))}</td>` +
    `<td class="fs-vcrow__ratio">${escapeHtml(r.ratio ?? '—')}</td>` +
    '</tr>'
  );

  return (
    '<table class="fs-vctable" id="fs-vc-allocation">' +
    '<thead><tr>' +
    '<th scope="col" class="fs-vctable__h">VC ALLOCATION</th>' +
    '<th scope="col" class="fs-vctable__h fs-vctable__h--fig">AMOUNT</th>' +
    '<th scope="col" class="fs-vctable__h fs-vctable__h--fig">' +
    'RATIO TO WEEKLY MINIMUM</th>' +
    '</tr></thead>' +
    `<tbody>${view.allocation.map(row).join('')}</tbody>` +
    '</table>'
  );
}

/**
 * §23's four in-season read-only figures.
 *
 * SEPARATED FROM THE SEVEN ABOVE BECAUSE THEY ARE A DIFFERENT KIND OF FACT. The
 * seven are what the league SET; these four are what has since HAPPENED. Mixing
 * them into one table would invite a reader to think the pot additions are
 * something a commissioner configured.
 */
function inSeasonRegion(view) {
  if (!view.inSeason.length) return '';
  return (
    '<div class="fs-vcseason" id="fs-vc-in-season">' +
    '<div class="fs-vcseason__head">IN SEASON</div>' +
    view.inSeason.map((r) => (
      `<div class="fs-vcseason__row" data-in-season="${escapeHtml(r.id)}">` +
      `<span class="fs-vcseason__label">${escapeHtml(r.label)}</span>` +
      `<span class="fs-vcseason__value fs-money">${escapeHtml(
        allocationAmountText({ ...r, state: 'CONFIGURED' }))}</span>` +
      '</div>'
    )).join('') +
    '<div class="fs-note">Read-only. These are what the season has produced, ' +
    'not settings — each is summed from the ledger rather than counted.</div>' +
    '</div>'
  );
}

/**
 * §23's five Season Rules.
 *
 * PRODUCT RULES, AND NOT COMMISSIONER-EDITABLE. They are stated here so a GM
 * reading their league's settings can see which terms their commissioner chose
 * and which the product fixes, without having to infer the difference from the
 * absence of a control.
 */
function seasonRulesRegion(view) {
  if (!view.seasonRules.length) return '';
  return (
    '<div class="fs-vcrules" id="fs-season-rules">' +
    '<div class="fs-vcseason__head">SEASON RULES</div>' +
    view.seasonRules.map((r) => (
      '<div class="fs-vcrules__row">' +
      `<span class="fs-vcrules__label">${escapeHtml(r.label)}</span>` +
      `<span class="fs-vcrules__value">${escapeHtml(r.value)}</span>` +
      '</div>'
    )).join('') +
    '<div class="fs-note">Set by FantasyStakes, not by your commissioner.</div>' +
    '</div>'
  );
}

function settingsRegion() {
  const view = vcAllocation();

  if (!view.available) {
    return (
      '<section class="fs-rulesec" data-region="settings" ' +
      `data-state="${escapeHtml(settingsMode())}" ` +
      `data-alloc-state="unavailable">` +
      sectionHeading('LEAGUE SETTINGS') +
      note(view.unavailableReason === 'SETTINGS_LEGACY_SEASON'
        // A LEGACY SEASON IS NOT A FAILURE, and saying "could not be read"
        // would be false. It played under the retired economy, which has no VC
        // allocation table to show, and the reader is told that instead.
        ? 'This season was played under the previous economy, which has no VC '
          + 'allocation table. Its own settings are unchanged and its results '
          + 'stand; the table below applies from the current season onward.'
        : 'League settings could not be read for this session. The figures are '
          + 'not shown rather than shown wrongly — a league’s rules '
          + 'are not something to guess at.',
        { pending: true }) +
      '</section>'
    );
  }

  return (
    '<section class="fs-rulesec" data-region="settings" ' +
    `data-state="${escapeHtml(settingsMode())}" data-alloc-state="available">` +
    sectionHeading('LEAGUE SETTINGS',
                   settingsMode() === SETTINGS_MODE_AUTHORITATIVE
                     ? 'read-only' : 'example') +
    vcAllocationTable(view) +
    inSeasonRegion(view) +
    seasonRulesRegion(view) +
    // Stated on the surface, not only in the model: a row that looks editable
    // and is not should say why.
    '<div class="fs-note">Your league’s configuration. The Prop Pool '
    + 'Entry is set by the commissioner and freezes once the first Pool week '
    + 'of the season is collected. Everything else is fixed for the season '
    + '— changing any of it would re-price obligations GMs have already '
    + 'funded.</div>' +
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
 * The detail sheet for a VC ALLOCATION row that carries no control.
 *
 * IT SAYS WHERE THE FIGURE CAME FROM AND WHY IT CANNOT BE CHANGED. Six of the
 * seven rows are fixed for the season, and the reason is a rule rather than a
 * missing feature: changing any of them mid-season would re-price obligations
 * GMs have already funded. A sheet that simply repeated the number would leave
 * a reader to conclude the control was forgotten.
 *
 * @param {{id: string, label: string, amountCents: number|null, state: string,
 *          ratio: string|null, source: string}} row
 * @returns {{title: string, sub: string, body: string}}
 */
export function allocationSheet(row) {
  const unset = row.state === 'UNCONFIGURED';
  return {
    title: row.label,
    sub: 'League configuration',
    body:
      '<div class="fs-prev__row"><span class="fs-prev__label">Amount</span>' +
      `<span class="fs-prev__value fs-money">${escapeHtml(
        allocationAmountText(row))}</span></div>` +
      (row.ratio
        ? '<div class="fs-prev__row"><span class="fs-prev__label">Ratio to '
          + 'Weekly Minimum</span>'
          + `<span class="fs-prev__value">${escapeHtml(row.ratio)}</span></div>`
        : '') +
      '<div class="fs-rule__body">' +
      (unset
        // UNCONFIGURED IS NOT ZERO, and the sheet is where that distinction
        // becomes words rather than a dash in a cell.
        ? 'No amount has been entered for this. It is not the same as a league '
          + 'that has deliberately set it to zero — nobody has chosen '
          + 'either way yet, and this pillar opens unfunded until someone does.'
        : row.state === 'DECLINED'
          ? 'This league has deliberately set this to zero and plays without '
            + 'it. That is a governed choice, not a missing setting.'
          : 'Fixed for the season. Changing it would re-price obligations GMs '
            + 'have already funded, so no command exists to change it '
            + 'mid-season.') +
      '</div>' +
      `<div class="fs-rule__src">${escapeHtml(row.source)}</div>`,
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
  // WP3D — THE ATTRIBUTION JOINS THE LEGAL FOOTER, and only here.
  //
  // Rev 4.3 §22 draws a line this surface sits exactly on. The rules PROSE
  // mentions Yahoo repeatedly — Yahoo decides the podium, Yahoo decides what
  // happened on the field — and a reference to Yahoo inside an explanation of a
  // FantasyStakes rule is NOT a display of Yahoo Fantasy Information. It is
  // this product describing its own rules. Attributing it would be
  // over-attribution.
  //
  // What IS Yahoo Fantasy Information on this surface is the league's own name
  // in the header, which is the provider's name for it once a refresh has
  // bound one, and the provider-backed values the commissioner area below
  // reports. That is what the line attributes.
  //
  // ONE INSTANCE FOR THE WHOLE PANEL. The commissioner and provider views are
  // regions of this same visible surface, not separate pages, so a second copy
  // beside them would be the duplication §18 forbids.
  // NESTED INSIDE THE LEGAL BLOCK, not appended beside it. The rules scroller's
  // direct children are a certified sequence — rules, settings, lifecycle,
  // commissioner, legal — and a sixth child would change it. It also reads
  // correctly: the legal line and the source line are the same kind of thing,
  // and they belong in the same footer.
  return (
    '<div class="fs-legal" id="fs-legal">'
    + `<div class="fs-legal__line">${escapeHtml(LEGAL_LINE)}</div>`
    + attributionFooter()
    + '</div>'
  );
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
    '</div>',
  );

  return composer.toHTML();
}

/** Read-only provider state from the same served context as the masthead chip. */
export function buildProviderPanel() {
  const composer = new PanelComposer('provider');
  const state = sourceState();
  composer.add(tabHeader({
    title: 'PROVIDER INFORMATION',
    sub: leagueName() ?? LEAGUE_IDENTITY.name,
    asideLabel: 'Read-only connection state',
  }));
  composer.add(
    '<div class="fs-rulescroll">'
    + `<section class="fs-rulesec" data-region="provider" data-provider-family="${escapeHtml(state.family)}">`
    + sectionHeading('CURRENT PROVIDER')
    + '<div class="fs-rule">'
    + '<div class="fs-rule__head">CONNECTION STATE</div>'
    + `<div class="fs-rule__body" data-provider-label>${escapeHtml(state.label)}</div>`
    + '</div>'
    + '<div class="fs-note">This status comes from the league context currently served to this session. '
    + 'FantasyStakes does not infer provider authorization or readiness.</div>'
    + '</section>'
    + attributionFooter()
    + '</div>',
  );
  return composer.toHTML();
}

/** Existing virtual-credit and legal copy, presented in its own destination. */
export function buildAboutLegalPanel() {
  const composer = new PanelComposer('about');
  const credits = RULE_GROUPS.find((group) => group.id === 'credits');
  composer.add(tabHeader({
    title: 'ABOUT & LEGAL',
    sub: 'FantasyStakes',
    asideLabel: 'Product and legal information',
  }));
  composer.add(
    '<div class="fs-rulescroll">'
    + '<section class="fs-rulesec" data-region="about-legal">'
    + sectionHeading('VIRTUAL CREDITS')
    + `<div class="fs-note">${escapeHtml(CREDITS_DISCLAIMER)}</div>`
    + (credits ? credits.rules.slice(0, 2).map((rule) => (
      '<div class="fs-rule">'
      + `<div class="fs-rule__head">${escapeHtml(rule.heading)}</div>`
      + `<div class="fs-rule__body">${escapeHtml(rule.body)}</div>`
      + '</div>'
    )).join('') : '')
    + '</section>'
    + legalFooter()
    + '</div>',
  );
  return composer.toHTML();
}

/** League-configured values, deliberately separate from the fixed Rules. */
export function buildLeagueSettingsPanel() {
  const composer = new PanelComposer('settings');
  composer.add(tabHeader({
    title: 'LEAGUE SETTINGS',
    sub: leagueName() ?? LEAGUE_IDENTITY.name,
    asideLabel: 'Configured league values',
  }));
  composer.add('<div class="fs-rulescroll">' + settingsRegion() + '</div>');
  return composer.toHTML();
}

/** Role-aware league operations, kept out of both read-only destinations. */
export function buildCommissionerPanel() {
  const composer = new PanelComposer('commissioner');
  composer.add(tabHeader({
    title: 'COMMISSIONER CONTROLS',
    sub: leagueName() ?? LEAGUE_IDENTITY.name,
    asideLabel: 'League operations',
  }));
  composer.add('<div class="fs-rulescroll">' + lifecycleArea()
    + commissionerArea() + '</div>');
  return composer.toHTML();
}

/**
 * @param {HTMLElement} panel
 * @param {{openSheet: Function}} api
 */
export function bindRules(panel, api) {
  bindAccordions(panel);

  /* THE ONE EDITABLE SETTING KEEPS ITS PATH ACROSS §23's RENAME.
   *
   * §23 calls the row Prop Pool Entry; the settings response, the command and
   * the server's bound all call it `pool-bet`, and renaming those would rename
   * a governed mutation to make a table read better. So the table's row id is
   * mapped to the settings row it opens, in ONE place, and every other row
   * opens the plain detail sheet built from the figure itself.
   *
   * A row with no mapping is not inert: it opens its own sheet naming the
   * source the figure came from, because "where does this number come from" is
   * the question a settings table exists to answer. */
  const OPENS_SETTING = { 'prop-pool-entry': 'pool-bet' };

  panel.querySelectorAll('[data-alloc]').forEach((el) => {
    el.addEventListener('click', () => {
      const view = vcAllocation();
      const row = view.allocation.find((r) => r.id === el.dataset.alloc);
      if (!row) return;

      const mapped = OPENS_SETTING[row.id];
      if (mapped) {
        const setting = settingsRows().find((s) => s.id === mapped);
        if (setting) {
          api.openSheet(settingSheet(setting));
          return;
        }
      }
      api.openSheet(allocationSheet(row));
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
