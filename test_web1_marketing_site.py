#!/usr/bin/env python3
"""WEB-1 - static validation for the FantasyStakes public marketing site.

WHAT THIS SUITE IS FOR. The marketing site has no backend, no build step and no
runtime, so nothing about it fails loudly. A dropped section, a paraphrased
contractual string, a demo link that quietly points at the wrong place, a
stylesheet reference that 404s - every one of those ships silently and is
discovered by a reader rather than by us. This suite is the thing that notices.

WHAT IT DELIBERATELY DOES NOT DO. It does not open a browser and it does not
measure layout; `tools/marketing/preview_check.mjs` does that against a real
headless Chrome at six viewports. This file asserts the things that are true of
the FILES: the locked copy, the contractual attribution, the single demo
configuration point, link integrity, and the hosting metadata Cloudflare Pages
will serve.

THE COPY ASSERTIONS ARE VERBATIM AND THAT IS THE POINT. Marketing copy for a
product that must not be mistaken for a real-money sportsbook is not editorial
comfort - it is the boundary of what the product claims. Every locked string is
compared character for character, apostrophes included.

    python -m pytest test_web1_marketing_site.py -q
"""

from __future__ import annotations

import base64
import hashlib
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent
SITE = REPO / "site"

#: Every published HTML document, relative to the publish root.
PAGES = ["index.html", "terms/index.html", "privacy/index.html",
         "contact/index.html", "404.html"]

#: Pages that carry the full marketing footer. 404 carries a reduced one.
FOOTER_PAGES = ["index.html", "terms/index.html", "privacy/index.html",
                "contact/index.html"]

#: The contractual Yahoo attribution. Fixed by the Yahoo API Access and Use
#: Agreement and reproduced character for character - never paraphrased, never
#: templated. The application asserts the same string in
#: test_wp3d_provider_attribution.py; this is the site's copy of that guarantee.
YAHOO_ATTRIBUTION = "Fantasy data provided by Yahoo Fantasy"

#: The live demo destination, cut over in WEB-2b. The application root, which
#: answers 303 to its own entry point - never an internal path, never Railway's
#: generated hostname.
LIVE_DEMO_URL = "https://app.fantasystakesapp.com"

#: The hero headline, locked by WEB-1a. The wordmark is the visual centrepiece
#: of the POR hero; this sentence is the page heading.
LOCKED_HERO = "Add a Vegas-style sportsbook game to your fantasy league."

#: The "What is FantasyStakes" headline, locked SEPARATELY from the hero.
#:
#: These two were one string in the WEB-1 brief, which is why WEB-1a had to
#: replace both at once. They are now independent: the hero can be reworded
#: without dragging this with it, and this without touching the hero. The
#: `test_the_two_headlines_are_locked_independently` case is what keeps them
#: from silently collapsing back into one.
LOCKED_WHAT_IS = "A new game built on the league you already play."

#: The section label above it, locked verbatim.
LOCKED_WHAT_IS_LABEL = "What is FantasyStakes"

#: Every retired hero variant, banned from the published site outright.
#:
#: NOT SCOPED TO THE HERO ELEMENT. The first of these was used by the WEB-1
#: brief for BOTH the hero and the "What is FantasyStakes" headline, so a
#: hero-only ban would have let the retired message survive one screen below the
#: new one. The list grows; nothing is ever removed from it.
SUPERSEDED_HEROES = [
    "Turn your fantasy league into a whole new game.",          # WEB-1
    "Add a Vegas-style fantasy game to your existing league.",  # WEB-1a
]

#: Copy that appears in the approved POR HTML but predates the current
#: marketing POR. The POR governs FORMAT; these are its old words.
OBSOLETE_POR_MESSAGING = [
    "Pure action",          # superseded by "Sportsbook action"
    "Play FantasyStakes",   # superseded by "Try the Demo"
    "Build on it.",         # superseded by "Modernize it."
    "The ledger keeps score",
    "Four simple steps",
]

#: The approved visual POR, recorded in the repository so the design authority
#: is versioned with the site rather than living in an external local folder.
POR_REFERENCE = REPO / "spec" / "fantasystakes_por_mobile_website.html"
POR_SHA256 = "2cbb57582511d6775453e3c0eb7d7ba738e8c5a7278ccbeff6a5e1ba94f28106"

#: The locked homepage section order (POR section 4). Order is asserted, not
#: just membership - the narrative only works in this sequence.
#:
#: TEN SECTIONS, NOT ELEVEN. The standalone "Built to keep the league moving /
#: More action. Less to manage." section made the commissioner argument one
#: screen before the commissioner section made it properly, so it was folded
#: into For Commissioners and its close became that section's close. And
#: `how-it-works` is now `how-to-play`, which is what the section is called on
#: the page, in the navigation and in the footer of every page.
LOCKED_SECTION_ORDER = [
    "top",            # 1  Hero
    "what-is",        # 2  What is FantasyStakes
    "two-ways",       # 3  Two ways to compete
    "commissioners",  # 4  Commissioner (carries the folded-in "More action")
    "players",        # 5  Player
    "credits",        # 6  Virtual credits
    "how-to-play",    # 7  How to Play
    "demo",           # 8  Demo
    "faq",            # 9  FAQ
    "get-started",    # 10 Final CTA
]

#: Locked homepage copy. Each entry is a fragment that must appear verbatim.
LOCKED_COPY = [
    # 5 Hero - WEB-1a locked headline
    "Add a Vegas-style sportsbook game to your fantasy league.",
    "FantasyStakes adds a Vegas-style sportsbook game layer to the fantasy "
    "league you already play.",
    "No deposits. No payouts. No house. No vig.",
    "See How to Play",
    # 6 What is FantasyStakes
    "A new game built on the league you already play.",
    "What is FantasyStakes",
    "FantasyStakes modernizes the fantasy sports experience by adding a "
    "sportsbook-style game layer to the league you already play.",
    "Your regular fantasy matchups, standings and playoffs remain the "
    "foundation.",
    "Your league. Your projections. Calculated odds for every matchup.",
    # 7 Two ways to compete
    "Two new ways to compete",
    "Go head-to-head. Or take on the whole league.",
    "Bench Boss",
    "Bad Beat",
    "Kicker Chaos",
    "Calculated for your league.",
    "Powered by your league’s action.",
    "More competition. More action. More ways to win.",
    # 8 Commissioner - now also carries the folded-in "More action" close
    "Don’t replace your league. Modernize it.",
    "No new draft room. No new waiver system. No need to abandon your league "
    "history. Just more ways for everyone to compete.",
    "More action. Less to manage.",
    # 9 Player
    "More ways to win every week.",
    "Every settled Matchup and Prop Pool also builds a separate FantasyStakes "
    "season, giving you another set of standings and another FantasyStakes "
    "Championship to chase.",
    "Real odds. Sportsbook action. More ways to win.",
    # 10 Virtual credits
    "The odds are real. The action is fast. Stakes are virtual credits. "
    "FantasyStakes keeps score.",
    "FantasyStakes is played entirely with virtual credits. Credits have no "
    "cash value and cannot be purchased, deposited, withdrawn or redeemed.",
    "FantasyStakes Championship",
    "Grand Championship",
    "Virtual credits track the action. The ledger keeps the score.",
    # 11 How to Play
    "Connect your league. Find your action. Compete all season.",
    "Connect your league.",
    "Find your action.",
    "Pick your market and credits.",
    "Follow the season.",
    # 12 Demo
    "See FantasyStakes in action.",
    "No Yahoo account required. No real money. Just a fully playable "
    "FantasyStakes demo.",
    "Try the Demo",
    # 15 Final CTA
    "Your league already has the rivalries. FantasyStakes gives you more ways "
    "to settle them.",
    # 16 Footer
    "Fantasy Stakes for Fantasy Leagues",
    "No house. No vig. No cash. Only FantasyStakes.",
]

