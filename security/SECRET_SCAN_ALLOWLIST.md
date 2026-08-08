# Secret-Scan Allowlist

**Status:** Governing verification artifact
**Date:** 2026-08-04
**Scope:** the MVP clean tree only

---

## 0. What this file is, and what it is not

This file pre-registers **specific, known-benign, database-shaped test fixtures** — and, in Entries 5–8, **one security control and its documentation** — so the secret scan (gate G-12) can pass without weakening.

**It is not a suppression list.** The following are explicitly **NOT** suppressed and must continue to fail the scan wherever they appear:

- PostgreSQL URI patterns generally
- password patterns generally
- `localhost` findings generally
- any test directory, in whole or in part
- test fixtures as a class

**Every entry below is scoped to one exact file and one exact fixture.** No broad regex exemption is granted anywhere in this document. **The secret scan must still fail on unexpected credential-shaped content**, including inside the same file, including inside the same test.

**No complete fixture string and no credential-like component is reproduced in this file.** Entries are identified by path, line, and test identifier only.

---

## 1. Allowed fixtures — 11

**Entries 1–2** — engine-construction control proof, one file:
`tests/test_af1_engine_control_surface_red.py` (clean-tree path; source path
`test_af1_engine_control_surface_red.py`). That file is the control proof for the governed
engine-construction surface. Its entire purpose is to assert how engines are **constructed**
from URLs, which is why it contains URL-shaped literals at all.

**Entries 3–4 — group A**, loopback URI fixtures in `tests/test_support_crash_selftest.py`.

**Entries 5–8 — group B**, the Guard-4 forbidden-host denylist and its documentation. These
differ in kind from every other entry in this file: they are **not** fixtures. They are a
security control and the prose that documents it. They match the scan because they contain
the literal host tokens the harness exists to **refuse**. Removing or masking them would
weaken Guard 4, which is the opposite of the intended outcome.

**Group B verification standard, binding on Entries 5–8.** For each, the matched token is
**not** part of a URI, a connection string, an environment value, a credential object, or
executable connection configuration.

**Group A verification standard, binding on Entries 3–4**, and identical to the standard
Entries 1–2 use: none of `.connect()` · `.execute()` · `begin()` · `sessionmaker` ·
`create_all` appears in the enclosing region.

**Entries 9–11 — group C**, three `generic-api-key` false positives in the governed pool
catalog `spec/pool_catalog_rev1_3.json`. Each is the `"key"` field of a pool definition — a
long descriptive snake_case product identifier. The rule fires on the literal field name
`key` combined with the entropy of a long identifier. They are **not** credentials, and they
are **not** fixtures: they are product-catalog content.

**Group C verification standard, binding on Entries 9–11.** A required code-usage check
proved that pool definition `key` values never enter authentication, authorization, signing,
credential-comparison, secret-handling, or access-control paths. Every consumption site is a
catalog lookup, market identification, persistence/reference key, or test validation. The
value is a **product identifier only**. This standard is re-verified at every G-12 run.

| # | Path | Enclosing identifier | Line | Group |
|---|---|---|---|---|
| 1 | `tests/test_af1_engine_control_surface_red.py` | `test_3_hook_independent_of_import_order` / `PG_DUMMY_URL` | 278 | — |
| 2 | `tests/test_af1_engine_control_surface_red.py` | `test_7_scheme_normalization` | 521 | — |
| 3 | `tests/test_support_crash_selftest.py` | `_SAFE_URL` | 65 | A |
| 4 | `tests/test_support_crash_selftest.py` | `test_child_dbname_guard_still_fires_for_a_bad_url` | 497 | A |
| 5 | `tests/test_support_postgres.py` | `_FORBIDDEN_HOST_PATTERNS` | 57 | B |
| 6 | `tests/test_support_postgres.py` | `setup_postgres_test_db` Guard-4 docstring | 132 | B |
| 7 | `tests/test_support_crash.py` | `_FORBIDDEN_HOST_PATTERNS` | 126 | B |
| 8 | `spec/FR_VAL10_AF_ENGINE_CONTROL_SURFACE_MODULE_SPEC_Rev8.md` | Guard-4 documentation table row | 416 | B |
| 9 | `spec/pool_catalog_rev1_3.json` | pool definition `catalog_number` 89 — "Matchups with 10+ Combined TDs" | 3311 | C |
| 10 | `spec/pool_catalog_rev1_3.json` | pool definition `catalog_number` 90 — "Matchups with 500+ Combined Rushing Yards" | 3354 | C |
| 11 | `spec/pool_catalog_rev1_3.json` | pool definition `catalog_number` 91 — "Matchups with 700+ Combined Offensive Yards" | 3397 | C |

