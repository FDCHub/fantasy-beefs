# Mock 2024 fantasy football league — replaces Yahoo API for development/testing.
# 10-team, 14-week regular season (wks 1-14) + 3-week playoffs (wks 15-17).
# Head-to-head matchups pair teams by index each week: (0v1, 2v3, 4v5, 6v7, 8v9),
# rotating each week via SCHEDULE below.

TEAMS = [
    {
        "id": 1,
        "name": "Mahomes Alone",
        "owner": "Kevin Mahoney",
        "email": "kevin.mahoney@gmail.com",
        "roster": [
            {"name": "Patrick Mahomes",    "pos": "QB"},
            {"name": "Derrick Henry",      "pos": "RB"},
            {"name": "Josh Jacobs",        "pos": "RB"},
            {"name": "CeeDee Lamb",        "pos": "WR"},
            {"name": "Justin Jefferson",   "pos": "WR"},
            {"name": "Sam LaPorta",        "pos": "TE"},
            {"name": "Puka Nacua",         "pos": "FLEX"},
            {"name": "Harrison Butker",    "pos": "K"},
            {"name": "Dallas Cowboys",     "pos": "DEF"},
            {"name": "Kyren Williams",     "pos": "RB"},
            {"name": "Amon-Ra St. Brown",  "pos": "WR"},
            {"name": "Jake Ferguson",      "pos": "TE"},
            {"name": "Jayden Daniels",     "pos": "QB"},
            {"name": "Tony Pollard",       "pos": "RB"},
            {"name": "Deebo Samuel",       "pos": "WR"},
        ],
        "scores": [112.4, 98.6, 134.2, 119.8, 145.0, 88.3, 127.6, 103.4,
                   156.2, 91.7, 138.5, 115.9, 99.4, 142.1, 87.6, 130.8, 121.3],
    },
    {
        "id": 2,
        "name": "Hurts So Good",
        "owner": "Phil Hurtado",
        "email": "phil.hurtado@gmail.com",
        "roster": [
            {"name": "Jalen Hurts",        "pos": "QB"},
            {"name": "Saquon Barkley",     "pos": "RB"},
            {"name": "De'Von Achane",      "pos": "RB"},
            {"name": "Tyreek Hill",        "pos": "WR"},
            {"name": "Davante Adams",      "pos": "WR"},
            {"name": "Dallas Goedert",     "pos": "TE"},
            {"name": "Brian Robinson",     "pos": "FLEX"},
            {"name": "Tyler Bass",         "pos": "K"},
            {"name": "San Francisco 49ers","pos": "DEF"},
            {"name": "Rachaell Mostert",   "pos": "RB"},
            {"name": "Jaylen Waddle",      "pos": "WR"},
            {"name": "T.J. Hockenson",     "pos": "TE"},
            {"name": "Jordan Love",        "pos": "QB"},
            {"name": "Aaron Jones",        "pos": "RB"},
            {"name": "Tee Higgins",        "pos": "WR"},
        ],
        "scores": [124.7, 118.2, 108.5, 141.3, 97.6, 133.0, 115.8, 89.4,
                   147.9, 122.1, 101.4, 138.6, 126.3, 94.7, 155.2, 108.9, 97.4],
    },
    {
        "id": 3,
        "name": "Run CMC",
        "owner": "Mac Forrester",
        "email": "mac.forrester@gmail.com",
        "roster": [
            {"name": "Christian McCaffrey","pos": "RB"},
            {"name": "Josh Allen",         "pos": "QB"},
            {"name": "Breece Hall",        "pos": "RB"},
            {"name": "Ja'Marr Chase",      "pos": "WR"},
            {"name": "DeVonta Smith",      "pos": "WR"},
            {"name": "Travis Kelce",       "pos": "TE"},
            {"name": "Stefon Diggs",       "pos": "FLEX"},
            {"name": "Brandon Aubrey",     "pos": "K"},
            {"name": "Baltimore Ravens",   "pos": "DEF"},
            {"name": "Jahmyr Gibbs",       "pos": "RB"},
            {"name": "DJ Moore",           "pos": "WR"},
            {"name": "David Njoku",        "pos": "TE"},
            {"name": "Tua Tagovailoa",     "pos": "QB"},
            {"name": "Jonathan Taylor",    "pos": "RB"},
            {"name": "Mike Evans",         "pos": "WR"},
        ],
        "scores": [131.8, 144.5, 92.7, 128.4, 116.2, 105.9, 149.1, 118.6,
                   87.3, 139.7, 124.0, 98.2, 145.5, 110.8, 102.4, 143.7, 88.1],
    },
    {
        "id": 4,
        "name": "Lamar Mania",
        "owner": "Jackson Raves",
        "email": "jackson.raves@gmail.com",
        "roster": [
            {"name": "Lamar Jackson",      "pos": "QB"},
            {"name": "David Montgomery",   "pos": "RB"},
            {"name": "Alvin Kamara",       "pos": "RB"},
            {"name": "Keenan Allen",       "pos": "WR"},
            {"name": "Calvin Ridley",      "pos": "WR"},
            {"name": "Mark Andrews",       "pos": "TE"},
            {"name": "Joe Mixon",          "pos": "FLEX"},
            {"name": "Evan McPherson",     "pos": "K"},
            {"name": "Pittsburgh Steelers","pos": "DEF"},
            {"name": "Kareem Hunt",        "pos": "RB"},
            {"name": "Rashee Rice",        "pos": "WR"},
            {"name": "Trey McBride",       "pos": "TE"},
            {"name": "Sam Darnold",        "pos": "QB"},
            {"name": "Chuba Hubbard",      "pos": "RB"},
            {"name": "Chris Godwin",       "pos": "WR"},
        ],
        "scores": [107.6, 125.3, 119.8, 93.4, 138.7, 112.1, 99.5, 143.2,
                   115.0, 86.8, 131.4, 107.9, 128.6, 118.3, 94.7, 140.2, 109.8],
    },
    {
        "id": 5,
        "name": "Ja'Marr the Merrier",
        "owner": "Marcy Bengston",
        "email": "marcy.bengston@gmail.com",
        "roster": [
            {"name": "Joe Burrow",         "pos": "QB"},
            {"name": "Tony Pollard",       "pos": "RB"},
            {"name": "Jahmyr Gibbs",       "pos": "RB"},
            {"name": "Ja'Marr Chase",      "pos": "WR"},
            {"name": "Cooper Kupp",        "pos": "WR"},
            {"name": "Dalton Kincaid",     "pos": "TE"},
            {"name": "Kareem Hunt",        "pos": "FLEX"},
            {"name": "Justin Tucker",      "pos": "K"},
            {"name": "New York Jets",      "pos": "DEF"},
            {"name": "Gus Edwards",        "pos": "RB"},
            {"name": "Zay Flowers",        "pos": "WR"},
            {"name": "Pat Freiermuth",     "pos": "TE"},
            {"name": "Baker Mayfield",     "pos": "QB"},
            {"name": "Najee Harris",       "pos": "RB"},
            {"name": "Jerry Jeudy",        "pos": "WR"},
        ],
        "scores": [118.9, 105.4, 143.6, 88.7, 127.2, 116.8, 101.3, 135.4,
                   122.7, 148.0, 94.1, 130.5, 112.8, 99.6, 139.3, 118.7, 104.2],
    },
    {
        "id": 6,
        "name": "Room to Grubb",
        "owner": "Ryan Grubb",
        "email": "ryan.grubb@gmail.com",
        "roster": [
            {"name": "Dak Prescott",       "pos": "QB"},
            {"name": "Jonathan Taylor",    "pos": "RB"},
            {"name": "Aaron Jones",        "pos": "RB"},
            {"name": "Davante Adams",      "pos": "WR"},
            {"name": "Amari Cooper",       "pos": "WR"},
            {"name": "Jake Ferguson",      "pos": "TE"},
            {"name": "Jaylen Warren",      "pos": "FLEX"},
            {"name": "Cairo Santos",       "pos": "K"},
            {"name": "Miami Dolphins",     "pos": "DEF"},
            {"name": "Zamir White",        "pos": "RB"},
            {"name": "Brandin Cooks",      "pos": "WR"},
            {"name": "Luke Musgrave",      "pos": "TE"},
            {"name": "Anthony Richardson", "pos": "QB"},
            {"name": "Tyler Allgeier",     "pos": "RB"},
            {"name": "Van Jefferson",      "pos": "WR"},
        ],
        "scores": [103.2, 116.7, 129.4, 97.8, 142.3, 108.5, 124.9, 91.6,
                   137.1, 113.4, 99.0, 145.8, 106.7, 122.3, 88.5, 133.9, 115.6],
    },
    {
        "id": 7,
        "name": "This Is The Kelce Way",
        "owner": "Travis Mando",
        "email": "travis.mando@gmail.com",
        "roster": [
            {"name": "Travis Kelce",       "pos": "TE"},
            {"name": "Justin Herbert",     "pos": "QB"},
            {"name": "Rachaell Mostert",   "pos": "RB"},
            {"name": "Tyreek Hill",        "pos": "WR"},
            {"name": "Michael Pittman Jr.","pos": "WR"},
            {"name": "Kyren Williams",     "pos": "RB"},
            {"name": "Zack Moss",          "pos": "FLEX"},
            {"name": "Wil Lutz",           "pos": "K"},
            {"name": "Cleveland Browns",   "pos": "DEF"},
            {"name": "Joshua Kelley",      "pos": "RB"},
            {"name": "Chris Moore",        "pos": "WR"},
            {"name": "Noah Fant",          "pos": "TE"},
            {"name": "Geno Smith",         "pos": "QB"},
            {"name": "Damien Harris",      "pos": "RB"},
            {"name": "Marquise Brown",     "pos": "WR"},
        ],
        "scores": [109.5, 122.8, 96.3, 135.7, 111.4, 88.9, 140.2, 104.6,
                   118.3, 129.7, 93.5, 147.1, 101.8, 115.4, 130.6, 97.3, 112.9],
    },
    {
        "id": 8,
        "name": "Mixon It Up",
        "owner": "Jo Mixley",
        "email": "jo.mixley@gmail.com",
        "roster": [
            {"name": "Joe Mixon",          "pos": "RB"},
            {"name": "Kirk Cousins",       "pos": "QB"},
            {"name": "Gus Edwards",        "pos": "RB"},
            {"name": "Tee Higgins",        "pos": "WR"},
            {"name": "D.J. Moore",         "pos": "WR"},
            {"name": "Cole Kmet",          "pos": "TE"},
            {"name": "Devin Singletary",   "pos": "FLEX"},
            {"name": "Jake Moody",         "pos": "K"},
            {"name": "Kansas City Chiefs", "pos": "DEF"},
            {"name": "Dameon Pierce",      "pos": "RB"},
            {"name": "Curtis Samuel",      "pos": "WR"},
            {"name": "Juwan Johnson",      "pos": "TE"},
            {"name": "C.J. Stroud",        "pos": "QB"},
            {"name": "Latavius Murray",    "pos": "RB"},
            {"name": "K.J. Hamler",        "pos": "WR"},
        ],
        "scores": [98.7, 113.2, 127.5, 104.9, 89.6, 121.4, 108.3, 136.8,
                   95.2, 118.7, 142.0, 102.4, 126.1, 93.8, 117.5, 144.3, 106.7],
    },
    {
        "id": 9,
        "name": "Ekeler Island",
        "owner": "Austin Webb",
        "email": "austin.webb@gmail.com",
        "roster": [
            {"name": "Austin Ekeler",      "pos": "RB"},
            {"name": "Trevor Lawrence",    "pos": "QB"},
            {"name": "D'Andre Swift",      "pos": "RB"},
            {"name": "Diontae Johnson",    "pos": "WR"},
            {"name": "Rashod Bateman",     "pos": "WR"},
            {"name": "Evan Engram",        "pos": "TE"},
            {"name": "Samaje Perine",      "pos": "FLEX"},
            {"name": "Greg Joseph",        "pos": "K"},
            {"name": "Philadelphia Eagles","pos": "DEF"},
            {"name": "Kenyan Drake",       "pos": "RB"},
            {"name": "Parris Campbell",    "pos": "WR"},
            {"name": "Tyler Higbee",       "pos": "TE"},
            {"name": "Tommy DeVito",       "pos": "QB"},
            {"name": "Miles Sanders",      "pos": "RB"},
            {"name": "Mecole Hardman",     "pos": "WR"},
        ],
        "scores": [94.3, 107.8, 118.6, 85.4, 131.2, 99.7, 114.5, 127.3,
                   90.8, 143.6, 104.1, 116.9, 88.2, 135.4, 111.7, 98.6, 122.4],
    },
    {
        "id": 10,
        "name": "Wren It Rains It Pours",
        "owner": "Wren Stormfield",
        "email": "wren.stormfield@gmail.com",
        "roster": [
            {"name": "Jared Goff",         "pos": "QB"},
            {"name": "Najee Harris",       "pos": "RB"},
            {"name": "Khalil Herbert",     "pos": "RB"},
            {"name": "Elijah Moore",       "pos": "WR"},
            {"name": "Nelson Agholor",     "pos": "WR"},
            {"name": "Gerald Everett",     "pos": "TE"},
            {"name": "Darrynton Evans",    "pos": "FLEX"},
            {"name": "Nick Folk",          "pos": "K"},
            {"name": "Buffalo Bills",      "pos": "DEF"},
            {"name": "Tony Jones Jr.",     "pos": "RB"},
            {"name": "Emmanuel Sanders",   "pos": "WR"},
            {"name": "Adam Trautman",      "pos": "TE"},
            {"name": "Sean Clifford",      "pos": "QB"},
            {"name": "Patrick Taylor",     "pos": "RB"},
            {"name": "Tyler Johnson",      "pos": "WR"},
        ],
        "scores": [88.1, 101.4, 112.7, 79.6, 125.3, 93.8, 107.2, 118.5,
                   84.4, 130.1, 97.6, 109.3, 82.7, 121.8, 95.4, 113.6, 104.2],
    },
]

