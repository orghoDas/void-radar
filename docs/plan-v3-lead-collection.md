# Void Radar Plan v3 - Lead Collection

Date: 2026-08-21
Status: adopted
Supersedes `docs/plan-v2-non-technical-segment.md` and the source priorities in
`docs/signal-first-apify-roadmap.md`.

---

## 0. What changed in v3

| | v2 | v3 |
| --- | --- | --- |
| Purpose | find, qualify, send | **find, qualify, rank, hand off** |
| Sending | in scope | **out of scope** |
| Contacts | decision-makers only, verified before export | **every contact found, labelled by quality** |
| Technical filtering | keyword and GitHub only | **plus an LLM classifier** |
| Output | send-ready campaign | **ranked datasheet for a third party** |

### Consequence of removing sending

The original brief revises scoring weights against reply data. With no sends
there are no replies, so **scoring stays assumption-based and cannot be
validated**. The ranking is an informed prior, not a measured model. This is
stated on the datasheet so the recipient does not mistake it for evidence.

Suppression and verification remain in the pipeline. We are not sending, but we
are handing someone else a list they will send from, and unlabelled bad
addresses damage their domain rather than ours.

---

## 1. Objective

```text
Produce a ranked datasheet of non-technical organisations that need software
built, with every contact and web presence we can attribute to them, so that
another person can run outreach from it.
```

Success is the quality and defensibility of the sheet, not conversations.

---

## 2. The target

Organisations that **buy** software and do not **build** it.

Confirmed present in the data already:

```text
Universities and colleges      34   Manchester, Leeds, Teesside, Northumbria
NHS trusts and healthcare      14   Guy's and St Thomas', Berkshire Healthcare
Police and fire services        9   Leicestershire Constabulary, Dorset Fire
Airports and transport          7   Luton Airport, Transport for Gtr Manchester
Central government agencies     7   National Audit Office, Post Office
Housing associations            6   Platform Housing, Eastlight Community Homes
Councils                        6   Kent County, Portsmouth City, Cotswold
Energy, utilities, water        5   Offshore Renewable Energy Catapult
Charities and trusts            4   National Trust, Tullie House Museum
Private companies              53   Bank of England, Vantage RE, Celtic Sea Power
```

Explicitly not the target: software companies, dev agencies, and startups with
technical founders. 759 of the current 808 companies are exactly that, which is
what Phase A and Phase C exist to correct.

---

## 3. Phase A - Segment scoring  (DONE)

**Purpose.** Stop excluding the buyers we want and stop rewarding the builders
we do not.

**Built.**
- Size no longer disqualifies. Previously `>500 employees` was a hard
  disqualifier; Luton Airport and Kent County Council were auto-excluded before
  anyone looked. Now a small penalty plus a "verify capacity" note.
- GitHub became two-way. A confirmed small or absent public footprint adds +14
  and a positive reason instead of merely being an absent negative.
- 31 non-technical industry terms added to fit scoring, so a haulage firm scores
  +18 rather than -6.

**Current effect.** 11 companies excluded on GitHub evidence (Grafana 590 repos,
Coder 237, PlanetScale 155, Addepar 51). 13 companies boosted.

```text
GATE  Non-technical companies are a majority of companies scoring >= 50.
      NOT MET. Only 24 of 808 companies have been GitHub-checked, and the
      population is still 94% technical by origin.
```

---

## 4. Phase B - Live-opportunity sources

**Purpose.** Replace the technical population with organisations that have a
documented, funded software need.

### What we explore

Measured on 2026-08-21, not assumed:

| Portal | Status | Live software rate | Auth |
| --- | --- | --- | --- |
| UK Find a Tender | 200 | **2 per 100 releases** | none |
| UK Contracts Finder | 200 | 3 per ~12,000 | none |
| Public Contracts Scotland | 200 | unmapped | none |
| EU TED | 200 | untested, high volume | none |
| Sell2Wales | **500** | n/a | none |

