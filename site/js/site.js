/* ==========================================================================
 * FantasyStakes marketing site - behaviour
 *
 * TWO JOBS AND NO MORE:
 *   1. point every "Try the Demo" control at the single configured URL;
 *   2. run the mobile navigation disclosure.
 *
 * Everything else on this page - the FAQ, anchor scrolling, every layout
 * response - is HTML and CSS. A marketing page that cannot render without
 * JavaScript is a marketing page that sometimes does not render.
 *
 * NO MODULE, NO BUILD, NO DEPENDENCY. Deferred so it never blocks paint.
 * ========================================================================== */

(function () {
  'use strict';

  /* -- 1. The demo destination -------------------------------------------- */

  /**
   * Point every `data-fs-demo-link` control at `config.demoUrl`.
   *
   * The v7 markup already carries the same destination in each control's
   * `href`, so a reader with JavaScript turned off still reaches the demo.
   * This only ever REPLACES that value - it never creates a link, and it
   * never leaves one pointing at nothing. `config.js` remains the single
   * place the destination is named.
   */
  function applyDemoDestination() {
    var config = window.FS_SITE_CONFIG || {};
    var url = typeof config.demoUrl === 'string' ? config.demoUrl.trim() : '';
    if (!url) return;

    var links = document.querySelectorAll('[data-fs-demo-link]');
    for (var i = 0; i < links.length; i += 1) {
      links[i].setAttribute('href', url);

      // An off-site demo opened in a new tab needs `noopener`, and a same-page
      // anchor must never be given `target` at all.
      var offSite = url.charAt(0) !== '#';
      if (offSite && config.demoOpensInNewTab) {
        links[i].setAttribute('target', '_blank');
        links[i].setAttribute('rel', 'noopener');
      } else {
        links[i].removeAttribute('target');
        links[i].removeAttribute('rel');
      }
    }
  }

  /* -- 2. Mobile navigation ------------------------------------------------ */

  /**
   * A disclosure, not a menu widget.
   *
   * The panel is a plain list of links that the stylesheet lays out as a row on
   * wide viewports and as a stack on narrow ones. The button flips
   * `data-open` and mirrors it in `aria-expanded`.
   *
   * `data-open` RATHER THAN THE `hidden` PROPERTY, because the HTML rendering
   * spec gives `[hidden]` `display: none !important` in the user-agent sheet.
   * A panel closed that way could not be re-shown as a desktop row by any
   * author rule, so a reader who opened the menu on a phone and then rotated
   * into a tablet layout would lose the navigation entirely.
   */
  function initNavigation() {
    var toggle = document.querySelector('[data-fs-nav-toggle]');
    var panel = document.getElementById('site-nav');
    if (!toggle || !panel) return;

    // The panel starts closed only once scripting is confirmed present. Without
    // this, a no-JavaScript reader would get a permanently collapsed navigation
    // and a button that does nothing - so the markup ships the panel open and
    // the toggle hidden, and both are corrected here.
    toggle.removeAttribute('hidden');

    function setOpen(open) {
      panel.setAttribute('data-open', open ? 'true' : 'false');
      toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
      toggle.setAttribute('aria-label', open ? 'Close menu' : 'Open menu');
    }

    toggle.addEventListener('click', function () {
      setOpen(panel.getAttribute('data-open') !== 'true');
    });

    // Following an in-page anchor should reveal the destination, not leave the
    // panel covering it.
    panel.addEventListener('click', function (event) {
      var link = event.target.closest ? event.target.closest('a') : null;
      if (link) setOpen(false);
    });

    document.addEventListener('keydown', function (event) {
      if (event.key !== 'Escape' || panel.getAttribute('data-open') !== 'true') return;
      setOpen(false);
      toggle.focus();
    });

    setOpen(false);
  }

  function init() {
    applyDemoDestination();
    initNavigation();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
}());
