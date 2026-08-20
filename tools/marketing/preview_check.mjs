/* ==========================================================================
 * FantasyStakes marketing site - local preview verification
 *
 *   node tools/marketing/preview_check.mjs [--out <dir>]
 *
 * Serves site/ exactly as Cloudflare Pages will - directory index resolution,
 * a 404 page with a 404 status, and every header in site/_headers, the CSP
 * included - then drives a real headless Chrome over it at the six viewports
 * the brief names and asserts what a human would otherwise have to eyeball.
 *
 * WHAT IT ASSERTS AND WHY EACH ONE IS HERE:
 *
 *   no horizontal overflow      the single most common mobile defect, and the
 *                               one screenshots hide because the scrollbar is
 *                               off-canvas
 *   the demo call to action     the site has one job; a viewport where the
 *                               button is not visible is a broken site
 *   navigation at every width   the disclosure has to collapse below 900px and
 *                               be a row at and above it, in BOTH directions.
 *                               Five links now, not four: the row is what
 *                               overflows first when a link is added, and a
 *                               wrapped topbar is a 110px bar
 *   every anchor resolves       an in-page link to a missing id fails silently
 *                               in a browser and is invisible in review
 *   the FAQ opens               <details> is native, but a stylesheet can still
 *                               collapse its panel to zero height
 *   the two cards hold shape    chips on one row and a closing line that does
 *                               not wrap. Both are width-dependent and both
 *                               fail as a ragged card rather than as an error,
 *                               which is exactly the class of defect a
 *                               screenshot review skims past
 *   tap targets                 44px minimum on the controls a thumb uses
 *   a clean console             which under this server includes CSP
 *                               violations and any 404 on a local asset
 *
 * Screenshots are written for human review; they are evidence, not assertions.
 * ========================================================================== */

