# Atlas SaaS: Fictional Company Brief

**Purpose:** This is the synthetic data source the Lens Demo uses to generate dynamic Data Stories and ground chat conversations. It is **not** the persona document (that lives in `nomocoda/lens-voice`). It is the *fictional company state*, the "data" Lens is reading from in the demo, in lieu of real client systems.

**How it gets used:** The Cloudflare Worker reads this document and includes it in every inference call that generates Data Stories or seeds a chat. The persona brief tells Lens *who Lens is*. This document tells Lens *what it currently sees about Atlas SaaS*.

**How to update:** Edit this file to evolve the demo's fictional company state. Cards regenerate automatically on the next visitor session (or after the localStorage cache expires). Stay internally consistent; contradictions in the brief produce contradictions in the cards.

**Last updated:** 2026-04-12. Rewritten from Acme Industrial to tech/SaaS theme.

---

## 1. Company snapshot

**Atlas SaaS, Inc.** is a mid-market B2B workflow-automation platform headquartered in Austin, Texas. Founded 2017, currently Series B ($28M raised to date). CEO and co-founder has led the company since inception.

- **Headcount:** 148 (87 engineering, 24 sales/CS, 18 marketing, 12 G&A, 7 product)
- **ARR:** $14.2M (up from $9.8M 12 months ago; 45% YoY growth, decelerating from 62% last year)
- **Gross margin:** 78% (target is 80%, weighed down by professional services revenue mix)
- **Net revenue retention:** 112% (down from 118% two quarters ago)
- **Cash on hand:** $11.3M
- **Burn rate:** $620K/mo (18 months of runway at current burn)
- **Customers:** 340 paying accounts (up from 280 a year ago)
- **Product:** Atlas Workflow, a no-code workflow builder for mid-market ops, finance, and HR teams. Core value prop: replaces spreadsheet-and-email processes with automated, auditable workflows.
- **Connected systems Lens reads from (in the fiction):** HubSpot CRM, Stripe billing, Mixpanel analytics, Slack, Linear (eng project management), Greenhouse (recruiting), Notion (docs/wiki), Google Workspace, Zendesk support, ProfitWell metrics, and the internal admin dashboard.

---

## 2. The CEO (the Lens user in this demo)

The demo persona is **the CEO of Atlas SaaS**. No name, no headshot. Just the role. The CEO is the one Lens is talking to in chat, the one whose perspective shapes which insights surface as cards.

**What this CEO cares about, in priority order:**
1. Closing the Series C process without distraction killing Q2 execution
2. Landing the Ridgeline Health deal, which would be the company's first enterprise logo and proof of upmarket readiness
3. Net revenue retention trending down; churn is quiet but persistent
4. Engineering velocity and whether the platform rewrite is on track for the June beta
5. The VP Engineering departure and whether the interim structure holds
6. Pipeline coverage for H2; the board wants to see $20M ARR exiting the year
7. Long-term: whether the AI copilot feature (Atlas Assist) can be the wedge into enterprise

**What the CEO doesn't want from Lens:**
- Dashboard regurgitation. The CEO already has Mixpanel and ProfitWell. Lens should surface what's *between* the dashboards, not restate them.
- Action items dressed up as questions ("what would you like to focus on?"). The CEO came to Lens to get lift, not to be quizzed.
- Pretending to know things it doesn't. The CEO will trust Lens more for one honest "I don't have access to that" than for ten plausible-sounding fabrications.

---

## 3. Org structure (key people Lens references by name)

- **CEO:** the user
- **CFO:** Megan Park, joined 8 months ago from a late-stage fintech, running Series C prep and board reporting
- **CTO / Co-founder:** Daniel Choi, technical co-founder, leading the platform rewrite personally
- **VP Engineering:** *Position open.* Rachel Navarro left 3 weeks ago. Two interim eng leads (Clara Mendes, backend; Amir Haddad, frontend) are covering.
- **VP Sales:** Kevin O'Malley, hunter, two years in role, leading the Ridgeline Health deal personally
- **VP Marketing:** Sophie Zhang, owns demand gen and brand, worried about the CAC trend
- **Head of Product:** Jess Wilder, sole PM, responsible for both the existing product and the Atlas Assist roadmap
- **Head of Customer Success:** Marco Reyes, managing a 340-account book with a team of 6. Stretched thin.
- **Head of Support:** Diana Okafor, runs a Zendesk-based support org. CSAT has been slipping.
- **Director of People Ops:** Alex Tan, handles recruiting, culture, and retention
- **Senior Engineer (staff-level):** Nina Volkov, highest-IC engineer, key to the platform rewrite, being recruited by Stripe
- **AE (mid-market):** Priya Sharma, owns the Ridgeline Health deal day-to-day under Kevin

