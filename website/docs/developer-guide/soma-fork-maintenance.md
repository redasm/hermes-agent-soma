# Hermes Agent Soma fork maintenance policy

This fork is the runtime host for Soma, not the home of the companion domain.
Its permanent delta from upstream must stay generic enough to serve other
plugins and must not contain Soma personality, relationship, affect, interest,
or simulated-life rules.

## Current fork delta

The first host batch is already merged:

- `81ac03996 feat(cron): add companion delivery host contract`
- merged by `770b8bfa0`
- upstream synchronized by `f0a117280`

That batch adds four optional, backward-compatible cron fields
(`response_mode`, `attach_to_session`, `context_provider`, and private
`metadata`), bounded `cron_context`, and post-delivery `cron_delivery`
receipts. This is the right kind of fork change: it is a general scheduling and
delivery contract with no Soma domain imports.

The following generic host batches are now also implemented:

- versioned plugin capability discovery and a plugin → scheduler → delivery receipt E2E test;
- scoped profile, timezone, and browser-authorization observations;
- Windows OS-mediated location with explicit `granted | denied | unavailable` status and no IP fallback.

Focused verification on 2026-07-16:

```text
36 passed in 4.18s
```

The wider focused selection reached `77 passed, 1 failed`; the single failure
occurred while importing `gateway.run` because the local Windows environment
lacked `concurrent_log_handler`, before the tested gateway-drain behavior ran.
It is an environment dependency gap, not evidence that the cron contract
failed.

## What belongs in this fork

Only host/runtime capabilities belong here:

| Capability | Host responsibility |
| --- | --- |
| Scheduling | Durable jobs, wake-up, retry, pause/delete, execution identity |
| Scheduled context | Invoke a named plugin provider and inject bounded ephemeral context without changing the cached system prompt |
| Delivery | Resolve platform targets, send text/media, attach a turn to a session, return a structured receipt |
| Origin identity | Provide opaque profile/platform/chat/thread/user/session keys with strict tenant isolation |
| Tool execution | Discover and dispatch configured tools with structured success/error results |
| Web and browser | Own search providers, browser processes, authenticated sessions, approvals, and access-control enforcement |
| Device context | Expose system timezone and explicitly authorized location/device observations |
| Secrets and config | Store provider credentials in normal Hermes configuration/secret mechanisms; never put them in prompts or receipts |
| Plugin lifecycle | Stable hook registration, capability discovery, state-directory conventions, shutdown and upgrade behavior |
| Observability | Redacted operational logs and host-level health; no relationship-content analytics by default |

These APIs must use neutral names and contracts. A hook may be motivated by
Soma, but it must not import Soma or encode assumptions such as “girlfriend”,
“mood”, “life moment”, or a specific social platform.

## What must stay outside this fork

The following belong to the `ethos-soma` package:

- identity constitution, OCEAN personality, VAD affect, trust and relationship state;
- preferred conversational language inferred from long-term interaction;
- quiet-hours policy, outreach budgets, interruption cost and the decision to stay silent;
- interest profiles, topic continuity, relevance ranking and discovery deduplication;
- real/simulated world separation, life events, autobiographical journal and visual identity;
- companion goals, commitments, outcomes, preference learning and behavior evaluation;
- prompt composition that turns grounded evidence into a natural companion message;
- companion data export, correction and deletion semantics.

Platform-specific X, Weibo, Xiaohongshu, Google Places, or sports connectors do
not belong in the Hermes core either. Prefer an existing host tool, an MCP
server, a service-gated provider, or a separately installed plugin. Hermes owns
the authenticated browser/session boundary; a connector owns platform parsing;
Soma consumes normalized candidates and decides whether they are worth sharing.

## Commit and upstream-sync policy

Do not combine upstream synchronization with local product changes.

1. `sync(upstream): ...` — merge or rebase an upstream release with no new Soma-host behavior.
2. `feat|fix(cron|plugins|gateway|tools): ...` — one generic host contract or bug fix plus its tests.
3. `docs(soma-host): ...` — contract and compatibility documentation.
4. Update the compatibility matrix only after the matching Soma adapter tests pass.

Each feature commit must be independently revertible. Avoid a long-lived pile
of edits on `main`; use a focused `codex/...` branch, run the affected upstream
tests, merge it, and then synchronize upstream in a separate commit. Prefer
upstreaming generic host patches. Fork-only behavior should be limited to
changes that upstream has not yet accepted or that are deliberately product
distribution concerns.

## Next host batches

The order below is dependency-driven. Companion-domain work is intentionally
absent.

### H1 — Harden the existing cron contract (implemented)

- Preserve `response_mode`, provider, origin identity and private metadata through all create/update/list/dashboard/gateway paths.
- Prove metadata and captured session identity never appear in generated text or public job responses.
- Add an end-to-end test with a real temporary `HERMES_HOME`, plugin hooks, scheduler execution and a fake delivery adapter.
- Document version/capability detection so an older plugin can degrade safely.

Exit gate: the end-to-end receipt identifies one execution and one delivery
target without exposing correlation IDs to the user.

### H2 — Stable plugin runtime capabilities (implemented foundation)

- Add a structured capability query for scheduler, delivery, search, browser, image and location services.
- Return typed/structured dispatch errors instead of requiring plugins to parse strings.
- Stabilize `TurnOrigin`/target identity and plugin-scoped state paths.

Exit gate: a plugin can select a supported path without guessing tool names or
matching English error text.

### H3 — Authorized real-world observations (timezone/location implemented)

- Expose the configured system timezone as structured host context.
- Add an explicit-permission location observation contract; desktop OS location and platform-shared location are providers, not silent IP geolocation.
- Expose browser-session availability and authorization provenance without exposing cookies or tokens.

Exit gate: plugins receive only the minimum observation needed, can distinguish
unavailable from denied, and cannot access credentials.

### H4 — Search/browser provider surface (capability discovery implemented)

- Keep `web_search` as the public-web primitive.
- Provide a generic way for installed MCP/provider tools to advertise normalized search capabilities.
- Do not add permanent core tools named after X, Weibo or Xiaohongshu.
- If authenticated search orchestration becomes reusable, implement it as a service-gated browser/provider contract rather than pretending a nonexistent `browser_search` tool is available.

Exit gate: the host can truthfully report which public or authorized sources
are available, and no connector bypasses platform access controls.

## Release rule

A Hermes fork release and an Ethos/Soma release remain independently
versioned. A release note must list:

- the upstream Hermes base commit;
- fork-only commits;
- the minimum/maximum tested `ethos-soma` version;
- focused and end-to-end test results;
- known degraded capabilities.

The fork may be the recommended distribution, but Ethos/Soma must continue to
degrade on upstream Hermes and remain testable through its standalone host
adapter. This prevents the companion's identity and data from becoming trapped
inside one runtime fork.