### What we scrape

Tender notices classified CPV `72*` (IT services) or `48*` (software packages).
From each notice:

```text
buying organisation name and domain
tender title, description, CPV classification
budget amount and currency
tender deadline and publication date
named contact: person, email, telephone
notice URL as evidence
```

### What we build

1. **Find a Tender adapter.** First, because it has the highest measured live
   rate. Critical implementation note: Find a Tender puts CPV at
   `tender.items[].additionalClassifications[].id` and leaves
   `tender.classification` **empty on 76% of releases**. Reading the Contracts
   Finder path returns zero records silently. The adapter must read all three
   known paths and treat an empty CPV set as suspicious rather than as a miss.
2. **EU TED adapter.** POST search with `classification-cpv=72*`.
3. **Public Contracts Scotland.** Map the schema before writing the adapter.
4. **Sell2Wales.** Re-probe. Do not build against a 500.
5. **Daily cadence.** `sources.cadence` and `sources.last_run_at` exist and are
   unused. Live tenders are missed by depth and caught by frequency: scanning
   12,000 notices instead of 2,500 found older tenders, not more live ones.
6. **Portal blocklist, extended.** 467 notices resolved to an e-sourcing
   intermediary rather than the buyer. Proactis, Jaggaer, In-Tend, MyTenders,
   BIP Solutions and Sourcedogg must never become company records.

```text
GATE  20+ live software tenders with future deadlines, from 3+ portals,
      refreshed daily.
```

---

## 5. Phase C - LLM technical/non-technical classifier

**Purpose.** Keyword matching cannot tell a logistics company that mentions
"platform" from a platform company. A model reading the site can.

### What we explore

The company's own website - homepage, about, services, team - condensed to
structure rather than truncated. The existing condenser already strips scripts,
styles and hydration payloads; naive truncation fed a model nothing but `<head>`
and it correctly returned nulls.

### What we build

A classifier returning a validated verdict:

```text
company_type          software_vendor | agency | non_technical_buyer | unclear
builds_software       true | false | unknown
engineering_signals   list of quoted evidence found on the page
buyer_signals         list of quoted evidence found on the page
confidence            0-1
```

**Validation, non-negotiable.** Every claim must be quoted from the fetched
text. A verdict whose evidence does not appear on the page is discarded, the
same rule that already caught a model inventing `founders@natural.com` when the
company is `natural.co`.

**Gating.** Runs only on companies that pass cheap filters first, which is what
keeps model spend proportional. Measured cost so far: **$0.0003 per company**,
so classifying all 808 costs about 25 cents.

**Ordering.** Deterministic checks run first and the model only decides what
they cannot: keyword match, then GitHub footprint, then the classifier.

```text
GATE  Every company scoring >= 50 carries a classifier verdict with quoted
      evidence. Software vendors and agencies are excluded from the datasheet.
```

---

## 6. Phase D - Contact and web presence capture

**Changed in v3.** Previously: decision-makers only, verified before export.
Now: **capture everything, label everything, discard nothing.**

### What we scrape, per company

```text
Emails        every address found on the company's own domain
              contact, about, team, careers, support, press, imprint pages
              mailto: links, structured data, footer text
People        every named person with a role, where stated
Phones        published telephone numbers
Web presence  website, careers page, ATS board, blog, docs
Social        LinkedIn company URL, X handle, others as found
Procurement   named tender contacts from notices, which are public record
```

### What we build

1. **Site-wide contact sweep**, replacing the current narrow decision-maker
   crawl. Same actor, wider page set, no role filtering.
2. **Contact quality labelling** on every row rather than filtering:
   ```text
   contact_kind        person | role_inbox | generic | unknown
   on_company_domain   true | false
   deliverability      deliverable_domain | role_address | no_mx | invalid
   source_type         website | procurement_notice | hn_post | social
   source_url          where it was found
   ```
3. **Web presence table** so a company's pages are queryable, not buried in a
   payload.