---

## 4. Financial state (Revenue domain material)

### Q1 actuals (closed 7 days ago)
- **New ARR added:** $980K (target was $1.1M, 89% of plan)
- **Churned ARR:** $340K (largest single churn: Beacon Logistics, $72K, cited "lack of enterprise features")
- **Net new ARR:** $640K
- **ARR exiting Q1:** $14.2M
- **Gross margin:** 77.8%
- **Burn:** $1.86M for the quarter ($620K/mo)

### Q2 (in progress, 11 days into the quarter)
- **Q2 new ARR target:** $1.4M (the board plan ramps up quarterly)
- **Pipeline coverage:** 2.1x ($2.94M weighted pipeline against $1.4M target; industry benchmark is 3-4x)
- **Currently committed:** $420K from deals in contract stage
- **Gap to target:** $980K, of which Ridgeline Health ($380K ARR) is the marquee deal
- **Risk to Q2:** Pipeline coverage is thin, and the two largest mid-market deals are stalling

### Revenue mix
- **Self-serve / SMB:** 38% of ARR, healthy but low growth (market is saturating)
- **Mid-market:** 54% of ARR, the growth engine, but deal cycles are lengthening
- **Enterprise:** 8% of ARR (3 accounts), where the Series C story lives
- **Professional services:** $1.1M TTM (margins are 22%, dragging blended gross margin below 80%)

### Unit economics
- **CAC:** $18,200 (up from $14,800 a year ago; Sophie is worried)
- **LTV:** $62,000 (stable)
- **LTV:CAC ratio:** 3.4x (down from 4.2x, still healthy but trending the wrong way)
- **Payback period:** 14 months (up from 11)

### Series C process
- **Status:** Early conversations with 4 firms. Term sheet target: end of Q2.
- **Target raise:** $40-50M at $180-220M pre-money
- **Board expectation:** $20M ARR exit rate by December to justify the valuation
- **Megan's concern:** Net revenue retention decline could spook growth-stage investors. She wants it back above 115% before the roadshow.

---

## 5. Customers (Customers domain material)

### Top 10 accounts by ARR

1. **NexGen Financial:** $420K ARR. Fintech. 2-year customer, expanded twice. Healthy. Uses Atlas across ops, compliance, and onboarding teams. Power user, generates most of Atlas's case studies. Account owner: Kevin.

2. **Ridgeline Health:** **$380K ARR, in active sales cycle.** Healthcare SaaS. Would be Atlas's largest enterprise logo. They need SOC 2 Type II (Atlas has it), HIPAA BAA (Atlas has it), and SSO/SCIM (Atlas has it as of last quarter). Decision expected by end of April. Priya Sharma is day-to-day. **Blocker:** Their IT security team wants an on-prem data residency option Atlas doesn't have. Kevin is positioning the new AWS GovCloud deployment (shipping May) as the answer.

3. **Tidewater Insurance:** $310K ARR. Insurance. Enterprise. Signed 6 months ago. Onboarding was rocky; took 14 weeks vs. the 6-week target. They've only activated 40% of purchased seats. Marco has a rescue plan in flight.

4. **Clearpath Logistics:** $180K ARR. Logistics. Mid-market. Healthy, low-touch. Renewal in 90 days.

5. **Prism Analytics:** $165K ARR. Data/analytics. Mid-market. **Renewal in 34 days.** Usage has dropped 30% over the last quarter. The champion (their VP Ops) left in March. No new champion identified. Marco flagged it last week.

6. **Sagebrush Media:** $142K ARR. Media/publishing. 18-month customer. Stable.

