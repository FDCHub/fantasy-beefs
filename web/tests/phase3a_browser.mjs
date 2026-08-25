import { createReporter, withPage } from './browser-harness.mjs';

const { check, section, finish } = createReporter();
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

await withPage({ origin: process.env.FS_TEST_ORIGIN, settleMs: 1000 }, async ({ evaluate, setViewport }) => {
  await evaluate(`return fetch('/demo/enter', {method:'POST', credentials:'include'}).then(r => r.json())`);
  await evaluate(`location.href='/app/index.html'; true`);
  await wait(4500);
  await evaluate(`return new Promise(resolve=>{const end=Date.now()+12000;const p=()=>{if(document.querySelector('.fs-tabbar__item[data-destination="league"]'))resolve(true);else if(Date.now()>end)resolve(false);else setTimeout(p,100)};p()})`);

  section('Preview exposes four real collapsed accordions');
  await evaluate(`document.querySelector('.fs-tabbar__item[data-destination="league"]').click(); true`);
  await evaluate(`return new Promise(resolve=>{const end=Date.now()+12000;const p=()=>{if(document.querySelector('[data-card-action="challenge"]'))resolve(true);else if(Date.now()>end)resolve(false);else setTimeout(p,100)};p()})`);
  await evaluate(`document.querySelector('[data-preview-opponent]').click(); true`);
  await wait(1200);
  const preview = await evaluate(`
    const buttons=[...document.querySelectorAll('.fs-sheet [data-accordion-toggle]')];
    const titles=buttons.map(b=>b.textContent.trim().replace(/[⌄›]/g,'').trim());
    const initial=buttons.map(b=>b.getAttribute('aria-expanded'));
    const toggles=buttons.map(b=>{ b.click(); const open=b.getAttribute('aria-expanded'); b.click(); return open; });
    return {titles, initial, toggles};
  `);
  check('four preview accordions are ordered exactly', JSON.stringify(preview.titles) === JSON.stringify([
    'LINEUPS','ON OFFER','WHY THE LINE LOOKS THIS WAY','THE READ']), JSON.stringify(preview));
  check('all preview accordions start collapsed and toggle', preview.initial.every(v=>v==='false') && preview.toggles.every(v=>v==='true'));
  await evaluate(`const x=document.querySelector('.fs-sheet__close'); if(x)x.click(); true`);

  for (const [width,height] of [[320,568],[375,667],[390,844]]) {
    await setViewport(width,height);
    await evaluate(`return new Promise(resolve=>{const end=Date.now()+12000;const p=()=>{if(document.querySelector('.fs-tabbar__item[data-destination="action"]'))resolve(true);else if(Date.now()>end)resolve(false);else setTimeout(p,100)};p()})`);
    await evaluate(`document.querySelector('.fs-tabbar__item[data-destination="action"]').click(); true`);
    await wait(700);
    const status = await evaluate(`
      const panel=document.querySelector('#panel-action');
      const nav=document.querySelector('.fs-tabbar').getBoundingClientRect();
      const secs=[...panel.querySelectorAll('.fs-railsec')];
      const cards=[...panel.querySelectorAll('.fs-wcard--lifecycle')];
      const rects=cards.map(c=>c.getBoundingClientRect());
      const figures=[...panel.querySelectorAll('[data-rail="action"] .fs-wcard__figures')].map(e=>{
        const r=e.getBoundingClientRect(), c=e.closest('.fs-wcard--lifecycle').getBoundingClientRect();
        return {w:r.width,h:r.height,top:r.top,bottom:r.bottom,cardTop:c.top,cardBottom:c.bottom,
          visible:r.width>20&&r.height>5&&r.top>=c.top&&r.bottom<=c.bottom};
      });
      const counts=Object.fromEntries(secs.map(s=>[s.dataset.rail,s.querySelectorAll('.fs-rail__item').length]));
      const pools=Object.fromEntries(secs.map(s=>[s.dataset.rail,s.querySelectorAll('.fs-wcard--pool-status').length]));
      const bottom=Math.max(...secs.map(s=>s.getBoundingClientRect().bottom));
      return {counts,pools,bottom,navTop:nav.top,clearance:nav.top-bottom,
        minW:Math.min(...rects.map(r=>r.width)),maxW:Math.max(...rects.map(r=>r.width)),
        minH:Math.min(...rects.map(r=>r.height)),maxH:Math.max(...rects.map(r=>r.height)),
        figures,docOverflow:document.documentElement.scrollWidth-document.documentElement.clientWidth};
    `);
    check(`${width} Status fits above nav`, status.clearance >= -0.5, JSON.stringify(status));
    check(`${width} Status cards remain equal`, status.maxW-status.minW<=1 && status.maxH-status.minH<=1, JSON.stringify(status));
    check(`${width} Action figures are visibly laid out`, status.figures.length>0 && status.figures.every(f=>f.visible), JSON.stringify(status.figures));
    check(`${width} Locked and Resolved show legitimate Pools`, status.counts.live>=2&&status.counts.live<=3&&status.pools.live>=1&&status.pools.completed>=1, JSON.stringify(status));
    check(`${width} has no page horizontal overflow`, status.docOverflow<=0, `${status.docOverflow}px`);

    if (width === 390) {
      await evaluate(`document.querySelector('[data-rail="action"] [data-card-action="wager"]').click(); true`);
      await wait(250);
      const lockedBefore=await evaluate(`document.querySelector('.fs-sheet').textContent`);
      await evaluate(`document.querySelector('.fs-sheet [data-respond="counter"]').click(); true`);
      await wait(250);
      const counter=await evaluate(`
        const buttons=[...document.querySelectorAll('.fs-sheet [data-accordion-toggle]')];
        return {titles:buttons.map(b=>b.textContent.trim()), collapsed:buttons.every(b=>b.getAttribute('aria-expanded')==='false'),
          input:Boolean(document.querySelector('#fs-cstake-input')), send:Boolean(document.querySelector('#fs-cstake-send')),
          text:document.querySelector('.fs-sheet').textContent};
      `);
      check('Counter has four-accordion parity and usable controls', counter.titles.length===4&&counter.collapsed&&counter.input&&counter.send,
        JSON.stringify(counter.titles));
      check('opening Counter preserves locked incoming context', /incoming proposal remains locked/i.test(counter.text), counter.text);
      await evaluate(`document.querySelector('#fs-cstake-cancel').click(); document.querySelector('.fs-sheet__close')?.click(); true`);
    }

    await evaluate(`document.querySelector('.fs-tabbar__item[data-destination="ledger"]').click(); true`);
    await wait(500);
    const account=await evaluate(`
      const s=document.querySelector('#panel-ledger .fs-lscroll');
      const cells=[...document.querySelectorAll('#fs-strip-ledger .fs-strip__cell')];
      const escrow=cells.find(c=>c.querySelector('.fs-strip__label')?.textContent.trim()==='Escrow');
      const min=cells.find(c=>c.querySelector('.fs-strip__label')?.textContent.trim()==='Min Left');
      const er=escrow.getBoundingClientRect(), mr=min.getBoundingClientRect();
      return {scrollHeight:s.scrollHeight,clientHeight:s.clientHeight,
        diff:s.scrollHeight-s.clientHeight, overlap:!(er.right<=mr.left||mr.right<=er.left||er.bottom<=mr.top||mr.bottom<=er.top)};
    `);
    check(`${width} Account collapsed content fits`, account.scrollHeight<=account.clientHeight, JSON.stringify(account));
    check(`${width} Escrow remains separate from Min Left`, !account.overlap, JSON.stringify(account));
  }
});

finish();
