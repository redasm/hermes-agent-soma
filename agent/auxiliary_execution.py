"""Topical helpers for the Soma host integration."""
from __future__ import annotations
from typing import Any, Optional, Callable
import logging
logger = logging.getLogger(__name__)

def _prepare_aux_request(
    task: Optional[str],
    *,
    provider: Optional[str],
    model: Optional[str],
    base_url: Optional[str],
    api_key: Optional[str],
    main_runtime: dict[str, Any],
    messages: list,
    temperature: Optional[float],
    max_tokens: Optional[int],
    tools: Optional[list],
    tool_choice: Optional[str] = None,
    timeout: Optional[float],
    extra_body: Optional[dict],
    reasoning_config: Optional[dict],
    extra_headers: Optional[dict[str, str]],
    api_mode: Optional[str],
    route_info: Optional[dict[str, str]],
    async_mode: bool,
) -> object:
    """Shared head of call_llm/async_call_llm: resolve route + client, publish it, build request kwargs.
    Sync-only: compression fast lane, per-request ``extra_headers``, and ``base_info`` falling
    back to the resolved base_url when the client exposes none."""
    from agent.auxiliary_client import (
        AsyncCodexAuxiliaryClient, CodexAuxiliaryClient, _PreparedAuxRequest, _build_call_kwargs, _compression_fast_lane_controls, _convert_openai_images_to_anthropic, _effective_aux_timeout, _fallback_provider_from_label, _get_auxiliary_task_config, _get_task_extra_body, _get_task_no_progress_timeout, _is_anthropic_compat_endpoint, _record_route_info, _resolve_call_client, _resolve_task_provider_model, _set_relay_auxiliary_route
    )
    resolved_provider, resolved_model, resolved_base_url, resolved_api_key, resolved_api_mode = _resolve_task_provider_model(
        task, provider, model, base_url, api_key)
    if api_mode:
        resolved_api_mode = api_mode
    effective_extra_body = _get_task_extra_body(task)
    effective_extra_body.update(extra_body or {})
    client, final_model, resolved_provider, effective_provider = _resolve_call_client(
        task, provider=provider, model=model, base_url=base_url, api_key=api_key,
        resolved_provider=resolved_provider, resolved_model=resolved_model,
        resolved_base_url=resolved_base_url, resolved_api_key=resolved_api_key,
        resolved_api_mode=resolved_api_mode, main_runtime=main_runtime, async_mode=async_mode,
    )
    effective_timeout = _effective_aux_timeout(task, timeout)
    # Codex-Responses-only: real SDK clients reject an unrecognized ``no_progress_timeout``
    # kwarg, so only resolve/forward it when the route is actually a Codex stream (#108104).
    no_progress_timeout = (
        _get_task_no_progress_timeout(task)
        if isinstance(client, (CodexAuxiliaryClient, AsyncCodexAuxiliaryClient)) else None
    )
    request_provider = effective_provider or resolved_provider
    if not async_mode:
        compression_config = _get_auxiliary_task_config("compression") if task == "compression" else {}
        _, effective_extra_body = _compression_fast_lane_controls(
            task, actual_provider=request_provider, actual_model=final_model,
            requested_provider=provider, requested_model=model, route_config=compression_config,
            leak_guard_config=compression_config, max_tokens=max_tokens,
            extra_body=effective_extra_body,
        )
    _set_relay_auxiliary_route(request_provider, final_model, resolved_api_mode)
    _record_route_info(route_info, _fallback_provider_from_label(request_provider), final_model)
    if async_mode:
        base_info = str(getattr(client, "base_url", "") or "")
    else:
        base_info = str(getattr(client, "base_url", resolved_base_url) or "")
        if task:
            logger.info("Auxiliary %s: using %s (%s)%s",
                         task, request_provider or "auto", final_model or "default",
                         f" at {base_info}" if base_info and "openrouter" not in base_info else "")
    # Client's actual base_url so endpoint-specific temperature overrides work on
    # auto-detected routes (api.moonshot.ai vs api.kimi.com/coding).
    kwargs = _build_call_kwargs(
        request_provider,
        final_model,
        messages,
        temperature=temperature,
        max_tokens=max_tokens,
        tools=tools,
        tool_choice=tool_choice,
        timeout=effective_timeout,
        extra_body=effective_extra_body,
        reasoning_config=reasoning_config,
        base_url=base_info or resolved_base_url,
        task=task,
        no_progress_timeout=no_progress_timeout,
    )
    if extra_headers:
        kwargs["extra_headers"] = dict(extra_headers)
    # Convert image blocks for Anthropic-compatible endpoints (e.g. MiniMax)
    client_base = str(getattr(client, "base_url", "") or "")
    if _is_anthropic_compat_endpoint(request_provider, client_base):
        kwargs["messages"] = _convert_openai_images_to_anthropic(kwargs["messages"])
    return _PreparedAuxRequest(
        client, final_model, kwargs, resolved_provider, request_provider, resolved_model,
        resolved_base_url, resolved_api_key, resolved_api_mode, effective_timeout,
        effective_extra_body, base_info)