7. **Halcyon Brands:** $128K ARR. D2C/retail. Health unclear; support tickets up 40%, but usage is flat. Could go either way at renewal.

8. **Ironclad Construction:** $115K ARR. Construction. Expansion opportunity; they use Atlas for procurement workflows only, but their HR team has expressed interest.

9. **Northwind Education:** $98K ARR. EdTech. Small but strategic; the CEO knows their CEO personally.

10. **Verdant Agriculture:** $87K ARR. AgTech. Healthy. Quiet account.

### Recent churn (last 90 days)
- **Beacon Logistics:** $72K ARR. Churned citing "lack of enterprise features" (specifically: no custom RBAC, no audit log export, no API rate-limit controls). These are all on the platform rewrite roadmap.
- **FreshCart:** $48K ARR. Acquired by a competitor that standardized on a different tool.
- **Two SMB accounts:** $31K combined. Price sensitivity.

### Pipeline (active deals)

- **Ridgeline Health, $380K ARR, final negotiations.** Enterprise healthcare. Decision by end of April. Blocker is data residency (see above). Kevin is leading personally.
- **Meridian Corp, $220K ARR.** Mid-market fintech. Was moving fast, went quiet 2 weeks ago. Kevin suspects they're evaluating a competitor (probably Workato or Tray.io).
- **Apex Partners, $160K ARR.** Mid-market consulting. Discovery stage. Strong ICP fit.
- **CityGrid Municipal, $95K ARR.** Government/municipal. Long sales cycle expected. SOC 2 and FedRAMP Moderate would be required. Atlas has SOC 2; FedRAMP is not on the roadmap.
- **Three SMB inbounds:** $45K combined ARR. Standard self-serve motion.

---

## 6. Ops (Ops domain material)

### Engineering

- **Platform rewrite ("Atlas 2.0"):** The monolithic Rails app is being rebuilt as a React + Go microservices architecture. Daniel (CTO) is leading it personally. **Beta target: June 15.** 62% complete as of last sprint. The rewrite is the prerequisite for most enterprise features (custom RBAC, audit logs, API controls, the exact things Beacon cited when they churned).
- **Velocity:** Story points per engineer are up 22% since switching to weekly sprints 6 weeks ago. Bug count per sprint is down.
- **Interim eng leadership:** Clara Mendes (backend, 4 direct reports) and Amir Haddad (frontend, 3 direct reports) are covering for the VP Eng vacancy. Both are strong ICs promoted into management for the first time. Neither has said they want the VP role permanently.
- **Atlas Assist (AI copilot feature):** Jess Wilder is spec'ing it. Uses a third-party LLM API to suggest workflow automations from natural language. **Alpha internal demo: May 1.** The board sees this as the enterprise wedge.
- **Tech debt:** CI pipeline takes 38 minutes (was 22 minutes a year ago). Daniel wants to fix it but won't prioritize it over the rewrite.

### Infrastructure
- **Uptime (last 90 days):** 99.91% (target: 99.95%)
- **Incidents (last 30 days):** 2 P2s, both related to database connection pooling under load. No P1s.
- **AWS spend:** $47K/mo, up 18% QoQ. The rewrite should reduce this (the monolith is inefficient) but short-term costs are higher because both systems run in parallel.

### Support
- **Zendesk CSAT (last 30 days):** 82% (target: 90%, was 88% three months ago)
- **Median first-response time:** 4.2 hours (target: 2 hours)
- **Ticket volume:** Up 28% QoQ. Diana's team hasn't grown; same 3 support agents since last year.
- **Top ticket categories:** Workflow builder UX confusion (34%), integration sync failures (22%), billing questions (18%)
- **Tidewater Insurance:** Generating 3x the ticket volume of any other account, mostly onboarding-related

### Product
- **NPS (trailing 90 days):** 38 (down from 46 six months ago)
- **NPS by segment:** SMB: 42, Mid-market: 36, Enterprise: 28
- **Feature requests (top 3 by vote count):** 1) Custom RBAC (94 votes), 2) Workflow versioning (71 votes), 3) Native Salesforce integration (63 votes)
- **Trial-to-paid conversion:** 8.2% (down from 9.7%; Sophie suspects the onboarding flow is the issue, not lead quality)