#: The seven locked FAQ entries, question then answer, both verbatim.
#:
#: TIGHTENED, NOT GROWN FOR ITS OWN SAKE. Two entries left. "Is there a house?"
#: restated the footer claim and the real-money answer directly above it, and
#: "Can I get additional credits?" explained Top-Off rules - a game mechanic,
#: which belongs inside the game rather than on a marketing page that would
#: date the moment a league changed the setting. What replaced them answers
#: what a reader still does not know after reading the page: where the odds
#: come from, what a virtual credit actually is, and how a league starts.
LOCKED_FAQ = [
    (
        "Does FantasyStakes handle real money?",
        "No. FantasyStakes does not accept deposits, process payments or make "
        "payouts. The game is played entirely with virtual credits. Any "
        "separate arrangements between league members happen independently of "
        "FantasyStakes.",
    ),
    (
        "Does FantasyStakes replace Yahoo?",
        "No. Yahoo remains your fantasy league platform. FantasyStakes sits "
        "alongside it and adds new Matchups, Prop Pools, standings and "
        "championships without replacing your draft, waivers, league standings "
        "or history.",
    ),
    (
        "How are the odds created?",
        "FantasyStakes uses your league’s scoring settings and player "
        "projections to simulate matchups and generate calculated moneylines, "
        "spreads and over/unders for your league.",
    ),
    (
        "What are virtual credits?",
        "Virtual credits are how FantasyStakes keeps score. They track "
        "competition results and have no cash value. They cannot be purchased, "
        "deposited, withdrawn or redeemed.",
    ),
    (
        "What can I play?",
        "You can go head-to-head with other GMs using moneylines, spreads and "
        "over/unders, or take on the whole league through weekly FantasyStakes "
        "Prop Pools.",
    ),
    (
        "Does the demo require Yahoo?",
        "No. The demo uses a fictional sample league and does not require Yahoo "
        "authentication.",
    ),
    (
        "How do I use FantasyStakes with my league?",
        "The commissioner connects the league, and FantasyStakes builds the "
        "experience around that league’s teams, settings, scoring and "
        "projections.",
    ),
]

#: Game mechanics that are deliberately NOT on the marketing page. Every one of
#: them is real and every one of them is explained inside the product. Stating
#: them here turns a marketing page into a rulebook and dates it the first time
#: a league changes a setting.
RULES_THAT_BELONG_IN_THE_GAME = [
    "Top-Off", "Top Off", "Weekly Minimum Reserve", "Championship Reserve",
    "rollover", "skunk", "postseason eligibility",
]

#: Claims this product must never make. FantasyStakes takes no deposits, makes
#: no payouts and sells nothing, so any of these on the page is a
#: misrepresentation regardless of where it came from.
FORBIDDEN_CLAIMS = [
    "win real money", "win cash", "cash prize", "cash prizes", "real cash",
    "cash payout", "cash payouts", "withdraw your", "withdraw funds",
    "deposit funds", "make a deposit", "buy credits", "purchase credits",
    "buy virtual credits", "add funds", "credit card", "payment method",
    "cash out", "guaranteed win", "risk-free bet", "free bet", "sign-up bonus",
    "deposit bonus", "wager real",
]

#: Yahoo is a data source and nothing else. None of this may appear anywhere.
FORBIDDEN_ENDORSEMENT = [
    "powered by yahoo", "official partner", "yahoo partner", "partnered with yahoo",
    "sponsored by yahoo", "endorsed by yahoo", "yahoo-approved", "yahoo approved",
    "in partnership with yahoo", "an official", "yahoo sponsor",
]

#: Any of these means a tracker, an ad network or a remote dependency got in.
FORBIDDEN_THIRD_PARTY = [
    "google-analytics", "googletagmanager", "gtag(", "connect.facebook",
    "doubleclick", "hotjar", "segment.com", "mixpanel", "cdn.jsdelivr",
    "unpkg.com", "cdnjs.cloudflare", "fonts.googleapis", "fonts.gstatic",
]

PRODUCTION_ORIGIN = "https://fantasystakesapp.com"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def read(rel: str) -> str:
    return (SITE / rel).read_text(encoding="utf-8")


class Collector(HTMLParser):
    """Collect tags, attributes, ids and text, and prove the nesting closes.

    Not a validator in the W3C sense and does not pretend to be. It catches the
    failure that actually happens when hand-writing a long page: an element
    opened and never closed, or closed in the wrong order, which silently
    reparents everything after it.
    """

    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
            "meta", "param", "source", "track", "wbr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.tags: list[tuple[str, dict[str, str]]] = []
        self.ids: list[str] = []
        self.text_parts: list[str] = []
        self.errors: list[str] = []
        self._script_type: str | None = None
        self.ld_json: list[str] = []

    def handle_starttag(self, tag, attrs):
        attributes = {k: (v or "") for k, v in attrs}
        self.tags.append((tag, attributes))
        if "id" in attributes:
            self.ids.append(attributes["id"])
        if tag == "script":
            self._script_type = attributes.get("type")
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        attributes = {k: (v or "") for k, v in attrs}
        self.tags.append((tag, attributes))
        if "id" in attributes:
            self.ids.append(attributes["id"])

    def handle_endtag(self, tag):
        if tag in self.VOID:
            return
        if not self.stack:
            self.errors.append(f"</{tag}> with nothing open")
            return
        if self.stack[-1] != tag:
            self.errors.append(f"</{tag}> closes <{self.stack[-1]}>")
            return
        self.stack.pop()
        if tag == "script":
            self._script_type = None

    def handle_data(self, data):
        if self._script_type == "application/ld+json":
            self.ld_json.append(data)
        elif not self.stack or self.stack[-1] not in ("script", "style"):
            self.text_parts.append(data)

    @property
    def text(self) -> str:
        return re.sub(r"\s+", " ", "".join(self.text_parts))


