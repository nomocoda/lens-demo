# Revenue Operator, Intelligence Brief

> Phase A, Archetype Intelligence Brief | Revenue Domain | B2B SaaS, 50-500 employees

## 1. Who this archetype actually is

The Revenue Operator in B2B SaaS is the architect of the revenue system itself. Where the Revenue Generator closes deals and the Revenue Developer fills the top of the funnel, the Revenue Operator makes sure the entire system is clean, consistent, and producing numbers that can be trusted. Their accountability is measured in forecast accuracy, CRM data quality, pipeline governance, and the reliability of the process and tooling layer that every other revenue team member depends on.

This is the person who spends Monday morning verifying that Salesforce and Clari agree before the Wednesday forecast call. Who notices that the pipeline definition Sales is using does not match the pipeline definition Finance is tracking and makes it stop. Who builds the stage-gate rules, deploys the mandatory field validation, tightens the deduplication logic, and retires the six dashboards nobody remembers creating. A good week is a forecast call that runs half the time it used to because the prep work is automated and the numbers are trusted from the first slide. A bad week is a QBR interrupted by a 30-minute argument about whether the pipeline number includes unqualified trials — an argument that would not exist if the governance was locked.

The Revenue Operator lives in Salesforce, Clari, HubSpot, Outreach, Looker, and whatever BI stack the company has assembled. They own the handoff definitions, the routing rules, the attribution model, the lifecycle stage governance, and the QBR change log. They are the single person who can look at a number from any of those systems and tell you whether to trust it.

## 2. Real roles that map to this archetype

**Core titles:**
- VP of Revenue Operations
- Director of Revenue Operations
- Sales Operations Manager
- Revenue Operations Analyst (senior individual contributor)
- Head of Sales Operations

**Seniority variations:**
- 50-150 employees: Often a single Sales Ops Manager who owns both systems administration and process governance without a team
- 150-350 employees: Director-level RevOps with one or two analysts; dedicated ownership of Salesforce admin, data quality, and forecasting infrastructure
- 350-500 employees: VP RevOps with a small team; governance across CRM, marketing ops, CS ops, and BI; begins to own cross-functional lifecycle definitions

**Edge cases that fit:**
- Revenue Enablement Manager: when the role crosses into process governance, tooling, and CRM integrity rather than pure content and training
- GTM Operations Lead: when the scope is cross-functional but focused on system integrity and forecasting rather than strategy

**Titles that sound similar but don't fit:**
- CRO / VP Sales: the Revenue Leader archetype -- owns territory and quota outcomes, not system integrity
- AE / Account Executive: the Revenue Generator archetype -- owns deal closure, not process infrastructure
- SDR / BDR: the Revenue Developer archetype -- owns pipeline creation, not governance
- Marketing Ops Manager: adjacent but lives in the demand gen and campaign infrastructure, not pipeline and forecast governance
- Finance Controller / VP Finance: shares interest in forecast accuracy but from a GL and audit angle the Revenue Operator explicitly avoids

## 3. What they spend their time on

**Daily:** The Revenue Operator opens Salesforce first and checks data health: stale close dates, missing mandatory fields, records that failed overnight sync with Clari. They triage any routing exceptions that fired overnight and clear the queue before the daily lead assignment cycle runs. They monitor forecast vs. actuals on open commit-tier deals to catch drift before it reaches the forecast call.

**Weekly:** The weekly rhythm anchors on the Wednesday forecast call. The Revenue Operator owns the prep: pipeline health report, stage distribution review, coverage ratio check. After the call, they log what surfaced as data quality issues and schedule the fix. They also run the week's lead routing report, check attribution model consistency across the Sales and Marketing dashboards, and clear any sync errors between systems.

**Monthly:** Stage-gate performance review (are deals moving through the refined gates faster or slower?), lead lifecycle governance audit (are MQL-to-SQL transitions happening under the validated automation rules?), and a dashboard rationalization pass to retire anything producing redundant numbers. They produce one clean monthly pipeline report that Sales, Marketing, and Finance can each cite without reconciling.

