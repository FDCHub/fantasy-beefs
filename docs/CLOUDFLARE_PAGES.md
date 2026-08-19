# FantasyStakes marketing site — Cloudflare Pages

The public marketing site for **fantasystakesapp.com**. It is a static site with
no backend, no build step and no dependencies, and it deploys entirely
independently of the FantasyStakes application.

| | |
|---|---|
| Branch | `web/fantasystakesapp-marketing` |
| Base | `9490127` — `fantasystakes-1.0.0-rc3` |
| Publish root | `site/` |
| Build command | *(none)* |
| Production domain | `https://fantasystakesapp.com` |
| Application domain | `https://app.fantasystakesapp.com` — **separate project, separate work stream** |

The application and the demo are deployed on Railway by a different work stream.
Nothing in this directory touches Railway, its environment, or DNS.

---

## 1. What is in the publish root

```
site/
  index.html            the whole marketing page — twelve locked sections
  terms/index.html      placeholder, marked for owner and legal completion
  privacy/index.html    placeholder; the "This website" section is factual today
  contact/index.html    placeholder address; deliberately no server-side form
  404.html              served with a 404 status by Pages
  styles/site.css       the only stylesheet
  js/config.js          THE DEMO DESTINATION — the only file to edit at cutover
  js/site.js            demo links + the mobile navigation disclosure
  assets/               favicon.svg, the four PNG icons, og-image.png
  robots.txt sitemap.xml site.webmanifest
  _headers _redirects   Cloudflare Pages hosting configuration
```

Everything else — the asset generator, the preview checker — lives in
`tools/marketing/` and is never published.

---

## 2. Turning the demo on

When the application demo is live, edit **one line** in `site/js/config.js`:

```js
demoUrl: 'https://app.fantasystakesapp.com/demo/enter',
```

Every "Try the Demo" control on the site is marked `data-fs-demo-link` and is
pointed at that value at load. There is no second place to change, and
`test_web1_marketing_site.py` fails if a second one ever appears.

Until then the controls fall back to `#demo`, the on-page demo section — a link
that always resolves, with or without JavaScript. No application hostname is
hardcoded anywhere in the site.

---

## 3. Creating the Pages project

**Not done in this pass.** No Cloudflare CLI is installed and no Cloudflare
credentials are present in this environment, so creating the project requires
account access this session does not have. The steps below are the exact ones
the account owner needs.

### Option A — GitHub-connected (recommended)

1. Cloudflare dashboard → **Workers & Pages** → **Create** → **Pages** →
   **Connect to Git**.
2. Authorise the Cloudflare GitHub app for `FDCHub/fantasy-beefs`.
3. Select the repository, then:
   - **Production branch:** `web/fantasystakesapp-marketing`
   - **Framework preset:** None
   - **Build command:** *(leave empty)*
   - **Build output directory:** `site`
   - **Root directory:** *(leave as the repository root)*
4. **Save and Deploy.** The first build publishes to
   `https://<project>.pages.dev` — free, and it touches no DNS.
5. Open the `.pages.dev` URL and confirm the homepage, the FAQ, the mobile menu
   and the four legal destinations. This is the preview gate before any domain
   work.

Every later push to that branch redeploys automatically; every other branch gets
its own preview URL.

### Option B — direct upload

Only if the Git connection is not wanted:

```bash
npm install -g wrangler        # not installed in this environment
wrangler login                 # opens a browser; needs account access
wrangler pages project create fantasystakes-site --production-branch web/fantasystakesapp-marketing
wrangler pages deploy site --project-name fantasystakes-site
```

This loses automatic redeploys on push, which is why Option A is preferred.

---

## 4. Attaching the domain — a later, separate pass

**Do none of this until the `.pages.dev` preview has been reviewed and
approved.** Attaching a domain changes public DNS.

1. The zone `fantasystakesapp.com` must be on Cloudflare (nameservers pointed at
   Cloudflare). **Changing nameservers is a separate decision and was
   deliberately not made in this pass.**
2. Pages project → **Custom domains** → **Set up a domain** → `fantasystakesapp.com`.
   Cloudflare creates the record itself; do not hand-create it first.
3. Repeat for `www.fantasystakesapp.com`. Both hostnames must be attached for
   the `www` → apex rule in `site/_redirects` to fire — attaching only the apex
   leaves `www` unresolved and that rule is never reached.
4. Leave `app.fantasystakesapp.com` alone. It is the application's record, owned
   by the Railway work stream. Attaching the apex to Pages does not affect it,
   but nothing here should touch it either.

> **Pick one `www` mechanism.** `site/_redirects` handles it at Pages. A
> Cloudflare Redirect Rule at the zone would handle it earlier. Running both is
> how a redirect loop gets built.

---

## 5. Headers, CSP and caching

`site/_headers` is the whole hosting policy. Highlights:

- **`Content-Security-Policy: default-src 'none'`** and `connect-src 'none'` —
  the site talks to nothing, so any fetch, beacon or socket is refused by the
  browser even if one arrived by accident.
- **The one inline block** on the site is the FAQ JSON-LD in `index.html`, and it
  is allowed by `sha256` hash rather than by `'unsafe-inline'`. Edit that block
  and the hash must be regenerated:

  ```bash
  python -c "import base64,hashlib,re; s=open('site/index.html',encoding='utf-8').read(); \
  b=re.findall(r'<script type=\"application/ld\+json\">(.*?)</script>',s,re.S)[0]; \
  print('sha256-'+base64.b64encode(hashlib.sha256(b.encode()).digest()).decode())"
  ```

  `test_web1_marketing_site.py::test_the_json_ld_hash_in_the_csp_matches_the_page`
  recomputes it and fails on drift, so this cannot rot silently.
- `X-Frame-Options: DENY`, `frame-ancestors 'none'`, `nosniff`,
  `strict-origin-when-cross-origin`, and a `Permissions-Policy` that switches off
  every device capability the site has no use for.
- `js/config.js` is capped at a five-minute cache. A week of stale caching on the
  demo destination would be a week of readers sent to the wrong place after the
  switch is thrown.

No cookie banner, because there are no cookies: no analytics, no advertising, no
third-party embed, no local storage.

---

## 6. Verifying a change

Both run against the files in this branch and need nothing installed.

```bash
# Static: locked copy, the Yahoo attribution, link integrity, headers, the CSP
# hash, SEO metadata, the single demo configuration point.
python -m pytest test_web1_marketing_site.py -q

# Live: serves site/ WITH the real _headers (CSP included) and drives a headless
# Chrome at 375, 390, 430, 768, 1024 and 1440 — overflow, navigation, anchors,
# the FAQ, tap targets, reduced motion and a clean console.
node tools/marketing/preview_check.mjs --out ./preview-shots
```

Regenerate the icons and the social card after editing `site/assets/favicon.svg`
or `tools/marketing/og-image.html`:

```bash
node tools/marketing/build_assets.mjs
```

The PNGs are committed, because Pages serves this repository with no build step.

---

## 7. Serving it by hand

```bash
python -m http.server 8080 --directory site
```

Good enough to read the page. It does **not** apply `_headers`, so it will not
catch a CSP mistake — `preview_check.mjs` is the one that does.
