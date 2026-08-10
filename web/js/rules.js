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

import { PanelComposer, escapeHtml, sectionHeading, tabHeader } from './components.js';
import { LEGAL_LINE, RULE_GROUPS, SETTINGS, SETTINGS_SEAM } from './data/rules-data.js';
import { LEAGUE_IDENTITY } from './demo-state.js';
import { bindCommissioner, commissionerArea } from './commissioner.js';

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
    '<section class="fs-rulesec" data-region="settings">' +
    sectionHeading('LEAGUE SETTINGS', 'read-only') +
    `<div class="fs-settings" id="fs-settings">${SETTINGS.map(settingRow).join('')}</div>` +
    // Stated on the surface, not only in the model: a row that looks editable
    // and is not should say why.
    '<div class="fs-note">Current league configuration. These are read-only in ' +
    'this build because no governed configuration command exists to call — the ' +
    'economy stop, Pool entry, Skunk amount and payout split are set through ' +
    'league setup, and no route changes any of them.</div>' +
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
    body:
      '<div class="fs-prev__row"><span class="fs-prev__label">Current</span>' +
      `<span class="fs-prev__value fs-money"${exact}>${escapeHtml(setting.value)}</span></div>` +
      `<div class="fs-rule__body">${escapeHtml(setting.detail)}</div>` +
      `<div class="fs-rule__src">${escapeHtml(setting.source)}</div>` +
      `<div class="fs-note is-warn">Read-only. ${escapeHtml(SETTINGS_SEAM.needs)}. ` +
      'This surface implements no configuration path of its own.</div>',
  };
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
    sub: LEAGUE_IDENTITY.name,
    asideLabel: RULES_SUBTITLE,
  }));

  // No strip and no disclaimer: this tab summarises no position.
  composer.add(
    '<div class="fs-rulescroll">' +
    rulesRegion() +
    settingsRegion() +
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
      const setting = SETTINGS.find((s) => s.id === el.dataset.setting);
      if (setting) api.openSheet(settingSheet(setting));
    });
  });

  bindCommissioner(panel, api);
}