**Quarterly:** The QBR is the Revenue Operator's biggest governance moment. They own the agenda for the process changes being locked, present the attribution model for approval, and leave the meeting with a list of changes that are either locked for production or explicitly deferred. Between QBRs, they track the live status of every locked change.

## 4. What they read and listen to

**Podcasts:**
- *RevOps FM*, practitioner discussions on systems, process, and forecast infrastructure
- *Operations with Sean Lane*, RevOps strategy and cross-functional alignment
- *The Salesforce Admins Podcast*, system administration, automation, and data hygiene tactics
- *B2B Revenue Vitals* (Chris Walker), demand and revenue attribution discussions

**Communities:**
- RevOps Co-op, the primary practitioner community for RevOps and Sales Ops discussions
- Salesforce Trailhead Community, system administration, flow, and data integrity
- Revenue Collective / Pavilion RevOps chapter, senior-level strategy and tooling conversations
- Clari Users Group, forecast methodology and platform configuration

**Benchmark reports they cite:**
- SiriusDecisions / Forrester pipeline coverage ratios (2.5x-4x by segment)
- Clari Revenue Grid benchmarks (stage progression rates, forecast accuracy bands)
- Salesforce State of Sales (CRM adoption rates, data quality benchmarks)
- Bridge Group Sales Operations Survey (tooling stack, admin-to-rep ratios)

## 5. What they complain about (and where it hurts)

**1. The forecast call turns into a data quality meeting.**
The number on slide two is different from the number on slide four because Marketing ran their pipeline figure through a different Salesforce report. Twenty minutes disappear reconciling definitions that should have been locked in Q1. The forecast call exists to talk about deals, not to argue about what counts as pipeline. *Goal-pursuit friction: Goal 1 (Forecast Accuracy and Data Quality).*

**2. Stage gates that exist only on paper.**
Sales built a four-stage process with documented entry criteria. Nobody enforces them. Deals move from Stage 2 to Stage 4 in a single afternoon without meeting the Stage 3 criteria. The conversion rate analytics become meaningless when the stages themselves are not consistently applied. *Goal-pursuit friction: Goal 2 (Pipeline Governance and Definitional Alignment).*

**3. Routing rules that accumulate until they contradict each other.**
The lead routing logic was built over three years by four different people. Four overlapping rules cover the same territory criteria with slightly different priority weights. One fires and the next overrides it. Manual exception rate climbs. The Revenue Operator knows the fix -- collapse the rules -- but getting approval requires a cross-functional meeting that has been on the calendar four times. *Goal-pursuit friction: Goal 3 (Process and Tooling Efficiency).*

**4. Attribution disputes that relitigate at every QBR.**
Marketing says they sourced the deal. Sales says the BDR sourced it. Finance is not sure it counts as pipeline-sourced because the trial started before the lead was created. The attribution model was never locked in a governance event, so every QBR restarts from scratch. *Goal-pursuit friction: Goal 2 (Pipeline Governance and Definitional Alignment).*

**5. Dashboard proliferation that nobody is willing to own the retirement of.**
There are eleven dashboards in Looker and Salesforce that overlap in meaningful ways. Three were built by former employees. Retiring them requires confirming that nobody depends on them -- which requires a survey, which becomes a project, which never gets prioritized. The Revenue Operator runs on four dashboards and ignores the rest. *Goal-pursuit friction: Goal 3 (Process and Tooling Efficiency).*

## 6. What would offend them

**Individual rep field-completion as an accountability signal.** The Revenue Operator cares about stage-level and pipeline-level data completeness because bad data breaks the forecast and the attribution model. A card that attributes incomplete fields to a specific rep is a manager conversation, not an intelligence conversation. Completeness signals live at the gate level, not the rep level.

**Compensation, OTE, or commissions data.** The Revenue Operator does not own comp. Surfacing commission structure or OTE data is out of scope and crosses into HR territory the archetype explicitly avoids.