def parse(rel: str) -> Collector:
    collector = Collector()
    collector.feed(read(rel))
    return collector


@pytest.fixture(scope="module")
def parsed() -> dict[str, Collector]:
    return {page: parse(page) for page in PAGES}


# ---------------------------------------------------------------------------
# 1. The site exists and is shaped for Cloudflare Pages
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("rel", PAGES + [
    "robots.txt", "sitemap.xml", "site.webmanifest", "_headers", "_redirects",
    "styles/site.css", "js/site.js", "js/config.js",
    "assets/favicon.svg", "assets/favicon-32.png", "assets/apple-touch-icon.png",
    "assets/icon-192.png", "assets/icon-512.png", "assets/og-image.png",
])
def test_required_file_exists(rel):
    path = SITE / rel
    assert path.is_file(), f"missing {rel}"
    assert path.stat().st_size > 0, f"{rel} is empty"


def test_terms_privacy_and_contact_destinations_exist():
    """The footer links three legal destinations. All three must resolve."""
    for destination in ("terms", "privacy", "contact"):
        assert (SITE / destination / "index.html").is_file(), destination


def test_no_build_artefacts_or_tooling_inside_the_publish_root():
    """Everything under site/ is served to the public, so nothing else lives there."""
    strays = [p.relative_to(SITE).as_posix() for p in SITE.rglob("*")
              if p.is_file() and p.suffix in {".mjs", ".py", ".md", ".log"}]
    assert strays == [], f"tooling inside the publish root: {strays}"


# ---------------------------------------------------------------------------
# 2. Locked structure and copy
# ---------------------------------------------------------------------------

def test_homepage_sections_present_in_the_locked_order():
    html = read("index.html")
    found = re.findall(r'<section[^>]*\sid="([^"]+)"', html)
    assert found == LOCKED_SECTION_ORDER, f"section order drifted: {found}"


@pytest.mark.parametrize("fragment", LOCKED_COPY, ids=lambda s: s[:38])
def test_locked_homepage_copy_is_verbatim(parsed, fragment):
    assert fragment in parsed["index.html"].text, f"missing locked copy: {fragment!r}"


def test_hero_headline_is_the_h1(parsed):
    """The WEB-1a locked hero is the h1, and it is the only h1.

    The POR makes the FANTASYSTAKES wordmark the visual centrepiece of the hero
    and marks it up as the page heading. Here the wordmark is the brand lockup
    and the locked headline is the h1 - identical on screen, correct in the
    document outline.
    """
    html = read("index.html")
    h1s = re.findall(r"<h1[^>]*>(.*?)</h1>", html, re.S)
    assert len(h1s) == 1, f"expected exactly one h1, found {len(h1s)}"
    assert re.sub(r"<[^>]+>", "", h1s[0]).strip() == LOCKED_HERO


def test_the_what_is_headline_is_locked():
    """The section h2 is its own locked string, not an echo of the hero."""
    html = read("index.html")
    section = re.search(r'<section class="section" id="what-is".*?</section>', html, re.S)
    assert section, "the What is FantasyStakes section is missing"
    block = section.group(0)

    heading = re.search(r'<h2 id="what-is-title">(.*?)</h2>', block, re.S)
    assert heading, "the What is section has no h2"
    assert re.sub(r"<[^>]+>", "", heading.group(1)).strip() == LOCKED_WHAT_IS

    label = re.search(r'<p class="eyebrow">(.*?)</p>', block, re.S)
    assert label, "the What is section has no eyebrow label"
    assert label.group(1).strip() == LOCKED_WHAT_IS_LABEL


def test_the_two_headlines_are_locked_independently():
    """The hero and the What is section must never share a headline again.

    They were one string in the WEB-1 brief. Locking them apart means a future
    change to either one cannot quietly reintroduce the duplication.
    """
    assert LOCKED_HERO != LOCKED_WHAT_IS
    html = read("index.html")
    assert html.count(f">{LOCKED_WHAT_IS}<") == 1, (
        "the What is headline appears more than once"
    )
    hero = re.search(r'<h1 id="hero-title">(.*?)</h1>', html, re.S)
    assert LOCKED_WHAT_IS not in re.sub(r"<[^>]+>", "", hero.group(1))


def test_the_what_is_body_copy_is_the_approved_three_paragraphs():
    """Three paragraphs, in order, each one verbatim.

    The middle paragraph is the one that earns the section: it is the only
    place on the page that says HOW the odds exist - league settings, scoring
    and projections, simulated into moneylines, spreads and over/unders. Losing
    it would leave "calculated odds" as an unexplained claim everywhere else.
    """
    text = parse("index.html").text
    paragraphs = [
        "FantasyStakes modernizes the fantasy sports experience by adding a "
        "sportsbook-style game layer to the league you already play. Your "
        "league stays intact, but every week brings more ways to compete "
        "through calculated odds, head-to-head FantasyStakes Matchups and "
        "league-wide FantasyStakes Prop Pools.",
        "FantasyStakes uses your league’s settings, scoring system and player "
        "projections to simulate head-to-head outcomes and generate calculated "
        "moneylines, spreads and over/unders for matchups throughout your "
        "league. The result is a sportsbook-style market built around the "
        "teams and players you actually compete with every week.",
        "Your regular fantasy matchups, standings and playoffs remain the "
        "foundation. FantasyStakes adds its own virtual-credit competition, "
        "season-long standings and FantasyStakes Championship alongside them.",
    ]
    cursor = -1
    for paragraph in paragraphs:
        found = text.find(paragraph, cursor + 1)
        assert found > -1, f"missing What is paragraph: {paragraph[:60]!r}"
        assert found > cursor, "the What is paragraphs are out of order"
        cursor = found


@pytest.mark.parametrize("rel", PAGES)
@pytest.mark.parametrize("retired", SUPERSEDED_HEROES, ids=lambda s: s[:34])
def test_no_superseded_hero_ever_returns(rel, retired):
    """Every retired hero variant stays retired, on every page.

    Checked against the raw source rather than the extracted text, so an
    occurrence hiding in a meta description, an Open Graph tag or a comment is
    caught as readily as one in the markup.
    """
    assert retired not in read(rel), f"{rel} still carries a retired hero: {retired!r}"