# Week-by-week matchup pairs (0-indexed team IDs within TEAMS list).
# 5 games per week, 14 regular season weeks, weeks 15-17 are playoffs.
SCHEDULE = [
    [(0,1),(2,3),(4,5),(6,7),(8,9)],   # wk 1
    [(0,2),(1,4),(3,6),(5,8),(7,9)],   # wk 2
    [(0,3),(1,5),(2,7),(4,9),(6,8)],   # wk 3
    [(0,4),(1,6),(2,8),(3,9),(5,7)],   # wk 4
    [(0,5),(1,7),(2,9),(3,8),(4,6)],   # wk 5
    [(0,6),(1,8),(2,4),(3,7),(5,9)],   # wk 6
    [(0,7),(1,9),(2,5),(3,4),(6,8)],   # wk 7
    [(0,8),(1,2),(3,5),(4,7),(6,9)],   # wk 8
    [(0,9),(1,3),(2,6),(4,8),(5,7)],   # wk 9
    [(0,1),(2,9),(3,8),(4,7),(5,6)],   # wk 10
    [(0,2),(1,8),(3,7),(4,6),(5,9)],   # wk 11
    [(0,3),(1,7),(2,8),(4,9),(5,6)],   # wk 12
    [(0,4),(1,6),(2,9),(3,5),(7,8)],   # wk 13
    [(0,5),(1,9),(2,7),(3,6),(4,8)],   # wk 14
    # playoffs (weeks 15-17): top-6 teams by record advance
    [(0,5),(1,4),(2,3)],               # wk 15 quarterfinals
    [(0,1),(2,3)],                     # wk 16 semifinals  (placeholder pairs)
    [(0,1)],                           # wk 17 championship
]

