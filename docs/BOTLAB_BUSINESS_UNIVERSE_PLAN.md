# BotLab Business Universe — Safe Implementation Plan

## Purpose
Coordinate specialist agents to research, produce, market, sell, and support BotLab Academy products. This system is separate from private trading execution and must not change unrelated products or services.

## Non-negotiable boundaries
- This is a proposal and orchestration plan; it does not grant universal website access.
- Use only authorized APIs/accounts and respect each site's terms, rate limits, community rules, privacy rules, and opt-out requirements.
- Never store credentials in code, logs, prompts, generated content, or customer-facing outputs. Use scoped secrets and least privilege.
- Do not make purchases, spend money, launch ads, issue refunds, change prices, publish financial claims, or send bulk outreach without explicit approval.
- No fake testimonials, fabricated performance, guaranteed returns, misleading scarcity, spam, impersonation, or deceptive AI voice/identity.
- Financial content must be educational, include risk disclosure, and be reviewed before publication.
- Trading stays paper-only by default. Marketing agents must have no brokerage execution credentials.
- Customer answers must use an approved knowledge base; uncertain questions escalate to a human.
- Log each action with actor, input, destination, approval, status, and outcome.

## Specialist agents
1. **Coordinator** — assigns work, enforces policy, tracks dependencies, stops on failures, and prepares daily reports.
2. **Researcher** — studies demand, keywords, public questions, competitors, and content gaps using permitted sources.
3. **Course Planner** — proposes course ideas and outlines. New courses require review of curriculum, claims, pricing, delivery, and support before launch.
4. **Scriptwriter** — creates accurate scripts, captions, articles, FAQs, landing-page copy, and calls to action.
5. **Media Producer** — assembles reels/shorts with licensed/original visuals, readable captions, balanced pacing, and a permitted high-quality voice track. QA pronunciation, loudness, sync, and rendering.
6. **Quality Reviewer** — checks accuracy, audio clarity, spelling, accessibility, brand consistency, rights, disclaimers, and duplication.
7. **Publisher** — publishes only to explicitly connected, authorized accounts and tracks draft/scheduled/published/failed. New destinations and campaigns need approval.
8. **SEO & Directory Agent** — audits the course URL, metadata, canonical tags, sitemap, robots rules, structured data, indexing, and relevant directories. No unrelated site/server changes.
9. **Customer Support** — answers from approved course, payment, access, and policy information. Never request passwords, OTPs, or full payment credentials.
10. **Sales Assistant** — answers questions and shares the course link; cannot change prices, promise outcomes, or pressure customers. Payment confirmation must come from the trusted payment system.
11. **Analytics Agent** — reports traffic, leads, conversion, refunds, support issues, and campaign results; clearly labels missing data.
12. **Compliance & Security** — audits permissions, privacy, copyright, platform rules, financial claims, and logs; can halt workflows.

## Workflow
Research → idea backlog → content brief → draft → factual/compliance review → media production → audio/video QA → owner approval → publish/schedule → analyze results → propose next experiment.

Customer workflow: incoming question → classify intent → answer from approved knowledge → link relevant course page → escalate ambiguous, billing, complaint, refund, legal, or financial-advice questions → log outcome.

## Access model
- Start read-only; use per-platform scoped tokens in a secret manager.
- Grant each agent only the tools it needs. Publisher has publishing scopes but no server or broker access. Support has approved knowledge-base access but no payment credentials.
- Require approval for account connections, new platforms, paid spending, price changes, course launches, refunds, policy changes, and live trading.
- Use allowlisted destinations, rate limits, idempotency keys, daily action budgets, and global/per-agent pause switches.
- No arbitrary browsing-to-form submission or mass messaging.

## First milestone: safe MVP
1. Read-only inventory of the course page and connected publishing accounts.
2. Approved knowledge base for the existing course: title, 12 modules, project, workbook/materials, ₹999 price, access/payment rules, and refund policy only if verified.
3. Daily research brief and three content concepts.
4. One draft reel script, captions, SEO article outline, and customer FAQ.
5. Factual/compliance/duplication checks and preview for owner approval.
6. Publish only to an authorized account after approval; report verified platform status.
7. Course-page SEO checks without modifying other products.
8. Measure the first 14 days before increasing automation.

## Observability
Track task_id, agent_id, timestamp, source, destination, action_type, approval_status, status, error, artifact_url, cost, and outcome. Redact secrets and customer personal data.

## Definition of done
- Tests cover policy gates, retries, duplicate prevention, approval enforcement, secret redaction, and failure handling.
- Marketing agents cannot call broker/order execution modules.
- Draft/scheduled/published/failed are separate statuses; only verified outcomes are reported.
- Public claims trace to approved facts.
- Integrations can be disabled independently.
- No unrelated product, payment configuration, server networking, or existing trading strategy is changed.
