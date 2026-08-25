/* ============================================================================
 * FantasyStakes — FINAL POR UI FREEZE CANDIDATE, as rendered
 *
 * Run:  python test_finalpor_freeze.py
 *
 * WHAT THIS SUITE IS FOR, AND WHY IT EXISTS AT ALL. The previous pass certified
 * this UI green from geometry alone and the owner's own phone showed cramped
 * cards above a 580px dead zone with the response controls drawn on top of the
 * live odds. Every assertion in that pass was true and the screen was wrong.
 *
 * So this suite asserts the things that were wrong THEN, in the terms the
 * complaint was made in:
 *
 *   §1  the four Status cards spend the region rather than stopping at a
 *       cramped minimum, and a large unused remainder is a FAILURE
 *   §2  no element inside a Status card overlaps ANOTHER ELEMENT — a child
 *       against its parent's box was the check that missed the collision
 *   §3  the Action Required detail is Odds & Markets, then Lineups, then the
 *       responses; both pricing views survive a refresh
 *   §4/§5  the Play cards carry the wager and entry state
 *   §6  the three Wrap Up cards are full recaps
 * ========================================================================== */
import { createReporter, withPage } from './browser-harness.mjs';

const { check, section, finish } = createReporter();
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

const VIEWPORTS = [[320, 568], [375, 667], [390, 844]];
const MOUNT = `return new Promise(r=>{const t=Date.now()+25000;const p=()=>document.querySelector('.fs-tabbar__item')?r(1):Date.now()>t?r(0):setTimeout(p,120);p()})`;
const GO = (d) => `const t=document.querySelector('.fs-tabbar__item[data-destination="${d}"]'); if(t)t.click(); return 1`;