import { mkdir, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { withBrowser, goto, evaluate } from './chrome.mjs';

const VIEWPORTS = [
  { width: 375, height: 812, mobile: true, label: '375-iphone-se' },
  { width: 390, height: 844, mobile: true, label: '390-iphone-14' },
  { width: 430, height: 932, mobile: true, label: '430-iphone-pro-max' },
  { width: 768, height: 1024, mobile: true, label: '768-tablet' },
  { width: 1024, height: 800, mobile: false, label: '1024-laptop' },
  { width: 1440, height: 900, mobile: false, label: '1440-desktop' },
];

const PAGES = ['/', '/terms/', '/privacy/', '/contact/'];

/** The live demo destination, cut over in WEB-2b. Must match site/js/config.js. */
const LIVE_DEMO_URL = 'https://app.fantasystakesapp.com';

/** The section ids the locked homepage order requires, in order. */
const REQUIRED_SECTIONS = [
  'top', 'what-is', 'two-ways', 'commissioners', 'players',
  'credits', 'how-to-play', 'demo', 'faq', 'get-started',
];

/** Locked navigation: five section links, in order, plus the demo control. */
const NAV_LINKS = [
  'What is FantasyStakes', 'How to Play', 'For Commissioners', 'For Players', 'FAQ',
];

const outArg = process.argv.indexOf('--out');
const OUT = outArg > -1 ? process.argv[outArg + 1] : join(tmpdir(), 'fantasystakes-preview');

let failures = 0;
function check(ok, label, detail) {
  if (ok) {
    console.log(`  [PASS] ${label}`);
  } else {
    failures += 1;
    console.log(`  [FAIL] ${label}${detail ? ` - ${detail}` : ''}`);
  }
}

await mkdir(OUT, { recursive: true });

await withBrowser(async ({ cdp, origin }) => {
  /* Console, exception and browser-log capture. Log.entryAdded is the one that
     matters most: CSP violations and failed subresource loads arrive there, and
     neither shows up as a page exception. */
  const problems = [];
  cdp.on((message) => {
    if (message.method === 'Runtime.exceptionThrown') {
      problems.push(`exception: ${message.params.exceptionDetails.text}`);
    }
    if (message.method === 'Runtime.consoleAPICalled' && message.params.type === 'error') {
      problems.push(`console.error: ${message.params.args.map((a) => a.value).join(' ')}`);
    }
    if (message.method === 'Log.entryAdded' && message.params.entry.level === 'error') {
      problems.push(`${message.params.entry.source}: ${message.params.entry.text}`);
    }
  });

  /* ── Every page renders, and every page renders clean ──────────────────── */
  console.log('\nPages');
  for (const path of PAGES) {
    await cdp.send('Emulation.setDeviceMetricsOverride', {
      width: 390, height: 844, deviceScaleFactor: 1, mobile: true,
    });
    await goto(cdp, origin + path, 500);
    const title = await evaluate(cdp, 'return document.title;');
    const h1 = await evaluate(cdp, 'return (document.querySelector("h1")||{}).textContent || "";');
    check(Boolean(title), `${path} has a title`, title);
    check(h1.trim().length > 0, `${path} has an h1`, h1.trim().slice(0, 60));
  }

  /* ── 404 behaviour ────────────────────────────────────────────────────── */
  const notFound = await fetch(`${origin}/definitely-not-a-page`);
  check(notFound.status === 404, '/definitely-not-a-page returns 404', String(notFound.status));
  check((await notFound.text()).includes('not in this league'), '404 body is the styled 404 page');

  /* ── Headers actually reach the browser ───────────────────────────────── */
  console.log('\nHeaders (served from site/_headers)');
  const headRes = await fetch(`${origin}/`);
  for (const name of ['content-security-policy', 'x-content-type-options', 'referrer-policy', 'permissions-policy', 'x-frame-options']) {
    check(Boolean(headRes.headers.get(name)), `/ sends ${name}`);
  }

  /* ── Homepage structure ───────────────────────────────────────────────── */
  console.log('\nHomepage structure');
  await goto(cdp, `${origin}/`, 600);

  const sections = await evaluate(cdp, `
    return ${JSON.stringify(REQUIRED_SECTIONS)}.filter(function (id) {
      return !document.getElementById(id);
    });
  `);
  check(sections.length === 0, 'all locked homepage sections are present', sections.join(', '));

  const brokenAnchors = await evaluate(cdp, `
    var out = [];
    var links = document.querySelectorAll('a[href^="#"]');
    for (var i = 0; i < links.length; i += 1) {
      var id = links[i].getAttribute('href').slice(1);
      if (id && !document.getElementById(id)) out.push(id);
    }
    return out;
  `);
  check(brokenAnchors.length === 0, 'every in-page anchor resolves', brokenAnchors.join(', '));

  const demoLinks = await evaluate(cdp, `
    var links = document.querySelectorAll('[data-fs-demo-link]');
    var out = [];
    for (var i = 0; i < links.length; i += 1) out.push(links[i].getAttribute('href'));
    return out;
  `);
  check(demoLinks.length >= 4, 'at least four Try the Demo controls', `found ${demoLinks.length}`);
  check(new Set(demoLinks).size === 1, 'every demo control shares one destination', demoLinks.join(' | '));

  /* WEB-2b. These hrefs are read AFTER site.js has run, so this is the value a
     reader actually clicks - not the fallback the markup shipped. */
  check(
    demoLinks.every((href) => href === LIVE_DEMO_URL),
    'every demo control resolves to the live demo root',
    demoLinks.join(' | '),
  );
  check(
    demoLinks.every((href) => !href.startsWith('#')),
    'no demo control is left on the on-page placeholder',
    demoLinks.join(' | '),
  );
  check(
    demoLinks.every((href) => !/railway/i.test(href)),
    'no demo control names the hosting platform host',
    demoLinks.join(' | '),
  );

  const faq = await evaluate(cdp, `
    var items = document.querySelectorAll('.faq details');
    if (items.length === 0) return { count: 0 };
    // Measured on the <details> element itself. A closed <details> still gives
    // its hidden children a resolvable box in Chrome, so measuring the answer
    // panel would report the same height open or closed and prove nothing.
    // The POR ships the FIRST entry open, so the measurement drives the state
    // explicitly rather than assuming it starts closed - and puts it back.
    var first = items[0];
    var was = first.open;
    first.open = false;
    var closed = first.getBoundingClientRect().height;
    first.open = true;
    var open = first.getBoundingClientRect().height;
    first.open = was;
    return { count: items.length, closed: closed, open: open, shipsOpen: was };
  `);
  check(faq.count === 7, 'seven FAQ entries', `found ${faq.count}`);
  check(faq.open > faq.closed + 20, 'the FAQ opens and closes', JSON.stringify(faq));
  check(faq.shipsOpen === true, 'the first FAQ entry ships open, as the POR does');

  const attribution = await evaluate(cdp, `
    return (document.querySelector('.attribution') || {}).textContent || '';
  `);
  check(
    attribution.replace(/\s+/g, ' ').trim() === 'Fantasy data provided by Yahoo Fantasy',
    'the Yahoo attribution string is exact',
    attribution.trim(),
  );

  /* ── Every viewport ───────────────────────────────────────────────────── */
  for (const vp of VIEWPORTS) {
    console.log(`\nViewport ${vp.width}x${vp.height}`);
    await cdp.send('Emulation.setDeviceMetricsOverride', {
      width: vp.width, height: vp.height, deviceScaleFactor: 1, mobile: vp.mobile,
    });
    await goto(cdp, `${origin}/`, 500);

    const overflow = await evaluate(cdp, `
      var d = document.documentElement;
      return { scroll: d.scrollWidth, client: d.clientWidth, inner: window.innerWidth };
    `);
    check(
      overflow.scroll <= overflow.client + 1,
      'no horizontal overflow',
      `scrollWidth ${overflow.scroll} vs clientWidth ${overflow.client}`,
    );

    const nav = await evaluate(cdp, `
      function box(el) { return el ? el.getBoundingClientRect() : null; }
      var toggle = document.querySelector('[data-fs-nav-toggle]');
      var panel = document.getElementById('site-nav');
      var cta = document.querySelector('.topbar [data-fs-demo-link]');
      var t = box(toggle), p = box(panel), c = box(cta);
      return {
        toggleVisible: !!t && t.width > 0 && t.height > 0,
        toggleSize: t ? Math.min(t.width, t.height) : 0,
        panelVisible: !!p && p.height > 0,
        ctaVisible: !!c && c.width > 0 && c.height > 0,
        ctaTop: c ? c.top : -1,
        expanded: toggle ? toggle.getAttribute('aria-expanded') : null,
        barHeight: document.querySelector('.topbar').getBoundingClientRect().height,
        navRight: p ? p.right : 0,
        barRight: document.querySelector('.topbar__inner').getBoundingClientRect().right,
        navFits: !!p && !!c && p.right <= c.left + 1,
        linksOnOneRow: (function () {
          var links = document.querySelectorAll('#site-nav a');
          if (!links.length) return false;
          var top = links[0].getBoundingClientRect().top;
          for (var i = 1; i < links.length; i += 1) {
            if (Math.abs(links[i].getBoundingClientRect().top - top) > 1) return false;
          }
          return true;
        }())
      };
    `);

    check(nav.ctaVisible, 'the topbar Try the Demo control is visible');
    check(nav.ctaTop >= 0 && nav.ctaTop < vp.height, 'the topbar call to action is above the fold', String(nav.ctaTop));

    if (vp.width < 900) {
      check(nav.toggleVisible, 'the menu toggle is shown below 900px');
      check(nav.toggleSize >= 40, 'the menu toggle is at least 40px', String(nav.toggleSize));
      check(!nav.panelVisible, 'the navigation panel starts collapsed');
      check(nav.expanded === 'false', 'aria-expanded starts false', String(nav.expanded));

      const opened = await evaluate(cdp, `
        var toggle = document.querySelector('[data-fs-nav-toggle]');
        toggle.click();
        var panel = document.getElementById('site-nav');
        var links = panel.querySelectorAll('a');
        var min = Infinity;
        for (var i = 0; i < links.length; i += 1) {
          min = Math.min(min, links[i].getBoundingClientRect().height);
        }
        var labels = [];
        for (var j = 0; j < links.length; j += 1) labels.push(links[j].textContent.trim());
        return {
          visible: panel.getBoundingClientRect().height > 0,
          expanded: toggle.getAttribute('aria-expanded'),
          links: links.length,
          labels: labels,
          minLinkHeight: min
        };
      `);
      check(opened.visible, 'tapping the toggle opens the navigation');
      check(opened.expanded === 'true', 'aria-expanded flips to true');
      check(opened.links === NAV_LINKS.length, 'five navigation links', String(opened.links));
      check(
        opened.labels.join(' | ') === NAV_LINKS.join(' | '),
        'the navigation carries the locked five, in order',
        opened.labels.join(' | '),
      );
      check(opened.minLinkHeight >= 44, 'navigation links are at least 44px tall', String(opened.minLinkHeight));

      const closed = await evaluate(cdp, `
        document.querySelector('#site-nav a').click();
        var panel = document.getElementById('site-nav');
        var toggle = document.querySelector('[data-fs-nav-toggle]');
        return { visible: panel.getBoundingClientRect().height > 0, expanded: toggle.getAttribute('aria-expanded') };
      `);
      check(!closed.visible, 'following a navigation link closes the panel');
      check(closed.expanded === 'false', 'aria-expanded returns to false');
    } else {
      check(!nav.toggleVisible, 'the menu toggle is hidden at 900px and up');
      check(nav.panelVisible, 'the navigation row is shown at 900px and up');
      // A stacked list turns the 62px bar into a 110px one and pushes the hero
      // down; the bar height is the cheapest way to notice.
      check(
        nav.barHeight <= 70,
        'the topbar stays a single row at 900px and up',
        `${Math.round(nav.barHeight)}px`,
      );
      check(nav.linksOnOneRow, 'the five navigation links share one row');
      check(nav.navFits, 'the topbar row fits without clipping a link',
        `nav ${Math.round(nav.navRight)} vs bar ${Math.round(nav.barRight)}`);
    }

    const hero = await evaluate(cdp, `
      var section = document.getElementById('top');
      var brand = document.querySelector('.brand');
      var h1 = document.getElementById('hero-title');
      var cta = section.querySelector('.cta-row .btn--primary');
      var box = section.getBoundingClientRect();
      var b = brand.getBoundingClientRect();
      var t = h1.getBoundingClientRect();
      var centred = Math.abs((b.left + b.right) / 2 - window.innerWidth / 2);
      return {
        height: box.height,
        viewport: window.innerHeight,
        brandCentreOffset: centred,
        // scrollWidth exceeds clientWidth exactly when the wordmark is being
        // clipped by the page-level overflow guard - which is what the POR
        // source does at 390px and what this build must not do.
        brandTextWidth: brand.scrollWidth,
        brandBoxWidth: brand.clientWidth,
        brandOverflow: brand.scrollWidth - brand.clientWidth,
        brandSize: parseFloat(getComputedStyle(brand).fontSize),
        h1Size: parseFloat(getComputedStyle(h1).fontSize),
        h1Text: h1.textContent.trim(),
        align: getComputedStyle(h1).textAlign,
        ctaWidth: cta ? cta.getBoundingClientRect().width : 0
      };
    `);
    check(
      hero.height >= hero.viewport - 62 - 1,
      'the hero fills the viewport below the topbar',
      `${Math.round(hero.height)} vs ${hero.viewport - 62}`,
    );
    check(hero.brandCentreOffset < 2, 'the wordmark lockup is centred', String(Math.round(hero.brandCentreOffset)));
    check(
      hero.brandOverflow <= 1,
      'the wordmark fits its column without clipping',
      `text ${Math.round(hero.brandTextWidth)} in ${Math.round(hero.brandBoxWidth)}`,
    );
    check(hero.align === 'center', 'the hero is centre-aligned', hero.align);
    check(hero.brandSize > hero.h1Size, 'the wordmark outsizes the headline',
      `brand ${Math.round(hero.brandSize)} vs h1 ${Math.round(hero.h1Size)}`);
    check(
      hero.h1Text === 'Add a Vegas-style sportsbook game to your fantasy league.',
      'the hero carries the WEB-1a locked headline',
      hero.h1Text,
    );
    if (vp.width < 700) {
      check(hero.ctaWidth > vp.width * 0.6, 'the primary call to action is full width below 700px',
        String(Math.round(hero.ctaWidth)));
    }

    /* PARALLEL CONSTRUCTION OF THE TWO COMPETE CARDS.
     *
     * From 700px up the cards sit side by side, and every property that makes
     * them read as one template is width-dependent and invisible in a diff:
     * equal height, chip rows on one line AND on the same line as each other,
     * closing lines on one line and on the same baseline, and identical
     * computed type in both. The cards' copy wraps differently, so all of this
     * is held by the card grid rather than by sentence length - which is
     * exactly why it needs measuring rather than reading.
     *
     * Line boxes are counted with a Range: a <p> reports one client rect
     * whether it wrapped or not, so `getClientRects().length` on the element
     * would always say 1 and prove nothing. */
    if (vp.width >= 700) {
      const cards = await evaluate(cdp, `
        function lineCount(el) {
          var range = document.createRange();
          range.selectNodeContents(el);
          return range.getClientRects().length;
        }
        function type(el) {
          if (!el) return null;
          var s = getComputedStyle(el);
          return [s.fontFamily, s.fontSize, s.fontWeight, s.fontStyle,
                  s.lineHeight, s.color].join(' | ');
        }
        function round(n) { return Math.round(n * 100) / 100; }
        var out = [];
        var articles = document.querySelectorAll('#two-ways .card');
        for (var i = 0; i < articles.length; i += 1) {
          var card = articles[i];
          var chips = card.querySelectorAll('.chip');
          var top = chips.length ? chips[0].getBoundingClientRect().top : 0;
          var oneRow = chips.length > 0;
          for (var j = 1; j < chips.length; j += 1) {
            if (Math.abs(chips[j].getBoundingClientRect().top - top) > 1) oneRow = false;
          }
          var note = card.querySelector('.card__note');
          var body = card.querySelector('p:not([class])');
          var odds = card.querySelector('.odds');
          var box = card.getBoundingClientRect();
          out.push({
            pill: (card.querySelector('.pill') || {}).textContent || '',
            pillType: type(card.querySelector('.pill')),
            headingType: type(card.querySelector('h3')),
            chips: chips.length,
            chipsOnOneRow: oneRow,
            chipType: type(chips[0]),
            chipRowTop: odds ? round(odds.getBoundingClientRect().top) : null,
            note: note ? note.textContent.trim() : null,
            noteLines: note ? lineCount(note) : 0,
            noteTop: note ? round(note.getBoundingClientRect().top) : null,
            noteType: type(note),
            bodyType: type(body),
            height: round(box.height),
            width: round(box.width)
          });
        }
        return out;
      `);

      check(cards.length === 2, 'two compete cards', `found ${cards.length}`);
      for (const card of cards) {
        const label = card.pill || '(unlabelled card)';
        check(card.chips === 3, `${label}: three chips`, String(card.chips));
        check(card.chipsOnOneRow, `${label}: the chips share one row`);
        check(card.note !== null, `${label}: the card closes on a gold line`);
        check(
          card.noteLines === 1,
          `${label}: the closing line stays on one line`,
          `${card.noteLines} lines for "${card.note}" in ${Math.round(card.width)}px`,
        );
      }

      if (cards.length === 2) {
        const [a, b] = cards;
        /* Geometry. Each of these was measurably wrong before the card grid:
           the chip rows and closing lines sat 32px apart at all three widths. */
        check(a.width === b.width, 'the two cards are the same width',
          `${a.width} vs ${b.width}`);
        check(a.height === b.height, 'the two cards are the same height',
          `${a.height} vs ${b.height}`);
        check(a.chipRowTop === b.chipRowTop,
          'both chip rows sit on the same line',
          `${a.chipRowTop} vs ${b.chipRowTop}`);
        check(a.noteTop === b.noteTop,
          'both closing lines sit on the same baseline',
          `${a.noteTop} vs ${b.noteTop}`);

        /* Typography. Same template means the same computed type and colour,
           not merely the same class names in the markup. */
        for (const [what, left, right] of [
          ['pill', a.pillType, b.pillType],
          ['heading', a.headingType, b.headingType],
          ['body copy', a.bodyType, b.bodyType],
          ['chips', a.chipType, b.chipType],
          ['closing line', a.noteType, b.noteType],
        ]) {
          check(left !== null && left === right,
            `both cards render ${what} with identical type and colour`,
            `${left} VS ${right}`);
        }
      }
    }

    /* THE CLOSING TAGLINE IS CENTRED ON THE SECTION, not on its own box.
       Measured with a Range over the text, because the element box can be
       centred while the words inside it are not - and it can equally be
       off-centre while `text-align: center` makes it look composed. This was
       92px left of centre at every desktop width before the fix. */
    const tagline = await evaluate(cdp, `
      var close = document.querySelector('.close');
      var wrap = close.querySelector('.wrap');
      var tag = close.querySelector('.tagline');
      var range = document.createRange();
      range.selectNodeContents(tag);
      var text = range.getBoundingClientRect();
      var column = wrap.getBoundingClientRect();
      return {
        offset: ((text.left + text.right) / 2) - ((column.left + column.right) / 2),
        text: tag.textContent.trim(),
        lines: range.getClientRects().length
      };
    `);
    check(
      Math.abs(tagline.offset) <= 1,
      'the closing tagline is centred on the section',
      `${Math.round(tagline.offset)}px off centre`,
    );
    check(
      tagline.text === 'Real odds. Sportsbook action. More ways to win.',
      'the closing tagline is the locked line',
      tagline.text,
    );

    /* Anchor scrolling has to land the heading clear of the sticky topbar. */
    const anchored = await evaluate(cdp, `
      location.hash = '';
      location.hash = '#faq';
      var head = document.querySelector('.topbar').getBoundingClientRect();
      var title = document.getElementById('faq-title').getBoundingClientRect();
      return { topbarBottom: head.bottom, titleTop: title.top };
    `);
    check(
      anchored.titleTop >= anchored.topbarBottom - 1,
      'an anchor jump clears the sticky topbar',
      `title ${Math.round(anchored.titleTop)} vs topbar ${Math.round(anchored.topbarBottom)}`,
    );

    await evaluate(cdp, "history.replaceState(null, '', location.pathname); window.scrollTo(0, 0); return 1;");
    await new Promise((ok) => setTimeout(ok, 150));
    const shot = await cdp.send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
    await writeFile(join(OUT, `home-${vp.label}.png`), Buffer.from(shot.data, 'base64'));
  }

  /* ── The footer is navigation and the contractual line ───────────────── */
  console.log('\nFooter');
  await cdp.send('Emulation.setDeviceMetricsOverride', {
    width: 1024, height: 800, deviceScaleFactor: 1, mobile: false,
  });
  await goto(cdp, `${origin}/`, 500);
  const footer = await evaluate(cdp, `
    var f = document.querySelector('.footer');
    var close = document.querySelector('.close');
    var links = f.querySelectorAll('.footer__links a');
    var labels = [];
    for (var i = 0; i < links.length; i += 1) labels.push(links[i].textContent.trim());
    var bottom = f.querySelector('.footer__bottom');
    var rows = bottom ? bottom.querySelectorAll('p') : [];
    return {
      height: Math.round(f.getBoundingClientRect().height),
      closeHeight: Math.round(close.getBoundingClientRect().height),
      labels: labels,
      bottomRows: rows.length,
      attributionHref: (f.querySelector('.attribution a') || {}).href || '',
      paragraphs: f.querySelectorAll('p').length,
      text: f.textContent
    };
  `);
  /* Whitespace is collapsed HERE, not in the page. `\s` inside a template
     literal is not a recognised escape, so it reaches the browser as a bare
     `s` and the regex quietly deletes every letter s in the footer. */
  footer.text = footer.text.replace(/\s+/g, ' ').trim();

  check(
    footer.labels.join(' | ') === 'How to Play | FAQ | Terms | Privacy | Contact',
    'the footer nav is the locked five, in order',
    footer.labels.join(' | '),
  );
  check(footer.paragraphs === 2,
    'the footer carries two lines: the attribution and the copyright',
    String(footer.paragraphs));
  check(footer.bottomRows === 2, 'the bottom row has both halves', String(footer.bottomRows));
  check(
    footer.attributionHref === 'https://football.fantasysports.yahoo.com/',
    'the Yahoo attribution is still a link to Yahoo Fantasy',
    footer.attributionHref,
  );
  check(footer.text.includes('Fantasy data provided by Yahoo Fantasy'),
    'the contractual attribution string is intact');
  check(footer.text.includes('\u00a9 2026 FantasyStakes'),
    'the copyright line is intact');
  /* Everything the final visual lock took out. */
  for (const retired of [
    'FANTASYSTAKES',
    'Fantasy Stakes for Fantasy Leagues',
    'No house. No vig. No cash. Only FantasyStakes.',
    'Credits have no cash value',
  ]) {
    check(!footer.text.includes(retired), `the footer no longer restates "${retired}"`);
  }
  check(!/rights reserved/i.test(footer.text), 'the footer does not say All Rights Reserved');
  check(footer.height < footer.closeHeight / 4,
    'the footer is subordinate to the closing call to action',
    `footer ${footer.height} vs close ${footer.closeHeight}`);

  /* ── Reduced motion is honoured ───────────────────────────────────────── */
  console.log('\nPreferences');
  await cdp.send('Emulation.setEmulatedMedia', {
    features: [{ name: 'prefers-reduced-motion', value: 'reduce' }],
  });
  await goto(cdp, `${origin}/`, 400);
  const scrollBehaviour = await evaluate(cdp, `
    return getComputedStyle(document.documentElement).scrollBehavior;
  `);
  check(scrollBehaviour === 'auto', 'smooth scrolling is off under prefers-reduced-motion', scrollBehaviour);
  await cdp.send('Emulation.setEmulatedMedia', { features: [] });

  /* ── Nothing complained ───────────────────────────────────────────────── */
  console.log('\nConsole');
  check(problems.length === 0, 'no console errors, exceptions or CSP violations', problems.join(' | '));
});

console.log(`\nscreenshots: ${OUT}`);
if (failures > 0) {
  console.log(`\nFAILED: ${failures} check(s)`);
  process.exit(1);
}
console.log('\nAll checks PASSED');