---

## 7. Team (Team domain material)

### Key roles open
- **VP Engineering:** Rachel Navarro left 3 weeks ago. Cited burnout and a competing offer from Datadog. **No search started.** Alex Tan (People Ops) is waiting on whether the CEO wants to promote Clara or Amir, or run an external search. The interim structure is holding but both Clara and Amir are showing strain.
- **Senior Engineer (platform):** Open 30 days. Four candidates in pipeline, one in final round (strong, but wants full remote; Atlas is hybrid-first).
- **Support Engineer (2 positions):** Open 18 days. Diana needs them yesterday. Ticket volume is crushing the existing team.
- **Enterprise AE:** Open 6 weeks. Kevin wants someone with healthcare vertical experience for the Ridgeline deal and the accounts that follow.
- **Content Marketing Manager:** Sophie's team. Open 3 weeks.

### Retention concerns
- **Nina Volkov (Staff Engineer):** Being actively recruited by Stripe. She's key to the platform rewrite. Daniel is aware but hasn't escalated to the CEO. She hasn't said she's leaving, but she's taking the calls.
- **Clara Mendes (interim eng lead):** Increasingly frustrated by the scope of the interim role. Told a peer she "didn't sign up to be a manager." If Clara leaves, the backend rewrite is in serious trouble.
- **Marco Reyes (Head of CS):** Managing 340 accounts with 6 CSMs. His 1:1 cadence with the CEO dropped 60% last month. He's quiet, not complaining, which is its own signal.
- **Two mid-market AEs:** Approached by a well-funded competitor (FlowStack) at SaaStr last month. Kevin heard about it secondhand.

### Recent retention wins
- **Amir Haddad:** Declined a frontend lead role at Figma in March. Took a 12% retention raise and the interim lead title.
- **Three engineers** opted into the technical interview panel this month, a positive culture signal.

### Engagement signals
- Engineering pulse survey (March): Engagement up overall after the sprint cadence change. But the "confidence in leadership" score dropped, almost certainly the VP Eng departure shaking people.
- Three senior engineers from FlowStack (competitor) updated their LinkedIn profiles to "open to work" last week, a potential recruiting opportunity.

---

## 8. Market (Market domain material)

### Competitors
- **FlowStack:** Series C ($65M raised), 200 employees. Direct competitor in mid-market workflow automation. Just launched an AI feature (FlowStack Copilot) that's getting press coverage. Their pricing is 20% higher than Atlas at mid-tier but they're aggressively discounting to win deals.
- **Workato / Tray.io:** Enterprise integration platforms. Not direct competitors at the mid-market, but they're moving downmarket and showing up in deals Atlas used to win unopposed.
- **Zapier:** SMB/prosumer. Not a direct competitor for mid-market but sets pricing expectations at the low end.
- **Internal "build it ourselves" / spreadsheets:** Still the #1 competitor in most deals. Atlas's biggest enemy is inertia.

### Industry signals
- **AI copilot features:** Every workflow/automation platform is shipping one. FlowStack's Copilot launched 3 weeks ago. Atlas Assist is in alpha. The window to be "first" is closed; the window to be "best" is open for another 6 months.
- **Mid-market SaaS consolidation:** Buyers are cutting vendors. Average mid-market company reduced their SaaS stack by 12% in the last year. Atlas benefits (replaces multiple tools) and suffers (procurement scrutiny is higher).
- **HIPAA/SOC 2 as table stakes:** Healthcare and fintech verticals now require both as minimum. Atlas has both. FlowStack has SOC 2 but not HIPAA BAA.

### Calendar / events
- **SaaStr Annual:** June 10-12, San Francisco. Atlas has a booth. CEO is on a panel ("Workflow Automation in the AI Era"). FlowStack will also be there.
- **Board meeting:** April 28. Megan is preparing the deck. Key agenda: Series C timeline, ARR trajectory, VP Eng succession.
- **Atlas Assist alpha demo:** May 1, internal. Jess is leading. Daniel's platform rewrite needs to be far enough along for the demo to run on the new architecture.
- **Ridgeline Health decision:** Expected by end of April.
- **Prism Analytics renewal:** Due May 16. At risk (usage declining, champion departed).