**Revenue recognition, deferred revenue, or GL-level finance.** The Revenue Operator cares about pipeline accuracy and forecast-to-actual. Once a deal is closed, the handoff to Finance is complete. GL entries, ASC 606 treatment, and deferred revenue schedules are a Finance Controller conversation, not a RevOps conversation.

**GDPR compliance, consent flags, or PII governance.** Lead data compliance lives with Legal and Marketing Ops. The Revenue Operator ensures data quality for forecasting and pipeline governance, not regulatory compliance.

**Headcount planning, team sizing, or ramp curves.** RevOps may inform headcount models, but the decision is a Revenue Leader conversation. Surfacing team capacity or hiring recommendations is overreach.

**Recommendations about which deals to prioritize.** The Revenue Operator sets the system for prioritizing deals -- the stage gates, the coverage ratios, the attribution model. They do not tell the AE which deal to call on next. Lens surfaces the system performance; the human makes every deal-level decision.

## 7. Five "that's me" quotes they would say

**Quote 1:** "We spent 28 minutes on the forecast call last Wednesday versus 90 minutes the week before. The pipeline health report prep is automated now. That's the whole story."

**Quote 2:** "We had three different pipeline numbers in the same QBR deck. Sales, Marketing, and Finance each pulled from a different report with a different definition. That ended in April when we locked the definition."

**Quote 3:** "The Stage 3-to-Stage 4 conversion rate jumped 15 points after we added the mandatory gate fields. Turns out half those deals were not actually at Stage 3 -- they just had not been updated."

**Quote 4:** "The lead routing exception rate dropped from 12% to under 2% after we collapsed four overlapping territory rules into one. I do not know why we had four rules. Neither does anyone else."

**Quote 5:** "We retired six dashboards this month and nobody noticed. That tells you everything you need to know about how many people were actually using them."

## 8. Signal shapes worth distinguishing

The Revenue Operator's mental model separates signals that look superficially similar but answer different questions. Cards must respect that separation. Conflating them collapses two cards into one and drops the more diagnostic signal.

**P-RO-01 (forecast accuracy 58% to 76% after Stage 4 close-date validation rule) is distinct from P-RO-13 (forecast call duration 90 minutes to 28 minutes after data-prep automation).** Both signals describe improvements to the forecast cycle, but they operate on different layers. P-RO-01 is an upstream data quality story: the validation rule forces close-date accuracy at the gate, and the forecast reflects reality more accurately as a result. P-RO-13 is a meeting cadence efficiency story: the prep automation replaces manual triage work, and the call itself runs faster because the numbers are ready before anyone arrives. The first is about whether the input data is trustworthy. The second is about what you can do with trustworthy data.

**P-RO-02 (pipeline definition lock across Sales, Marketing, and Finance) is distinct from P-RO-05 (attribution model lock via governance review).** Both are definitional governance events, but they govern different artifacts. P-RO-02 defines what counts as pipeline -- the boundary conditions that determine whether a record shows up in the pipeline report at all. P-RO-05 defines how sourced pipeline is credited -- which touchpoints get attributed to which function. A company can have a locked pipeline definition and an unresolved attribution model, and the reverse is also true. Each lock resolves a different class of QBR dispute.

**P-RO-03 (stale close-date auto-flag at Stage 3+) is distinct from P-RO-10 (Stage 4 mandatory-field completion).** Both are data quality automation signals, but they operate on different surfaces and trigger in different ways. P-RO-03 fires on temporal drift -- a close date that has aged past a threshold without being updated. The fix is a date refresh. P-RO-10 fires on missing structured data -- specific fields that must be present before a deal advances. The fix is field population. One is a recency problem; the other is a completeness problem. Both degrade forecast accuracy through different mechanisms.

**P-RO-04 (pipeline coverage ratio 4.1x) is distinct from P-RO-12 (account dedup tightens active account count to 1,290).** Both feed the pipeline coverage calculation, but from different directions. P-RO-04 is the resulting ratio -- the output of dividing pipeline value by quota. P-RO-12 is a correction to the denominator -- deduplication removes inflated record counts that were making the active account pool look larger than it is. One reports the metric; the other corrects the input that the metric depends on.

