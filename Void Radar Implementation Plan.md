# Void Radar  
## Concise Step-by-Step Implementation Plan

## Phase 1 — Define the Foundation

Before development, define:

- Target company size
- Target regions
- Preferred startup stages
- Priority industries
- Void service categories
- Initial prospect scoring rules

Initial Void service categories:

```text
MVP Development
Web Application
Mobile Application
Dedicated Engineering Team
AI Integration
Backend Development
ERP / Internal Systems
Automation
Product Redesign
Website Development
```

---

# Phase 2 — Set Up the Core System

Create the project structure:

```text
void-radar/

├── backend/
├── frontend/
├── apify/
├── database/
└── workflows/
```

Recommended stack:

```text
Python        → backend and intelligence
FastAPI       → API
Supabase      → PostgreSQL/database
Apify         → scraping and crawling
Next.js       → Void Radar dashboard
n8n           → orchestration later
LLM API       → company and opportunity analysis
```

Create the main database tables:

```text
companies
founders
sources
source_records
research_runs
signals
opportunities
scores
contacts
```

---

# Phase 3 — Build One Trusted Discovery Source

Start only with:

```text
Y Combinator
```

Create an Apify Actor that collects:

```text
Company name
Founder
Website
Industry
Location
Batch / stage information
Source URL
```

Flow:

```text
YC
 ↓
Apify Actor
 ↓
Raw Records
 ↓
FastAPI
 ↓
Supabase
```

Do not build all trusted-source connectors yet.

---

# Phase 4 — Normalize and Resolve Companies

Normalize:

```text
Company names
Domains
Founder names
Locations
```

Then build entity resolution.

Example:

```text
Flow AI
FlowAI Ltd.
FlowAI Technologies
flowai.com
```

should become:

```text
Canonical Company:
FlowAI

Domain:
flowai.com

Sources:
YC
Techstars
etc.
```

Domain should be one of the strongest identifiers.

Uncertain matches should be flagged rather than automatically merged.

---

# Phase 5 — Build the Domain Resolver

If the source does not provide a reliable website:

```text
Company
 ↓
Web search
 ↓
Candidate domains
 ↓
Remove social/directories/news sites
 ↓
Rank candidates
 ↓
LLM if necessary
 ↓
Verify against company information
```

Store:

```text
domain
confidence
evidence
```

---

# Phase 6 — Build the Generic Company Researcher

Create one reusable Apify Actor:

```text
company-researcher
```

Input:

```text
company_id
domain
```

Research important pages only:

```text
Homepage
About
Product
Pricing
Customers
Careers
Blog
News
Team
Contact
```

Extract normal structured information with code first.

Examples:

```text
Emails
Links
Social profiles
Metadata
JSON-LD
Job links
Page titles
Dates
```

Use AI only for interpretation.

---

# Phase 7 — Create the Evidence Packet

Convert collected information into one structured research object.

Example:

```text
Company information
Founder information
Website content
Product information
Careers
Recent updates
Funding signals
Technical signals
Source URLs
```

Then pass this evidence packet to the AI system.

This reduces unnecessary LLM calls and improves reliability.

---

# Phase 8 — Build the Intelligence Layer

The AI engine should determine:

```text
What does the company do?

What stage is it in?

Who are its customers?

How technical is the product?

How strong is its technical capacity?

Is the company growing?

What important signals exist?

Could Void realistically help?
```

Keep three categories separate:

```text
Facts
Observations
Inferences
```

Every important inference should contain supporting evidence and confidence.

---

# Phase 9 — Build Signal Detection

Detect signals such as:

```text
Funding
Expansion
New customers
New partnerships
Hiring
Product launches
MVP development
New markets
Technical hiring
Direct request for developers/agencies
```

Store signals separately so that company history can be tracked later.

---

# Phase 10 — Build the Void Opportunity Engine

Compare the company evidence against Void's service taxonomy.

Example:

```text
Recently funded
+
Expanding internationally
+
Small visible engineering team
+
Software-heavy product
        ↓
Possible Opportunity:
Dedicated Engineering Team
```

Each opportunity should contain:

```text
Service
Confidence
Reasoning
Supporting evidence
```

Return only the best 1–3 opportunities.

---

# Phase 11 — Build Prospect Scoring

Initial scoring model:

```text
Company Fit             25%
Opportunity Strength    25%
Timing                   20%
Technical Capacity Gap   15%
Commercial Potential     10%
Source Confidence         5%
```

Output:

```text
Overall Prospect Score
+
Score breakdown
+
Reasons
+
Penalties
```

The score must always be explainable.

---

# Phase 12 — Complete the First End-to-End Pipeline

Before adding anything else, make this work:

```text
YC
 ↓
Apify Discovery
 ↓
Normalization
 ↓
Entity Resolution
 ↓
Supabase
 ↓
Domain Resolution
 ↓
Company Research
 ↓
Evidence Packet
 ↓
AI Analysis
 ↓
Signal Detection
 ↓
Opportunity Detection
 ↓
Prospect Score
 ↓
Supabase
```

