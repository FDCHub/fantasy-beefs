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
import { FAMILY_DEMO, sourceState } from './provider-state.js';

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

function rulesRegion(idSuffix = '') {
  return (
    '<section class="fs-rulesec" data-region="rules">' +
    sectionHeading('LEAGUE RULES') +
    `<div class="fs-rules" id="fs-rule-groups${idSuffix}">${RULE_GROUPS.map(ruleRow).join('')}</div>` +
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
function inSeasonRegion(view, idSuffix = '') {
  if (!view.inSeason.length) return '';
  return (
    `<div class="fs-vcseason" id="fs-vc-in-season${idSuffix}">` +
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
function seasonRulesRegion(view, idSuffix = '') {
  if (!view.seasonRules.length) return '';
  return (
    `<div class="fs-vcrules" id="fs-season-rules${idSuffix}">` +
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

function settingsRegion(idSuffix = '') {
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
    // FINAL POR §2B — SEASON RULES SITS ABOVE IN SEASON.
    //
    // The two blocks answer different questions, and the fixed one is the one
    // a reader needs first: SEASON RULES states the terms the product sets,
    // which is the frame IN SEASON's running totals are then read against.
    // Only the order changes; both blocks keep their own content and markup.
    seasonRulesRegion(view, idSuffix) +
    inSeasonRegion(view, idSuffix) +
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

/* ── FINAL POR §2 · THE SETTINGS DETAIL SHEETS ──────────────────────────────
 *
 * The gear opens the Settings root sheet, and every one of its four entries now
 * opens a DETAIL SHEET rather than navigating to a tab-style destination.
 *
 * WHY THE CONTENT IS NOT REBUILT. Rules and League Settings are approved as
 * they are, so these sheets render the SAME region functions the panels do.
 * What is dropped is the panel chrome: `tabHeader()` gave each destination an
 * app page-header, which is exactly the treatment §2 retires — inside a sheet
 * it read as a second primary tab. The sheet's own title carries the name, and
 * `sheet()` supplies the universal upper-left X for free.
 *
 * WHY THEY PUSH RATHER THAN REPLACE. A detail pushed onto the Settings root
 * pops back to it, so the X returns the reader to the list they chose from and
 * a second X returns them to the app. That is the "closes naturally" the
 * ruling asks for, and it is the stack's existing behaviour rather than a new
 * one. Rows INSIDE a detail push again for the same reason.
 */

/** Rules, in the approved formatting, presented as a Settings detail. */
export function rulesSheet() {
  return {
    title: RULES_TITLE,
    /* THE IDENTITY IS THE LEAGUE, in the same slot the other three details put
     * it. This was `RULES_SUBTITLE` — the tagline the panel carried in its
     * aside — which left the Rules detail the only one of the four that did
     * not say WHOSE rules it was showing. A sheet has one subtitle, and the
     * league name is the fact worth spending it on. */
    sub: leagueName() ?? LEAGUE_IDENTITY.name,
    body: `<div class="fs-setdetail">${rulesRegion('-sheet')}</div>`,
    onMount: (host) => { bindAccordions(host); },
  };
}

/** League Settings, in the approved formatting, presented as a Settings detail. */
export function leagueSettingsSheet() {
  return {
    title: 'LEAGUE SETTINGS',
    sub: leagueName() ?? LEAGUE_IDENTITY.name,
    body: `<div class="fs-setdetail">${settingsRegion('-sheet')}</div>`,
    onMount: (host, api) => {
      bindAccordions(host);
      bindSettingsRows(host, { openSheet: (spec) => api.push(spec) });
    },
  };
}

/* PROVIDER INFORMATION, WRITTEN FOR A GM RATHER THAN FOR AN ENGINEER.
 *
 * §2C asks this surface to explain what the fantasy provider IS and what
 * FantasyStakes does with it. The previous copy stated a connection state and
 * a disclaimer about inference — true, but it answered a question nobody with a
 * fantasy team was asking. There is no OAuth, no endpoint and no token here,
 * because none of that changes what a GM should expect to see.
 *
 * WHAT IT MUST NOT DO IS OVERCLAIM. The identity and the connection line come
 * from `sourceState()`, the same served context the masthead chip reads, so
 * this sheet cannot say "connected" on a page that could not read the league. */
export function providerSheet() {
  const state = sourceState();
  const isDemo = state.family === FAMILY_DEMO;
  const provider = isDemo ? 'FantasyStakes Demo' : (state.label || 'Not connected');

  const row = (label, value) => (
    '<div class="fs-prev__row">'
    + `<span class="fs-prev__label">${escapeHtml(label)}</span>`
    + `<span class="fs-prev__value" data-provider-field="${escapeHtml(label)}">${escapeHtml(value)}</span>`
    + '</div>'
  );

  return {
    title: 'PROVIDER INFORMATION',
    sub: leagueName() ?? LEAGUE_IDENTITY.name,
    body:
      '<div class="fs-setdetail">'
      + `<section class="fs-rulesec" data-region="provider" data-provider-family="${escapeHtml(state.family)}">`
      + sectionHeading('YOUR FANTASY PROVIDER')
      + '<div class="fs-note">Your fantasy provider is the service that actually '
      + 'runs your fantasy football league — the rosters, the weekly matchups '
      + 'and the scoring. FantasyStakes does not run your league. It connects '
      + 'to it.</div>'
      + row('Provider', provider)
      + row('Connection', state.label || 'Not connected')
      + (isDemo
        ? '<div class="fs-note">This is the FantasyStakes Demo. Every team, '
          + 'result and Credit you see is sample data created to show how the '
          + 'product works. No real fantasy league is connected.</div>'
        : '')
      + sectionHeading('WHAT FANTASYSTAKES READS')
      + '<div class="fs-note">FantasyStakes reads the parts of your league it '
      + 'needs to settle play: your teams and owners, the weekly schedule, '
      + 'each team’s lineup and the points your league scores them. That is '
      + 'all it asks for.</div>'
      + sectionHeading('WHAT FANTASYSTAKES NEVER CHANGES')
      + '<div class="fs-note">The connection is read-only. FantasyStakes never '
      + 'sets a lineup, makes a trade, edits a roster or changes a score in '
      + 'your fantasy league.</div>'
      + sectionHeading('WHO DECIDES THE RESULT')
      + '<div class="fs-note">Your provider does. Whatever your fantasy league '
      + 'says happened on the field is what FantasyStakes settles against — '
      + 'the final points, who won the matchup, and the standings. '
      + 'FantasyStakes adds the stakes on top; it never overrules the '
      + 'result.</div>'
      + '</section>'
      + attributionFooter()
      + '</div>',
  };
}

/* ABOUT & LEGAL — SHORT, PLAIN, AND ONLY WHAT THE PRODUCT ALREADY CLAIMS.
 *
 * §2D fixes the label and asks for understandable coverage of what the product
 * is and what a Credit is not. The virtual-credit sentence is the approved
 * `CREDITS_DISCLAIMER` and the money statements below it are the ones the
 * product already makes everywhere else — no deposits, no payments, no
 * payouts. Nothing here invents a legal position the application does not
 * already take. */
export function aboutLegalSheet() {
  const credits = RULE_GROUPS.find((group) => group.id === 'credits');
  return {
    title: 'ABOUT & LEGAL',
    sub: 'FantasyStakes',
    body:
      '<div class="fs-setdetail">'
      + '<section class="fs-rulesec" data-region="about-legal">'
      + sectionHeading('WHAT FANTASYSTAKES IS')
      + '<div class="fs-note">FantasyStakes is a companion to your fantasy '
      + 'football league. It adds matchup wagers and prop pools on top of the '
      + 'league you already play, keeps score of them, and settles them '
      + 'against your provider’s official results.</div>'
      + sectionHeading('VIRTUAL CREDITS')
      + `<div class="fs-note">${escapeHtml(CREDITS_DISCLAIMER)}</div>`
      + '<div class="fs-note">Credits are used for keeping score and for '
      + 'display. They have no cash value.</div>'
      + sectionHeading('MONEY')
      + '<div class="fs-note">FantasyStakes does not accept deposits, does not '
      + 'process payments and does not make payouts. Anything your league '
      + 'chooses to settle between its members happens outside this '
      + 'product.</div>'
      + (credits ? credits.rules.slice(0, 2).map((rule) => (
        '<div class="fs-rule">'
        + `<div class="fs-rule__head">${escapeHtml(rule.heading)}</div>`
        + `<div class="fs-rule__body">${escapeHtml(rule.body)}</div>`
        + '</div>'
      )).join('') : '')
      + '</section>'
      + legalFooter()
      + '</div>',
  };
}

/** The four Settings details, by the menu entry id that opens each. */
export const SETTINGS_DETAIL_SHEETS = Object.freeze({
  rules: rulesSheet,
  settings: leagueSettingsSheet,
  provider: providerSheet,
  about: aboutLegalSheet,
});

/**
 * @param {HTMLElement} panel
 * @param {{openSheet: Function}} api
 */
export function bindRules(panel, api) {
  bindAccordions(panel);
  bindSettingsRows(panel, api);
  bindCommissioner(panel, api);
  bindLifecycle(panel);
}

/**
 * The allocation and settings row handlers, bound wherever those rows render.
 *
 * EXTRACTED SO ONE BEHAVIOUR SERVES TWO CONTAINERS. Final POR §2 moves League
 * Settings from a tab-style destination into a detail sheet, and the rows
 * inside it have to keep opening exactly what they opened before. Duplicating
 * the handlers would let the sheet and the panel drift; this is the same code
 * for both, and the caller supplies how a further level is opened — `openSheet`
 * from a panel, a stack `push` from inside a sheet.
 *
 * @param {HTMLElement} root
 * @param {{openSheet: Function}} api
 */
export function bindSettingsRows(root, api) {
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

  root.querySelectorAll('[data-alloc]').forEach((el) => {
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

  root.querySelectorAll('[data-setting]').forEach((el) => {
    el.addEventListener('click', () => {
      const setting = settingsRows().find((s) => s.id === el.dataset.setting);
      if (setting) api.openSheet(settingSheet(setting));
    });
  });
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
