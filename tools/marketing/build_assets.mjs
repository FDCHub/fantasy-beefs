/* ==========================================================================
 * FantasyStakes marketing site - generate the raster assets
 *
 *   node tools/marketing/build_assets.mjs
 *
 * WHAT IT MAKES, and why each one has to be a PNG rather than the SVG we
 * already have:
 *
 *   site/assets/favicon-32.png       legacy favicon - some clients ignore SVG
 *   site/assets/apple-touch-icon.png iOS home screen - reads PNG only
 *   site/assets/icon-192.png         web manifest
 *   site/assets/icon-512.png         web manifest
 *   site/assets/og-image.png         social card - scrapers do not render SVG
 *
 * Rasterised by the same headless Chrome the preview check uses, so the build
 * has no image library and no dependency to install. The sources are
 * site/assets/favicon.svg and tools/marketing/og-image.html; both are text,
 * both are reviewable in a diff, and neither is a binary someone has to trust.
 *
 * COMMIT THE OUTPUT. Cloudflare Pages serves this repository directly with no
 * build step, so the PNGs are part of the site, not a build artefact.
 * ========================================================================== */

import { writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { withBrowser, goto, SITE_ROOT } from './chrome.mjs';

const ICONS = [
  { file: 'favicon-32.png', size: 32 },
  { file: 'apple-touch-icon.png', size: 180 },
  { file: 'icon-192.png', size: 192 },
  { file: 'icon-512.png', size: 512 },
];

async function shoot(cdp, { width, height }) {
  await cdp.send('Emulation.setDeviceMetricsOverride', {
    width, height, deviceScaleFactor: 1, mobile: false,
  });
  // The monogram SVG has rounded corners; without this the corners rasterise
  // transparent, which iOS renders as black-on-black chrome rather than as the
  // mark. An opaque page background is the right answer for an app icon.
  await cdp.send('Emulation.setDefaultBackgroundColorOverride', {
    color: { r: 11, g: 11, b: 10, a: 1 },
  });
  const shot = await cdp.send('Page.captureScreenshot', {
    format: 'png',
    clip: { x: 0, y: 0, width, height, scale: 1 },
    captureBeyondViewport: true,
  });
  return Buffer.from(shot.data, 'base64');
}

await withBrowser(async ({ cdp, origin }) => {
  for (const icon of ICONS) {
    await goto(cdp, `${origin}/assets/favicon.svg`, 250);
    const png = await shoot(cdp, { width: icon.size, height: icon.size });
    await writeFile(join(SITE_ROOT, 'assets', icon.file), png);
    console.log(`  wrote assets/${icon.file}  ${icon.size}x${icon.size}  ${png.length} bytes`);
  }

  await goto(cdp, `${origin}/_tools/og-image.html`, 500);
  const card = await shoot(cdp, { width: 1200, height: 630 });
  await writeFile(join(SITE_ROOT, 'assets', 'og-image.png'), card);
  console.log(`  wrote assets/og-image.png  1200x630  ${card.length} bytes`);
});

console.log('assets built');