**In every entry the line number is diagnostic evidence, never sole identity.** Identity is
the path plus the enclosing identifier plus the expected shape. A shifted line does not carry
its allowance with it — see §3.4.

**Owner of all eight entries: Fraser D. Coleman.**

---

### Entry 1

| Field | Value |
|---|---|
| **Source file** | `tests/test_af1_engine_control_surface_red.py` |
| **Line** | 278 |
| **Test identifier** | `test_3_hook_independent_of_import_order` |
| **Fixture identifier** | `PG_DUMMY_URL` |
| **Shape** | PostgreSQL scheme · placeholder user:pass pair · loopback host · database name `nonexistent_db_af1` |
| **Reason required** | Proves the SQLite foreign-key pragma hook is attached per-engine and is **not** attached to a PostgreSQL engine, independent of module import order. The assertion is about the constructed engine's event registration, so a PostgreSQL-shaped URL is unavoidable. |
| **Why local / synthetic / non-routable** | Host is **loopback** — it cannot leave the machine. The database name `nonexistent_db_af1` is deliberately non-existent and self-documenting. The user:pass pair is a structural placeholder, not a credential: the file contains **zero** occurrences of `password`, `PGPASSWORD`, `secret`, `token`, or `api_key`. |
| **Verified: never connects** | Confirmed by read. Lines 270–296 contain **no** `.connect()`, `.execute()`, `engine.begin()`, `sessionmaker`, or `create_all`. The test asserts on engine construction only. |
| **Scanner rule** | Allow **only**: this exact path, line 278, fixture name `PG_DUMMY_URL`, loopback host, database name `nonexistent_db_af1`. A change to the host, the database name, or the line's fixture name **revokes the allowance and must fail the scan.** |
| **Manual-review procedure** | On any diff touching lines 270–296: confirm the host is still loopback, the database name is still `nonexistent_db_af1`, and no connection call has been introduced. If any of the three changed, treat as a new finding, not a moved allowance. |
| **Owner** | Fraser D. Coleman |
| **Expiration / review condition** | Review at each of: (a) any edit to `test_af1_engine_control_surface_red.py`; (b) the VAL-10 gate that closes `FR-VAL10-ai–al`; (c) any change to the governed engine-construction surface. **No time-based expiry** — the allowance is tied to the fixture, not to a date. |

---

### Entry 2

| Field | Value |
|---|---|
| **Source file** | `tests/test_af1_engine_control_surface_red.py` |
| **Line** | 521 |
| **Test identifier** | `test_7_scheme_normalization` |
| **Fixture identifier** | inline argument to `_get_engine(...)` |
| **Shape** | Legacy `postgres` scheme · placeholder user:pass pair · **single-character synthetic host** · single-character database name |
| **Reason required** | Proves the legacy `postgres://` scheme is normalized to `postgresql://` while a `sqlite://` URL passes through unmodified. The test's entire subject is the URL scheme, so a scheme-bearing literal is the test. |
| **Why local / synthetic / non-routable** | The host is a **single character** — not a resolvable hostname, not a registered domain, not an IP. It is a syntactic placeholder chosen to make the URL parseable and nothing more. The database name is likewise a single character. |
| **Verified: never connects** | Confirmed by read. Lines 515–534 contain **no** `.connect()`, `.execute()`, `engine.begin()`, `sessionmaker`, or `create_all`. The test reads `eng.url.drivername` and asserts on it. |
| **Scanner rule** | Allow **only**: this exact path, line 521, single-character host, single-character database name, legacy `postgres` scheme. Any multi-character host, any dotted host, any change of scheme **revokes the allowance and must fail the scan.** |
| **Manual-review procedure** | On any diff touching lines 515–534: confirm the host remains a single character and no connection call has been introduced. A host that gains a dot is a finding. |
| **Owner** | Fraser D. Coleman |
| **Expiration / review condition** | Same three conditions as Entry 1. No time-based expiry. |

---

### Entry 3 — group A