4. **Suppression retained.** We do not send, but the recipient will. Free-mail
   hosts, aggregators and platform domains stay excluded so the sheet does not
   hand them a domain-reputation problem.

**What does not change:** no email guessing, no SMTP probing, no pattern
permutation. Every address is one that was published somewhere, with the URL
recorded. "Where did you get this" must always have an answer.

```text
GATE  Every company in the datasheet has all discoverable contacts, each with
      a kind, a deliverability label, and a source URL.
```

---

## 7. Phase E - Social enrichment  (BUILT, UNRUN)

LinkedIn and X through Apify Store actors: the vendor operates collection, we
consume results and pay per event.

**What we explore.** LinkedIn company search by sector and geography, which is
the useful half. X is built but expected to be low yield - companies rarely
post that they need a development partner.

**What we build.** Already built: runner, normaliser, CLI. Vendor output is
untrusted, so a field rename produces zero records and a loud rejection count
rather than silently wrong ones. Non-technical filtering is on by default.

Isolated by design: disabling this module changes no other pipeline output.

```text
GATE  A live run returns usable non-technical companies at a known cost per record.
      BLOCKED - Apify account is on the FREE plan and these actors are pay-per-event.
```

---

## 8. Phase F - Scoring and ranking

**Purpose.** The datasheet is ordered by defensible priority, not by whatever
order rows were collected.

### Score composition

```text
total = fit x intent / 100
```

**Fit** - is this the kind of organisation we want?
```text
+ non-technical sector match
+ GitHub shows no substantial engineering footprint
+ LLM classifier says non_technical_buyer
+ resolvable domain and reachable website
- software vendor or agency          (disqualifying)
- confirmed in-house engineering org  (disqualifying)
- free-mail or suppressed domain      (disqualifying)
```

**Intent** - is there a current, funded reason to talk?
```text
PROCUREMENT_NOTICE        90   published budget and deadline
STALE_ENGINEERING_ROLE    85   approved budget they cannot spend
HIRING_SPIKE              78
OPERATIONS_SOFTWARE_NEED  72
TECH_STACK_NEED           62
FUNDING_EVENT             58
PROCUREMENT_HISTORY       40   bought software before, nothing open now
```

Intent decays with age. A tender that closed last year is weaker than one open
now, and the score must say so rather than treating both as current.

### Ranking tiers on the datasheet

```text
A  non-technical, live funded need, person-level contact
B  non-technical, live funded need, role inbox only
C  non-technical, historical buying evidence
D  unclassified or thin evidence
X  excluded: software vendor, agency, or in-house engineering confirmed
```

Excluded rows stay in the workbook on their own sheet with the reason, so the
recipient can audit the exclusion instead of trusting it.

```text
GATE  Every row carries fit, intent, total, tier, and the reasons behind them.
```

---

## 9. Phase G - Datasheet handoff

**Purpose.** One file another person can work from without needing this repo.

### Sheets

```text
Leads       ranked, one row per contact, with company context
Companies   one row per organisation with scores, signals, evidence
Contacts    every contact with kind, deliverability, source URL
Excluded    what was removed and why
Sources     what was scanned, when, and how much it produced
Notes       what the scores mean and what they do not
```

The Notes sheet states plainly that scores are an informed prior, never
validated against replies, because no outreach was sent from this system.

```text
GATE  A person outside this project can use the sheet without explanation.
```

---

## 10. What we are not building

- No email sending, sequencing, warmup, or outcome capture.
- No email guessing or SMTP probing.
- No direct LinkedIn scraping. Store actors only, where the vendor operates it.
- No proxy rotation or anti-detection. Needing it means the wrong source.
- No general-purpose crawler.
- No CRM.

## 11. Invariants

- Domain is the primary key.
- Signals are append-only events.
- Model output is validated against fetched text before persistence.
- Expensive operations are gated behind cheap filters.
- Every contact records where it came from.
- Suppression is applied even though we do not send.
