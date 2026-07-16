# Companion cron host contract

Hermes owns scheduling, one-turn context delivery, platform delivery, and the
delivery result. A companion plugin owns language preference, relationship
memory, personality, affect, life simulation, and the decision about what to
say. This boundary keeps the agent core generic while allowing proactive
messages to feel like part of the same relationship rather than an unrelated
English cron bot.

## Per-job fields

The `cronjob` tool, `cron.jobs.create_job()`, dashboard API, and gateway jobs
API accept these optional fields:

| Field | Purpose |
| --- | --- |
| `response_mode` | `framed` includes cron provenance and management text. `text_only` sends only the Agent's final content. When omitted, `cron.wrap_response` controls the existing behavior. |
| `attach_to_session` | Makes the delivered brief continuable in the origin conversation using Hermes' existing thread/mirror mechanism. |
| `context_provider` | Selects a plugin that may provide bounded context for this scheduled turn. No hook is called when omitted. |
| `metadata` | JSON object (maximum 8,192 UTF-8 bytes) used only for host-side correlation and delivery receipts. It is not prompt content. |

Existing jobs remain compatible: all four fields are optional, and an absent
`response_mode` still uses the global `cron.wrap_response` setting (default
`true`). Per-job precedence is:

1. `response_mode=framed` or `response_mode=text_only`;
2. `cron.wrap_response` from `config.yaml`;
3. the historical framed default.

For a companion job, the normal combination is:

```python
cronjob(
    action="create",
    name="soma-checkin",
    schedule="every 30m",
    prompt="Decide whether to reach out. Return [SILENT] when no message is warranted.",
    deliver="origin",
    response_mode="text_only",
    attach_to_session=True,
    context_provider="soma",
)
```

`job_id` and management text are therefore absent from the delivered companion
message. Operational jobs can continue using the framed default.

## `cron_context` hook

A plugin registers the hook with `ctx.register_hook("cron_context", callback)`.
Hermes invokes it only when a job explicitly names a `context_provider`.

Callback arguments:

```python
{
    "provider": "soma",
    "job_id": "...",
    "job_name": "soma-checkin",
    "schedule": {...},
    "target": {
        "platform": "telegram",
        "chat_id": "...",
        "thread_id": "...",   # when available
        "user_id": "...",     # when available
        "session_id": "...",  # when captured at job creation
    },
}
```

The hook does not receive the live conversation or system prompt. A matching
provider returns:

```python
{
    "provider": "soma",
    "context": "Preferred language: zh-CN\nRelevant relationship context: ...",
    "metadata": {"attempt_id": "internal-attempt-id"},
}
```

Hermes accepts results only when the returned `provider` exactly matches the
job's provider. Context from all matching results is combined and capped at
8,000 characters. It is injected into the current turn's user message as an
ephemeral data block; it does not change the cached system prompt and is not
persisted to conversation history. Hook errors, malformed results, and missing
providers degrade to the original self-contained cron prompt.

The optional returned `metadata` is run-scoped. It is merged into the delivery
receipt but is not persisted to `jobs.json` and never becomes prompt text. This
lets Soma create a fresh `attempt_id` on each tick without asking the LLM to
repeat it.

## Capability and observation discovery

Plugins can call `ctx.get_host_capabilities()` instead of probing tool names.
The versioned response reports scheduled context, receipts, text-only delivery,
session continuity, search, browser, image, and observation surfaces.
`ctx.get_host_observations()` returns minimum non-secret profile, timezone, and
browser state; `ctx.get_location_observation()` performs one OS-mediated
location observation.

Location status is `granted`, `denied`, or `unavailable`. The Windows provider
uses the OS Location API and never falls back to IP geolocation. Browser
authorization remains `unknown` unless a provider can prove an authorized
session; browser availability alone is not evidence of login.

## `cron_delivery` hook

Hermes emits this hook after every delivery decision made through the normal
cron execution path. The callback receives one argument:

```python
{
    "receipt": {
        "job_id": "...",
        "status": "delivered",  # delivered | skipped | failed
        "targets": [
            {"platform": "telegram", "chat_id": "...", "thread_id": None}
        ],
        "metadata": {
            "outcome_id": "internal-outcome-id",
            "attempt_id": "internal-attempt-id",
        },
        "error": None,
    }
}
```

`skipped` covers local/no-target delivery and intentional `[SILENT]` or empty
responses. `failed` includes a compact delivery error. Plugin hook failures are
logged and never turn a successful user delivery into a failed cron run.

A minimal Soma adapter is:

```python
def provide_context(provider, target, **_):
    if provider != "soma":
        return None
    context, attempt_id = soma.build_scheduled_context(target)
    return {
        "provider": "soma",
        "context": context,
        "metadata": {"attempt_id": attempt_id},
    }


def record_delivery(receipt, **_):
    soma.record_delivery(
        attempt_id=receipt["metadata"].get("attempt_id"),
        status=receipt["status"],
        error=receipt["error"],
    )


def register(ctx):
    ctx.register_hook("cron_context", provide_context)
    ctx.register_hook("cron_delivery", record_delivery)
```

## Visibility and safety

- Static and run-scoped `metadata` never enter the cron prompt, generated text,
  `cronjob list` result, dashboard job response, or gateway jobs response.
- The captured origin `session_id` is available to the selected context
  provider but removed from public dashboard and jobs API responses.
- Context is scoped by the stored origin identity. Plugins should treat target
  IDs as lookup keys, not instructions, and return only the minimum relevant
  user/relationship context.
- Correlation metadata is not an authorization boundary. A plugin must not use
  model- or API-supplied metadata as proof of identity, permission, or delivery.
- Hermes does not infer language or relationship state. Soma should persist a
  preferred language learned from long-term interaction and include it in the
  returned context. The scheduled Agent then generates the actual message in
  that language through the normal LLM/tool flow.
- Hermes does not move personality, affect, memory, or simulated daily life
  into core. Those remain plugin-domain state and can evolve independently.