def test_the_locked_hero_is_used_everywhere_the_hero_wording_appears():
    """Wherever the page states the hero, it states the CURRENT hero.

    The h1, the meta description, and the Open Graph and Twitter descriptions
    all carry hero wording and are the four places that drift apart when a
    headline changes. The image `alt` attributes deliberately carry the tagline
    instead and are not included.
    """
    html = read("index.html")
    assert f'<h1 id="hero-title">Add a <span class="gold">Vegas-style</span> {LOCKED_HERO.split("Vegas-style ", 1)[1][:-1]}.</h1>' in html

    for name, pattern in (
        ("meta description", r'<meta name="description" content="([^"]+)"'),
        ("og:description", r'<meta property="og:description" content="([^"]+)"'),
        ("twitter:description", r'<meta name="twitter:description" content="([^"]+)"'),
    ):
        match = re.search(pattern, html)
        assert match, f"{name} is missing"
        content = match.group(1)
        assert LOCKED_HERO[:-1] in content, (
            f"{name} does not carry the locked hero wording: {content}"
        )


@pytest.mark.parametrize("phrase", OBSOLETE_POR_MESSAGING)
def test_obsolete_por_messaging_is_not_carried_across(phrase):
    """The POR HTML is the VISUAL authority, not the message authority.

    Its own copy predates the current marketing POR - "Pure action" in place of
    "Sportsbook action", and "Play FantasyStakes" where the call to action is
    now "Try the Demo". Taking the format must not drag the wording along.
    """
    for rel in PAGES:
        assert phrase.lower() not in read(rel).lower(), (
            f"{rel} carries obsolete POR messaging: {phrase!r}"
        )


def test_matchups_and_pools_copy():
    text = parse("index.html").text
    assert ("Every opponent in your league becomes another matchup "
            "opportunity. FantasyStakes uses your league’s projections and "
            "scoring environment to generate calculated moneylines, spreads "
            "and over/unders for each pairing.") in text
    assert ("Every week in your league becomes another prop pool "
            "opportunity. FantasyStakes uses your league’s projections, "
            "scoring environment and weekly storylines to create fun, "
            "league-wide FantasyStakes Prop Pools.") in text


def test_the_two_cards_carry_their_market_and_pool_chips():
    """The chips are the cards' evidence, so they are asserted as a set.

    THE POOL NAMES ARE NAMED PRODUCTS, not examples of a genre - "Bench Boss"
    is a specific weekly pool, and a reader who saw "Highest scoring team" last
    week and "Bench Boss" this week would reasonably conclude the product had
    changed. The generic placeholders they replaced are banned below.
    """
    html = read("index.html")
    cards = re.findall(r'<article class="card">(.*?)</article>', html, re.S)
    assert len(cards) == 2, f"expected two cards, found {len(cards)}"

    matchups, pools = cards
    assert '<p class="pill">Matchups</p>' in matchups
    for market in ("Moneyline", "Spread", "Over/Under"):
        assert f'>{market}</span>' in matchups, f"the Matchups card lost {market!r}"

    assert '<p class="pill">Prop Pools</p>' in pools
    for pool in ("Bench Boss", "Bad Beat", "Kicker Chaos"):
        assert f'>{pool}</span>' in pools, f"the Prop Pools card lost {pool!r}"


def test_the_two_cards_are_structurally_parallel():
    """Same elements, same order, same closing treatment - twice.

    The two cards sit side by side from 700px up, so any difference in their
    shape reads as a difference in the product rather than as a layout choice.
    Both are: gold category pill, heading, one paragraph, a row of chips, and
    one gold line closing the card.
    """
    html = read("index.html")
    cards = re.findall(r'<article class="card">(.*?)</article>', html, re.S)
    assert len(cards) == 2

    shapes = []
    for card in cards:
        found = re.findall(
            r'<p class="(pill|card__note)"|<(h3)>|<div class="(odds)"', card)
        shapes.append([next(part for part in match if part) for match in found])
    assert shapes[0] == shapes[1] == ["pill", "h3", "odds", "card__note"], shapes
    for card in cards:
        assert card.count("<h3>") == 1
        assert card.count('<div class="odds"') == 1
        assert card.count('<span class="chip') == 3
        # The closing line is the LAST thing in the card, under the chips.
        assert card.rindex('class="card__note"') > card.rindex('class="odds"')

    assert 'class="card__key"' not in html, (
        "the retired pool legend is still in the markup"
    )


def test_the_retired_pool_legend_is_gone_from_the_stylesheet_too():
    """A rule nobody selects is a rule the next reader has to rule out."""
    assert ".card__key" not in read("styles/site.css")


@pytest.mark.parametrize("placeholder", [
    "Highest scoring team", "Top WR", "Closest margin",
])
def test_the_generic_pool_placeholders_are_gone(placeholder):
    """The pre-naming placeholders never come back, on any page."""
    for rel in PAGES:
        assert placeholder not in read(rel), f"{rel} still shows {placeholder!r}"


@pytest.mark.parametrize("question,answer", LOCKED_FAQ, ids=lambda s: s[:38])
def test_locked_faq_is_verbatim(parsed, question, answer):
    text = parsed["index.html"].text
    assert question in text, f"missing FAQ question: {question!r}"
    assert answer in text, f"missing FAQ answer for: {question!r}"


def test_faq_uses_native_disclosure_elements():
    """Seven <details> on hairlines - the POR treatment - no scripted accordion.

    Native disclosure means the FAQ is keyboard operable, screen-reader
    announced and printable with JavaScript off.
    """
    html = read("index.html")
    faq = re.search(r'<section class="section faq".*?</section>', html, re.S)
    assert faq, "the FAQ section is not the POR faq block"
    assert faq.group(0).count("<details") == len(LOCKED_FAQ) == 7


@pytest.mark.parametrize("mechanic", RULES_THAT_BELONG_IN_THE_GAME)
def test_game_rules_stay_inside_the_game(mechanic):
    """The marketing page states what the game IS, never how it is scored.

    The retired "Can I get additional credits?" answer walked a reader through
    Top-Off limits, which is a rulebook paragraph in a marketing FAQ: it dates
    the page the first time a league changes the setting, and it is the wrong
    place to learn it either way.
    """
    for rel in PAGES:
        assert mechanic.lower() not in read(rel).lower(), (
            f"{rel} states the game rule {mechanic!r}; that belongs in the product"
        )


def test_how_to_play_has_four_ordered_steps():
    html = read("index.html")
    steps = re.search(r'<ol class="steps">(.*?)</ol>', html, re.S)
    assert steps, "the How to Play steps are not an ordered list"
    assert steps.group(1).count("<li") == 4
    titles = re.findall(r"<h3>(.*?)</h3>", steps.group(1), re.S)
    assert titles == ["Connect your league.", "Find your action.",
                      "Pick your market and credits.", "Follow the season."], titles


