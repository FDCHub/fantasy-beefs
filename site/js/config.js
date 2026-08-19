/* ==========================================================================
 * FantasyStakes marketing site - SITE CONFIGURATION
 *
 * THIS IS THE ONLY FILE TO EDIT WHEN THE DEMO GOES LIVE.
 *
 * Every "Try the Demo" control on the site - the masthead button, the hero
 * primary call to action, the demo section and the final call to action - is
 * marked `data-fs-demo-link` in the markup and is pointed at `demoUrl` by
 * `site.js`. There is deliberately no second place to change.
 *
 * WHEN THE APPLICATION IS LIVE, set:
 *
 *     demoUrl: "https://app.fantasystakesapp.com/demo/enter"
 *
 * and change nothing else.
 *
 * WHY THE DEFAULT IS AN ON-PAGE ANCHOR RATHER THAN A HOSTNAME. The application
 * deployment is owned by a different work stream and its hostname is not ours
 * to guess; a placeholder host baked into the markup would ship a dead link the
 * moment someone forgot it was a placeholder. `#demo` always resolves, on this
 * page, with or without JavaScript, and it lands the reader on the section that
 * explains what the demo is. That is the correct behaviour for a site whose
 * demo is not yet reachable.
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
  demoUrl: '#demo',

  /**
   * Whether the demo opens in a new tab. Left off while `demoUrl` is an
   * on-page anchor; turning it on for a same-page anchor would open a second
   * copy of this page, which is worse than useless.
   * @type {boolean}
   */
  demoOpensInNewTab: false,
};
