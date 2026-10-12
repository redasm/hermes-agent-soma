# Soma upstream sync (2026-10-12)

The fork is synchronized from `e798d68b23` to the upstream main snapshot
`590af66a58c2b3eb3c5edd1dcfefa09c625ae18a`. The original fork head is retained
as `backup/pre-upstream-sync-20261012`. This is a local integration; no remote
branch is published by this operation.

The merge preserves upstream provider routing, prompt caching, tool policy,
profile isolation, durable scheduling and delivery verification while migrating
Soma's companion/agent interaction mode, plugin-native LLM and host contract,
private capability execution, scheduled events and voice lifecycle hooks.
Feishu DM session configuration, OpenAI image endpoint configuration and the
Soma-owned Windows installer origin migration remain supported.

## Implementation locations

The public host and adapter APIs remain stable. Their implementation is split
into topical siblings so upstream file and complexity caps remain satisfied:

- `hermes_cli/plugins_host.py`: host capabilities, observations, scheduled events
  and inspector registration; `plugins_error.py`: plugin error classifications.
- `agent/agent_init_settings.py`: agent settings; `auxiliary_execution.py`:
  sync/async request execution; `auxiliary_tool_choice.py`: Responses native
  function-choice projection, including request-local reserved-name aliases.
- `gateway/run_turn_conversation.py`: companion ownership, private delegation
  and delivery receipts; `run_turn_display.py`: display policy;
  `run_turn_runner_prompt.py`: per-turn ephemeral prompt isolation;
  `run_inbound_commands.py`: busy slash-command policy and Discord input notes.
- `gateway/platforms/base_receipts.py`: generation-owned receipt callbacks;
  `base_requeue.py`: queued-turn backoff; `api_server_cron.py`: cron response
  projection and shared multimodal content normalization.
- `cron/scheduler_receipts.py`: delivery evidence and plugin notification;
  `scheduler_delivery_settings.py`: continuable delivery surface selection.
- `plugins/platforms/discord/adapter_voice_lifecycle.py`: voice output,
  speech-start and delivery lifecycle; `plugins/platforms/feishu/adapter_inbound.py`:
  normalized inbound events; `tui_gateway/methods_plugin_inspect.py`: scoped RPC.

## Validation

Run all tests through `scripts/run_tests.sh`. Targeted regressions cover agent
prompt restoration, native plugin LLM/trust gates, auxiliary fallback/tool choice,
companion private execution, plugin discovery, cron context/receipts/scheduled
events, Feishu, busy gateway input, stream/progress, voice interruption/lifecycle,
image configuration, host observations and generated RPC contracts. A native
Windows regression invokes the real installer repository-staging functions
against local Git repositories. Shared TypeScript checking and desktop bootstrap
unit tests also pass.

Both `python scripts/check --base 41cd7b649d` and the final
`python scripts/check --base 590af66a58` pass all 12 checks, with zero blocking
or advisory code-health findings. The final gateway/voice/scheduler/plugin batch
passes 357 tests with four platform/dependency skips; the final small rerun
passes 128 tests. The Responses/voice-reset boundary batch passes 96 tests.
The release artifact/channel/sequencer/progress/stable suites pass all 98 tests,
and the native Windows installer staging regression passes. These batches
partly overlap; their counts must not be added as unique coverage.

All 8,460 Python files present during final syntax verification compile.
Shared TypeScript checking passes; desktop bootstrap tests pass 13 cases with
one skipped. The test snapshots use the repository's actual files in an isolated
WSL tree; native installer behavior is checked on Windows.

The entire upstream test suite and complete desktop/website builds are not run.
Live provider, messaging platform and device permission integrations require
operator configuration and were not exercised by these isolated regressions.