def test_how_to_play_is_named_the_same_thing_everywhere():
    """One name for the section, on every page that points at it.

    The section was "How it works" and is now "How to Play". The id, the
    navigation, the hero's secondary call to action and the footer of all four
    footer pages have to move together, or a reader follows a link labelled one
    thing to a heading called another - and on the legal pages, to nothing at
    all, because a dead fragment scrolls nowhere and reports no error.
    """
    for rel in PAGES:
        body = read(rel)
        assert "how-it-works" not in body, f"{rel} still points at the old id"
        assert "How It Works" not in body, f"{rel} still uses the old label"

    home = read("index.html")
    assert '<section class="section" id="how-to-play"' in home
    assert '<a class="nav__link" href="#how-to-play">How to Play</a>' in home
    assert '<a class="btn btn--secondary" href="#how-to-play">See How to Play</a>' in home
    for rel in ("terms/index.html", "privacy/index.html", "contact/index.html",
                "404.html"):
        assert '<a href="/#how-to-play">How to Play</a>' in read(rel), rel


# ---------------------------------------------------------------------------
# 3. The contractual Yahoo attribution
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("rel", PAGES)
def test_yahoo_attribution_is_exact(rel, parsed):
    assert YAHOO_ATTRIBUTION in parsed[rel].text, (
        f"{rel} does not carry the exact attribution string"
    )


@pytest.mark.parametrize("rel", PAGES)
def test_no_yahoo_endorsement_language(rel):
    body = read(rel).lower()
    for phrase in FORBIDDEN_ENDORSEMENT:
        assert phrase not in body, f"{rel} implies endorsement: {phrase!r}"


@pytest.mark.parametrize("rel", PAGES)
def test_no_yahoo_sign_in_on_the_static_site(rel):
    """Yahoo retention authorisation is open; the static site must not offer auth."""
    body = read(rel).lower()
    for phrase in ("sign in with yahoo", "log in with yahoo", "connect with yahoo",
                   "oauth", "api.login.yahoo.com", "authorize"):
        assert phrase not in body, f"{rel} exposes Yahoo authentication: {phrase!r}"


# ---------------------------------------------------------------------------
# 4. The product must not be mistaken for a real-money sportsbook
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("rel", PAGES)
def test_no_real_money_claims(rel):
    body = read(rel).lower()
    for phrase in FORBIDDEN_CLAIMS:
        assert phrase not in body, f"{rel} makes a forbidden claim: {phrase!r}"


def test_the_virtual_credit_disclaimer_is_on_every_footer_page(parsed):
    disclaimer = ("FantasyStakes is played entirely with virtual credits. "
                  "Credits have no cash value and cannot be purchased, "
                  "deposited, withdrawn or redeemed.")
    for rel in FOOTER_PAGES:
        assert disclaimer in parsed[rel].text, f"{rel} is missing the credit disclaimer"


# ---------------------------------------------------------------------------
# 5. The demo destination has exactly one configuration point
# ---------------------------------------------------------------------------

def test_demo_url_is_configured_in_exactly_one_file():
    """One file ASSIGNS the destination. Others may read it; none may set it."""
    owners = [p.relative_to(SITE).as_posix()
              for p in SITE.rglob("*")
              if p.is_file() and p.suffix in {".html", ".js", ".css"}
              and re.search(r"demoUrl\s*:", p.read_text(encoding="utf-8"))]
    assert owners == ["js/config.js"], f"demoUrl is assigned in {owners}"


def test_config_declares_the_live_demo_url():
    """WEB-2b cut the demo over to the live application root, exactly.

    THE ROOT, not `/app/index.html`. The root answers 303 to the application's
    own entry point, so linking to the redirect target instead would pin this
    site to an internal path the application is free to change.
    """
    config = read("js/config.js")
    match = re.search(r"demoUrl:\s*'([^']+)'", config)
    assert match, "config.js has no demoUrl"
    assert match.group(1) == LIVE_DEMO_URL, (
        f"demoUrl is {match.group(1)!r}, expected {LIVE_DEMO_URL!r}"
    )


def test_the_demo_url_is_no_longer_a_placeholder():
    """The pre-cutover placeholder and the POST-only route are both rejected.

    `#demo` was correct while the application had no reachable demo; shipping it
    as the live destination now would silently strand every reader on this page.
    `/demo/enter` answers POST only - a GET returns 405 - so it can never be the
    target of a link, however plausible it looks.
    """
    demo_url = re.search(r"demoUrl:\s*'([^']+)'", read("js/config.js")).group(1)
    assert demo_url != "#demo", "the demo destination is still the placeholder"
    assert not demo_url.startswith("#"), "the demo destination is an on-page anchor"
    assert "/demo/enter" not in demo_url, "/demo/enter answers POST only"
    assert demo_url.startswith("https://"), "the demo destination is not https"
    assert not demo_url.endswith("/"), "trailing slash - keep the value exact"


def test_every_demo_control_routes_through_the_single_config_point(parsed):
    """The markup names no URL; it ships a fallback that always resolves.

    `site.js` rewrites these to `demoUrl` on load. The markup deliberately keeps
    `#demo` rather than the live URL: hard-coding it would create four more
    places to change at the next cutover, which is the exact failure the single
    configuration point exists to prevent. Without JavaScript a reader lands on
    the demo section of this page - degraded, never a dead link.
    """
    for rel in PAGES:
        hrefs = [attrs.get("href") for tag, attrs in parsed[rel].tags
                 if tag == "a" and "data-fs-demo-link" in attrs]
        if rel == "index.html":
            assert len(hrefs) == 4, f"{rel} has {len(hrefs)} demo controls, expected 4"
        for href in hrefs:
            assert href in ("#demo", "/#demo"), f"{rel} demo fallback is {href!r}"
            assert LIVE_DEMO_URL not in href, (
                f"{rel} hard-codes the demo URL in markup; it belongs in config.js"
            )


def test_no_railway_hostname_appears_anywhere_in_the_site():
    """Railway's generated host is deployment plumbing and changes without notice.

    Forbidden in EVERY published file, `config.js` included - there is no file
    for which naming it would be correct.
    """
    for path in SITE.rglob("*"):
        if not path.is_file() or path.suffix not in {".html", ".js", ".css", ".xml", ".txt"}:
            continue
        body = path.read_text(encoding="utf-8").lower()
        for host in ("railway.app", "up.railway", "railway.internal"):
            assert host not in body, f"{path.relative_to(SITE)} names {host}"


