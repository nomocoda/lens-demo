# Atlas SaaS: Fictional Company Brief

**Purpose:** This is the synthetic data source the Lens Demo uses to generate dynamic Data Stories and ground chat conversations. It is **not** the persona document (that lives in `data/persona.md` and `data/voice-brief.md`). It is the *fictional company state*, the "data" Lens is reading from in the demo, in lieu of real client systems.

**How it gets used:** The Cloudflare Worker reads this document and includes it in every inference call that generates Data Stories or seeds a chat. The persona brief tells Lens *who Lens is*. This document tells Lens *what it currently sees about Atlas SaaS*.

**How to update:** Edit this file to evolve the demo's fictional company state. Cards regenerate automatically on the next visitor session (or after the localStorage cache expires). Stay internally consistent; contradictions in the brief produce contradictions in the cards.

**Last updated:** 2026-04-20. Recast for the VP of Marketing persona. Ops renamed to Product. Team and Market retired as domains; their signals redistributed into Marketing, Product, and Revenue.

---

## 1. Company snapshot

**Atlas SaaS, Inc.** is a mid-market B2B workflow-automation platform headquartered in Austin, Texas. Founded 2017, currently Series B ($28M raised to date). B2B SaaS company profile: 148 employees, $14.2M ARR, preparing Series C.

- **Headcount:** 148 (87 engineering, 24 sales/CS, 18 marketing, 12 G&A, 7 product)
- **ARR:** $14.2M (up from $9.8M 12 months ago; 45% YoY growth, decelerating from 62% last year)
- **Net revenue retention:** 112% (down from 118% two quarters ago)
- **Customers:** 340 paying accounts (up from 280 a year ago)
- **Product:** Atlas Workflow, a no-code workflow builder for mid-market ops, finance, and HR teams. Core value prop: replaces spreadsheet-and-email processes with automated, auditable workflows.
- **Connected systems Lens reads from (in the fiction):** HubSpot (marketing automation and CRM), Salesforce (opportunities, closed-won attribution), Google Analytics, LinkedIn Ads Manager, Google Ads, SEMrush, Mixpanel product analytics, Zendesk support, ProfitWell metrics, Slack, Notion, Google Workspace.

---

## 2. Atlas SaaS leadership team

Atlas is run by a small executive team and two co-founders. Each leader owns a functional domain. Lens describes the company and its leaders; who the current Lens user is, and what falls inside their seat, comes from the role declared in the operating instructions — not from this section.

**Sophie Zhang — VP of Marketing.** Owns demand gen, content, product marketing, brand, and growth. Reports to the CEO. Manages a team of 18. Primary systems: HubSpot, Salesforce (marketing views), Google Analytics, LinkedIn Ads, Google Ads, SEMrush. The marketing function is accountable for pipeline contribution (expected to source 30%+), CAC efficiency (blended CAC $18.2K, up from $14.8K), MQL-to-SQL conversion, content-influenced pipeline, competitive positioning against FlowStack, and GTM execution for Atlas Assist.

**Kevin O'Malley — VP of Sales.** Owns pipeline conversion and the revenue number. Leading the Ridgeline Health deal personally. Primary systems: Salesforce (opportunity and forecast views), Gong, Outreach. The revenue function is accountable for pipeline coverage, deal velocity, quota attainment, expansion, and rep-level performance. Source of truth for weighted pipeline dollar figures, coverage ratios, quota attainment, and the revenue forecast.

**Jess Wilder — Head of Product.** Owns the Atlas Assist roadmap and the platform rewrite timeline. Primary systems: Linear, Mixpanel, Notion. The product function is accountable for sprint velocity, defect rates, feature adoption, roadmap progress, deployment frequency, and incident signals. Source of truth for engineering capacity and release timing.

**Megan Park — CFO.** Approves function-level budgets. Tracks CAC payback and pipeline coverage for the board. Primary systems: NetSuite, ProfitWell, board reporting tooling. Source of truth for consolidated financial figures, ARR, burn, runway, and any figure shared with investors.

**Marco Reyes — Head of Customer Success.** Source of NPS data, reference account availability, and case study pipeline.

**Diana Okafor — Head of Support.** Top-ticket categories are content and in-app education signals. CSAT is tracked by Support but is not connected to Lens's data systems. Lens has no visibility into CSAT figures.

**Founders:**
- **CEO / Co-founder:** leading Series C prep. All VPs report to the CEO.
- **CTO / Co-founder (Daniel Choi):** leading the platform rewrite and Atlas Assist engineering alongside Jess.