| Field | Value |
|---|---|
| **Source file** | `tests/test_support_crash_selftest.py` |
| **Enclosing identifier** | module-level constant `_SAFE_URL` |
| **Line** *(diagnostic evidence, not sole identity)* | 65 |
| **Scanner category** | PostgreSQL URI with userinfo |
| **Expected shape** | a `postgresql://` URI assigned to a module-level constant · loopback host · structural placeholder userinfo · deliberately non-existent database name |
| **Host class** | **loopback — non-routable off-host** |
| **Purpose** | Provides a known-safe URL against which the crash-selftest harness exercises its own guards. |
| **Verified: never connects** | None of `.connect()` · `.execute()` · `begin()` · `sessionmaker` · `create_all` appears in the enclosing region. **The constant is never used to open a connection.** |
| **Fail-closed on drift** | The allowance is **void** if the enclosing identifier changes, if the host class ceases to be loopback, if the syntactic shape changes, or if any of the five call forms appears in the enclosing region. **A shifted line number does not carry the allowance with it.** |
| **Owner** | Fraser D. Coleman |
| **Review condition** | Re-verified at every Gate E run. **Revoked automatically** on any drift condition above. |

---

### Entry 4 — group A

| Field | Value |
|---|---|
| **Source file** | `tests/test_support_crash_selftest.py` |
| **Enclosing identifier** | `test_child_dbname_guard_still_fires_for_a_bad_url` |
| **Line** *(diagnostic evidence, not sole identity)* | 497 |
| **Scanner category** | PostgreSQL URI with userinfo |
| **Expected shape** | a `postgresql://` URI constructed inline within the test body · loopback host · structural placeholder userinfo · deliberately invalid database name |
| **Host class** | **loopback — non-routable off-host** |
| **Purpose** | The fixture exists to prove the database-name guard fires against a deliberately bad URL. **The URI must be malformed for the test to have meaning.** |
| **Verified: never connects** | None of the five call forms appears in the enclosing test body. **The URL is passed to the guard, never to a driver.** |
| **Fail-closed on drift** | As Entry 3, keyed on the **test identifier** rather than a module constant. |
| **Owner** | Fraser D. Coleman |
| **Review condition** | As Entry 3. |

---

### Entry 5 — group B

| Field | Value |
|---|---|
| **Source file** | `tests/test_support_postgres.py` |
| **Enclosing identifier** | `_FORBIDDEN_HOST_PATTERNS` |
| **Line** *(diagnostic evidence, not sole identity)* | 57 |
| **Scanner category** | hosted-database host token |
| **Expected shape** | a tuple of bare host substrings · **no scheme · no userinfo · no port · no surrounding URI** |
| **Purpose** | Defines the host tokens Guard 4 refuses. **This is the security control itself.** |
| **Verified** | The matched token is **not** part of a URI, a connection string, an environment value, a credential object, or executable connection configuration. It is a literal in a denylist tuple. |
| **Fail-closed on drift** | **Void** if the identifier changes, if the tuple gains a scheme or userinfo, or if any element is interpolated into a connection string. **Void if the construct ceases to be a denylist.** |
| **Owner** | Fraser D. Coleman |
| **Review condition** | Re-verified at every Gate E run. **Because this entry allowlists a security control, any change to Guard 4's shape requires the entry to be re-approved rather than adjusted.** |

---

### Entry 6 — group B

| Field | Value |
|---|---|
| **Source file** | `tests/test_support_postgres.py` |
| **Enclosing identifier** | `setup_postgres_test_db` — Guard 4 explanatory docstring |
| **Line** *(diagnostic evidence, not sole identity)* | 132 |
| **Scanner category** | hosted-database host token |
| **Expected shape** | prose inside a docstring naming the forbidden host tokens descriptively · **no scheme · no userinfo · no assignment** |
| **Purpose** | Documents why Guard 4 refuses those hosts. |
| **Verified** | As Entry 5. **The token appears in prose, not in executable configuration.** |
| **Fail-closed on drift** | **Void** if the token moves out of the docstring, or if the docstring is replaced by executable code. |
| **Owner** | Fraser D. Coleman |
| **Review condition** | As Entry 5. |

---

### Entry 7 — group B

| Field | Value |
|---|---|
| **Source file** | `tests/test_support_crash.py` |
| **Enclosing identifier** | `_FORBIDDEN_HOST_PATTERNS` |
| **Line** *(diagnostic evidence, not sole identity)* | 126 |
| **Scanner category** | hosted-database host token |
| **Expected shape** | As Entry 5. |
| **Purpose** | As Entry 5 — **the same control in the crash-test harness.** |
| **Verified** | As Entry 5. |
| **Fail-closed on drift** | As Entry 5. |
| **Owner** | Fraser D. Coleman |
| **Review condition** | As Entry 5. |

---

### Entry 8 — group B