def test_the_application_hostname_lives_only_in_the_config():
    """Exactly one published file may name the application domain."""
    named = [p.relative_to(SITE).as_posix()
             for p in SITE.rglob("*")
             if p.is_file() and p.suffix in {".html", ".js", ".css"}
             and "app.fantasystakesapp.com" in p.read_text(encoding="utf-8")]
    assert named == ["js/config.js"], f"the application domain is named in {named}"


# ---------------------------------------------------------------------------
# 6. Link and asset integrity
# ---------------------------------------------------------------------------

def _resolve(rel_page: str, target: str) -> Path | None:
    """Map a root-relative site path to the file Cloudflare Pages would serve."""
    path = target.split("?")[0].split("#")[0]
    if not path:
        return None
    if path.endswith("/"):
        return SITE / path.lstrip("/") / "index.html"
    candidate = SITE / path.lstrip("/")
    if candidate.is_dir():
        return candidate / "index.html"
    return candidate


@pytest.mark.parametrize("rel", PAGES)
def test_every_internal_link_and_asset_resolves(rel, parsed):
    missing = []
    for tag, attrs in parsed[rel].tags:
        for attribute in ("href", "src"):
            target = attrs.get(attribute)
            if not target or target.startswith(("http://", "https://", "mailto:", "tel:", "data:", "#")):
                continue
            assert target.startswith("/"), (
                f"{rel} uses the relative path {target!r}; subdirectory pages "
                f"need root-relative paths"
            )
            resolved = _resolve(rel, target)
            if resolved is None or not resolved.is_file():
                missing.append(target)
    assert missing == [], f"{rel} links to missing files: {missing}"


@pytest.mark.parametrize("rel", PAGES)
def test_every_in_page_anchor_has_a_target(rel, parsed):
    ids = set(parsed[rel].ids)
    dangling = []
    for tag, attrs in parsed[rel].tags:
        href = attrs.get("href", "")
        if tag == "a" and href.startswith("#") and len(href) > 1:
            if href[1:] not in ids:
                dangling.append(href)
    assert dangling == [], f"{rel} has anchors with no target: {dangling}"


@pytest.mark.parametrize("rel", PAGES)
def test_ids_are_unique(rel, parsed):
    ids = parsed[rel].ids
    duplicates = {i for i in ids if ids.count(i) > 1}
    assert not duplicates, f"{rel} repeats ids: {duplicates}"


@pytest.mark.parametrize("rel", PAGES)
def test_markup_nesting_closes(rel, parsed):
    collector = parsed[rel]
    assert collector.errors == [], f"{rel}: {collector.errors}"
    assert collector.stack == [], f"{rel} leaves open: {collector.stack}"


@pytest.mark.parametrize("rel", PAGES)
def test_document_basics(rel):
    html = read(rel)
    assert html.startswith("<!DOCTYPE html>"), f"{rel} has no doctype"
    assert '<html lang="en">' in html, f"{rel} declares no language"
    assert '<meta charset="utf-8">' in html, f"{rel} declares no charset"
    assert 'name="viewport"' in html, f"{rel} has no viewport meta"


@pytest.mark.parametrize("rel", PAGES)
def test_no_third_party_resources(rel, parsed):
    body = read(rel).lower()
    for needle in FORBIDDEN_THIRD_PARTY:
        assert needle not in body, f"{rel} pulls in {needle!r}"
    # `<link rel="canonical">` and `<link rel="alternate">` are declarations, not
    # fetches, and their whole job is to name the absolute production URL. Only
    # the rel values that actually pull bytes over the network are checked.
    fetching_rels = {"stylesheet", "icon", "apple-touch-icon", "manifest",
                     "preload", "prefetch", "preconnect", "dns-prefetch",
                     "modulepreload", "mask-icon"}
    for tag, attrs in parsed[rel].tags:
        for attribute in ("src", "href"):
            target = attrs.get(attribute, "")
            if not target.startswith(("http://", "https://")):
                continue
            if tag in ("script", "img", "iframe"):
                pytest.fail(f"{rel} loads {tag} from {target}")
            if tag == "link" and set(attrs.get("rel", "").split()) & fetching_rels:
                pytest.fail(f"{rel} fetches a remote resource: {target}")


# ---------------------------------------------------------------------------
# 7. SEO, social and hosting metadata
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("rel", FOOTER_PAGES)
def test_seo_and_social_metadata(rel):
    html = read(rel)
    assert re.search(r"<title>.+?</title>", html), f"{rel} has no title"
    assert re.search(r'<meta name="description" content=".{50,}?">', html), (
        f"{rel} has no usable meta description"
    )
    assert f'<link rel="canonical" href="{PRODUCTION_ORIGIN}' in html, (
        f"{rel} has no production canonical"
    )
    for prop in ("og:type", "og:title", "og:description", "og:url", "og:image"):
        assert f'property="{prop}"' in html, f"{rel} is missing {prop}"
    assert 'name="twitter:card" content="summary_large_image"' in html, (
        f"{rel} has no Twitter card"
    )


def test_404_is_not_indexed():
    assert 'name="robots" content="noindex' in read("404.html")


def test_robots_allows_indexing_and_points_at_the_sitemap():
    robots = read("robots.txt")
    assert "User-agent: *" in robots
    assert "Allow: /" in robots
    assert f"Sitemap: {PRODUCTION_ORIGIN}/sitemap.xml" in robots


def test_sitemap_lists_every_indexable_page_on_the_production_domain():
    locations = re.findall(r"<loc>(.*?)</loc>", read("sitemap.xml"))
    assert locations == [
        f"{PRODUCTION_ORIGIN}/",
        f"{PRODUCTION_ORIGIN}/terms/",
        f"{PRODUCTION_ORIGIN}/privacy/",
        f"{PRODUCTION_ORIGIN}/contact/",
    ], locations


def test_open_graph_image_is_the_declared_size():
    """A social card that is not 1200x630 is cropped by the scrapers that read it."""
    png = (SITE / "assets" / "og-image.png").read_bytes()
    assert png[:8] == b"\x89PNG\r\n\x1a\n", "og-image.png is not a PNG"
    width = int.from_bytes(png[16:20], "big")
    height = int.from_bytes(png[20:24], "big")
    assert (width, height) == (1200, 630), f"og-image.png is {width}x{height}"
    assert len(png) < 600_000, f"og-image.png is {len(png)} bytes"


def test_favicon_is_an_original_monogram():
    svg = read("assets/favicon.svg")
    assert "<svg" in svg and "</svg>" in svg
    assert ">F</tspan>" in svg and ">S</tspan>" in svg, "the mark is not the FS monogram"
    for colour in ("#0b0b0a", "#f3eddc", "#c8a24d"):
        assert colour in svg, f"the mark departs from the locked palette ({colour})"


