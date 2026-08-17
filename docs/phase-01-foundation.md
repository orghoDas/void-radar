# Void Radar Phase 1 Foundation

This document defines the first operating assumptions for Void Radar before
implementation begins. These choices are intentionally narrow so the first YC
pipeline can be judged by prospect quality before adding more sources,
automation, contact enrichment, or outreach.

## 1. Product Objective

Void Radar helps Void Studio identify companies worth investigating for
business development.

External sources answer:

```text
Who should we investigate?
```

Void Radar answers:

```text
Why should Void care about this company?
```

The MVP should produce a ranked set of prospects where the top 20 companies are
genuinely worth manual review by Void's BD team.

## 2. Initial ICP

### Target Company Size

Primary target:

```text
Mid-market companies
Large companies
```

Secondary target:

```text
Funded startups only when they show clear enterprise, platform, or growth potential
```

Reasoning:

- Mid-to-large companies are more likely to have meaningful budgets, complex
  workflows, internal systems, integration needs, and ongoing delivery demand.
- Larger organizations are stronger fits for dedicated teams, ERP/internal
  systems, automation, customer portals, backend/API work, and AI integration.
- Small startups should not dominate discovery unless there is strong evidence
  of budget, growth, urgency, or a high-value product opportunity.

### Target Regions

Initial priority regions:

```text
United States
European Union
United Kingdom
Rest of Europe
```

Region handling:

- Prefer companies with English-language websites or English public material.
- Keep location as evidence, not as a hard exclusion unless it creates an
  operational barrier.
- Store city, country, and source-provided location separately when available.

### Preferred Startup Stages

Primary stages:

```text
Any stage, if the company matches Void's target size, region, and service fit.
```

Secondary stages:

```text
Recently funded
Recently expanded
Recently launched a new product
Hiring or scaling a technical/product team
Modernizing operations or internal systems
```

Lower priority:

```text
Dormant company
Company with no recent public activity
Company with no visible service fit for Void
```

### Priority Industries

Priority industries are derived from Void's public website and portfolio so the
system matches Void's actual positioning, services, and case-study language.

Source reviewed:

```text
https://www.voidstudio.tech/
https://www.voidstudio.tech/portfolio
```

Website-derived positioning:

```text
Validated digital products
Strategic design and development
AI-powered validation
UX/UI design
Full-stack development
MVP development
Product growth
Launch support
Dedicated product teams
Landing pages
Full system development
Internal systems and automation
```

High-priority industries and company categories:

```text
B2B SaaS
FinOps and financial platforms
Logistics and operations platforms
E-commerce and retail technology
Marketplaces
AgriTech and food supply-chain platforms
EdTech, learning platforms, and exam systems
LegalTech and professional-services workflow tools
HealthTech and wellness technology
Real estate, construction, and property technology
Travel and hospitality technology
AI-enabled consumer or business applications
Internal operations, admin dashboards, and business systems
```

Medium priority:

```text
Restaurants, cafes, and food brands needing conversion-focused web presence
Consumer apps with strong product or AI angle
D2C brands needing e-commerce or web experience improvements
Bookshops, grocery, and inventory-heavy commerce businesses
Banking or fintech landing pages and product surfaces
```

Lower priority unless strong evidence exists:

```text
Pure content businesses
Local offline services
Agencies or consultancies
Hardware-only companies
Crypto projects without a clear product/business case
Highly regulated businesses with no software delivery angle
```

Cross-industry service-fit signals:

```text
Complex internal workflows
Customer or partner portal needs
Software-heavy operations
Backend/API integration needs
Legacy system modernization
Automation opportunities
AI validation or AI integration opportunities
Product redesign or web application needs
Dedicated engineering capacity needs
Launch, growth, or conversion support needs
```

## 3. Void Service Taxonomy

Use controlled internal service IDs. The AI should map opportunities into these
categories instead of inventing new service names.