### Fundraising landscape
- **Series C market (B2B SaaS, $10-20M ARR):** Competitive but not frozen. Investors want 40%+ growth, 110%+ NRR, clear path to $30M ARR. Atlas hits 2 of 3 (growth is 45%, NRR is 112%). The $20M ARR exit-rate target for December is the proof point.
- **Comparable rounds (last 6 months):** Two workflow-adjacent companies raised at 12-15x ARR. Atlas at $14.2M ARR would target $180-220M pre-money, within range if Q2 executes.

---

## 9. Recent activity (the "what's happened in the last 7 days" feel)

### Slack snippets (real-feeling, attributable to specific people)
- **Clara Mendes** (yesterday, 4:47 PM, #engineering): *"Sprint 22 retro: velocity held. But I need to flag something. The rewrite has zero test coverage on the auth module and we're 3 weeks from beta. Daniel, can we talk about this tomorrow?"*
- **Kevin O'Malley** (2 days ago, 11:15 AM, #sales): *"Ridgeline update: their CISO wants a call about data residency. I positioned the GovCloud deployment but he wants to talk to Daniel directly. Can we make that happen this week?"*
- **Marco Reyes** (today, 9:22 AM, #customer-success): *"Prism Analytics usage dropped another 14% this month. Their VP Ops left in March and nobody's picked up the internal champion role. Renewal is May 16. I think we need an exec-to-exec play here."*
- **Diana Okafor** (yesterday, 3:10 PM, #support): *"CSAT dropped to 78% this week. We're drowning in Tidewater tickets and it's dragging everything else down. I need those two support hires."*
- **Sophie Zhang** (3 days ago, 10:30 AM, #marketing): *"CAC report for Q1 is in. $18.2K, up from $14.8K a year ago. Paid channels are getting expensive. I want to shift budget toward content and community; need to talk through it."*
- **Daniel Choi** (yesterday, 6:02 PM, #engineering): *"Rewrite status: 62% complete. Auth module, billing integration, and the migration tooling are the remaining heavy lifts. June 15 beta is tight but doable if we don't lose anyone."*
- **Megan Park** (4 days ago, 2:45 PM, #leadership): *"Q1 close: $14.2M ARR. We need $5.8M net new to hit the $20M exit-rate target. That's $1.45M per quarter. Doable, but we've never added more than $1.1M in a quarter."*
- **Alex Tan** (this morning, 8:15 AM, DM to CEO): *"Still waiting on direction on the VP Eng search. Clara and Amir are holding it together but I'm seeing stress signals. Do you want me to start an external search, or are we promoting one of them?"*

### Email / meetings
- **Yesterday:** CEO had 1:1s with Megan (Series C prep), Kevin (Ridgeline update), and Daniel (rewrite status).
- **3 days ago:** CEO took a call with a Series C investor (Gradient Ventures): exploratory, positive, they want to see Q2 numbers.
- **This week ahead:** Board prep call with Megan on Wednesday. Kevin is setting up the Ridgeline CISO call for Thursday or Friday.
- **Next week:** Monthly all-hands. CEO needs to address the VP Eng vacancy and the Atlas Assist timeline. People are asking questions.

### Decision queue (the CEO's open-decisions list)
- VP Engineering: promote Clara, promote Amir, or external search? **Decision needed this week.** Ambiguity is causing strain.
- Ridgeline Health data residency: commit to GovCloud timeline for the CISO call? **Decision needed by Thursday.**
- Prism Analytics: exec-to-exec rescue attempt or let it churn? **Decision needed before May 16 renewal.**
- Support hiring: approve 2 support engineers or restructure the support model? **Decision needed this week.** CSAT is in freefall.
- CAC strategy: shift budget from paid to content/community? **Decision needed before May campaign planning.**
- Nina Volkov retention: preemptive counter-offer or wait? **Decision needed soon.** Stripe is moving fast.
- Series C timeline: roadshow in June (aggressive) or September (safer, more data)? **Decision needed by board meeting April 28.**

---

## 10. The cross-domain connections (the "interesting" cards)

These are not pre-written cards. They're examples of the kinds of cross-domain connections worth surfacing when generating cards from this brief. Listed here as a guide to the patterns to look for.

- **Platform rewrite ↔ Beacon churn ↔ Ridgeline deal ↔ Series C:** Beacon churned citing missing enterprise features. Those features live in the rewrite. Ridgeline needs some of them (RBAC, audit logs). The rewrite beta is June 15. The Series C roadshow needs enterprise logos. One engineering timeline is the linchpin for revenue, fundraising, and retention.

- **VP Eng vacancy ↔ Clara/Amir strain ↔ Nina retention ↔ rewrite timeline:** No VP Eng, two stressed interim leads, the best IC being recruited away, and the most important engineering project in company history all happening simultaneously. A single departure could cascade.

- **Prism Analytics churn risk ↔ NRR decline ↔ Series C valuation:** Prism is $165K ARR at risk. If it churns, NRR drops further below the 115% threshold Megan says investors need. One mid-market renewal has Series C implications.

- **CSAT decline ↔ Tidewater onboarding ↔ support staffing ↔ NPS drop:** Support is underwater because Tidewater is generating 3x normal ticket volume from a bad onboarding. CSAT is dragging NPS. NPS is a board metric. The fix is either more support headcount or fixing the Tidewater root cause, or both.

- **CAC increase ↔ trial conversion decline ↔ competitive pressure:** CAC is up because paid channels are more expensive AND trial conversion is down. If the conversion issue is onboarding UX (Sophie's hypothesis), fixing it would improve both metrics simultaneously. If it's competitive (FlowStack discounting), the response is different.

- **FlowStack Copilot launch ↔ Atlas Assist timeline ↔ SaaStr panel:** FlowStack shipped their AI feature. Atlas Assist demos internally May 1. The CEO is on a SaaStr panel in June about "Workflow Automation in the AI Era." The panel is an opportunity to position Atlas Assist, but only if there's something real to show.

- **Nina Volkov recruitment ↔ Daniel not escalating:** Same pattern as Clara's stress signals: information the CEO doesn't have yet. Lens noticing this is exactly the kind of "human bandwidth protection" the product is for.

- **FlowStack "open to work" engineers ↔ Atlas VP Eng search ↔ senior engineer hiring:** Three senior engineers at Atlas's main competitor just signaled availability. Atlas has a VP Eng opening and a senior engineer req. The recruiting window is narrow.

---

## 11. Card generation guidance

- **Stay neutral.** Signals are not classified as risks, opportunities, or trends. The card surfaces what's happening. The reader applies their own judgment. Never frame a card as a warning or a win.
- **Vary the time horizon.** Some cards are urgent (this week). Some are 30-day. Some are quarter-out. Mix them so the card feed feels like real continuous monitoring, not a daily alert dump.
- **Lead with what only the CEO can act on.** Engineering sprint details belong in a standup, not the CEO's card feed. If a card could be solved by a director without CEO involvement, it's probably the wrong card to surface to the CEO.
- **Use specific numbers and names.** Generic observations ("review your customer concentration") are useless. Specific observations ("Prism Analytics usage dropped 30% and their champion left; $165K ARR, 34 days to renewal") are the value.
- **Surface, don't decide.** The card makes the situation legible. The decision is the CEO's to make. The card never recommends, prescribes, or directs action.
- **Cross-domain connections are the highest-value cards.** Single-domain cards are good. Multi-domain cards are better, because they show Lens doing what no individual department head can do: connecting dots across silos.
- **Stay grounded in this document.** Do not invent new people, new accounts, or new vendors. The fictional company is bounded by what's in this brief. If something isn't here, don't pretend it is. Future updates to this document add new material; only what's written here is visible.

---

## 12. Future expansions to this brief

When this brief gets richer, the cards get richer. Areas to expand later:
- More named characters with personalities and backstories
- More historical context (what happened last quarter, last year)
- More specific Slack/email threads with multi-turn conversations
- More numerical detail in financial sections (cohort analysis, segment-level metrics)
- A "company calendar" of events over the next 90 days
- A "competitive intel" section with more specific FlowStack moves
- A "customer health scorecard" with more accounts than the top 10
- Product usage telemetry (feature adoption rates, workflow complexity distribution)