**VP Engineering:** *Position open.* Rachel Navarro left three weeks ago. Interim leads Clara Mendes (backend) and Amir Haddad (frontend) are covering. Cross-functional impact: platform rewrite timing touches the GTM calendar, Atlas Assist launch, and release cadence.

**AE (mid-market): Priya Sharma.** Day-to-day owner of the Ridgeline Health deal.

---

## 3. Marketing team composition

Sophie's marketing org reports (the 18-person marketing function):
- **Director of Content:** runs the blog, SEO, long-form assets.
- **Director of Demand Gen:** owns paid channels, email nurture, campaign execution.
- **Head of Product Marketing:** owns launch briefs, sales enablement, competitive positioning.
- **Head of Brand and Events:** owns SaaStr and regional events, brand consistency, PR.
- **Content Marketing Manager:** role open 3 weeks. Backlog is accumulating; Atlas Assist launch content is at risk.

---

## 4. Marketing (Marketing domain material)

### Pipeline contribution

- **Marketing-sourced pipeline (Q1):** $1.24M weighted, 42% of total pipeline. B2B SaaS benchmark at Atlas's size is 25-40%; Atlas is running above.
- **Marketing-sourced pipeline (Q2, 11 days in):** $320K created, on pace for ~$1.1M by quarter close. That projects to 37% of total pipeline if Kevin's team scales outbound as planned.
- **Marketing-influenced pipeline:** 64% of closed-won deals touched marketing content before close. Benchmark is 30-50%. Atlas is content-heavy.
- **Top-of-funnel channel mix (last two quarters):** Inbound went from 18% to 35% of pipeline. Paid dropped from 41% to 28%. Events held flat at 18%. Outbound held at the remainder.

### CAC and channel economics

- **Blended CAC (Q1):** $18,200, up from $14,800 a year ago.
- **CAC payback:** 14 months, up from 11. Best-in-class B2B SaaS is under 18 months; Atlas is inside the window but trending the wrong way.
- **LTV:CAC:** 3.4x, down from 4.2x a year ago.
- **CAC by channel (Q1):**
  - Content and organic: $6,800 (down from $8,200)
  - LinkedIn Ads: $22,400 (up from $16,100)
  - Google Ads: $14,900 (flat)
  - Events: $28,600 (SaaStr and two regional conferences)
  - Partner referrals: $4,200 (small volume, best unit economics)
- **Channel ROI divergence:** The gap between content CAC and paid CAC was 2.4x six months ago. It's 3.3x now. Paid is not getting worse in absolute terms; content is getting better.

### Lead volume and conversion

- **MQLs (Q1):** 2,840 total, up 18% YoY.
- **MQL-to-SQL conversion:** 11.2%, down from 13.4% two quarters ago. Inside B2B SaaS benchmark of 10-15% but trending toward the floor.
- **SQL-to-closed-won:** 22% (stable).
- **Conversion by source (Q1):** Content leads convert to SQL at 17%. Paid leads convert at 7%. The gap is widening.

### Content-influenced pipeline

- **Top content asset by attribution:** The "Workflow Automation ROI Calculator" (launched 2023) touches 38% of all closed-won deals. No other single asset is above 11%. Redundancy is thin if the calculator's traffic changes.
- **Blog traffic (Q1):** 84,400 sessions, up 12% QoQ. Organic and SEO driving most of the growth.
- **Gated content conversion:** 6.8% visitor-to-MQL on the calculator page. Gated-tool benchmark is 4-6%.
- **Content gap:** No long-form content on Atlas Assist yet. Alpha is May 1. The Content Marketing Manager role has been open 3 weeks.

### Dark funnel and word-of-mouth

- **Closed-won deals with no attributed first touch (Q1):** 8 deals, $640K combined ARR. That's 22% of closed-won by count, 31% by revenue.
- **Self-reported source (post-close survey):** "Heard about Atlas from a peer" is 28% of new customers, up from 18% a year ago.
- **Community signal:** Atlas mentions on r/workflowautomation and LinkedIn (unprompted) are up 40% QoQ. No paid amplification driving it.
- **Attribution read:** 31% of revenue is coming from deals the model can't source. Either a working channel Atlas is underinvesting in, or a measurement gap.

### Competitive displacement