# ---------------------------------------------------------------------------
# 8. Cloudflare Pages headers and redirects
# ---------------------------------------------------------------------------

def test_security_headers_are_declared():
    headers = read("_headers")
    for name in ("X-Content-Type-Options: nosniff",
                 "X-Frame-Options: DENY",
                 "Referrer-Policy:",
                 "Permissions-Policy:",
                 "Content-Security-Policy:"):
        assert name in headers, f"_headers is missing {name}"


def test_content_security_policy_is_restrictive_but_permits_the_site():
    policy = next(line for line in read("_headers").splitlines()
                  if "Content-Security-Policy:" in line)
    for directive in ("default-src 'none'", "script-src 'self'", "style-src 'self'",
                      "img-src 'self' data:", "frame-ancestors 'none'",
                      "base-uri 'self'", "object-src 'none'"):
        assert directive in policy, f"CSP is missing {directive}"
    assert "'unsafe-inline'" not in policy, "CSP allows inline script or style"
    assert "'unsafe-eval'" not in policy


def test_the_json_ld_hash_in_the_csp_matches_the_page():
    """The one inline block on the site is allowed by hash, so it cannot drift.

    Edit the FAQ JSON-LD without regenerating the hash and the browser silently
    refuses the block; this test is what turns that into a visible failure.
    """
    blocks = re.findall(
        r'<script type="application/ld\+json">(.*?)</script>',
        read("index.html"), re.S)
    assert len(blocks) == 1, f"expected one JSON-LD block, found {len(blocks)}"
    digest = base64.b64encode(hashlib.sha256(blocks[0].encode("utf-8")).digest()).decode()
    assert f"'sha256-{digest}'" in read("_headers"), (
        "the CSP script hash does not match the JSON-LD block; regenerate it"
    )


def test_www_redirects_to_the_apex():
    redirects = read("_redirects")
    assert f"https://www.fantasystakesapp.com/* {PRODUCTION_ORIGIN}/:splat 301!" in redirects


# ---------------------------------------------------------------------------
# 9. Responsive, accessible and cheap
# ---------------------------------------------------------------------------

def test_responsive_breakpoints_exist():
    """The POR has ONE breakpoint at 700px; everything else is fluid by clamp.

    900px is the site's own addition and exists for one reason: the navigation
    disclosure the POR topbar does not have.
    """
    css = read("styles/site.css")
    for width in (700, 900):
        assert f"@media (min-width: {width}px)" in css, f"no {width}px breakpoint"
    assert css.count("@media (min-width:") == 2, (
        "extra breakpoints have crept in; the POR layout is clamp-driven"
    )


def test_reduced_motion_is_honoured():
    css = read("styles/site.css")
    assert "@media (prefers-reduced-motion: reduce)" in css
    block = css.split("@media (prefers-reduced-motion: reduce)")[1]
    assert "scroll-behavior: auto" in block
    assert "transition-duration: .01ms !important" in block


def test_focus_is_visible_and_never_removed():
    css = read("styles/site.css")
    assert ":focus-visible" in css
    assert re.search(r":focus-visible\s*{[^}]*outline:\s*2px solid", css)
    assert "outline: none" not in css.replace(":focus:not(:focus-visible) { outline: none; }", "")


def test_the_locked_palette_is_used_verbatim():
    css = read("styles/site.css")
    for name, value in (("bg", "#0b0b0a"), ("ivory", "#f3eddc"), ("muted", "#b8ad8e"),
                        ("gold", "#c8a24d"), ("gold2", "#e0bd68")):
        assert f"--{name}:" in css, f"missing --{name}"
        assert value in css, f"the locked {name} value {value} is not in the stylesheet"


def test_the_primary_navigation_is_the_locked_five():
    """Five section links, in order, each resolving to a section on this page.

    "What is FantasyStakes" is first because it is the section that explains
    the product; before this change the page's own explanation was the one
    section the navigation did not offer.
    """
    html = read("index.html")
    nav = re.search(r'<nav class="nav" id="site-nav".*?</nav>', html, re.S)
    assert nav, "the primary navigation is missing"
    links = re.findall(r'<a class="nav__link" href="#([^"]+)">(.*?)</a>', nav.group(0))
    assert links == [
        ("what-is", "What is FantasyStakes"),
        ("how-to-play", "How to Play"),
        ("commissioners", "For Commissioners"),
        ("players", "For Players"),
        ("faq", "FAQ"),
    ], links
    # The sixth locked destination is the demo, which is the topbar's gold link
    # rather than a section link - it leaves the page.
    assert '<a class="mini-link" href="#demo" data-fs-demo-link>Try the Demo</a>' in html


def test_skip_link_and_landmarks():
    html = read("index.html")
    assert '<a class="skip" href="#main">' in html
    assert '<main id="main">' in html
    assert "<header class=" in html and "<footer class=" in html
    assert '<nav class="nav" id="site-nav" aria-label="Primary">' in html


def test_decorative_product_motifs_are_labelled():
    """Odds and credit figures read as noise unless the illustration is named."""
    html = read("index.html")
    motifs = re.findall(r'role="img"([^>]*)', html)
    assert len(motifs) >= 4, f"only {len(motifs)} labelled illustrations"
    for attributes in motifs:
        assert "aria-label=" in attributes, "a role=img illustration has no label"


def test_the_payload_stays_small():
    """No framework, no webfont, no stock photography - so this must stay true."""
    total = sum(p.stat().st_size for p in SITE.rglob("*") if p.is_file())
    assert total < 900_000, f"the whole site is {total} bytes"
    assert (SITE / "styles" / "site.css").stat().st_size < 45_000
    assert (SITE / "js" / "site.js").stat().st_size < 20_000


def test_there_is_no_cookie_banner_because_there_are_no_cookies():
    for rel in PAGES:
        body = read(rel).lower()
        assert "document.cookie" not in body
        assert "cookie banner" not in body
        assert "localstorage" not in body


# ---------------------------------------------------------------------------
# 9b. The Cloudflare Workers Static Assets deployment configuration (WEB-2a)
# ---------------------------------------------------------------------------

WRANGLER = REPO / "wrangler.jsonc"


def _wrangler_config() -> dict:
    """Parse wrangler.jsonc.

    JSONC is JSON plus comments. The file uses only whole-line `//` comments, so
    stripping those is enough and avoids taking a dependency on a JSONC parser
    to read a nine-line config.
    """
    import json
    lines = []
    for line in WRANGLER.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("//"):
            continue
        lines.append(line)
    return json.loads("\n".join(lines))


def test_the_worker_config_exists_and_parses():
    assert WRANGLER.is_file(), "wrangler.jsonc is missing"
    assert isinstance(_wrangler_config(), dict)


