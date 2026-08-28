/*
 FantasyStakes Canonical Cross-Tab Fixture v4
 Independent UI-coherence source of truth.

 v4 remediation delta (FSR-024, UPSIDE LEFT):
  The Action strip's UPSIDE LEFT cell read a hard-coded 5700 that no longer described
  anything. It is now derived from the accepted, unresolved proposals in Action's own
  lifecycle, so the literal is deleted rather than corrected. No other canonical value
  changed in this pass.

 v3 remediation delta (FSR-023, cross-surface escrow blocker):
  The Action lifecycle held four live issuer commitments (Hank accepted, Dolly pending
  outgoing, Reba issuer-escrow retained under counter, Loretta accepted) plus one funded
  Prop Pool ticket, but the Ledger carried only Hank T20, a mis-stated Dolly T16 and the
  pool ticket. Committed capital is now DERIVED from lifecycle state on both surfaces and
  materialised here as one schedule, so the two can be independently cross-checked instead
  of both reading the same literal.

  IN PLAY and WEEKLY MINIMUM qualification are deliberately NOT the same quantity:
    IN PLAY      = every held commitment  (accepted + pending issuer + counter-pending
                   issuer + funded pool)                                   = 8100 cents
    QUALIFYING   = governed qualifying gameplay only (accepted Versus + funded pool);
                   a pending or counter-pending offer is committed but does not yet
                   qualify                                                 = 4100 cents

 v2 remediation deltas (UI-contract closeout):
  FSR-005  IN PLAY / qualifying weekly commitments include unresolved Prop Pool capital.
  FSR-016  Governed Skunk Pot is a named canonical account; Skunk never routes to Settled Counterparties.
  FSR-007  Governed settings carry explicit authority / season-lock classification (CFG-107, CFG-1003).
  FSR-002  Canonical demo navigation routes, so the persistent gear entry point is never a dead control.

 All locked UI modules consume this same object/version.
 Production provider/ledger services replace the fixture later without changing UI contracts.
*/
(function(global){
  const teams = [
    {id:"T01",name:"Pain Sanders"},
    {id:"T02",name:"Hank Williams"},
    {id:"T03",name:"Dolly Parton"},
    {id:"T04",name:"Reba McEntire"},
    {id:"T05",name:"Willie Nelson"},
    {id:"T06",name:"Johnny Cash"},
    {id:"T07",name:"Patsy Cline"},
    {id:"T08",name:"Waylon Jennings"},
    {id:"T09",name:"Loretta Lynn"},
    {id:"T10",name:"George Strait"},
    {id:"T11",name:"Tammy Wynette"},
    {id:"T12",name:"Merle Haggard"}
  ];

  const painMatch = [5,-5,10,0,15,-10,5,10,0,15];
  const painPool  = [0,5,-5,10,5,-5,10,0,5,5];

  function balancedWeek(seedPain, week, salt){
    const vals=[seedPain];
    for(let i=1;i<=10;i++) vals.push(((i*3 + week*(salt+1) + salt*2)%13)-6);
    vals.push(-vals.reduce((a,v)=>a+v,0));
    return vals;
  }

  const weeklyResults={};
  for(let week=1;week<=10;week++){
    const matchVals=balancedWeek(painMatch[week-1],week,1);
    const poolVals=balancedWeek(painPool[week-1],week,3);
    const skunkTeamIndex = week===7 ? 0 : ((week*2)%11)+1;
    const match={},pool={},skunk={};
    teams.forEach((t,i)=>{
      match[t.id]=matchVals[i];
      pool[t.id]=poolVals[i];
      skunk[t.id]=i===skunkTeamIndex ? -10 : 0;
    });
    weeklyResults[week]=Object.freeze({
      published:true,
      match:Object.freeze(match),
      pool:Object.freeze(pool),
      skunk:Object.freeze(skunk),
      yahoo:Object.freeze({skunkTeamId:teams[skunkTeamIndex].id})
    });
  }
  weeklyResults[11]=Object.freeze({published:false});

  function seasonTotalsThrough(throughWeek){
    const out={};
    teams.forEach(t=>out[t.id]={match:0,pool:0,skunk:0,score:0});
    for(let w=1;w<=throughWeek;w++){
      const r=weeklyResults[w];
      if(!r?.published) continue;
      teams.forEach(t=>{
        out[t.id].match += r.match[t.id]||0;
        out[t.id].pool += r.pool[t.id]||0;
        out[t.id].skunk += r.skunk[t.id]||0;
      });
    }
    teams.forEach(t=>out[t.id].score=out[t.id].match+out[t.id].pool+out[t.id].skunk);
    return out;
  }

  const seasonThroughWeek10=seasonTotalsThrough(10);

  const FS_CANON = Object.freeze({
    version:"FS_CANONICAL_CROSS_TAB_FIXTURE_V4",
    brand:Object.freeze({
      tagline:"Real odds. Pure action. More ways to win."
    }),
    league:Object.freeze({
      id:"whispers-demo-2026",
      name:"WHISPERS DEMO LEAGUE",
      season:2026,
      currentWeek:11,
      completedThroughWeek:10,
      currentUserId:"T01",
      currentUser:"Pain Sanders",
      teams:Object.freeze(teams.map(Object.freeze)),
      officialYahooMatchups:Object.freeze([
        Object.freeze(["Pain Sanders","Dolly Parton"]),
        Object.freeze(["Hank Williams","Johnny Cash"]),
        Object.freeze(["Reba McEntire","Willie Nelson"]),
        Object.freeze(["Patsy Cline","Merle Haggard"]),
        Object.freeze(["Waylon Jennings","Loretta Lynn"]),
        Object.freeze(["George Strait","Tammy Wynette"])
      ])
    }),
    scoringProfile:Object.freeze({
      version:"FS_SCORING_PROFILE_WHISPERS_2026_V1",
      upstream:"YAHOO_LEAGUE_SCORING_SETTINGS",
      status:"CONFIRMED"
    }),
    settings:Object.freeze({
      weeklyFantasyStakesCompetition:14000,
      fantasyStakesChampionship:8000,
      seasonAllocation:22000,
      weeklyMinimum:1000,
      standardPropPoolEntry:100,
      skunkFee:1000,
      unspentMinimumDestination:"FROZEN · RETURNED AT SEASON END",
      matchupMarkets:"MONEYLINE · SPREAD · O/U",
      termsModes:"FIXED + DYNAMIC",
      propPoolsEnabled:true
    }),
    action:Object.freeze({
      // FSR-005 / FSR-023: current-week committed capital is decomposed so every module
      // aggregates components rather than hard-coding a total. Every value below is a
      // materialisation of currentWeekCommitments and is proven against the Action
      // lifecycle by the reconciliation suite - it is not an independent source.
      wallet:9400,
      unresolvedVersusEscrow:8000,
      unresolvedPropPoolCommitments:100,
      inPlay:8100,
      // FSR-023: narrower than inPlay on purpose - pending and counter-pending offers are
      // committed capital but are not yet qualifying gameplay.
      qualifyingCommitmentsThisWeek:4100,
      // FSR-024: upsideLeft is deliberately absent. Remaining upside is a property of the
      // accepted, unresolved proposals in the Action lifecycle, so Action derives it via
      // Resolver.commitmentTotals().upsideLeft. There is no canonical literal to drift.
      currentWeek:11
    }),

    /* FSR-023 - the current week's unresolved commitments, in posting order.
       Each record is derived from Action lifecycle state; the Account Ledger builds its
       current-week postings from this schedule instead of from hard-coded literals, and
       the reconciliation suite proves the schedule against the live lifecycle. */
    currentWeekCommitments:Object.freeze([
      Object.freeze({key:"POOL_SINGLE",kind:"POOL",definitionKey:"punterPointsSingle",
        opponent:null,lifecycle:"FUNDED",role:"ENTRANT",cents:100,qualifying:true,
        date:"Nov 13",desc:"Single Team: Punter Points \u00b7 funded pool entry"}),
      Object.freeze({key:"VERSUS_HANK",kind:"VERSUS",definitionKey:null,
        opponent:"Hank Williams",lifecycle:"ACCEPTED",role:"ISSUER",cents:2000,qualifying:true,
        date:"Nov 15",desc:"Pain vs Hank \u00b7 accepted wager escrow"}),
      Object.freeze({key:"VERSUS_DOLLY",kind:"VERSUS",definitionKey:null,
        opponent:"Dolly Parton",lifecycle:"PENDING_OUTGOING",role:"ISSUER",cents:2000,qualifying:false,
        date:"Nov 15",desc:"Pain vs Dolly \u00b7 pending issuer escrow"}),
      Object.freeze({key:"VERSUS_REBA",kind:"VERSUS",definitionKey:null,
        opponent:"Reba McEntire",lifecycle:"COUNTER_PENDING",role:"ISSUER",cents:2000,qualifying:false,
        date:"Nov 15",desc:"Pain vs Reba \u00b7 issuer escrow retained under counter"}),
      Object.freeze({key:"VERSUS_LORETTA",kind:"VERSUS",definitionKey:null,
        opponent:"Loretta Lynn",lifecycle:"ACCEPTED",role:"ISSUER",cents:2000,qualifying:true,
        date:"Nov 15",desc:"Pain vs Loretta \u00b7 accepted wager escrow"})
    ]),
    accounts:Object.freeze({
      leagueEconomy:"League Economy",
      wallet:"Wallet",
      weeklyMinimumEscrow:"Weekly Minimum Escrow",
      activeBetEscrow:"Active Bet Escrow",
      propPoolCommitted:"Punter Points Pool",
      championshipReserve:"Championship Reserve",
      skunkPot:"Skunk Pot",
      settledCounterparties:"Settled Counterparties"
    }),
    // FSR-005: user-facing IN PLAY aggregates exactly these unresolved-commitment accounts.
    inPlayAccounts:Object.freeze(["Active Bet Escrow","Punter Points Pool"]),
    // FSR-016: governed destination for a score-bearing Skunk Fee (LED-105, LED-343).
    skunkRouting:Object.freeze({
      destination:"Skunk Pot",
      basis:"LED-343",
      scoreBearing:true,
      countsTowardWallet:false,
      countsTowardInPlay:false
    }),
    // FSR-007: authority + season-lock classification for governed League Settings.
    // Basis: CFG-107 (first-acceptance freeze) and CFG-1003 (season-fixed parameters).
    settingsAuthority:Object.freeze({
      basis:"CFG-107 · CFG-1003",
      seasonConfigurationFrozen:true,
      frozenAt:"FIRST_ACCEPTED_WAGER",
      seasonLockLabel:"LOCKED FOR 2026",
      gmView:"READ ONLY",
      classification:Object.freeze({
        weeklyFantasyStakesCompetition:"COMMISSIONER_SEASON_FIXED",
        fantasyStakesChampionship:"COMMISSIONER_SEASON_FIXED",
        seasonAllocation:"DERIVED",
        weeklyMinimum:"COMMISSIONER_SEASON_FIXED",
        standardPropPoolEntry:"COMMISSIONER_SEASON_FIXED",
        skunkFee:"COMMISSIONER_SEASON_FIXED",
        unspentMinimumDestination:"COMMISSIONER_SEASON_FIXED",
        matchupMarkets:"COMMISSIONER_SEASON_FIXED",
        termsModes:"COMMISSIONER_SEASON_FIXED",
        propPools:"COMMISSIONER_SEASON_FIXED"
      })
    }),
    // FSR-002 / FSR-021: one canonical route target per locked screen, so the persistent
    // gear entry point and the bottom nav resolve deterministically in the demo package.
    routes:Object.freeze({
      standings:"fantasystakes_STANDINGS_WRAPUP_deterministic_v8_upside.html#standings",
      action:"fantasystakes_ACTION_uncluttered_full_prototype_v24_upside.html",
      wrapup:"fantasystakes_STANDINGS_WRAPUP_deterministic_v8_upside.html#wrap",
      account:"fantasystakes_ACCOUNT_GEAR_uncluttered_v25_upside.html",
      gear:"fantasystakes_ACCOUNT_GEAR_uncluttered_v25_upside.html#gear"
    }),
    account:Object.freeze({
      pointsChampionshipNet:0,
      fantasyStakesChampionshipNet:0,
      topOffs:0
    }),
    weeklyResults:Object.freeze(weeklyResults),
    seasonThroughWeek10:Object.freeze(
      Object.fromEntries(Object.entries(seasonThroughWeek10).map(([k,v])=>[k,Object.freeze(v)]))
    )
  });

  global.FS_CANON=FS_CANON;
})(window);
