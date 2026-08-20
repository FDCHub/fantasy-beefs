/* ==========================================================================
 * FantasyStakes marketing site - SITE CONFIGURATION
 *
 * THIS IS THE ONLY FILE THAT NAMES THE DEMO DESTINATION.
 *
 * Every "Try the Demo" control on the site - the topbar link, the hero primary
 * call to action, the demo section and the final call to action - is marked
 * `data-fs-demo-link` in the markup and is pointed at `demoUrl` by `site.js`.
 * There is deliberately no second place to change, and
 * `test_web1_marketing_site.py` fails if a second one ever appears.
 *
 * LIVE SINCE WEB-2b. `https://app.fantasystakesapp.com` answers 303 to
 * `/app/index.html` and serves the FantasyStakes UI, so the marketing site
 * links to the ROOT and lets the application own its own routing. Linking to
 * the redirect target instead would pin this file to an internal path the
 * application is free to change.
 *
 * NOT `/demo/enter`. That route exists but answers POST only - a GET returns
 * 405 - so it cannot be the target of a link. An earlier revision of this file
 * recommended it; that guidance was wrong and is corrected here.
 *
 * NEVER THE PLATFORM HOSTNAME. The application is reached through its own
 * domain. The hosting platform's generated deployment host is plumbing, it
 * changes without notice, and a test forbids it appearing anywhere in `site/` -
 * including in a comment such as this one, which is why it is described rather
 * than written out.
 *
 * WITHOUT JAVASCRIPT the markup fallback `#demo` still resolves, landing the
 * reader on the section of this page that explains the demo. That is a
 * deliberate consequence of keeping ONE configuration point: putting the live
 * URL in the markup would make four more places to change. No control is ever
 * a dead link either way.
 *
 * NOT A MODULE. A plain script, loaded before `site.js`, so the value is
 * readable by anything on the page and editable by anyone who can open a text
 * file - which is the whole point of a single configuration location.
 * ========================================================================== */

window.FS_SITE_CONFIG = {
  /**
   * Where every "Try the Demo" control points.
   * @type {string}
   */
  demoUrl: 'https://app.fantasystakesapp.com',

  /**
   * Whether the demo opens in a new tab.
   *
   * Off: the demo is the destination a reader came for, not an aside, and a
   * forced new tab takes the back button away from them. `site.js` attaches
   * `rel="noopener"` automatically if this is ever turned on.
   * @type {boolean}
   */
  demoOpensInNewTab: false,
};
