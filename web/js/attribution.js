/* ============================================================================
 * FantasyStakes — source presentation: the provider chip and the Yahoo line
 * WP3D · Rev 4.3 §21, §23 · under the owner ruling of 2026-08-16
 *
 * TWO RENDERERS, ONE QUESTION. Both answer "where did this come from", and both
 * take their answer from `provider-state.js` rather than deciding anything
 * themselves.
 *
 *   sourceChip()          the six-label state, in the app chrome, once
 *   attributionFooter()   the exact contractual Yahoo line, per surface
 *
 * THE ATTRIBUTION TEXT IS A CONTRACTUAL STRING AND IS WRITTEN ONCE.
 *
 *     Fantasy data provided by Yahoo Fantasy
 *
 * Not paraphrased, not templated, not assembled from parts. It lives in one
 * constant so there is exactly one thing to audit and nothing to drift. The
 * executed Yahoo API Access and Use Agreement is the authority; Rev 4.3 §23
 * records the requirement, and the hyperlink target below is the owner's ruling
 * of 2026-08-16.
 *
 * WHAT IS DELIBERATELY ABSENT. No logo. No mark. No "Powered by", no "Official
 * partner", no "Yahoo-approved", no endorsement language of any kind. Rev 4.3
 * §23 permits none of it, and the product is FantasyStakes. The attribution
 * states a data source and stops.
 *
 * AND IT NEVER APPEARS IN DEMO. Not because the Demo panels are a different
 * component — they are the same five tabs — but because `attributionEligible()`
 * reads the authoritative provider binding, and Demo is not Yahoo-backed. A
 * synthetic league presented under a Yahoo attribution would be the single most
 * misleading thing this product could render.
 * ========================================================================== */

import { escapeHtml } from './components.js';
import {
  SOURCE_DEMO, attributionEligible, sourceState,
} from './provider-state.js';

/**
 * The required attribution, exactly as the agreement requires it.
 *
 * DO NOT EDIT THIS STRING. It is contractual text, asserted character for
 * character by `test_wp3d_provider_attribution.py`.
 */
export const YAHOO_ATTRIBUTION_TEXT = 'Fantasy data provided by Yahoo Fantasy';

/**
 * The official Yahoo Fantasy destination the attribution links to.
 *
 * OWNER RULING, 2026-08-16. Yahoo-owned, and the Fantasy Football product this
 * league integrates with. The URL is the link TARGET and never visible copy —
 * a printed URL is not attribution and would read as advertising.
 */
export const YAHOO_ATTRIBUTION_HREF = 'https://football.fantasysports.yahoo.com/';

/**
 * The source chip for the app chrome.
 *
 * ONE INSTANCE, IN THE MASTHEAD, ON EVERY TAB. It belongs to the league rather
 * than to any panel, so repeating it per surface would be repeating the same
 * fact five times; putting it in the chrome states it once, persistently, and
 * survives every tab change without being redrawn.
 *
 * IT IS TEXT, NOT A COLOUR. Rev 4.3 §26 and WP3D §35: the state must be
 * readable, so the label carries the whole meaning and the styling only
 * distinguishes it. A GM who cannot see the accent colour still reads `DEMO`.
 *
 * IT IS CONTEXT, NOT THE HEADLINE. Sized and placed beneath the identity block,
 * in the meta column that already holds the gear and the COMMISSIONER badge —
 * the established grammar for "true, and secondary".
 *
 * @returns {string}
 */
export function sourceChip() {
  const state = sourceState();
  return (
    `<div class="fs-source" data-source-state="${escapeHtml(state.family)}" `
    + `data-source-label="${escapeHtml(state.label)}">`
    + `<span class="fs-source__label">${escapeHtml(state.label)}</span>`
    + '</div>'
  );
}

/**
 * The Yahoo attribution, for one surface that is displaying Yahoo Fantasy
 * Information.
 *
 * TWO CONDITIONS, BOTH REQUIRED, AND THE CALLER OWNS THE SECOND. This function
 * checks that the CONTEXT is Yahoo-backed and has produced usable data;
 * `showsYahooInformation` is the panel's own statement that it actually drew
 * some. A panel that draws nothing Yahoo passes `false` and gets nothing back —
 * which is why Rules & Settings, whose prose merely mentions Yahoo, is not
 * attributed for that.
 *
 * A REAL ANCHOR, so it is keyboard-focusable and announced as a link by the
 * same semantics every other link in the product uses. `rel="noopener"` because
 * it leaves the product.
 *
 * @param {{showsYahooInformation?: boolean}} [spec]
 * @returns {string} the footer, or '' when attribution does not apply
 */
export function attributionFooter(spec = {}) {
  const { showsYahooInformation = true } = spec;
  if (!showsYahooInformation) return '';
  if (!attributionEligible()) return '';

  return (
    '<div class="fs-attribution" data-attribution="yahoo">'
    + `<a class="fs-attribution__link" href="${YAHOO_ATTRIBUTION_HREF}" `
    + 'target="_blank" rel="noopener noreferrer">'
    + escapeHtml(YAHOO_ATTRIBUTION_TEXT)
    + '</a></div>'
  );
}

/**
 * Whether this session is running on the synthetic Demo provider.
 *
 * Exported for the surfaces that must positively suppress Yahoo wording rather
 * than merely fail to add it — the Matchup Preview being the one that used to
 * carry a source banner of its own.
 *
 * @returns {boolean}
 */
export function isDemoSource() {
  return sourceState().label === SOURCE_DEMO;
}