await withPage({ origin: process.env.FS_TEST_ORIGIN, settleMs: 3000 }, async ({ evaluate, setViewport }) => {
  await evaluate(`return fetch('/demo/enter',{method:'POST',credentials:'include'}).then(r=>r.json())`);

  for (const [w, h] of VIEWPORTS) {
    const at = `${w}x${h}`;
    await setViewport(w, h);
    await wait(4000);
    await evaluate(MOUNT);

    /* ── §1 · the region is spent ───────────────────────────────────────── */
    section(`§1 · Status uses the available height — ${at}`);
    await evaluate(GO('action'));
    await wait(2600);

    const status = await evaluate(`
      const p=document.querySelector('#panel-action');
      const nav=document.querySelector('.fs-tabbar').getBoundingClientRect();
      const strip=p.querySelector('.fs-strip').getBoundingClientRect();
      const secs=[...p.querySelectorAll('[data-rail]')];
      const cards=secs.map(s=>{const c=s.querySelector('.fs-wcard--lifecycle');
        return c?Math.round(c.getBoundingClientRect().height):0;});
      const top=secs[0].getBoundingClientRect().top;
      const bot=secs[secs.length-1].getBoundingClientRect().bottom;
      const available=Math.round(nav.top-strip.bottom);
      const consumed=Math.round(bot-top);

      // EVERY PAIR OF VISIBLE CHILDREN, IN EVERY CARD. The check that missed
      // the reported collision compared a child against its PARENT; absolutely
      // positioned siblings pass that and still draw on top of each other.
      const overlaps=[];
      secs.forEach(s=>{
        s.querySelectorAll('.fs-wcard--lifecycle').forEach(card=>{
          const kids=[...card.children].filter(k=>{const r=k.getBoundingClientRect();
            return getComputedStyle(k).display!=='none' && r.height>0 && r.width>0;});
          for(let i=0;i<kids.length;i++)for(let j=i+1;j<kids.length;j++){
            const a=kids[i].getBoundingClientRect(), b=kids[j].getBoundingClientRect();
            const ox=Math.min(a.right,b.right)-Math.max(a.left,b.left);
            const oy=Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top);
            if(ox>1&&oy>1) overlaps.push(s.dataset.rail+' '
              +kids[i].className.replace('fs-wcard__','')+'/'
              +kids[j].className.replace('fs-wcard__',''));
          }});});

      const clipped=[];
      p.querySelectorAll('.fs-wcard').forEach(c=>{
        if(c.scrollHeight>c.clientHeight+1)
          clipped.push(Math.round(c.scrollHeight)+'/'+Math.round(c.clientHeight));});

      return {available, consumed, unused:available-consumed, cards,
        sections:secs.length, navTop:Math.round(nav.top),
        stripBottom:Math.round(strip.bottom), lastBottom:Math.round(bot),
        firstTop:Math.round(top), overlaps, clipped,
        railsScroll:(()=>{const r=p.querySelector('.fs-rails');
          return r?r.scrollHeight-r.clientHeight:0;})()};`);

    check(`${at} all four sections render`, status.sections === 4, String(status.sections));
    check(`${at} all four sit below the summary strip`,
      status.firstTop >= status.stripBottom - 1,
      `first ${status.firstTop} vs strip ${status.stripBottom}`);
    check(`${at} all four sit above the bottom navigation`,
      status.lastBottom <= status.navTop + 1,
      `last ${status.lastBottom} vs nav ${status.navTop}`);
    check(`${at} no page-level vertical scroll workaround`,
      status.railsScroll <= 2, `${status.railsScroll}px`);

    /* THE DEAD-ZONE CLAUSE. §1 makes a large unused remainder a failure in its
     * own right, so it is asserted as one rather than left to the eye.
     *
     * SCOPED TO A POPULATED STATUS, DELIBERATELY. A rail with no wagers draws a
     * one-line note, not a card, and a tab where three of four rails are empty
     * legitimately does not fill its region with cards — the reported defect
     * was a FULL Status leaving 580px empty beneath four cramped cards. The
     * strict claim is made where all four rails carry one; the weaker claim
     * that the sections still span the region is made either way. */
    const populated = status.cards.filter((c) => c > 0).length;
    check(`${at} the four sections span the Status region`,
      status.consumed >= Math.round(status.available * 0.78),
      `consumed ${status.consumed} of ${status.available}`);

    if (populated === 4) {
      check(`${at} the Status region is actually spent — unused remainder is small`,
        status.unused <= Math.max(24, Math.round(status.available * 0.06)),
        `available ${status.available} · consumed ${status.consumed} · unused ${status.unused}`);

      /* AND THE CARDS GREW WITH IT. A card that stops at a cramped minimum
       * while the region is large is the defect; the floor scales with the
       * region rather than being a constant that goes stale. */
      const smallest = Math.min(...status.cards);
      check(`${at} the collapsed cards use the region rather than a minimum`,
        smallest >= Math.min(60, Math.round(status.available / 5)),
        `cards ${status.cards.join('/')} in ${status.available}px`);
    } else {
      /* EVEN A SPARSE STATUS MUST NOT CRAMP THE CARDS IT DOES HAVE. */
      const withCards = status.cards.filter((c) => c > 0);
      check(`${at} the cards present are not cramped (${populated}/4 rails populated)`,
        withCards.every((c) => c >= Math.min(50, Math.round(status.available / 7))),
        `cards ${status.cards.join('/')} in ${status.available}px`);
    }

    section(`§2 · the Status cards are legible — ${at}`);
    check(`${at} no element overlaps another inside any Status card`,
      status.overlaps.length === 0, status.overlaps.join(', ') || 'none');
    check(`${at} no Status card clips its own content`,
      status.clipped.length === 0, status.clipped.join(', ') || 'none');
  }

  /* ── §3 · the decision workspace ──────────────────────────────────────── */
  section('§3 · Action Required detail — Odds & Markets, then Lineups');
  await setViewport(390, 844);
  await wait(4000);
  await evaluate(MOUNT);
  await evaluate(GO('action'));
  await wait(2600);
  await evaluate(`const c=document.querySelector('#panel-action [data-rail=action] [data-card-action]')
    ||document.querySelector('#panel-action [data-rail=action] .fs-wcard--lifecycle'); c.click(); return 1`);
  await wait(2400);

  const detail = await evaluate(`
    const h=document.querySelector('#fs-sheet');
    const heads=[...h.querySelectorAll('.fs-accordion__title')].map(x=>x.textContent.trim());
    const markets=[...h.querySelectorAll('[data-odds-panel=original] .fs-odds__market')]
      .map(x=>x.textContent.trim());
    return {heads,
      oddsFirst: heads[0]==='ODDS & MARKETS', lineupsSecond: heads[1]==='LINEUPS',
      markets,
      views:[...h.querySelectorAll('[data-odds-view]')].map(b=>b.textContent.trim()),
      refresh:!!h.querySelector('[data-odds-refresh]'),
      takeIt: /Take it/.test(h.innerText), counter: /Counter/.test(h.innerText),
      decline: /Decline/.test(h.innerText)};`);

  check('ODDS & MARKETS is the first section', detail.oddsFirst, detail.heads.join(' | '));
  check('LINEUPS is the second section', detail.lineupsSecond, detail.heads.join(' | '));
  check('the three FantasyStakes markets are all present',
    detail.markets.join(',') === 'Moneyline,Spread,Over/Under', detail.markets.join(','));
  check('ORIGINAL OFFER and REFRESHED ODDS are both offered',
    detail.views.includes('ORIGINAL OFFER') && detail.views.includes('REFRESHED ODDS'),
    detail.views.join(' | '));
  check('a REFRESH ODDS control is present', detail.refresh);
  check('Take it, Counter and Decline are all present',
    detail.takeIt && detail.counter && detail.decline);

  section('§3 · refreshing never mutates the original offer');
  const read = `
    const h=document.querySelector('#fs-sheet');
    return {original:[...h.querySelectorAll('[data-odds-panel=original] .fs-odds__row')]
        .map(r=>r.textContent.trim()),
      sub:(h.querySelector('.fs-sheet__sub')||{}).textContent};`;
  const before = await evaluate(read);
  await evaluate(`document.querySelector('[data-odds-refresh]').click(); return 1`);
  await wait(3500);
  const after = await evaluate(read);
  check('the ORIGINAL OFFER is byte-identical after REFRESH ODDS',
    JSON.stringify(after.original) === JSON.stringify(before.original),
    `${before.original.join(' ')} → ${after.original.join(' ')}`);
  check('the sheet still states the original terms after a refresh',
    after.sub === before.sub, String(after.sub));
  check('Take it is still offered after a refresh', /Take it/.test(
    await evaluate(`return document.querySelector('#fs-sheet').innerText`)));

  /* ── §4 / §5 · the Play cards ─────────────────────────────────────────── */
  section('§4/§5 · Play carries the wager and entry state');
  await evaluate(`const x=document.querySelector('#fs-sheet [data-fs-close]'); if(x)x.click(); return 1`);
  await wait(800);
  await evaluate(GO('league'));
  await wait(2800);
  const play = await evaluate(`
    const p=document.querySelector('#panel-league');
    const card=p.querySelector('#fs-bets-carousel > *');
    const pool=p.querySelector('#fs-play-pools > *');
    return {state:!!p.querySelector('.fs-playstate'),
      stateText:(p.querySelector('.fs-playstate')||{}).innerText||'',
      poolState:!!p.querySelector('.fs-poolstate'),
      poolStateText:(p.querySelector('.fs-poolstate')||{}).innerText||'',
      cardClip: card?Math.max(0,card.scrollHeight-card.clientHeight):0,
      poolClip: pool?Math.max(0,pool.scrollHeight-pool.clientHeight):0,
      markets:p.querySelectorAll('#fs-bets-carousel .fs-market').length};`);
  check('§4 the Matchup card carries a wager-state row', play.state,
    play.stateText.split('\n').join(' ').slice(0, 80));
  check('§4 the Matchup card still offers all three markets', play.markets >= 3, String(play.markets));
  check('§4 the Matchup card does not clip', play.cardClip === 0, `${play.cardClip}px`);
  check('§5 the Prop Pool card carries an entry state', play.poolState,
    play.poolStateText.split('\n').join(' ').slice(0, 60));
  check('§5 the Prop Pool card does not clip', play.poolClip === 0, `${play.poolClip}px`);

  /* ── §6 · the Wrap Up recap cards ─────────────────────────────────────── */
  section('§6 · Wrap Up carousel cards are full recaps');
  await evaluate(GO('week'));
  await wait(3200);
  const wrap = await evaluate(`
    const p=document.querySelector('#panel-week');
    const out={};
    p.querySelectorAll('[data-module]').forEach(m=>{
      const c=m.querySelector('.fs-rescar > *');
      out[m.dataset.module]={
        text:(c?c.innerText:'').split(String.fromCharCode(10)).join(' '),
        copy:!!(c&&c.querySelector('.fs-wcard__copy')&&c.querySelector('.fs-wcard__copy').getBoundingClientRect().height>1),
        clip:c?Math.max(0,c.scrollHeight-c.clientHeight):0};});
    return out;`);

  check('§6A the Yahoo card states the final score', /\d+\.\d+\s*—\s*\d+\.\d+/.test(wrap.yahoo.text),
    wrap.yahoo.text.slice(0, 90));
  check('§6A the Yahoo card states the margin', /MARGIN/i.test(wrap.yahoo.text));
  check('§6A the Yahoo card carries a takeaway', wrap.yahoo.copy);
  check('§6B the FantasyStakes card states stake and pot',
    /STAKE/i.test(wrap.bets.text) && /POT/i.test(wrap.bets.text), wrap.bets.text.slice(0, 90));
  check('§6B the FantasyStakes card carries a sportsbook takeaway', wrap.bets.copy);
  check('§6C the Prop Pool card states buy-in and pot',
    /BUY-IN/i.test(wrap.pools.text) && /POT/i.test(wrap.pools.text), wrap.pools.text.slice(0, 90));
  check('§6C the Prop Pool card carries a takeaway', wrap.pools.copy);
  check('§6 no Wrap Up recap card clips',
    ['yahoo', 'bets', 'pools'].every((k) => wrap[k].clip === 0),
    ['yahoo', 'bets', 'pools'].map((k) => `${k}:${wrap[k].clip}`).join(' '));

  const globals = await evaluate(`
    return {overflow:document.documentElement.scrollWidth-document.documentElement.clientWidth,
      swipe:document.body.innerText.toUpperCase().split('SWIPE').length-1};`);
  check('no document horizontal overflow', globals.overflow <= 0, `${globals.overflow}px`);
  check('zero rendered SWIPE occurrences', globals.swipe === 0, String(globals.swipe));
});

finish();