Test first with:

```text
50 companies
```

Then:

```text
100–500 companies
```

---

# Phase 13 — Human Validation

Review the highest-ranked companies manually.

For each prospect record:

```text
Good prospect / Bad prospect
Opportunity correct / Incorrect
Company information correct / Incorrect
```

Measure:

```text
Precision@20
```

Example:

```text
16 useful prospects out of top 20
= 80% Precision@20
```

Use incorrect results to refine:

```text
Identity matching
Research
Opportunity detection
Scoring
```

---

# Phase 14 — Build the Void Radar Dashboard

Once prospect quality is acceptable, build the Next.js interface.

Main prospect list:

```text
Company
Founder
Industry
Location
Score
Top opportunity
Latest signal
```

Company detail page:

```text
Company profile
Founders
Sources
Signals
Technical capacity
Opportunities
Score breakdown
Supporting evidence
Research history
```

Also add human feedback.

---

# Phase 15 — Add More Trusted Sources

After the YC pipeline is stable, add:

```text
Techstars
Antler
Seedcamp
500 Global
```

Each new source should simply produce the same standardized company schema.

The intelligence pipeline should remain unchanged.

---

# Phase 16 — Add Signal-First Discovery

Introduce a second discovery path:

```text
Funding announcement
Product launch
Accelerator announcement
Industry news
Relevant public discussion
        ↓
Identify company/founder
        ↓
Entity resolution
        ↓
Void research pipeline
```

Final discovery model:

```text
Trusted Company Sources
          +
Signal Sources
          ↓
Candidate Companies
```

---

# Phase 17 — Add Automation

Introduce n8n when the pipeline becomes repetitive.

Use it for:

```text
Scheduled source collection
Triggering Apify Actors
Webhook processing
Research queues
High-score alerts
Failure notifications
```

Keep important business logic in Python.

---

# Phase 18 — Add Contact Enrichment

Only enrich strong prospects.

Example:

```text
Prospect Score > threshold
        ↓
Find decision maker
        ↓
Find professional contact
        ↓
Verify contact
```

Store:

```text
Contact
Role
Source
Verification
Confidence
Last checked
```

Do not enrich every discovered company.

---

# Phase 19 — Add Outreach Intelligence

For qualified prospects, generate an internal outreach thesis:

```text
Why is this company interesting?

What could Void offer?

Why might now be a good time?

Who should be approached?

What evidence supports the recommendation?
```

Keep outreach human-controlled initially.

---

# Phase 20 — Add Monitoring and Rescoring

Monitor promising companies for new signals.

Example:

```text
Funding
Hiring
Expansion
New product
New partnership
Major customer
```

When something changes:

```text
Old Score: 65

New funding detected

New Score: 79

Expansion detected

New Score: 87
```

Surface the company again in Void Radar.

---

# Phase 21 — Refine Using Real Sales Results

Once the BD team starts using the system, record:

```text
Contacted
Replied
Meeting booked
Proposal sent
Won
Lost
```

Analyze which:

```text
Sources
Industries
Company stages
Signals
Opportunity types
Regions
```

actually generate successful business.

Then update the prospect scoring model using real Void data.

---

# Final Architecture

```text
           DISCOVERY

 Trusted Sources     Signal Sources
       │                  │
       └────────┬─────────┘
                ▼
              APIFY
                ↓
        Raw Company Data
                ↓
         Normalization
                ↓
       Identity Resolution
                ↓
             Supabase
                ↓
        Domain Resolution
                ↓
      Apify Company Research
                ↓
         Evidence Packet
                ↓
      Python + LLM Intelligence
                ↓
      ┌─────────┼──────────┐
      ▼         ▼          ▼
   Signals  Technical   Opportunities
             Capacity
      └─────────┼──────────┘
                ▼
        Prospect Scoring
                ↓
             Supabase
                ↓
          Void Radar
                ↓
         Human BD Review
                ↓
      Contact Enrichment
                ↓
            Outreach
                ↓
        Outcome Feedback
                ↓
       Scoring Refinement
```

# Recommended MVP Boundary

The MVP should include only:

```text
One trusted source
        ↓
Apify discovery
        ↓
Normalization
        ↓
Identity/domain resolution
        ↓
Supabase
        ↓
Company research
        ↓
Evidence packet
        ↓
AI analysis
        ↓
Signal detection
        ↓
Opportunity detection
        ↓
Prospect scoring
        ↓
Simple dashboard
        ↓
Human evaluation
```

Only after this produces consistently useful prospects should we add more sources, contact enrichment, monitoring, and automation.

The main success criterion is simple:

> **When Void's BD team opens the top 20 prospects, most of them should genuinely look worth investigating.**