def _call_llm_impl(
    task: str | None = None,
    *,
    provider: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    main_runtime: Optional[dict[str, Any]] = None,
    messages: list,
    temperature: Optional[float] = None,
    max_tokens: int | None = None,
    tools: list | None = None,
    tool_choice: Optional[str] = None,
    timeout: float | None = None,
    extra_body: dict | None = None,
    reasoning_config: Optional[dict] = None,
    extra_headers: Optional[dict[str, str]] = None,
    api_mode: str | None = None,
    stream: bool = False,
    stream_options: dict | None = None,
    route_info: Optional[dict[str, str]] = None,
) -> Any:
    """Centralized synchronous LLM call: resolve provider/model, auth, kwargs, fallbacks.
    task: aux task whose provider:model comes from config (ignored if provider set); api_mode
    overrides task config; timeout=None reads auxiliary.{task}.timeout; extra_headers override
    client defaults. stream=True returns the raw SDK stream (caller consumes/falls back)
    instead of a validated response. RuntimeError if no provider is configured."""
    from agent.auxiliary_client import (
        CodexAuxiliaryClient, _LadderStep, _TRANSIENT_RETRY_BACKOFF_BASE, _call_fallback_candidate_sync, _create_with_progress, _drive_ladder, _is_transient_transport_error, _ladder_step_call, _plan_aux_call, _provider_requires_stream, _relay_sync_completion, _relay_sync_stream, _retry_same_provider_sync, _should_retry_same_provider, _start_recovery_ladder, _transient_retry_count, _validate_llm_response, time
    )
    req, retry_kwargs, candidate_kwargs = _plan_aux_call(
        task,
        async_mode=False,
        provider=provider,
        model=model,
        base_url=base_url,
        api_key=api_key,
        main_runtime=main_runtime,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        tools=tools,
        tool_choice=tool_choice,
        timeout=timeout,
        extra_body=extra_body,
        reasoning_config=reasoning_config,
        extra_headers=extra_headers,
        api_mode=api_mode,
        route_info=route_info,
    )
    client, kwargs, request_provider = req.client, req.kwargs, req.request_provider
    # Streaming path (MoA aggregator): return the raw SDK stream, skipping validation and
    # the fallback chain (they assume a complete response); the caller owns reassembly/fallback.
    if stream:
        kwargs["stream"] = True
        if stream_options:
            kwargs["stream_options"] = stream_options
        if task == "moa_aggregator" and isinstance(client, CodexAuxiliaryClient):
            # Responses-shim clients consume the stream internally and return a completed
            # object Relay's managed stream would iterate; the MoA facade wraps it as one chunk.
            return client.chat.completions.create(**kwargs)
        return _relay_sync_stream(client, kwargs, provider=request_provider, api_mode=req.resolved_api_mode)

    def _primary(**validate_kw: Any) -> Any:
        # Retry on the same provider for a transient transport blip (connection reset / streaming-close /
        # incomplete chunked read / 5xx / 408) before the except-chain below escalates to provider/model
        # fallback. A dropped connection shouldn't abandon an otherwise-healthy provider — this especially
        # matters for pinned auxiliary calls like MoA reference advisors, where "fallback to another
        # provider" is not a meaningful recovery (the advisor is a specific model), so a transient blip that
        # isn't retried simply loses that advisor for the turn (root of the run2 double-advisor "Connection
        # error" collapse — a genuine upstream blip hitting both parallel advisors at once). Attempts are
        # bounded and use exponential backoff. Count is configurable via auxiliary.transient_retries
        # (default 2 retries → 3 total attempts); a second/third failure or any non-transient error falls
        # through to ``first_err`` and the existing fallback handling unchanged. Unified home for the
        # transient retry every auxiliary task shares. (PR #16587)
        return _validate_llm_response(
            _relay_sync_completion(
                client, kwargs, provider=request_provider, api_mode=req.resolved_api_mode,
                create=lambda request: _create_with_progress(
                    client, request, task,
                    force_stream=_provider_requires_stream(
                        request_provider, req.base_info or req.resolved_base_url),
                ),
            ),
            task, **validate_kw,
        )

    try:
        # Bounded same-provider retry (exponential backoff, auxiliary.transient_retries) for
        # transient blips before escalating to fallback — a dropped connection shouldn't
        # abandon a healthy provider (matters for pinned MoA advisors).
        try:
            return _primary(provider=request_provider, base_url=req.base_info)
        except Exception as transient_err:
            if not _should_retry_same_provider(task, transient_err, ""):
                raise
            _max_transient_retries = _transient_retry_count()
            _last_transient = transient_err
            for _attempt in range(1, _max_transient_retries + 1):
                _backoff = min(_TRANSIENT_RETRY_BACKOFF_BASE * (2.0 ** (_attempt - 1)), 8.0)
                logger.info("Auxiliary %s: transient transport error (attempt %d/%d); "
                            "retrying same provider after %.1fs before fallback: %s",
                            task or "call", _attempt, _max_transient_retries, _backoff, _last_transient)
                time.sleep(_backoff)
                try:
                    return _primary()
                except Exception as retry_transient:
                    if not _is_transient_transport_error(retry_transient):
                        raise
                    _last_transient = retry_transient
            raise _last_transient
    except Exception as first_err:
        def _perform(step: _LadderStep) -> Any:
            kind, args, kw = _ladder_step_call(step, req, retry_kwargs, candidate_kwargs)
            if kind == "call":
                return _validate_llm_response(_relay_sync_completion(*args, **kw), task)
            if kind == "retry":
                return _retry_same_provider_sync(**kw)
            return _call_fallback_candidate_sync(*args, **kw)
        return _drive_ladder(
            _start_recovery_ladder(first_err, req, retry_kwargs, task=task, async_mode=False, route_info=route_info),
            _perform)


