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
 * POINTED AT STAGING FOR THE TESTER ROUND. The v7 tester page sends readers to
 * the staging deployment of the application, because that is where the build
 * testers are being asked to exercise lives. At launch this value becomes
 * `https://app.fantasystakesapp.com`, which answers 303 to its own entry point
 * and serves the FantasyStakes UI - the marketing site links to that ROOT and
 * lets the application own its own routing. Changing the destination is this
 * one line and nothing else.
 *
 * THE PLATFORM HOSTNAME IS HERE ON PURPOSE, AND ONLY FOR NOW. The staging
 * deployment has no domain of its own, so the hosting platform's generated
 * host is the only address it has. That host is plumbing and can change
 * without notice, which is exactly why it is confined to this line: when
 * staging moves, or when the tester round ends, one line changes.
 * `test_no_railway_hostname_appears_anywhere_in_the_site` fails while this
 * value is in place. That failure is the reminder, not a defect to route
 * around - it clears the moment the launch destination goes back in.
 *
 * NOT `/demo/enter`. That route exists but answers POST only - a GET returns
 * 405 - so it cannot be the target of a link. An earlier revision of this file
 * recommended it; that guidance was wrong and is corrected here.
 *
 * WITHOUT JAVASCRIPT the v7 markup carries the same destination in the `href`
 * of every demo control, so all four work with scripting turned off. `site.js`
 * only ever REPLACES that value with this one; the two are kept identical so
 * that a reader gets the same destination either way.
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
  demoUrl: 'https://fantasystakes-app-staging-staging.up.railway.app/app/index.html',

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