| Service ID | Label | When it is relevant |
|---|---|---|
| `MVP` | MVP Development | Early company needs to build or validate a first product. |
| `WEB_APP` | Web Application | Browser-based product, SaaS, portal, dashboard, or workflow app. |
| `MOBILE_APP` | Mobile Application | Mobile-first customer, field, marketplace, or consumer workflow. |
| `DEDICATED_TEAM` | Dedicated Engineering Team | Company has growth/funding/product demand but limited visible engineering capacity. |
| `AI_INTEGRATION` | AI Integration | Product or workflow could benefit from practical LLM, automation, data extraction, search, or decision support. |
| `BACKEND` | Backend Development | APIs, services, integrations, data models, auth, or reliability work are likely needed. |
| `API` | API Development | Public/private API, integrations, partner connectivity, or platform extension is central. |
| `ERP` | ERP/Internal Systems | Operations, inventory, finance, procurement, or internal business system need is visible. |
| `INTERNAL_PORTAL` | Internal Portal | Staff/admin operations would benefit from a structured internal interface. |
| `CUSTOMER_PORTAL` | Customer Portal | Customers need self-service, onboarding, reporting, orders, bookings, or account workflows. |
| `MARKETPLACE` | Marketplace | Multi-sided supply/demand product, vendor onboarding, payments, trust, or listing workflows. |
| `AUTOMATION` | Automation | Manual, repetitive, document-heavy, or cross-tool business workflows are likely. |
| `PRODUCT_REDESIGN` | Product Redesign | Product/site exists but positioning, UX, conversion, or usability appears weak. |
| `WEBSITE` | Website Development | Company needs a credible marketing site, conversion path, or launch-ready presence. |

Opportunity rules:

- Return only the best 1-3 opportunities per company.
- Each opportunity must include confidence, reasoning, and supporting evidence.
- Do not recommend a service only because it is in Void's catalog.
- Prefer a smaller number of strong opportunities over broad speculation.

## 4. Prospect Types

Void Radar should classify prospects into one or more of these types.

| Type | Meaning | Example signals |
|---|---|---|
| `DIRECT_INTENT` | The company is explicitly asking for help. | Hiring developers, asking for agency, looking for MVP partner. |
| `TRIGGER` | A recent event makes timing stronger. | Funding, launch, expansion, partnership, hiring, major customer. |
| `OPPORTUNITY` | Evidence suggests Void could help even without stated intent. | Software-heavy business, weak product surface, small team, operational complexity. |
| `ENGAGEMENT` | Founder/company activity suggests relevance but weak buying intent. | Public discussions, community activity, relevant posts. |

Engagement should be treated as a weak supporting signal, not proof of intent.

## 5. Initial Scoring Model

Use a simple explainable weighted score for the MVP.

| Component | Weight | What it measures |
|---|---:|---|
| Company Fit | 25% | ICP match across stage, industry, geography, product type, and company size. |
| Opportunity Strength | 25% | How realistic and valuable the top Void opportunity appears. |
| Timing | 20% | Whether recent events make outreach or investigation timely. |
| Technical Capacity Gap | 15% | Whether the company may need external technical/product capacity. |
| Commercial Potential | 10% | Likely budget, urgency, growth upside, and deal value. |
| Source Confidence | 5% | Reliability and completeness of source, domain, and research evidence. |

Final output must include:

```text
overall_score
component_scores
positive_reasons
penalties
model_version
calculated_at
```

Initial model version:

```text
prospect_score_v0.1
```

### Component Score Guidance

Use a 0-100 score for each component.

Company Fit:

- 90-100: Strong match across stage, industry, geography, product type, and size.
- 70-89: Good match with one missing or uncertain dimension.
- 40-69: Possible but not clearly aligned.
- 0-39: Poor ICP match or important exclusion concern.

Opportunity Strength:

