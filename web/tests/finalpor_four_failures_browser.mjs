import { createReporter, withPage } from './browser-harness.mjs';

const { check, section, finish } = createReporter();
const VIEWPORTS = [[320, 568], [375, 667], [390, 844]];
const EXPECT_COMMISSIONER = process.env.FS_TEST_EXPECT_COMMISSIONER === '1';

await withPage({ origin: process.env.FS_TEST_ORIGIN,
  port: EXPECT_COMMISSIONER ? 9343 : 9333, settleMs: 1500 }, async ({ evaluate, setViewport }) => {
  const mounted = await evaluate(`return new Promise((resolve) => {
    const end = Date.now() + 12000;
    const poll = () => document.querySelector('#fs-gear')
      ? resolve(true) : Date.now() > end ? resolve(false) : setTimeout(poll, 100);
    poll();
  })`);
  check('the authenticated application mounts before interaction', mounted === true);

  section('Settings glyph is a rendered cog, not a sun');
  const gear = await evaluate(`
    const svg = document.querySelector('#fs-gear svg');
    const outer = svg && svg.querySelector('path');
    const circle = svg && svg.querySelector('circle');
    const box = outer ? outer.getBBox() : null;
    return {
      present: Boolean(svg && outer && circle),
      viewBox: svg && svg.getAttribute('viewBox'),
      rendered: svg ? svg.getBoundingClientRect().width : 0,
      moves: outer ? (outer.getAttribute('d').match(/M/gi) || []).length : 0,
      pathLength: outer ? outer.getTotalLength() : 0,
      outerBox: box ? { width: box.width, height: box.height } : null,
      innerRadius: circle ? Number(circle.getAttribute('r')) : 0,
    };
  `);
  check('gear has an outer cog contour and inner hub', gear.present
    && gear.viewBox === '0 0 24 24' && gear.moves === 1
    && gear.pathLength > 50 && gear.outerBox.width > 18 && gear.outerBox.height > 18
    && gear.innerRadius === 3, JSON.stringify(gear));
  check('gear is visibly rendered at the control', gear.rendered >= 20, `${gear.rendered}px`);

  section('Rules and League Settings are distinct rendered destinations');
  const destinations = await evaluate(`return (async () => {
    const waitFor = async (read) => {
      const end = Date.now() + 5000;
      let value;
      while (!(value = read()) && Date.now() < end) {
        await new Promise((resolve) => setTimeout(resolve, 50));
      }
      return value;
    };
    const open = async (id) => {
      const end = Date.now() + 5000;
      let panel = null;
      while (!panel && Date.now() < end) {
        if (!document.getElementById('fs-menu')) {
          document.querySelector('#fs-gear').click();
        }
        const row = await waitFor(() => document.querySelector(
          '#fs-menu [data-menu="' + id + '"]'));
        if (row) row.click();
        await new Promise((resolve) => setTimeout(resolve, 100));
        panel = document.querySelector('#panel-' + id + '.is-active');
      }
      return {
        id: panel.id,
        title: (panel.querySelector('.fs-tabhead__title') || {}).textContent || '',
        rules: panel.querySelectorAll('[data-region="rules"]').length,
        settings: panel.querySelectorAll('[data-region="settings"]').length,
        headings: [...panel.querySelectorAll('.fs-heading__text')].map((e) => e.textContent),
      };
    };
    return { rules: await open('rules'), settings: await open('settings') };
  })()`);
  check('Rules opens the Rules-only panel', destinations.rules.id === 'panel-rules'
    && destinations.rules.title === 'RULES' && destinations.rules.rules === 1
    && destinations.rules.settings === 0, JSON.stringify(destinations.rules));
  check('League Settings opens its own settings-only panel',
    destinations.settings.id === 'panel-settings'
    && destinations.settings.title === 'LEAGUE SETTINGS'
    && destinations.settings.rules === 0 && destinations.settings.settings === 1,
    JSON.stringify(destinations.settings));
  check('the destinations are different rendered panels',
    destinations.rules.id !== destinations.settings.id);

  section('All Settings destinations are real and role-aware');
  const settingsDestinations = await evaluate(`return (async () => {
    const gear = document.querySelector('#fs-gear');
    const waitFor = async (read) => {
      const end = Date.now() + 5000;
      let value;
      while (!(value = read()) && Date.now() < end) {
        await new Promise((resolve) => setTimeout(resolve, 50));
      }
      return value;
    };
    const openMenu = async () => {
      if (!document.getElementById('fs-menu')) gear.click();
      return waitFor(() => document.getElementById('fs-menu'));
    };
    const inspectMenu = async () => {
      const menu = await openMenu();
      return {
        destinations: ['rules','settings','provider','about'].map((id) => {
          const row = menu.querySelector('[data-menu="' + id + '"]');
          return { id, tag: row && row.tagName, kind: row && row.dataset.menuKind,
            pending: Boolean(row && row.classList.contains('is-pending')) };
        }),
        commissioner: Boolean(menu.querySelector('[data-menu="commissioner"][data-menu-kind="destination"]')),
      };
    };
    const click = async (id) => {
      const end = Date.now() + 5000;
      let panel = null;
      while (!panel && Date.now() < end) {
        const menu = await openMenu();
        const row = await waitFor(() => menu.querySelector('[data-menu="' + id + '"]'));
        if (row) row.click();
        await new Promise((resolve) => setTimeout(resolve, 100));
        panel = document.querySelector('#panel-' + id + '.is-active');
      }
      return { id: panel.id,
        title: panel.querySelector('.fs-tabhead__title').textContent,
        text: panel.textContent,
        providerLabel: (panel.querySelector('[data-provider-label]') || {}).textContent || '',
        providerFamily: (panel.querySelector('[data-provider-family]') || {}).dataset?.providerFamily || '' };
    };
    const menu = await inspectMenu();
    const provider = await click('provider');
    const about = await click('about');
    const mastProvider = document.querySelector('.fs-source')?.textContent || '';
    return { menu, provider, about, mastProvider };
  })()`);
  check('Rules, League Settings, Provider Information and About & Legal are controls',
    settingsDestinations.menu.destinations.every((row) => row.tag === 'BUTTON'
      && row.kind === 'destination' && !row.pending),
    JSON.stringify(settingsDestinations.menu.destinations));
  check('Provider Information opens a distinct rendered panel',
    settingsDestinations.provider.id === 'panel-provider'
      && settingsDestinations.provider.title === 'PROVIDER INFORMATION',
    JSON.stringify(settingsDestinations.provider));
  check('Provider Information renders the same authoritative state as the masthead',
    settingsDestinations.provider.providerLabel.length > 0
      && settingsDestinations.provider.providerLabel === settingsDestinations.mastProvider.trim(),
    JSON.stringify(settingsDestinations));
  check('Demo state stays distinct and no unavailable state claims Yahoo authorization',
    (settingsDestinations.provider.providerFamily !== 'demo'
      || settingsDestinations.provider.providerLabel === 'DEMO')
      && (!['none'].includes(settingsDestinations.provider.providerFamily)
        || !/YAHOO.*CONNECTED/i.test(settingsDestinations.provider.providerLabel)),
    JSON.stringify(settingsDestinations.provider));
  check('About & Legal opens a distinct rendered panel',
    settingsDestinations.about.id === 'panel-about'
      && settingsDestinations.about.title === 'ABOUT & LEGAL',
    JSON.stringify(settingsDestinations.about));
  check('About & Legal preserves the approved cashless positioning',
    /VIRTUAL CREDITS/.test(settingsDestinations.about.text)
      && /NO CASH VALUE/.test(settingsDestinations.about.text)
      && /cannot be deposited, withdrawn or redeemed/.test(settingsDestinations.about.text)
      && /All Rights Reserved/.test(settingsDestinations.about.text),
    settingsDestinations.about.text);
  check('Commissioner controls are separate and role-aware',
    settingsDestinations.menu.commissioner === EXPECT_COMMISSIONER,
    JSON.stringify({ expected: EXPECT_COMMISSIONER,
      rendered: settingsDestinations.menu.commissioner }));

  for (const [width, height] of VIEWPORTS) {
    await setViewport(width, height);
    const at = `${width}x${height}`;

    section(`Account Escrow geometry — ${at}`);
    const account = await evaluate(`
      FantasyStakes.goTo('ledger');
      const cells = [...document.querySelectorAll('#fs-strip-ledger .fs-strip__cell')];
      const escrow = cells[2], min = cells[3];
      const value = escrow.querySelector('.fs-strip__value');
      const context = escrow.querySelector('.fs-strip__context');
      const range = document.createRange();
      range.setStart(value.firstChild, 0);
      range.setEnd(value.firstChild, value.firstChild.length);
      const R = (source) => {
        const r = source.getBoundingClientRect();
        return { x:r.x, y:r.y, width:r.width, height:r.height,
                 right:r.right, bottom:r.bottom };
      };
      const valueText = R(range), contextRect = R(context), minRect = R(min), cellRect = R(escrow);
      const intersects = (a, b) => a.right > b.x && a.x < b.right
        && a.bottom > b.y && a.y < b.bottom;
      return { valueText, contextRect, minRect, cellRect,
        intersects: intersects(contextRect, minRect),
        valueCentered: Math.abs((valueText.x + valueText.width / 2)
          - (cellRect.x + cellRect.width / 2)),
        contextCentered: Math.abs((contextRect.x + contextRect.width / 2)
          - (cellRect.x + cellRect.width / 2)),
        beneath: contextRect.y >= valueText.bottom - .5,
        contextFont: getComputedStyle(context).fontSize,
        direction: getComputedStyle(value).flexDirection };
    `);
    check(`Escrow value is centered — ${at}`, account.valueCentered <= 1,
      JSON.stringify(account));
    check(`Escrow context is centered directly beneath — ${at}`,
      account.contextCentered <= 1 && account.beneath && account.direction === 'column',
      JSON.stringify(account));
    check(`Escrow context is secondary type — ${at}`,
      parseFloat(account.contextFont) < 10, account.contextFont);
    check(`Escrow context does not intersect MIN LEFT — ${at}`,
      account.intersects === false, JSON.stringify(account));

    section(`SWIPE uses Play's helper treatment — ${at}`);
    const swipe = await evaluate(`
      const style = (e) => { const s = getComputedStyle(e); return {
        fontSize:s.fontSize, fontWeight:s.fontWeight, color:s.color,
        lineHeight:s.lineHeight, letterSpacing:s.letterSpacing,
        className:e.className, parent:e.parentElement.className,
        last:e.parentElement.lastElementChild === e } };
      const read = (panel) => [...document.querySelectorAll(panel + ' .fs-heading')]
        .filter((h) => h.textContent.includes('SWIPE')).map((h) => ({
          title:h.querySelector('.fs-heading__text').textContent,
          helperText:(h.querySelector('.fs-heading__helper') || {}).textContent || '',
          helper:h.querySelector('.fs-heading__helper')
            ? style(h.querySelector('.fs-heading__helper')) : null }));
      return { play:read('#panel-league'), status:read('#panel-action'), wrap:read('#panel-week') };
    `);
    const canonical = swipe.play.length > 0 ? swipe.play[0].helper : null;
    check(`Play exposes the canonical SWIPE helper — ${at}`,
      Boolean(canonical), JSON.stringify(swipe.play));
    for (const [surface, rows] of Object.entries(swipe)) {
      check(`${surface} puts SWIPE in the helper slot — ${at}`,
        rows.length > 0 && rows.every((r) => r.helper && r.helper.className === 'fs-heading__helper'
          && r.helper.parent === 'fs-heading' && r.helper.last
          && !r.title.includes('SWIPE') && r.helperText.includes('SWIPE')),
        JSON.stringify(rows));
      check(`${surface} matches Play helper typography — ${at}`,
        Boolean(canonical) && rows.every((r) => ['fontSize','fontWeight','color','lineHeight','letterSpacing']
          .every((key) => r.helper[key] === canonical[key])), JSON.stringify(rows));
    }
  }
});

finish();