| Field | Value |
|---|---|
| **Source file** | `spec/FR_VAL10_AF_ENGINE_CONTROL_SURFACE_MODULE_SPEC_Rev8.md` |
| **Section anchor** *(discovered, not invented)* | `#### af-2 completion criteria — SATISFIED 2026-07-22` |
| **Enclosing anchor** | the Guard-4 documentation table row beneath that heading — the row whose `Guard` cell is `4` and whose `Line` cell is `` `:177` ``, in the two-row guard table headed `Guard \| Line \| Requirement` |
| **Line** *(diagnostic evidence, not sole identity)* | 416 |
| **Uniqueness** | **Verified.** The section anchor encloses **exactly one** Guard-4 table row. The row's own first cell (`4`) is **not** unique document-wide, which is why identity binds to the section heading plus the `Guard`/`Line` cell pair rather than to the first cell alone. |
| **Scanner category** | hosted-database host token |
| **Expected shape** | a markdown table cell naming forbidden host tokens descriptively · **no scheme · no userinfo · no assignment** |
| **Purpose** | Specification documentation of the Guard 4 host denylist. |
| **Verified** | As Entry 5. **The token appears in documentation prose, not in executable configuration.** |
| **Fail-closed on drift** | **Void** if the row moves out of its section, if the cell gains a scheme or userinfo, or if the document ceases to describe Guard 4. |
| **Owner** | Fraser D. Coleman |
| **Review condition** | As Entry 5. |

### Entry 9 — group C

| Field | Value |
|---|---|
| **Source file** | `spec/pool_catalog_rev1_3.json` |
| **Scanner rule** | `generic-api-key` |
| **Line** *(diagnostic evidence, not sole identity)* | 3311 |
| **Enclosing identifier** | pool definition `catalog_number` **89**, `display_name` "Matchups with 10+ Combined TDs", category Binary Qualifier Pools, mechanic PREDICTION |
| **Matched-value SHA-256** | `e4613079af00c74ea2d0fc47dde6bc54472c8afeef1bd017026e71baa6b710aa` |
| **Matched-value length** | 33 |
| **Character-class requirement** | `[A-Za-z0-9_]+` — verified, no other character present |
| **Field** | the pool-definition `"key"` field — confirmed |
| **Full file SHA-256** | `d9f779d3161b0d9f19551c2a2bd6b67af66f34d7c8104f7941559f916e36680c` |
| **Justification** | Governed product-catalog identifier, **not authentication material**. |
| **Code-usage-check result** | **PASS** — no pool `key` value reaches authentication, authorization, signing, credential-comparison, secret-handling, or access-control code. |
| **Fail-closed on drift** | Void on any of: path change · file SHA-256 change · scanner-rule change · enclosing pool identifier change · matched-value SHA-256 change · line change without an approved file-hash update · character class gaining any character outside `[A-Za-z0-9_]` · finding count for this file exceeding three. |
| **Owner** | Fraser D. Coleman |
| **Review condition** | Re-verified at every G-12 run. |

### Entry 10 — group C

| Field | Value |
|---|---|
| **Source file** | `spec/pool_catalog_rev1_3.json` |
| **Scanner rule** | `generic-api-key` |
| **Line** *(diagnostic evidence, not sole identity)* | 3354 |
| **Enclosing identifier** | pool definition `catalog_number` **90**, `display_name` "Matchups with 500+ Combined Rushing Yards", category Binary Qualifier Pools, mechanic PREDICTION |
| **Matched-value SHA-256** | `22b4b4f50fe71810daad44dcef47f98fe4d9fe8fae66533da1ee446d616dab9a` |
| **Matched-value length** | 44 |
| **Character-class requirement** | `[A-Za-z0-9_]+` — verified, no other character present |
| **Field** | the pool-definition `"key"` field — confirmed |
| **Full file SHA-256** | `d9f779d3161b0d9f19551c2a2bd6b67af66f34d7c8104f7941559f916e36680c` |
| **Justification** | Governed product-catalog identifier, **not authentication material**. |
| **Code-usage-check result** | **PASS** — as Entry 9. |
| **Fail-closed on drift** | As Entry 9. |
| **Owner** | Fraser D. Coleman |
| **Review condition** | Re-verified at every G-12 run. |

### Entry 11 — group C