PLAYOFF_WEEKS = {15, 16, 17}
REGULAR_SEASON_WEEKS = set(range(1, 15))


def get_team(team_id: int) -> dict:
    return next(t for t in TEAMS if t["id"] == team_id)


def weekly_results(week: int) -> list[dict]:
    """Return matchup results for a given week (1-indexed)."""
    pairs = SCHEDULE[week - 1]
    results = []
    for a_idx, b_idx in pairs:
        a, b = TEAMS[a_idx], TEAMS[b_idx]
        a_score = a["scores"][week - 1]
        b_score = b["scores"][week - 1]
        results.append({
            "week": week,
            "home": a["name"], "home_score": a_score,
            "away": b["name"], "away_score": b_score,
            "winner": a["name"] if a_score > b_score else b["name"],
        })
    return results


def standings() -> list[dict]:
    """Regular-season standings sorted by wins desc, then points-for desc."""
    records = {t["id"]: {"team": t, "w": 0, "l": 0, "pf": 0.0, "pa": 0.0}
               for t in TEAMS}
    for week in range(1, 15):
        for a_idx, b_idx in SCHEDULE[week - 1]:
            a, b = TEAMS[a_idx], TEAMS[b_idx]
            a_s, b_s = a["scores"][week - 1], b["scores"][week - 1]
            records[a["id"]]["pf"] += a_s
            records[a["id"]]["pa"] += b_s
            records[b["id"]]["pf"] += b_s
            records[b["id"]]["pa"] += a_s
            if a_s > b_s:
                records[a["id"]]["w"] += 1
                records[b["id"]]["l"] += 1
            else:
                records[b["id"]]["w"] += 1
                records[a["id"]]["l"] += 1
    return sorted(records.values(), key=lambda r: (-r["w"], -r["pf"]))