- **Competitive displacement rate (closed-won, last 90 days):** Atlas displaced FlowStack in 4 deals, displaced Workato in 2, replaced internal spreadsheet solutions in 11. Atlas lost 3 deals to FlowStack in the same window.
- **Win rate vs. FlowStack:** 57%, down from 62% six months ago.
- **Common reason cited in FlowStack losses:** Pricing (FlowStack is discounting aggressively) and FlowStack Copilot (launched 3 weeks ago).
- **Common reason cited in Atlas wins vs. FlowStack:** Time-to-value (Atlas onboards faster) and HIPAA BAA (FlowStack doesn't have one).

### GTM execution

- **Atlas Assist launch plan:**
  - May 1: Alpha internal demo (Jess leading)
  - May 15: External announcement (blog post, LinkedIn campaign, email to customer base)
  - June 10-12: SaaStr booth demo and CEO panel
  - June 15: Public beta to existing customers
- **GTM readiness signals (current):** Messaging brief 80% complete. Sales deck waiting on the alpha demo. Demo video not started. Launch blog post not started. No customer references yet (alpha hasn't happened). PR outreach started, 3 reporters briefed.
- **GTM execution velocity (historical):** The 2025 Workflow Templates launch took 18 days from announcement to first attributed pipeline. The 2024 SOC 2 launch took 9 days. Category benchmark for a launch like this is 10-14 days.

### Target accounts and ABM

- **ABM program (launched Q4 2025):** 80 target accounts. 42% have had at least one marketing touch. 18% have had a sales-qualified conversation. 3 have closed-won.
- **Target-account engagement signals (last 30 days):**
  - Pricing-page visits from target accounts: 14 accounts, up from 6 last month
  - Whitepaper downloads from target accounts: 9, up from 4
- **Tier 1 target accounts in active pipeline:** 11 of 20. Ridgeline Health is the largest.

### Reference customers and case studies

- **Published case studies (last 12 months):** 6. Two feature NexGen Financial. Gaps in healthcare, construction, and education verticals.
- **Reference customer requests (Q1):** 22. Declined 6 due to lack of available accounts in the requested vertical.
- **Case study pipeline:**
  - NexGen Financial expansion write-up (Q2 publish)
  - Sagebrush Media (awaiting legal approval)
  - Ridgeline Health (holding on close)

### Campaigns and content in flight

- **LinkedIn Ads spring campaign:** $42K committed. 4.2% CTR (above benchmark). CAC running at $21K, above blended target.
- **Content calendar (next 30 days):** 4 blog posts (2 AI-themed for Atlas Assist warm-up), 1 long-form guide on workflow ROI, 1 webinar co-hosted with HubSpot's integration team.
- **SaaStr panel prep:** CEO is preparing "Workflow Automation in the AI Era." Sophie is writing talking points and positioning.
- **Atlas Assist PR outreach:** 3 reporters briefed. Coverage targeted for May 15.

---

## 5. Revenue (Revenue domain material)

Revenue-domain signals for Atlas SaaS. Raw P&L consolidation lives with Megan (Finance). Pipeline, conversion slices, and unit economics below are the revenue-domain figures Atlas systems expose. Which of these figures a given role can surface is governed by the role's scope in the operating instructions — not declared here.

### Pipeline health

- **Q2 new ARR target:** $1.4M (company-wide).
- **Pipeline coverage:** 2.1x ($2.94M weighted against $1.4M target). Benchmark is 3-4x.
- **Marketing-sourced slice of Q2 pipeline:** $890K weighted, 30% of total.
- **Gap to target:** $980K, of which Ridgeline Health ($380K) is the marquee deal.
- **Q1 actual new ARR:** $980K (target was $1.1M, 89% of plan).
- **Q1 churned ARR:** $340K.

### Deal velocity

- **Median deal cycle (mid-market, Q1):** 68 days, up from 52 days last quarter. Procurement is adding review steps across the category.
- **Marketing-sourced deals cycle faster:** 58 days median, vs. 74 days for outbound-sourced. Content-warmed leads close quicker.
- **Sales capacity:** 4 mid-market AEs, 1 enterprise AE (Kevin). Pipeline-to-rep ratio is within norms.

### Revenue mix (positioning and case study angles)

- **Self-serve and SMB:** 38% of ARR. Low growth (market saturating).
- **Mid-market:** 54% of ARR. The engine.
- **Enterprise:** 8% of ARR (3 accounts). Series C story depends on this segment growing.

### Growth from existing customers

- **Net revenue retention:** 112% (down from 118% two quarters ago).
- **Expansion pipeline (next 90 days):** $420K across 11 accounts. Heavily weighted toward NPS 9-10 accounts (these expand at 2.3x the rate of NPS 7-8 accounts).
- **Renewal risk:** Prism Analytics ($165K ARR, renewal May 16). Champion departed in March; usage down 30%.
- **Reference marketing angle:** NexGen Financial expanded twice; case study refresh is in production.

### Series C context

- **Board expectation:** $20M ARR exit rate by December.
- **Growth-investor thresholds (B2B SaaS, $10-20M ARR):** 40%+ growth, 110%+ NRR, clear path to $30M ARR.
- **Marketing's role in diligence:** Pipeline contribution trajectory and CAC payback are the metrics investors will ask about.

---

## 6. Customers (Customers domain material, Marketing lens)

Customer signals the VP of Marketing watches: reference pool, NPS cohorts, case study readiness, expansion readiness.

### Top 10 accounts by ARR

1. **NexGen Financial:** $420K ARR. Fintech. 2-year customer, expanded twice. Power user. Strongest case study asset; ready for a third write-up.
2. **Ridgeline Health:** $380K ARR, in active sales cycle. Would be Atlas's largest enterprise logo and first healthcare reference. If it closes: priority case study, SaaStr panel anchor, major content push.
3. **Tidewater Insurance:** $310K ARR. Enterprise. Signed 6 months ago. Onboarding took 14 weeks vs. the 6-week target. Not case-study-ready; Marco has a rescue plan.
4. **Clearpath Logistics:** $180K ARR. Logistics. Healthy, low-touch. Renewal in 90 days. Possible case study.
5. **Prism Analytics:** $165K ARR. Mid-market analytics. Renewal in 34 days. Usage down 30%; champion left. Reference unlikely.
6. **Sagebrush Media:** $142K ARR. Media and publishing. 18-month customer. Stable. Case study in legal review.
7. **Halcyon Brands:** $128K ARR. D2C retail. Health unclear; support tickets up 40%, usage flat.
8. **Ironclad Construction:** $115K ARR. Construction. Uses Atlas for procurement workflows only; their HR team has expressed interest (expansion and campaign opportunity).
9. **Northwind Education:** $98K ARR. EdTech. Small but strategic; CEO relationship.
10. **Verdant Agriculture:** $87K ARR. AgTech. Healthy. Quiet account.

### NPS cohorts

- **Trailing 90-day NPS:** 38 (down from 46 six months ago).
- **NPS by segment:** SMB: 42, Mid-market: 36, Enterprise: 28.
- **NPS 9-10 accounts:** 47. Expansion rate is 2.3x higher than NPS 7-8 accounts. Primary pool for reference asks.
- **NPS 0-6 accounts:** 18. Tidewater and Halcyon are in this cohort.

### Recent churn (last 90 days)

- **Beacon Logistics:** $72K ARR. Cited "lack of enterprise features." Those features are on the platform rewrite (June 15 beta). Messaging angle for competitive content.
- **FreshCart:** $48K ARR. Acquired; new parent standardized on a competitor tool.
- **Two SMB accounts:** $31K combined. Price sensitivity.

### Active pipeline (marketing-relevant)

- **Ridgeline Health, $380K:** Enterprise healthcare. Close expected end of April. Major content and PR moment if it lands.
- **Meridian Corp, $220K:** Mid-market fintech. Went quiet 2 weeks ago. Kevin suspects a FlowStack evaluation. Competitive content may help.
- **Apex Partners, $160K:** Mid-market consulting. Discovery stage. Strong ICP fit.
- **CityGrid Municipal, $95K:** Government. FedRAMP is a gate (Atlas doesn't have it; not on roadmap).
- **Three SMB inbounds:** $45K combined. Standard self-serve motion.

---

## 7. Product (Product domain material, Marketing lens)

Product signals the VP of Marketing watches: launch readiness, feature adoption as content signal, GTM calendar anchors, support-ticket concentration as messaging signal.

### Atlas Assist (the GTM headline feature)

- **Status:** Alpha, internal demo May 1.
- **Public launch plan:** May 15 announcement, June 15 public beta.
- **Product marketing deliverables outstanding:** Messaging brief 80% complete, sales deck waiting on alpha, demo video not started, launch blog post not started, customer reference pending beta.
- **Strategic frame:** Board sees Atlas Assist as the enterprise wedge. FlowStack Copilot launched 3 weeks ago; the "first" window is closed, the "best" window is open for another 6 months.

### Platform rewrite ("Atlas 2.0")

- **Status:** 62% complete. Beta target June 15.
- **Enterprise features unlocked by the rewrite:** Custom RBAC, audit logs, API controls. Exact features Beacon cited when churning.
- **GTM dependency:** Atlas Assist demo runs on the new architecture. If the rewrite slips, the May 1 alpha slips, and the announcement calendar slips with it.
- **Engineering signal (internal):** Clara Mendes flagged zero test coverage on the auth module. She's surfacing it to Daniel this week.

### Feature adoption (launch-quality signal)

- **2025 Workflow Templates launch:** 48% of active users engaged with 3+ templates within 60 days. Above the 40% benchmark for a strong launch.
- **2025 Native Integrations launch (Slack, HubSpot, Salesforce):** 31% adoption in first 30 days. Below benchmark; integration onboarding was cited as friction.
- **Adoption-retention correlation:** Single-feature users churn at 2.4x the rate of multi-feature users.

### Product-adjacent marketing signals

- **NPS 38:** Primary source of reference-customer willingness.
- **Top feature requests (by vote):** Custom RBAC (94), Workflow versioning (71), Native Salesforce integration (63). All either in rewrite or on roadmap.
- **Trial-to-paid conversion:** 8.2%, down from 9.7%. Sophie's hypothesis is onboarding UX, not lead quality. Supports the content-over-paid budget read.
- **Support ticket volume up 28% QoQ:** "Workflow builder UX confusion" is 34% of tickets. Content and in-app education opportunity.
- **Tidewater Insurance ticket concentration:** 3x normal volume, onboarding-related. Not case-study-ready.

### GTM calendar anchors (next 90 days)

- **End of April:** Ridgeline Health decision
- **May 1:** Atlas Assist alpha demo (internal)
- **May 15:** Atlas Assist external announcement
- **May 16:** Prism Analytics renewal decision
- **June 10-12:** SaaStr Annual (booth, CEO panel, Atlas Assist demo)
- **June 15:** Platform rewrite beta and Atlas Assist public beta

---

## 8. Recent activity (the "last 7 days" feel)

### Slack snippets

- **Sophie Zhang** (3 days ago, 10:30 AM, #marketing): *"CAC report for Q1 is in. $18.2K, up from $14.8K a year ago. Paid is getting expensive. I want to shift budget toward content and community; need to talk through it."*
- **Sophie Zhang** (yesterday, 2:15 PM, #marketing): *"Inbound hit 35% of pipeline this quarter. First time over 30%. Content engine is working."*
- **Kevin O'Malley** (2 days ago, 11:15 AM, #sales): *"Ridgeline update: their CISO wants a call about data residency. Priya is coordinating. If we land this, Sophie, you'll have the healthcare case study you've been asking for."*
- **Marco Reyes** (today, 9:22 AM, #customer-success): *"Prism Analytics usage dropped another 14%. Champion left in March. Renewal May 16. Sophie, taking them off the case study shortlist."*
- **Diana Okafor** (yesterday, 3:10 PM, #support): *"Workflow builder UX tickets are 34% of volume. If content or in-app education can address this, ticket pressure drops."*
- **Jess Wilder** (4 days ago, 5:20 PM, #product): *"Atlas Assist alpha on track for May 1. Sophie, I'll send the updated messaging doc tomorrow. We need to decide on external positioning by Friday for PR outreach."*
- **Daniel Choi** (yesterday, 6:02 PM, #engineering): *"Rewrite 62% complete. Auth and billing integration are the remaining lifts. June 15 is tight but doable. Sophie, keep the GTM calendar honest."*
- **Megan Park** (4 days ago, 2:45 PM, #leadership): *"Q1 close: $14.2M ARR. Marketing-sourced pipeline was 42% in Q1. Series C investors will want to see that trend hold."*

### Open marketing decisions (Sophie's queue)

- **Budget reallocation:** Shift spend from paid to content and community? Signal points to yes (content CAC 3.3x better), but reducing paid reduces top-of-funnel volume. Decision needed before May campaign planning.
- **Content Marketing Manager hire:** Role open 3 weeks. Atlas Assist launch needs 4+ content pieces before May 15. Every week without a hire compresses the runway.
- **Ridgeline Health PR contingency:** Draft the announcement now or wait for signed contract? Kevin says "it's real"; legal says "not until signed." Decision needed this week.
- **Competitive response to FlowStack Copilot:** Direct comparison content, or let Atlas Assist speak for itself? Jess is leaning toward the latter.
- **Reference customer capacity:** 22 reference requests in Q1, 6 declined. Expand the pool or tighten criteria?

---

## 9. Cross-domain connections (examples of the "interesting" cards)

These are not pre-written cards. They're examples of the kinds of cross-domain connections worth surfacing for a VP of Marketing. Listed as patterns to look for.

- **Content CAC pulling away from paid CAC ↔ budget reallocation decision:** Content is 3.3x more efficient than paid on CAC. Shifting budget moves the blended number down; keeping the mix holds top-of-funnel volume. One budget decision determines next quarter's channel mix.

- **Pipeline contribution trajectory ↔ Series C diligence:** Marketing-sourced share was 42% in Q1, trending toward 37% in Q2 if sales scales outbound as planned. Investors index on marketing efficiency at this stage. The trajectory matters more than the absolute number.

- **Atlas Assist launch ↔ platform rewrite timeline ↔ SaaStr panel:** Three interlocking dates. If the rewrite slips, the May 1 alpha slips, the May 15 announcement slips, the SaaStr panel loses its demo. One engineering timeline shapes the entire GTM quarter.

- **FlowStack Copilot launch ↔ win rate vs. FlowStack ↔ Atlas Assist positioning:** Win rate against FlowStack dropped from 62% to 57% after Copilot shipped. Atlas Assist is the messaging response. Positioning is the lever.

- **Word-of-mouth growth ↔ attribution gap ↔ budget allocation:** 31% of closed-won revenue has no first-touch attribution. Community mentions up 40% QoQ. Either a working channel Atlas is underinvesting in, or a measurement gap. The diagnosis drives the action.

- **Content asset concentration ↔ channel fragility:** The ROI calculator touches 38% of closed-won deals. No other single asset is above 11%. One page carries a disproportionate share of pipeline sourcing.

- **Ridgeline Health close ↔ healthcare vertical strategy ↔ case study pipeline:** Ridgeline would be the healthcare reference anchor. Without it, the healthcare push has no proof point for the panel or the campaign.

- **Trial-to-paid decline ↔ ticket concentration ↔ content opportunity:** Conversion down 15%, "workflow builder UX confusion" is 34% of tickets. Same root cause. In-app education or content could address both.

- **NPS 9-10 cohort ↔ expansion pipeline ↔ reference pool:** 47 accounts in the top NPS tier. Expansion pipeline is concentrated there. Same accounts are the reference pool. Marketing and CS are drawing from the same well.

- **Content Marketing Manager vacancy ↔ Atlas Assist launch runway:** Role open 3 weeks. Atlas Assist launch content is 4+ pieces. Every week without a hire narrows the runway.

---

## 10. Card generation guidance

- **Stay neutral.** Signals are not classified as risks, opportunities, or trends. The card surfaces what's happening. The reader applies their own judgment. Never frame a card as a warning or a win.
- **Vary the time horizon.** Mix urgent (this week), 30-day, and quarter-out so the feed feels like continuous monitoring, not an alert dump.
- **Lead with what only a VP of Marketing can act on.** Tactical execution details belong in a team standup, not the VP's card feed. If a card could be handled by a director without VP involvement, it's probably the wrong card.
- **Use specific numbers and names.** Generic observations are useless. Specific observations (accounts, channels, percentages, benchmarks) are the value.
- **Surface, don't decide.** The card makes the situation legible. The decision is the VP's to make. The card never recommends, prescribes, or directs action.
- **Cross-domain connections are the highest-value cards.** Marketing ↔ Revenue, Marketing ↔ Product, Marketing ↔ Customers. Show the connections a department head can't see alone.
- **Stay grounded in this document.** Do not invent new people, accounts, or vendors. The fictional company is bounded by what's here.

### Language register — use

pipeline contribution, demand gen efficiency, CAC payback, MQL volume, MQL-to-SQL conversion, channel ROI, content-influenced pipeline, dark funnel, GTM execution velocity, competitive displacement rate, growth from existing customers.

### Language register — never

- "expansion revenue" → use "growth from existing customers"
- "opportunity" or "risk" as Signal labels → Signals are neutral
- "implementation gap" → rephrase without this term
- em dashes anywhere → restructure the sentence

---

## 11. Future expansions to this brief

When this brief gets richer, the cards get richer. Areas to expand later:
- Cohort-level analysis by acquisition channel and vintage
- Multi-touch attribution detail (first-touch vs. weighted-touch)
- Campaign-level performance history
- Deeper competitive intelligence on FlowStack, Workato, and emerging entrants
- Target-account detail (industry, intent signals, engagement scores)
- Reference customer availability matrix (vertical, use case, status)
- Product usage telemetry by feature and cohort
