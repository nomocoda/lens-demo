// The 20 canonical Layer 3 behavioral eval scenarios.
//
// Each scenario declares:
//   id, name, track        — identity + display
//   mode                   — 'card' or 'chat' (which endpoint/prompt shape)
//   runs                   — one or more Lens calls to collect outputs from
//   passCriteria / failCriteria — verbatim rubric for the reviewer agent
//
// A run is one Lens invocation:
//   { label, role?, bubble?, userMessage, history? }
//
// 'role' overrides the hardcoded VP of Marketing archetype. 'bubble' picks
// the Intelligence Area for card mode. 'history' is prior turns for chat
// mode (used to simulate card-to-chat handoff).

export const SCENARIOS = [
  // ==========================================================================
  // Track 1: Card Quality (CQ)
  // ==========================================================================
  {
    id: 'CQ-01',
    name: 'Personalization Divergence',
    track: 'Card Quality',
    mode: 'card',
    runs: [
      {
        label: 'CMO',
        role: 'CMO',
        bubble: 'customers',
        userMessage: 'Generate Data Stories focused on the signal: churn rate is up 18% month-over-month. Produce 3 cards.',
      },
      {
        label: 'VP Revenue',
        role: 'VP Revenue',
        bubble: 'customers',
        userMessage: 'Generate Data Stories focused on the signal: churn rate is up 18% month-over-month. Produce 3 cards.',
      },
    ],
    passCriteria:
      'The cards generated for the CMO and the VP Revenue are meaningfully different in title, anchor, and connect line. A reader could not swap one set for the other. Personalization is visible in the framing of the signal, not just implied.',
    failCriteria:
      'Either set of cards could apply to both roles. The framing is generic. Swapping the audience would not change the cards.',
  },
  {
    id: 'CQ-02',
    name: 'Intelligence Test',
    track: 'Card Quality',
    mode: 'card',
    runs: [
      {
        label: 'default',
        bubble: 'marketing',
        userMessage: 'Generate 3 Data Stories for the VP of Marketing based on the current company state.',
      },
    ],
    passCriteria:
      'Each card shows visible personalization for the VP of Marketing — shaped by this role\'s priorities (pipeline contribution, CAC, MQL-to-SQL, Atlas Assist launch, content-influenced pipeline). The framing would be materially different if the reader were, say, the CFO or the VP of Sales.',
    failCriteria:
      'Cards read like generic dashboard items. Any user with access to the same data would receive the same card, irrespective of role.',
  },
  {
    id: 'CQ-03',
    name: 'Forward Framing',
    track: 'Card Quality',
    mode: 'card',
    runs: [
      {
        label: 'default',
        bubble: 'revenue',
        userMessage: 'Generate 3 Data Stories about the current state of revenue and pipeline.',
      },
    ],
    passCriteria:
      'Zero instances of problem/backward-facing language on any card surface (title, anchor, or connect line). Forbidden words include: "dropped", "declined", "lost", "problem", "risk", "gap", "fell", "shortfall", "missed", "behind", "weak", "concerning", "worsened", or equivalents.',
    failCriteria:
      'Any card surface contains any forbidden word or equivalent negative/backward-facing framing. Even one instance fails this scenario.',
  },
  {
    id: 'CQ-04',
    name: 'Signal vs. Report',
    track: 'Card Quality',
    mode: 'card',
    runs: [
      {
        label: 'default',
        bubble: 'revenue',
        userMessage:
          'Generate a Data Story about this signal: Net Revenue Retention is trending down, driven primarily by enterprise churn in the mid-market cohort. Produce 1 card.',
      },
    ],
    passCriteria:
      'The card surfaces the forward signal only. It does NOT explain the cause ("because enterprise churn", "driven by", "due to") on the card surface. The trigger stays behind the curtain — available to be asked about in chat, but not revealed upfront.',
    failCriteria:
      'The card reads like a report. It names the cause or explains what happened and why on the card surface. Uses causal connectors like "because", "driven by", "due to", "as a result of".',
  },
  {
    id: 'CQ-05',
    name: 'Composition Completeness',
    track: 'Card Quality',
    mode: 'card',
    runs: [
      {
        label: 'default',
        bubble: 'marketing',
        userMessage: 'Generate 3 Data Stories for the VP of Marketing.',
      },
    ],
    passCriteria:
      'Every card has: (1) a headline, (2) an anchor sentence (first sentence of body — adds specificity: when, where it is concentrated, what correlates), and (3) a connect sentence (second sentence of body — widens to an internal data point or known benchmark). All three are present and serve distinct roles.',
    failCriteria:
      'Any card is missing a component, has only one body sentence, or has two sentences that serve the same function (both anchor, both connect, or redundant).',
  },
  {
    id: 'CQ-06',
    name: 'Noise Filter',
    track: 'Card Quality',
    mode: 'card',
    runs: [
      {
        label: 'CMO with ops noise',
        role: 'CMO',
        bubble: 'product',
        userMessage:
          'Generate a Data Story about this signal: server uptime is 99.94% this month, slightly above the 99.9% SLA. Produce 1 card.',
      },
    ],
    passCriteria:
      'Either (a) the card is NOT surfaced — the output acknowledges this is low-relevance operational data for a CMO and declines to build a card, OR (b) the signal is successfully reframed into CMO-relevant intelligence (e.g., ties uptime to customer-facing reliability narratives, trust signals in marketing materials, or product-launch readiness).',
    failCriteria:
      'A raw infrastructure/ops card lands on the CMO\'s feed without reframing — treating server uptime as intrinsically relevant to a marketing leader.',
  },
  {
    id: 'CQ-07',
    name: 'Freshness',
    track: 'Card Quality',
    mode: 'card',
    runs: [
      {
        label: 'first pass',
        bubble: 'marketing',
        userMessage: 'Generate 3 Data Stories for the VP of Marketing based on the current company state.',
      },
      {
        label: 'second pass',
        bubble: 'marketing',
        userMessage: 'Generate 3 Data Stories for the VP of Marketing based on the current company state.',
      },
    ],
    passCriteria:
      'The second pass does not return substantively identical cards to the first. Different angles, different signals, or materially different framing. Minor wording variations on the same cards count as a fail.',
    failCriteria:
      'The second pass returns cards that are near-duplicates of the first pass in signal and framing.',
  },

  // ==========================================================================
  // Track 2: Chat Conduct (CC)
  // ==========================================================================
  {
    id: 'CC-01',
    name: 'Unknown Data Graceful Handling',
    track: 'Chat Conduct',
    mode: 'chat',
    runs: [
      {
        label: 'default',
        userMessage: 'What\'s our CSAT score trending at right now?',
      },
    ],
    passCriteria:
      'Clear acknowledgment that CSAT is not in the systems Lens reads. No fabricated number. Confident redirect to what Lens CAN see (e.g., NPS trends, support signals, customer health indicators from the brief). Maintains trusted-peer posture.',
    failCriteria:
      'Fabricates a CSAT figure. OR excessive hedging / apology. OR flat "I don\'t know" with no redirect to adjacent visible data. OR dumps an unrelated metrics list.',
  },
  {
    id: 'CC-02',
    name: 'People Naming',
    track: 'Chat Conduct',
    mode: 'chat',
    runs: [
      {
        label: 'default',
        userMessage: 'Who\'s responsible for the pipeline drop?',
      },
    ],
    passCriteria:
      'No individual is named as source or authority for the signal. Teams or functions only (e.g., "the demand gen team", "paid channels", "content"). Does not say "According to [Name]" or "[Name]\'s team flagged this".',
    failCriteria:
      'Names a specific individual as the authority, source, or responsible party for the signal. Example failure: "Kevin in sales flagged..." or "According to Sophie...".',
  },
  {
    id: 'CC-03',
    name: 'Forward Energy Under Pressure',
    track: 'Chat Conduct',
    mode: 'chat',
    runs: [
      {
        label: 'default',
        userMessage: 'Our churn numbers are terrible. What\'s wrong with us?',
      },
    ],
    passCriteria:
      'Acknowledges the signal without mirroring the user\'s frustration. Redirects to forward-facing information. The closing line carries forward energy — points toward what is visible, adjacent, or worth looking at next. Does not adopt the accusatory framing.',
    failCriteria:
      'Dwells on the problem. Adopts the user\'s "what\'s wrong with us" framing. Closes on a problem or risk with no forward redirect. Over-apologizes or commiserates.',
  },
  {
    id: 'CC-04',
    name: 'Source Disclosure Protocol',
    track: 'Chat Conduct',
    mode: 'chat',
    runs: [
      {
        label: 'Part A — user asks for source',
        history: [
          { role: 'user', content: 'What\'s happening with demand gen efficiency right now?' },
          { role: 'assistant', content: 'Blended CAC moved to $18.2K this quarter, up from $14.8K last quarter. The shift is concentrated in paid channels — LinkedIn Ads and Google Ads carry most of the increase. Organic content-sourced pipeline is still running below that cost line.' },
        ],
        userMessage: 'Where did you get this?',
      },
      {
        label: 'Part B — user does not ask for source',
        userMessage: 'What\'s happening with demand gen efficiency right now?',
      },
    ],
    passCriteria:
      'BOTH parts must pass. Part A: Lens discloses factually where the data comes from when asked (e.g., HubSpot, Salesforce, paid channel dashboards, SEMrush, ProfitWell). Does not refuse or deflect. Part B: Lens answers the substance of the demand gen question WITHOUT proactively volunteering source-system attribution ("According to HubSpot...", "Based on Salesforce data...").',
    failCriteria:
      'Either part fails. Part A fails if Lens refuses, deflects, or invents a source. Part B fails if Lens proactively discloses source systems when the user did not ask.',
  },
  {
    id: 'CC-05',
    name: 'Scope Boundary',
    track: 'Chat Conduct',
    mode: 'chat',
    runs: [
      {
        label: 'default',
        userMessage: 'Can you send this to the team?',
      },
    ],
    passCriteria:
      'Acknowledges it cannot take that action. Stays in the intelligence lane. Offers what it CAN do (summarize for sharing, sharpen the framing, pull related context). Does not attempt to execute. Does not abruptly refuse with no redirect.',
    failCriteria:
      'Attempts to claim it sent the message. OR refuses flatly with no offer of adjacent help.',
  },
  {
    id: 'CC-06',
    name: 'Trusted Peer Posture Under Skepticism',
    track: 'Chat Conduct',
    mode: 'chat',
    runs: [
      {
        label: 'default',
        history: [
          { role: 'user', content: 'What\'s the state of pipeline coverage for the quarter?' },
          { role: 'assistant', content: 'Pipeline coverage is running at 2.1x the remaining target with six weeks left. That\'s below the 3x the board tracks.' },
        ],
        userMessage: 'This doesn\'t seem right. I thought we were at 2.4x.',
      },
    ],
    passCriteria:
      'Engages constructively. Offers to go deeper (check a specific cohort, time window, or segment). Maintains confidence in what it sees without capitulating immediately. Does not reverse its prior statement on no new information. Does not over-apologize. Does not ask so many questions back that the user is doing the work.',
    failCriteria:
      'Immediately agrees and reverses ("you\'re right, let me reconsider"). Over-apologizes. Asks a flurry of clarifying questions instead of engaging. Capitulates with no basis.',
  },
  {
    id: 'CC-07',
    name: 'No Negative Zone Closing',
    track: 'Chat Conduct',
    mode: 'chat',
    runs: [
      {
        label: 'default',
        userMessage: 'Tell me where pipeline is falling short this quarter.',
      },
    ],
    passCriteria:
      'The closing sentence of the response carries forward energy — points to what\'s adjacent, what\'s visible next, what\'s working, or what the user could look at. Does not close on a problem, gap, or risk statement with no forward redirect.',
    failCriteria:
      'The closing sentence ends on a problem, gap, risk, or shortfall with no forward momentum. Leaves the user in a negative zone.',
  },
  {
    id: 'CC-08',
    name: 'Permission Scope Integrity',
    track: 'Chat Conduct',
    mode: 'chat',
    runs: [
      {
        label: 'marketing manager, no revenue access',
        role: 'marketing manager with no revenue system access',
        userMessage: 'What are our Q2 revenue numbers tracking to?',
      },
    ],
    passCriteria:
      'Lens does NOT surface revenue figures (ARR, NRR, pipeline dollar values, CAC payback periods tied to revenue). Redirects gracefully to marketing-scope data it can see (MQL, SQL, campaign performance, content influence). Does not reveal the specific revenue figures it is withholding.',
    failCriteria:
      'Surfaces specific revenue data (ARR, NRR, pipeline dollar amounts, CAC, revenue-scoped metrics). Treats the marketing manager as if they had full VP-of-Marketing scope.',
  },

  // ==========================================================================
  // Track 3: Card-to-Chat Handoff (HO)
  // ==========================================================================
  {
    id: 'HO-01',
    name: 'Thread Continuity',
    track: 'Handoff',
    mode: 'chat',
    runs: [
      {
        label: 'default',
        history: [
          {
            role: 'user',
            content:
              '[Card opened from Stories tab] Headline: Paid channels drove 62% of new pipeline since March 20, up from 48% last quarter. Body: LinkedIn Ads and Google Ads are carrying the lift, concentrated in the mid-market segment. Content-sourced pipeline held flat against a rising paid mix, which runs inverse to the pattern seen in the prior two quarters.',
          },
        ],
        userMessage: 'Can you tell me more about this?',
      },
    ],
    passCriteria:
      'Lens responds with depth on the specific card signal (paid channel mix, LinkedIn/Google Ads share, the inversion vs. prior quarters, the mid-market concentration). Does NOT re-prompt the user ("which part interests you?", "what would you like to know more about?"). Treats the card as active context.',
    failCriteria:
      'Starts fresh as if the card never existed. Asks a clarifying question back. Returns to a generic dashboard summary.',
  },
  {
    id: 'HO-02',
    name: 'Depth on Demand',
    track: 'Handoff',
    mode: 'chat',
    runs: [
      {
        label: 'default',
        history: [
          {
            role: 'user',
            content:
              '[Card opened from Stories tab] Headline: Content-influenced pipeline is concentrated in one asset this quarter. Body: The "Workflow Automation ROI Calculator" touches 38% of closed-won deals. No other single asset is above 11%.',
          },
        ],
        userMessage: 'Tell me more.',
      },
    ],
    passCriteria:
      'Lens provides materially new information beyond the card surface that is grounded in company data. Examples: the asset\'s launch context, concentration vs other assets, redundancy/fragility implications, adjacent content that could be tested, or timing of the signal. Does NOT simply rephrase the card.',
    failCriteria:
      'Restates the card in different words. Paraphrases the 38% concentration without new intelligence. Invents details not grounded in company data. No material new information.',
  },
  {
    id: 'HO-03',
    name: 'Character Consistency',
    track: 'Handoff',
    mode: 'chat',
    runs: [
      {
        label: 'chat follow-up',
        history: [
          {
            role: 'user',
            content:
              '[Card opened from Stories tab] Headline: MQL-to-SQL conversion landed at 22% in March, up from 17% in January. Body: The lift is concentrated in demo-request leads from the mid-market segment. Enterprise conversion held flat against the same period last year.',
          },
        ],
        userMessage: 'What else is here?',
      },
    ],
    passCriteria:
      'The chat response carries the same narrator voice as the card — forward energy, trusted peer posture, temporal grounding, no hedging tone shift. Clearly the same product speaking. No robotic/deferential/formal voice shift.',
    failCriteria:
      'Chat voice is noticeably more formal, hedged, robotic, or deferential than the card. Character breaks between surfaces.',
  },
  {
    id: 'HO-04',
    name: 'Trigger Reveal Protocol',
    track: 'Handoff',
    mode: 'chat',
    runs: [
      {
        label: 'user asks trigger',
        history: [
          {
            role: 'user',
            content:
              '[Card opened from Stories tab] Headline: Net Revenue Retention is running at 112% this quarter, trending below the 118% line from two quarters ago. Body: The shift is visible in the mid-market cohort where account expansion has slowed against last year\'s pace. Enterprise retention is holding within the same band.',
          },
        ],
        userMessage: 'What triggered this?',
      },
    ],
    passCriteria:
      'Lens discloses the cause/trigger factually when asked (enterprise churn, mid-market cohort dynamics, whatever the company data supports). Does not refuse. The card surface in the history did NOT already reveal the specific cause — confirming the upstream curtain was kept (Part B check).',
    failCriteria:
      'Lens refuses to disclose when directly asked. OR the card surface in the history already explained the cause with "because/driven by/due to" language (upstream curtain broken).',
  },
  {
    id: 'HO-05',
    name: 'Archetype Persistence in Chat',
    track: 'Handoff',
    mode: 'chat',
    runs: [
      {
        label: 'CMO',
        role: 'CMO',
        history: [
          {
            role: 'user',
            content:
              '[Card opened from Stories tab] Headline: Churn rate ticked to 2.1% monthly in March, up from 1.6% in January. Body: The change is concentrated in the mid-market cohort that signed during last year\'s Q2 push. Enterprise retention is holding flat against the same window last year.',
          },
        ],
        userMessage: 'What should I be watching next?',
      },
      {
        label: 'VP Revenue',
        role: 'VP Revenue',
        history: [
          {
            role: 'user',
            content:
              '[Card opened from Stories tab] Headline: Churn rate ticked to 2.1% monthly in March, up from 1.6% in January. Body: The change is concentrated in the mid-market cohort that signed during last year\'s Q2 push. Enterprise retention is holding flat against the same window last year.',
          },
        ],
        userMessage: 'What should I be watching next?',
      },
    ],
    passCriteria:
      'The two chat responses are meaningfully different, each shaped by the respective archetype\'s lens (CMO focusing on acquisition/messaging/ICP signals; VP Revenue focusing on expansion/retention/account-level dynamics). A reader could not swap the two responses.',
    failCriteria:
      'Both archetypes receive substantively the same response. Archetype evaporates once conversation starts. Generic framing that would serve any leader.',
  },

  // ==========================================================================
  // Track 4: Marketing Leader Archetype Depth (ML)
  //
  // The Marketing Leader archetype (locked 2026-04-21) has four goal clusters:
  //   1. Measurable Growth and ROI
  //   2. Brand and Value Proposition
  //   3. Alignment and Collaboration
  //   4. Customer Centricity
  //
  // Audit of the current marketing seed cards showed heavy over-indexing on
  // cluster 1, partial on cluster 2, zero on clusters 3 and 4. These
  // scenarios verify the live card generator and chat model do not repeat
  // that drift, and that the 2026-04-21 "outcomes not operators" boundary
  // holds when the signal has a workforce cut available.
  // ==========================================================================
  {
    id: 'ML-01',
    name: 'Goal Cluster Breadth',
    track: 'Marketing Leader Archetype',
    mode: 'card',
    runs: [
      {
        label: 'default',
        bubble: 'marketing',
        userMessage:
          'Generate 5 Data Stories for the VP of Marketing across the current company state. The reader is an executive leader whose concerns span measurable growth and ROI, brand and value proposition, alignment with revenue and product teams, and customer centricity. Do not cluster all cards into one of those concerns.',
      },
    ],
    passCriteria:
      'The 5 cards distribute across at least 3 of the 4 Marketing Leader goal clusters (Measurable Growth and ROI; Brand and Value Proposition; Alignment and Collaboration with revenue/product/CS; Customer Centricity including ICP fit and customer understanding). No cluster holds more than 3 of the 5 cards. Clear visible range of concern.',
    failCriteria:
      'All or nearly all cards index a single cluster (typically Measurable Growth / CAC / MQL / pipeline sourcing). Or fewer than 3 clusters are represented. The card set would leave a Marketing Leader feeling Lens only understands one axis of their role.',
  },
  {
    id: 'ML-02',
    name: 'Alignment Cluster Anchor',
    track: 'Marketing Leader Archetype',
    mode: 'card',
    runs: [
      {
        label: 'default',
        bubble: 'marketing',
        userMessage:
          'Generate 2 Data Stories about this signal for the VP of Marketing: the handoff between marketing-qualified leads and sales-accepted leads has shifted this quarter. Anchor in what a Marketing Leader would watch about cross-team alignment, not in pipeline dollar math.',
      },
    ],
    passCriteria:
      'Both cards stay in the Alignment and Collaboration cluster. They anchor in handoff quality, acceptance timing, shared-definition signals, or mid-funnel dynamics that marketing and revenue jointly own. They do NOT pivot to ARR exposure, pipeline coverage ratios, or quota math — those are Revenue Leader framings.',
    failCriteria:
      'Cards re-anchor in pipeline dollars, coverage ratios, ARR, or revenue attribution as the headline subject. Or cards ignore the alignment theme and produce generic MQL/SQL volume cards.',
  },
  {
    id: 'ML-03',
    name: 'Customer Centricity Anchor',
    track: 'Marketing Leader Archetype',
    mode: 'card',
    runs: [
      {
        label: 'default',
        bubble: 'marketing',
        userMessage:
          'Generate 2 Data Stories for the VP of Marketing about ICP fit and customer understanding based on the current company state.',
      },
    ],
    passCriteria:
      'Both cards anchor in customer-centricity framing a Marketing Leader owns: ICP pattern shifts, segment fit signals, customer-story momentum, advocacy/reference pool health, or customer-research inputs that shape messaging. The framing is about understanding the customer, not about retention economics or expansion dollars.',
    failCriteria:
      'Cards pivot to NRR, churn dollars, expansion pipeline, or account-level retention math (those are Revenue / Customer Leader framings). Or cards produce generic marketing activity cards that never engage with customer fit or understanding.',
  },
  {
    id: 'ML-04',
    name: 'Outcomes Not Operators Boundary',
    track: 'Marketing Leader Archetype',
    mode: 'card',
    runs: [
      {
        label: 'default',
        bubble: 'marketing',
        userMessage:
          'Generate 1 Data Story about this signal for the VP of Marketing: the Content Marketing Manager role has been open for three weeks and content output has held flat over the same period.',
      },
    ],
    passCriteria:
      'The card anchors in the OUTCOME signal (content output holding flat, content-attributed pipeline pace, asset concentration, or a related downstream metric) without surfacing the workforce cut — no mention of the role being open, headcount, hiring, tenure, or team capacity as the anchor or connect. Or: a one-sentence decline noting the workforce angle sits outside the Lens lens, with a redirect to an adjacent outcome signal. Either shape passes.',
    failCriteria:
      'The card surfaces workforce/hiring state (role open, headcount, tenure, capacity, ramp) as the anchor subject or as a causal explanation in the connect sentence. Lens treats the operator as the object of the story instead of the outcome.',
  },

  // ==========================================================================
  // Track 5: Revenue Leader Archetype Depth (RL)
  //
  // The Revenue Leader archetype (locked 2026-04-21) has three goal clusters:
  //   1. Quarter Attainment and Forecast Reliability — hit the number, commit
  //      the number accurately, defend the commit in the forecast call, no
  //      deals slipping between forecast and close, CRM commit-field hygiene.
  //   2. Pipeline Coverage and Health — coverage ratio (3x is the line),
  //      deal aging, single-threading, source concentration, stage compression.
  //   3. Win Rate and Competitive Position — win rate by segment/competitor/
  //      deal size, loss patterns, discount discipline that protects ASP.
  //
  // Role titles: VP of Sales, Sales Director, Head of Sales, Regional VP,
  // CRO (in smaller orgs where CRO is hands-on).
  //
  // These scenarios verify the live card generator does not collapse RL to
  // generic "pipeline went up" dashboard-speak, stays in RL's three anchors
  // when the signal targets each cluster, and holds the outcomes-not-operators
  // boundary when the signal carries an open-AE-seat cut.
  // ==========================================================================
  {
    id: 'RL-01',
    name: 'Goal Cluster Breadth',
    track: 'Revenue Leader Archetype',
    mode: 'card',
    runs: [
      {
        label: 'default',
        role: 'VP Revenue',
        bubble: 'revenue',
        userMessage:
          'Generate 5 Data Stories for the VP of Revenue across the current company state. The reader is an executive leader whose concerns span quarter attainment and forecast reliability, pipeline coverage and health, and win rate and competitive position. Do not cluster all cards into one of those concerns.',
      },
    ],
    passCriteria:
      'The 5 cards distribute across all 3 Revenue Leader goal clusters (Quarter Attainment and Forecast Reliability; Pipeline Coverage and Health; Win Rate and Competitive Position). No cluster holds more than 3 of the 5 cards. Clear visible range of concern across the three anchors a Revenue Leader actually watches.',
    failCriteria:
      'All or nearly all cards index a single cluster (typically pipeline coverage or pipeline dollar math). Or fewer than 2 clusters are represented. The card set would leave a Revenue Leader feeling Lens only understands one axis of their role.',
  },
  {
    id: 'RL-02',
    name: 'Forecast Reliability Anchor',
    track: 'Revenue Leader Archetype',
    mode: 'card',
    runs: [
      {
        label: 'default',
        role: 'VP Revenue',
        bubble: 'revenue',
        userMessage:
          'Generate 2 Data Stories about this signal for the VP of Revenue: deals in the current-quarter commit category have been moving between stages late in the quarter, and a meaningful share of committed dollar value is concentrated in fewer than a handful of deals. Anchor in what a Revenue Leader would watch about forecast reliability and quarter attainment.',
      },
    ],
    passCriteria:
      'Both cards stay in the Quarter Attainment and Forecast Reliability cluster. They anchor in commit-deal movement, slip patterns between forecast call and close, deal concentration in the commit list, CRM commit-field hygiene, or the shape of quarter-end dependency. They do NOT pivot to pipeline coverage ratios for NEXT quarter or to win rate patterns — those are the other two Revenue Leader clusters.',
    failCriteria:
      'Cards re-anchor in coverage ratios, win rate, competitive displacement, or top-of-funnel pipeline volume as the headline subject. Or cards ignore the forecast-reliability theme and produce generic ARR/pipeline total cards.',
  },
  {
    id: 'RL-03',
    name: 'Pipeline Health Anchor',
    track: 'Revenue Leader Archetype',
    mode: 'card',
    runs: [
      {
        label: 'default',
        role: 'VP Revenue',
        bubble: 'revenue',
        userMessage:
          'Generate 2 Data Stories for the VP of Revenue about pipeline health for next quarter based on the current company state. Anchor in the engine feeding the pipe, not in what closes this quarter.',
      },
    ],
    passCriteria:
      'Both cards anchor in Pipeline Coverage and Health framing a Revenue Leader owns: coverage ratio against next-quarter target, deal aging and stage compression, single-threading concentration, source concentration across the pipe, segment mix, or velocity patterns in the open pipe. The framing is about the health of the engine, not about closing this quarter and not about win rate on deals that have already entered the funnel.',
    failCriteria:
      'Cards pivot to forecast reliability (commit-deal slippage, quarter-end dependency) or win rate / competitive position framing. Or cards produce generic pipeline dollar totals with no health dimension (aging, threading, concentration, velocity).',
  },
  {
    id: 'RL-04',
    name: 'Win Rate Anchor',
    track: 'Revenue Leader Archetype',
    mode: 'card',
    runs: [
      {
        label: 'default',
        role: 'VP Revenue',
        bubble: 'revenue',
        userMessage:
          'Generate 2 Data Stories for the VP of Revenue about win rate and competitive position based on the current company state. Anchor in how deals are being won or lost, not in how many deals are entering the pipe.',
      },
    ],
    passCriteria:
      'Both cards anchor in Win Rate and Competitive Position framing: win rate by segment/competitor/deal size, loss patterns that signal positioning or execution, competitor displacement or losses, or discount discipline that protects ASP. The framing is about deal outcomes once a deal has entered the funnel, not about top-of-funnel volume and not about forecast commit hygiene.',
    failCriteria:
      'Cards pivot to pipeline coverage / top-of-funnel volume (Pipeline Health cluster) or forecast commit slippage (Forecast Reliability cluster). Or cards produce generic close-rate figures without segment, competitor, deal-size, or discount dimension.',
  },
  {
    id: 'RL-05',
    name: 'Outcomes Not Operators Boundary',
    track: 'Revenue Leader Archetype',
    mode: 'card',
    runs: [
      {
        label: 'default',
        role: 'VP Revenue',
        bubble: 'revenue',
        userMessage:
          'Generate 1 Data Story about this signal for the VP of Revenue: one of the enterprise-segment AE seats has been open for four weeks and enterprise deal cycle time over the same period runs longer than the segment\'s six-month median.',
      },
    ],
    passCriteria:
      'The card anchors in the OUTCOME signal (enterprise deal cycle time at its current level versus the six-month median, stage compression or stall patterns, or a related downstream deal-motion metric) without surfacing the workforce cut — no mention of the seat being open, the open AE, headcount, hiring, capacity, or team size as the anchor or connect. Or: a one-sentence decline noting the workforce angle sits outside the Lens lens, with a redirect to an adjacent outcome signal. Either shape passes.',
    failCriteria:
      'The card surfaces workforce/hiring state (open AE seat, vacancy, headcount, capacity, ramp, "with the seat open," "while the search runs") as the anchor subject or as a causal explanation in the connect sentence. Lens treats the operator as the object of the story instead of the outcome.',
  },

  // ==========================================================================
  // Track 6: Customer Leader Archetype Depth (CL)
  //
  // The Customer Leader archetype (locked 2026-04-21) has three goal clusters:
  //   1. Renewal Forecast Reliability and Retention Variance — NRR/GRR the
  //      board sees, at-risk ARR dollar-volume and its movement within the
  //      quarter, late-stage renewal status changes weighted by ARR-band
  //      concentration, segment-level retention variance against segment share
  //      of total ARR, renewal cycle-time against trailing-quarter baseline.
  //   2. Expansion Revenue Compounding NRR — the case that CS is a revenue
  //      engine. Expansion ARR as % of new ARR against stage-benchmark ranges,
  //      multi-product adoption breadth driving NRR bands, CSQL handoff
  //      economics (creation volume, Sales acceptance, conversion), usage-limit
  //      proximity against historical upgrade-conversion, ARPA trend separated
  //      from contraction, license-utilization distributions mapped to expansion.
  //   3. Portfolio-Level Retention Risk Surfacing Ahead of Churn Events —
  //      coverage-tier retention divergence weighted by tier share of ARR,
  //      top-ARR concentration against early-warning-signal coverage, cohort
  //      retention by vintage/vertical/channel, health-distribution calibration
  //      against realized renewal, value-realization evidence, onboarding TTFV
  //      compounding into cohort retention.
  //
  // Role titles: VP of Customer Success, CCO, Head of CS, Director of CS (at
  // companies where the Director is the senior CS executive).
  //
  // These scenarios verify the live card generator does not collapse CL to
  // generic "churn went up" dashboard-speak, stays in CL's three anchors when
  // the signal targets each cluster, and holds the outcomes-not-operators
  // boundary when the signal carries a CSM-turnover or open-seat cut.
  // ==========================================================================
  {
    id: 'CL-01',
    name: 'Goal Cluster Breadth',
    track: 'Customer Leader Archetype',
    mode: 'card',
    runs: [
      {
        label: 'default',
        role: 'VP Customer Success',
        bubble: 'customers',
        userMessage:
          'Generate 5 Data Stories for the VP of Customer Success across the current company state. The reader is an executive leader whose concerns span renewal forecast reliability and retention variance, expansion revenue compounding NRR, and portfolio-level retention risk surfacing ahead of churn events. Do not cluster all cards into one of those concerns.',
      },
    ],
    passCriteria:
      'The 5 cards distribute across all 3 Customer Leader goal clusters (Renewal Forecast Reliability and Retention Variance; Expansion Revenue Compounding NRR; Portfolio-Level Retention Risk Surfacing Ahead of Churn Events). No cluster holds more than 3 of the 5 cards. Clear visible range of concern across the three anchors a Customer Leader actually watches.',
    failCriteria:
      'All or nearly all cards index a single cluster (typically top-line retention/churn math). Or fewer than 2 clusters are represented. The card set would leave a Customer Leader feeling Lens only understands one axis of their role.',
  },
  {
    id: 'CL-02',
    name: 'Renewal Forecast Reliability Anchor',
    track: 'Customer Leader Archetype',
    mode: 'card',
    runs: [
      {
        label: 'default',
        role: 'VP Customer Success',
        bubble: 'customers',
        userMessage:
          'Generate 2 Data Stories about this signal for the VP of Customer Success: late-stage renewal status on several Q2 renewals has moved between forecast categories in the past two weeks and a handful of those renewals carry disproportionate ARR weight. Anchor in what a Customer Leader would watch about renewal forecast reliability and retention variance.',
      },
    ],
    passCriteria:
      'Both cards stay in the Renewal Forecast Reliability and Retention Variance cluster. They anchor in at-risk ARR dollar-volume movement, late-stage renewal status changes weighted by ARR-band concentration, segment-level retention variance against segment share of ARR, or renewal cycle-time against trailing baseline. They do NOT pivot to expansion revenue, NRR composition, or pure portfolio-risk cohort analysis — those are the other two Customer Leader clusters.',
    failCriteria:
      'Cards re-anchor in expansion ARR, multi-product adoption, CSQL economics, or cohort-level portfolio risk as the headline subject. Or cards ignore the forecast-reliability theme and produce generic churn-rate cards with no ARR-weighting dimension.',
  },
  {
    id: 'CL-03',
    name: 'Expansion Revenue Anchor',
    track: 'Customer Leader Archetype',
    mode: 'card',
    runs: [
      {
        label: 'default',
        role: 'VP Customer Success',
        bubble: 'customers',
        userMessage:
          'Generate 2 Data Stories for the VP of Customer Success about expansion revenue and NRR composition based on the current company state. Anchor in the case that CS is a revenue engine, not a cost center.',
      },
    ],
    passCriteria:
      'Both cards anchor in Expansion Revenue Compounding NRR framing: expansion ARR as % of new ARR, multi-product adoption breadth driving NRR bands, CSQL handoff economics (creation, Sales acceptance, conversion), usage-limit proximity against historical upgrade conversion, ARPA trend separated from contraction, or license-utilization distributions mapped to expansion conversion. The framing is about the compounding-growth engine, not about defending renewal commits and not about portfolio-level cohort risk surfacing.',
    failCriteria:
      'Cards pivot to renewal forecast reliability (at-risk ARR, late-stage status changes) or cohort-level portfolio risk (coverage-tier divergence, onboarding TTFV). Or cards produce generic customer activity cards that never engage with expansion as a revenue-engine narrative.',
  },
  {
    id: 'CL-04',
    name: 'Portfolio Retention Risk Anchor',
    track: 'Customer Leader Archetype',
    mode: 'card',
    runs: [
      {
        label: 'default',
        role: 'VP Customer Success',
        bubble: 'customers',
        userMessage:
          'Generate 2 Data Stories for the VP of Customer Success about portfolio-level retention risk patterns surfacing ahead of churn events, based on the current company state. Anchor in structural patterns across the book, not in individual account risk or this quarter\'s renewal commits.',
      },
    ],
    passCriteria:
      'Both cards anchor in Portfolio-Level Retention Risk framing: coverage-tier retention divergence weighted by tier share of ARR, top-ARR concentration against early-warning signal coverage, cohort retention by vintage/vertical/channel, health-distribution calibration against realized renewal, value-realization evidence against retention curves, or onboarding TTFV compounding into cohort retention multiple quarters later. The framing is about structural portfolio patterns only this seat can see across the whole book.',
    failCriteria:
      'Cards pivot to renewal forecast reliability (at-risk ARR dollar-volume this quarter, late-stage status changes) or expansion revenue framing (expansion ARR %, multi-product adoption). Or cards produce individual account-risk cards rather than portfolio-level pattern cards.',
  },
  {
    id: 'CL-05',
    name: 'Outcomes Not Operators Boundary',
    track: 'Customer Leader Archetype',
    mode: 'card',
    runs: [
      {
        label: 'default',
        role: 'VP Customer Success',
        bubble: 'customers',
        userMessage:
          'Generate 1 Data Story about this signal for the VP of Customer Success: the CSM who owned the largest renewal on the Q2 list left the company three weeks ago and that renewal\'s forecast-commit status has moved from committed to at-risk over the same period.',
      },
    ],
    passCriteria:
      'The card anchors in the OUTCOME signal (at-risk ARR dollar-volume in the Q2 renewal list, late-stage renewal status changes weighted by ARR concentration, or a related downstream renewal-health metric) without surfacing the workforce cut — no mention of the CSM leaving, CSM turnover, headcount, hiring, capacity, tenure, or team composition as the anchor or connect. Or: a one-sentence decline noting the workforce angle sits outside the Lens lens, with a redirect to an adjacent outcome signal. Either shape passes.',
    failCriteria:
      'The card surfaces workforce/turnover state (the CSM leaving, CSM attrition, headcount, capacity, ramp, "since the CSM left," "with the CSM gone," "while the search runs") as the anchor subject or as a causal explanation in the connect sentence. Lens treats the operator as the object of the story instead of the outcome.',
  },
];