**P-RO-07 (Stage 3 to Stage 4 conversion 32% to 47%) is distinct from P-RO-10 (Stage 4 mandatory-field completion).** Both are products of the same gate intervention -- the Stage 3 gate definition refresh and the Stage 4 mandatory fields were deployed in the same wave. But they measure different downstream effects. P-RO-07 is a conversion rate signal: the refined gate is filtering deals more accurately, so the deals that advance are more likely to close. P-RO-10 is a data completeness signal: the mandatory fields ensure that every deal that reaches Stage 4 carries the structured data the forecast model and battlecard usage analysis depend on. The gate produces better conversion; the fields produce better data quality.

**P-RO-09 (lead routing exception rate 12% to 1.8%) is distinct from P-RO-15 (MQL-to-SQL lifecycle governance).** Both are lifecycle infrastructure signals, but they govern different stages and different error types. P-RO-09 is about the routing rules that assign an inbound lead to the right owner at the moment of creation. The exception rate measures how often those rules fail and produce a manual override. P-RO-15 is about the validation rules that govern whether an MQL meets the criteria to advance to SQL. The governance metric measures what fraction of MQL-to-SQL transitions happen under validated automation versus manual override. One is assignment accuracy; the other is qualification accuracy. Both break down at different points in the lead lifecycle.

**P-RO-08 (6 dashboards retired) is distinct from P-RO-14 (5 of 7 QBR process changes locked).** Both are governance events, but at different scopes and cadences. P-RO-08 is a tooling rationalization signal -- redundant reporting infrastructure removed, admin hours reclaimed, and the reporting surface simplified. The fix is permanent. P-RO-14 is a process governance signal -- the QBR produced a specific list of changes, and most of them were locked before the quarter ended. The locked changes span the entire process stack (stage gates, attribution, routing, lifecycle, tooling). P-RO-08 is one item on the P-RO-14 list; they are not the same event.

## 9. Adjacent roles and interfaces

**Revenue Leader (CRO / VP Sales):** The Revenue Operator's primary stakeholder. The Revenue Leader owns the forecast outcome; the Revenue Operator owns the infrastructure that makes the forecast trustworthy. The CRO relies on the Revenue Operator to confirm the numbers before they leave the room. The Revenue Operator's work on stage gates, coverage ratios, and attribution definitions is directly accountable to the Revenue Leader.

**Revenue Generator (AE):** The Revenue Operator builds the stage definitions the AE must work within. Mandatory field requirements, close-date staleness rules, and stage-gate criteria all come from the Revenue Operator. The AE experiences these as process requirements; the Revenue Operator experiences them as data quality infrastructure.

**Revenue Developer (SDR / BDR):** Lead routing, sequencing tool uptime, MQL-to-SQL lifecycle governance -- the Revenue Developer depends on the Revenue Operator's infrastructure for their daily operating rhythm. When routing rules break or lead assignment fails, the Revenue Developer loses time. The lifecycle governance refresh that P-RO-15 describes is a Revenue Operator delivery that directly affects the Revenue Developer's output.

**Marketing Strategist / Marketing Builder:** Attribution model governance is the shared surface. The Marketing team sources pipeline; the Revenue Operator defines how sourced pipeline is credited. Attribution disputes trace back to whether the governance was locked in a QBR event. The P-RO-05 lock (multi-touch attribution model) resolves a recurring QBR conflict between Marketing and Revenue.

**Finance (Controller / CFO):** The Revenue Operator provides the pipeline number Finance uses for revenue forecasting. They share an interest in forecast accuracy but occupy different domains. The Revenue Operator's scope ends at closed-won; Finance's scope begins there. The handoff at close is the boundary. Finance uses the pipeline governance outputs; they do not own the process that produces them.

**Customer Leader (VP CS):** Post-sale account data in Salesforce -- account health scores, renewal dates, expansion flags -- lives in the same CRM the Revenue Operator maintains. Data hygiene changes that affect account records require coordination. The Revenue Operator's dedup rule (P-RO-12) directly affects the active account count the Customer Leader uses for coverage tier assignments.