if __name__ == "__main__":
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    print("2024 Fantasy Beefs — GM Email Roster\n")
    print("┌────┬────────────────────────────┬──────────────────────┬──────────────────────────────┐")
    print("│ #  │ Team                       │ Owner                │ Email                        │")
    print("├────┼────────────────────────────┼──────────────────────┼──────────────────────────────┤")
    for t in TEAMS:
        print(f"│ {t['id']:<2} │ {t['name']:<26} │ {t['owner']:<20} │ {t['email']:<28} │")
    print("└────┴────────────────────────────┴──────────────────────┴──────────────────────────────┘")

    print("\n2024 Fantasy Beefs — Regular Season Standings\n")
    print("┌────┬────────────────────────────┬──────┬──────┬──────────┬──────────┐")
    print("│ #  │ Team                       │  W   │  L   │    PF    │    PA    │")
    print("├────┼────────────────────────────┼──────┼──────┼──────────┼──────────┤")
    for rank, row in enumerate(standings(), 1):
        t = row["team"]
        print(f"│ {rank:<2} │ {t['name']:<26} │ {row['w']:>4} │ {row['l']:>4} │ {row['pf']:>8.1f} │ {row['pa']:>8.1f} │")
    print("└────┴────────────────────────────┴──────┴──────┴──────────┴──────────┘")

    print("\nWeek 1 Results\n")
    print("┌────────────────────────────┬───────────────┬────────────────────────────┐")
    print("│ Home                       │     Score     │ Away                       │")
    print("├────────────────────────────┼───────────────┼────────────────────────────┤")
    for r in weekly_results(1):
        score_str = f"{r['home_score']:.1f} - {r['away_score']:.1f}"
        print(f"│ {r['home']:<26} │ {score_str:^13} │ {r['away']:<26} │")
    print("└────────────────────────────┴───────────────┴────────────────────────────┘")