async def _async_call_llm_impl(
    task: str | None = None,
    *,
    provider: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    main_runtime: Optional[dict[str, Any]] = None,
    messages: list,
    temperature: Optional[float] = None,
    max_tokens: int | None = None,
    tools: list | None = None,
    tool_choice: Optional[str] = None,
    timeout: float | None = None,
    extra_body: dict | None = None,
    reasoning_config: Optional[dict] = None,
    route_info: Optional[dict[str, str]] = None,
) -> Any:
    """Centralized asynchronous LLM call; see call_llm() for full documentation.
    No per-request header / api_mode override on the async entry point."""
    from agent.auxiliary_client import (
        _LadderStep, _acreate_with_progress, _call_fallback_candidate_async, _drive_ladder_async, _ladder_step_call, _plan_aux_call, _provider_requires_stream, _relay_async_completion, _retry_same_provider_async, _should_retry_same_provider, _start_recovery_ladder, _to_async_client, _validate_llm_response
    )
    req, retry_kwargs, candidate_kwargs = _plan_aux_call(
        task,
        async_mode=True,
        provider=provider,
        model=model,
        base_url=base_url,
        api_key=api_key,
        main_runtime=main_runtime,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        tools=tools,
        tool_choice=tool_choice,
        timeout=timeout,
        extra_body=extra_body,
        reasoning_config=reasoning_config,
        extra_headers=None,
        api_mode=None,
        route_info=route_info,
    )
    client, kwargs, request_provider = req.client, req.kwargs, req.request_provider
    try:
        # Retry ONCE on the same provider for a transient blip before fallback (see call_llm()).
        # (PR #16587)
        _force_stream_async = _provider_requires_stream(request_provider, req.base_info or req.resolved_base_url)

        async def _acreate(_kwargs: dict[str, Any]) -> Any:
            return await _acreate_with_progress(client, _kwargs, task, force_stream=_force_stream_async)

        async def _primary(**validate_kw: Any) -> Any:
            return _validate_llm_response(
                await _relay_async_completion(
                    client, kwargs, provider=request_provider, api_mode=req.resolved_api_mode,
                    create=_acreate),
                task, **validate_kw)
        try:
            return await _primary(provider=request_provider, base_url=req.base_info)
        except Exception as transient_err:
            # The async Codex adapter wraps the sync stream via to_thread: same TimeoutError here.
            if not _should_retry_same_provider(task, transient_err, " (async)"):
                raise
            logger.info("Auxiliary %s (async): transient transport error; retrying "
                        "once on the same provider before fallback: %s", task or "call", transient_err)
            return await _primary()
    except Exception as first_err:
        async def _perform(step: _LadderStep) -> Any:
            kind, args, kw = _ladder_step_call(step, req, retry_kwargs, candidate_kwargs)
            if kind == "call":
                return _validate_llm_response(await _relay_async_completion(*args, **kw), task)
            if kind == "retry":
                return await _retry_same_provider_async(**kw)
            fb_client, fb_model, fb_label = args
            fb_client, _ = _to_async_client(fb_client, fb_model or "", is_vision=(task == "vision"))
            return await _call_fallback_candidate_async(fb_client, fb_model, fb_label, **kw)
        return await _drive_ladder_async(
            _start_recovery_ladder(first_err, req, retry_kwargs, task=task, async_mode=True, route_info=route_info),
            _perform)