| Field | Value |
|---|---|
| **Source file** | `spec/pool_catalog_rev1_3.json` |
| **Scanner rule** | `generic-api-key` |
| **Line** *(diagnostic evidence, not sole identity)* | 3397 |
| **Enclosing identifier** | pool definition `catalog_number` **91**, `display_name` "Matchups with 700+ Combined Offensive Yards", category Binary Qualifier Pools, mechanic PREDICTION |
| **Matched-value SHA-256** | `de853bbe20aea5aeb0f91efced8c45966e0013918698bb1fd0e1f4312c7a56ac` |
| **Matched-value length** | 46 |
| **Character-class requirement** | `[A-Za-z0-9_]+` — verified, no other character present |
| **Field** | the pool-definition `"key"` field — confirmed |
| **Full file SHA-256** | `d9f779d3161b0d9f19551c2a2bd6b67af66f34d7c8104f7941559f916e36680c` |
| **Justification** | Governed product-catalog identifier, **not authentication material**. |
| **Code-usage-check result** | **PASS** — as Entry 9. |
| **Fail-closed on drift** | As Entry 9. |
| **Owner** | Fraser D. Coleman |
| **Review condition** | Re-verified at every G-12 run. |

### Entries 9–11 — collective voiding conditions, binding

- **A change to the file SHA-256 voids Entries 9, 10, and 11 together.** They are not
  independently rescued by their individual value hashes.
- **A fourth `generic-api-key` finding in this file voids Entries 9, 10, and 11 together.**
- **Any finding not matched by an entry remains REAL.**
- **No entry may absorb a future finding by similarity.** Identity is exact: path, rule,
  enclosing pool definition, matched-value SHA-256, length, and character class.

These entries suppress **nothing structural**. There is no directory, file-wide, JSON-wide,
`key`-field-wide, or rule-wide exception, and no gitleaks configuration change.

---

## 2. Not allowlisted — recorded so their absence is deliberate

The same file contains further URL-shaped literals at lines 58, 103, 120, 177, 202, 296, 512, 524, and 530. **None is allowlisted and none needs to be:**

- Lines 120, 177, 202, 530 are `sqlite://` paths — local file or in-memory, no host, no credential component.
- Lines 58, 296, 512, 524 are **comments and formatted output strings**, not fixtures. They carry a scheme but no credential component.
- Line 103 is a usage example in a docstring/comment.

**Only two of the eleven URL-shaped occurrences carry a credential-shaped `user:pass@` component.** Both are allowlisted above. The other nine must continue to be evaluated on their merits by the scanner.

---

## 3. Scanner configuration requirements

1. **Path-and-line scoped.** Allowances are keyed on file path *and* line *and* fixture characteristics. A path-only or file-only exemption does not satisfy this document.
2. **No pattern-class suppression.** Do not add `postgres://`, `postgresql://`, `localhost`, `127.0.0.1`, or `*password*` to any global ignore list.
3. **No directory suppression.** `tests/` is scanned in full.
4. **Fail-closed on drift.** If a line number shifts, the allowance does **not** follow it automatically. Re-verify against the fixture characteristics and update this file deliberately. A silently migrating allowance is the failure mode this design exists to prevent.
5. **Redacted output.** Run the scanner with redaction enabled and use filename-only reporting (`-l`) for the manual grep checks. Never print a matched value.

---

## 4. Expected benign findings outside this allowlist

These are **key names and variable names, never values**. They are resolved by inspection at the gate, not by allowlisting:

| Location | What appears | Why it is not a secret |
|---|---|---|
| `scripts/yahoo_auth.py` | JSON **key names** for OAuth fields | Key names in a dictionary literal; the values are read from a file that does not enter the clean tree |
| `.env.example` | Environment variable **names** | Names only, no values — that is the file's purpose |
| `notifications/tuesday_sync.py` | `YAHOO_*` and `SMTP_*` env var **names** | `os.getenv` argument strings |
| `spec/MVP_DECISION_AND_FINDING_INDEX.md` | the token `5433` | Local Docker test-harness port; identifies a local container, not a remote host |

**Confirm each is a name, never a value.** If any of these ever carries a value, it is a real finding.

---

## 5. What must never be allowlisted

- Anything under `secrets/` — those paths do not enter the clean tree at all.
- Any local machine-specific settings file that may contain credentials.
- Any `.env` file other than `.env.example`.
- Any remote database host, in any file, for any reason.
- Any rotation-rehearsal or findings-register material — none of it enters the clean tree.

**If the scan produces a finding that is not one of Entries 1–8, or a §4 name, treat it as real.** Do not extend this file to make a scan pass. Extend it only when a new fixture or control is deliberately introduced and independently justified against every field in §1.

---

## 6. Gate relationship

This file is a precondition of **gate G-12 (secret scan)**, which itself gates `git init`.

**Zero real findings are required before any Git operation.** Once content enters Git history, removing it is a history rewrite — prohibited everywhere in this project. The scan is the last point at which that is cheap, and this allowlist exists so the scan can be strict rather than tolerated.