def test_the_worker_serves_the_publish_root():
    config = _wrangler_config()
    assert config["name"] == "fantasystakes-marketing"
    assert config["assets"]["directory"] == "./site"
    # The declared directory must actually be the publish root, not a path that
    # merely looks right.
    resolved = (REPO / config["assets"]["directory"].lstrip("./")).resolve()
    assert resolved == SITE.resolve(), f"assets.directory resolves to {resolved}"
    assert (resolved / "index.html").is_file()


def test_the_compatibility_date_is_sane():
    """A real, past ISO date. A future one is rejected by the Workers runtime."""
    import datetime
    value = _wrangler_config()["compatibility_date"]
    parsed = datetime.date.fromisoformat(value)
    assert parsed <= datetime.date.today(), f"compatibility_date {value} is in the future"
    assert parsed.year >= 2024, f"compatibility_date {value} is implausibly old"


def test_unknown_paths_get_the_styled_404_page():
    """WEB-2b. Without this key the runtime returns a bare, empty 404.

    WEB-2a proved that against the real Workers Static Assets runtime: with
    `not_found_handling` at its default of "none", an unknown path falls through
    to the generated no-op Worker and answers with zero bytes and no
    content-type, discarding the styled page WEB-1 certified.
    """
    assets = _wrangler_config()["assets"]
    assert assets.get("not_found_handling") == "404-page", (
        "unknown paths would return a blank 404 instead of site/404.html"
    )
    assert (SITE / "404.html").is_file(), "the page the setting points at is missing"


def test_the_worker_config_stays_assets_only():
    """No script, so no binding, and none of the superseded models.

    `main` would name a Worker entrypoint that does not exist and fail the
    build; `assets.binding` is only meaningful alongside `main`;
    `pages_build_output_dir` is Pages-only; `site`/`bucket` is the deprecated
    Workers Sites model that `assets` replaced.
    """
    config = _wrangler_config()
    for key in ("main", "pages_build_output_dir", "site", "bucket", "routes", "route"):
        assert key not in config, f"wrangler.jsonc should not set {key!r}"
    assert "binding" not in config["assets"], (
        "assets.binding requires a Worker script; this deployment has none"
    )


def test_the_worker_config_carries_no_credentials_or_local_paths():
    """Nothing account-identifying, nothing machine-specific, ever committed."""
    raw = WRANGLER.read_text(encoding="utf-8")
    config = _wrangler_config()
    for key in ("account_id", "api_token", "vars", "secrets"):
        assert key not in config, f"wrangler.jsonc must not carry {key!r}"
    for needle in ("C:\\", "C:/", "/Users/", "Downloads", "file://", "CLOUDFLARE_", "\\\\"):
        assert needle not in raw, f"wrangler.jsonc contains {needle!r}"


def test_no_custom_domain_is_attached_by_configuration():
    """WEB-2a is preview only: the apex must not be claimed from the repo."""
    raw = WRANGLER.read_text(encoding="utf-8").lower()
    config = _wrangler_config()
    assert "routes" not in config and "route" not in config
    for line in raw.splitlines():
        if line.lstrip().startswith("//"):
            continue
        assert "fantasystakesapp.com" not in line, (
            "a custom domain is referenced outside a comment"
        )


# ---------------------------------------------------------------------------
# 10. Fidelity to the approved visual POR (WEB-1a)
# ---------------------------------------------------------------------------

def test_the_visual_por_is_recorded_in_the_repository():
    """The design authority is versioned here, not referenced from a local folder.

    WEB-1a was reconciled against a specific artefact. Pinning its hash means a
    future reviewer can prove which one, and a clean checkout carries it.
    """
    assert POR_REFERENCE.is_file(), "the approved POR HTML is not in the repository"
    digest = hashlib.sha256(POR_REFERENCE.read_bytes()).hexdigest()
    assert digest == POR_SHA256, f"the recorded POR has changed: {digest}"


def test_por_layout_tokens_are_verbatim():
    """The POR's structural measurements, not approximations of them."""
    css = read("styles/site.css")
    for declaration in ("--max: 760px",      # the POR measure
                        "--radius: 22px",    # card corner
                        "--topbar-h: 62px"): # sticky bar
        assert declaration in css, f"the POR token {declaration!r} is missing"


def test_por_furniture_is_present():
    """The POR's signature components, each carrying its POR geometry."""
    css = read("styles/site.css")
    checks = {
        # Full-viewport centred hero under the sticky bar.
        "hero height": "min-height: calc(100svh - var(--topbar-h))",
        # Solid gold category pill - the one saturated gold shape on the page.
        "gold pill": "background: var(--gold2)",
        # Left gold rule with a wash falling away to the right.
        "quote rule": "border-left: 3px solid var(--gold)",
        # Numbered steps on hairlines rather than a row of cards.
        "step number": "border-radius: 50%",
        # Centred radial glow behind the closing call to action.
        "close glow": "radial-gradient(circle at 50% 50%",
        # One gold wash from above the fold, on the body.
        "body wash": "radial-gradient(circle at 50% -10%",
        # POR button: 52px, fully rounded, full width until 700px.
        "button": "min-height: 52px",
        "button width": "width: min(100%, 320px)",
    }
    for label, needle in checks.items():
        assert needle in css, f"POR {label} treatment is missing: {needle!r}"


def test_the_hero_lockup_is_the_por_wordmark():
    """FANTASY in ivory, STAKES in gold, uppercase, at display size."""
    html = read("index.html")
    assert ('<p class="brand"><span class="fantasy">FANTASY</span>'
            '<span class="stakes">STAKES</span></p>') in html
    assert "Fantasy Stakes for Fantasy Leagues" in html
    css = read("styles/site.css")
    assert ".brand .fantasy { color: var(--ivory); }" in css
    assert "text-transform: uppercase" in css


def test_the_por_pill_is_used_for_the_two_ways_cards():
    """The two category labels, in the POR's solid-gold pill.

    "Prop Pools", not "Pools". The public terminology is "FantasyStakes Prop
    Pools" on first reference and "Prop Pools" after it; a bare "Pools" is a
    third name for the same thing and reads as a different feature.
    """
    html = read("index.html")
    assert '<p class="pill">Matchups</p>' in html
    assert '<p class="pill">Prop Pools</p>' in html


def test_no_dead_classes_survive_the_reconciliation():
    """Every class the markup uses is defined; nothing points at deleted CSS."""
    css = read("styles/site.css")
    used = set()
    for rel in PAGES:
        for value in re.findall(r'class="([^"]+)"', read(rel)):
            used.update(value.split())
    missing = sorted(name for name in used if f".{name}" not in css)
    assert missing == [], f"markup uses classes with no styles: {missing}"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