- 90-100: Clear service opportunity with multiple supporting facts/signals.
- 70-89: Plausible opportunity with adequate evidence.
- 40-69: Weak or speculative opportunity.
- 0-39: No credible Void service opportunity.

Timing:

- 90-100: Recent strong trigger such as funding, launch, expansion, or urgent hiring.
- 70-89: Some recent growth or product signal.
- 40-69: Company looks active but timing is unclear.
- 0-39: Dormant, stale, or no timing evidence.

Technical Capacity Gap:

- 90-100: Software-heavy company with weak visible delivery capacity and active need.
- 70-89: Some gap between product ambition and visible capacity.
- 40-69: Capacity unclear.
- 0-39: Strong internal capacity or no technical product need.

Commercial Potential:

- 90-100: Strong budget likelihood and high-value project potential.
- 70-89: Reasonable budget and project size.
- 40-69: Small or uncertain commercial value.
- 0-39: Very low likely budget or poor deal fit.

Source Confidence:

- 90-100: Official source and verified domain with strong evidence.
- 70-89: Reliable source but some missing details.
- 40-69: Partial or ambiguous evidence.
- 0-39: Unverified, conflicting, or low-quality source data.

## 6. Exclusion Criteria

Exclude or heavily down-rank companies when evidence shows:

- No identifiable official company domain.
- Company appears inactive, closed, acquired beyond relevance, or abandoned.
- Business is outside Void's likely delivery capacity.
- Company is a direct agency/consultancy competitor with no partnership angle.
- The only available evidence is from low-quality directories or copied content.
- Opportunity would require unauthorized scraping, spam, or questionable data use.
- Business model is primarily illegal, deceptive, adult, gambling, or high-risk
  financial promotion.
- Product is hardware-only with no meaningful software/product/service angle.
- Company has a very large mature internal engineering organization and no clear
  external delivery gap.

Do not hard-exclude based only on:

- Low public GitHub activity.
- Missing founder social profile.
- Small team size.
- Absence of contact information.
- Weak marketing site if other evidence suggests strong opportunity.

## 7. Provenance and Evidence Rules

Every important claim must be represented as one of:

```text
FACT
OBSERVATION
INFERENCE
RECOMMENDATION
```

Important facts should keep:

```text
value
source
source_url
collected_at
confidence
```

Rules:

- Never mix facts and AI inferences in the same field.
- Preserve raw source records.
- Preserve source URLs.
- Store content hashes for researched pages when available.
- Keep model and scoring versions with generated analysis.
- Make ingestion idempotent.

## 8. Phase 1 Acceptance Criteria

Phase 1 is complete when the repo contains:

- A documented initial ICP.
- A controlled Void service taxonomy.
- Initial prospect types.
- Explainable scoring weights and component guidance.
- Initial exclusion and down-ranking criteria.
- Evidence/provenance rules for later implementation.

## 9. Open Decisions for Void

These should be confirmed after early testing or before scaling beyond the first
YC batch.

| Decision | Current default | Why it matters |
|---|---|---|
| Minimum useful company size | Mid-market | Keeps discovery focused on companies with stronger budget and operational complexity. |
| Maximum target company size | Large company allowed | Enterprise and larger companies may be strong fits for systems, automation, portals, and dedicated teams. |
| Priority region order | USA, Europe | Impacts scoring and source filters. |
| Priority industries | Website-derived initial list | Refine after Precision@20 review shows which categories produce useful prospects. |
| Startup stage preference | Any stage | Stage should matter less than company size, service fit, timing, and evidence. |
| Highest-priority services | `DEDICATED_TEAM`, `MVP`, `WEB_APP`, `AI_INTEGRATION`, `AUTOMATION` | Impacts opportunity scoring. |
| Regulated industries | Allow with caution | Impacts fintech, healthtech, insurtech scoring. |
| Contact enrichment threshold | Not part of MVP | Should be decided only after Precision@20 validation. |
