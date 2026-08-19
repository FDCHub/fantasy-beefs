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

#: The hero headline, locked by WEB-1a. The wordmark is the visual centrepiece
#: of the POR hero; this sentence is the page heading.
LOCKED_HERO = "Add a Vegas-style fantasy game to your existing league."

#: Retired by WEB-1a. The WEB-1 brief used it for BOTH the hero and the
#: "What is FantasyStakes" headline, so it is banned outright rather than only
#: in the hero - a half-replacement would leave the old message one screen below
#: the new one.
SUPERSEDED_HERO = "Turn your fantasy league into a whole new game."

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
LOCKED_SECTION_ORDER = [
    "top",            # 1  Hero
    "what-is",        # 2  What is FantasyStakes
    "more-action",    # 3  More action
    "two-ways",       # 4  Two ways to compete
    "commissioners",  # 5  Commissioner
    "players",        # 6  Player
    "credits",        # 7  Virtual credits
    "how-it-works",   # 8  How it works
    "demo",           # 9  Demo
    "faq",            # 10 FAQ
    "get-started",    # 11 Final CTA
]

#: Locked homepage copy. Each entry is a fragment that must appear verbatim.
LOCKED_COPY = [
    # 5 Hero - WEB-1a locked headline
    "Add a Vegas-style fantasy game to your existing league.",
    "FantasyStakes adds a Vegas-style sportsbook game layer to the fantasy "
    "league you already play.",
    "No deposits. No payouts. No house. No vig.",
    "See How It Works",
    # 6 What is FantasyStakes
    "FantasyStakes modernizes the fantasy sports experience by adding a "
    "sportsbook-style game layer to the league you already play.",
    "Your regular fantasy matchups, standings and playoffs remain the "
    "foundation.",
    # 7 More action
    "Built to keep the league moving",
    "More action. Less to manage.",
    "The game stays competitive. The recordkeeping stays simple.",
    # 8 Two ways to compete
    "Two new ways to compete",
    "Go head-to-head. Or take on the whole league.",
    "More competition. More action. More ways to win.",
    # 9 Commissioner
    "Don’t replace your league. Modernize it.",
    "No new draft room. No new waiver system. No need to abandon your league "
    "history. Just more ways to compete.",
    # 10 Player
    "More ways to win every week.",
    "Real odds. Sportsbook action. More ways to win.",
    # 11 Virtual credits
    "The odds are real. The action is your fantasy league. FantasyStakes "
    "keeps score.",
    "FantasyStakes is played entirely with virtual credits. Credits have no "
    "cash value and cannot be purchased, deposited, withdrawn or redeemed.",
    "All $ amounts shown in FantasyStakes represent virtual credits.",
    "FantasyStakes Championship Score",
    "Grand Champion",
    "More ways to compete. More ways to win.",
    # 12 How it works
    "Connect your league. FantasyStakes does the rest.",
    "Connect Yahoo",
    "Play with virtual credits",
    "Compete all season",
    "Crown the champion",
    # 13 Demo
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

#: The six locked FAQ entries, question then answer, both verbatim.
LOCKED_FAQ = [
    (
        "Does FantasyStakes handle real money?",
        "No. FantasyStakes does not accept deposits, process payments or make "
        "payouts. The game is played entirely with virtual credits. Any "
        "separate arrangements between league members happen independently of "
        "FantasyStakes.",
    ),
    (
        "Can I get additional credits?",
        "Yes, if your league allows Top-Offs. GMs may request additional "
        "virtual credits during the season, subject to the league’s preset "
        "Top-Off rules and limits. Top-Offs are part of the FantasyStakes game "
        "economy and cannot be purchased with real money.",
    ),
    (
        "Does FantasyStakes replace Yahoo?",
        "No. FantasyStakes sits on top of the Yahoo league you already play, "
        "adding new matchup opportunities, prop pools, standings and "
        "championships without replacing your existing league.",
    ),
    (
        "What can I play?",
        "You can go head-to-head with other GMs through FantasyStakes Matchups "
        "using moneylines, spreads and over/unders, or take on the whole league "
        "through weekly FantasyStakes Prop Pools.",
    ),
    (
        "Is there a house?",
        "No. There is no house in FantasyStakes. FantasyStakes is a "
        "peer-to-peer game, like a traditional fantasy sports league. It does "
        "not take the other side of your competitions and does not charge a "
        "vig.",
    ),
    (
        "Does the demo require Yahoo?",
        "No. The demo uses a fictional sample league and does not require Yahoo "
        "authentication.",
    ),
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


@pytest.mark.parametrize("rel", PAGES)
def test_the_superseded_hero_never_returns(rel):
    """WEB-1a retired this headline. It must not come back anywhere on the site.

    Not scoped to the hero: the WEB-1 brief used the same sentence as the
    "What is FantasyStakes" headline, so a partial replacement would leave the
    superseded message on the page one screen below the new one.
    """
    assert SUPERSEDED_HERO not in read(rel), f"{rel} still carries the superseded hero"


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
    assert ("Go head-to-head with anyone in your league using calculated "
            "moneylines, spreads and over/unders built around your league’s "
            "weekly projections and action.") in text
    assert ("Take on the whole league through weekly prop pools built around "
            "calling what happens next, from team scoring and player "
            "performances to other fantasy outcomes.") in text


@pytest.mark.parametrize("question,answer", LOCKED_FAQ, ids=lambda s: s[:38])
def test_locked_faq_is_verbatim(parsed, question, answer):
    text = parsed["index.html"].text
    assert question in text, f"missing FAQ question: {question!r}"
    assert answer in text, f"missing FAQ answer for: {question!r}"


def test_faq_uses_native_disclosure_elements():
    """Six <details> on hairlines - the POR treatment - and no scripted accordion.

    Native disclosure means the FAQ is keyboard operable, screen-reader
    announced and printable with JavaScript off.
    """
    html = read("index.html")
    faq = re.search(r'<section class="section faq".*?</section>', html, re.S)
    assert faq, "the FAQ section is not the POR faq block"
    assert faq.group(0).count("<details") == 6


def test_how_it_works_has_four_ordered_steps():
    html = read("index.html")
    steps = re.search(r'<ol class="steps">(.*?)</ol>', html, re.S)
    assert steps, "the How it works steps are not an ordered list"
    assert steps.group(1).count("<li") == 4


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


def test_config_declares_a_demo_url():
    config = read("js/config.js")
    assert re.search(r"demoUrl:\s*'[^']+'", config), "config.js has no demoUrl"


def test_every_demo_control_ships_the_same_safe_fallback(parsed):
    """With JavaScript off the fallback must still resolve, on every page."""
    for rel in PAGES:
        hrefs = [attrs.get("href") for tag, attrs in parsed[rel].tags
                 if tag == "a" and "data-fs-demo-link" in attrs]
        if rel == "index.html":
            assert len(hrefs) >= 4, f"{rel} has only {len(hrefs)} demo controls"
        for href in hrefs:
            assert href in ("#demo", "/#demo"), f"{rel} demo fallback is {href!r}"


def test_no_application_hostname_is_hardcoded():
    """The application deployment is another work stream; nothing here guesses it."""
    for path in SITE.rglob("*"):
        if not path.is_file() or path.suffix not in {".html", ".js", ".css", ".xml", ".txt"}:
            continue
        body = path.read_text(encoding="utf-8").lower()
        for host in ("railway.app", "up.railway", "app.fantasystakesapp.com"):
            if host in body and path.name != "config.js":
                pytest.fail(f"{path.relative_to(SITE)} hardcodes {host}")


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
    html = read("index.html")
    assert '<p class="pill">Matchups</p>' in html
    assert '<p class="pill">Pools</p>' in html


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
