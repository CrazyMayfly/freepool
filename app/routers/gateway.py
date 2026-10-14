"""OpenAI 兼容代理网关：档位路由 + 自动切换 + usage 计量。

切换语义：
- 请求前按额度账本预检，跳过 已耗尽/已过期/已下线 的候选模型；
- 上游返回 403 AllocationQuota.FreeTierOnly → 标记耗尽并换下一个候选
  （仅在尚未向客户端写出任何字节时重试，客户端无感知）；
- 其他上游错误不触发切换（换模型解决不了），原样透传；
- 全部候选不可用 → 409，附各候选状态。
"""

import json
import time
from typing import AsyncIterator

import httpx
from anyio import CancelScope, to_thread
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import select

from .. import quota, tier_router
from ..config import get_settings
from ..db import SessionLocal
from ..models import CatalogModel, UsageRecord

router = APIRouter()

SWITCHABLE_ERROR_CODES = {"AllocationQuota.FreeTierOnly"}
SKIP_STATUSES = {quota.STATUS_EXHAUSTED, quota.STATUS_EXPIRED, quota.STATUS_OFFLINE}
USABLE_STATUSES = {quota.STATUS_NORMAL, quota.STATUS_LOW}


def _auth_headers() -> dict:
    return {"Authorization": f"Bearer {get_settings().bailian_api_key}"}


def _safe_json(raw) -> dict | None:
    if raw is None:
        return None
    if isinstance(raw, (bytes, bytearray)):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError:
            return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


def _usage_from_openai(u) -> dict:
    if not isinstance(u, dict):
        return {}
    details_in = u.get("prompt_tokens_details") or {}
    details_out = u.get("completion_tokens_details") or {}
    return {
        "input_tokens": int(u.get("prompt_tokens") or 0),
        "output_tokens": int(u.get("completion_tokens") or 0),
        "total_tokens": int(u.get("total_tokens") or 0),
        "cached_tokens": int(details_in.get("cached_tokens") or 0),
        "reasoning_tokens": int(details_out.get("reasoning_tokens") or 0),
    }


def _error_from_body(body) -> tuple[str | None, str]:
    if not isinstance(body, dict):
        return None, ""
    err = body.get("error")
    if isinstance(err, dict):
        return err.get("code"), err.get("message") or ""
    return body.get("code"), body.get("message") or ""


def _record_sync(fields: dict) -> None:
    with SessionLocal() as db:
        quota.ensure_rule(db, fields["actual_model"])
        db.add(UsageRecord(**fields))
        db.commit()


async def _record(fields: dict) -> None:
    try:
        await to_thread.run_sync(_record_sync, dict(fields))
    except Exception:
        pass  # 计量失败不能影响主链路


def _precheck_sync(model: str):
    with SessionLocal() as db:
        st = quota.compute_status(db, model)
        return st.status if st else None


def _mark_exhausted(model: str, exhausted: bool = True) -> None:
    with SessionLocal() as db:
        quota.mark_exhausted(db, model, exhausted)


async def _sse_relay(
    resp: httpx.Response,
    *,
    client_include_usage: bool,
    record_fields: dict,
) -> AsyncIterator[bytes]:
    """转发 SSE；捕获最终 usage chunk，客户端未要求 usage 时剥离该 chunk。"""
    usage: dict = {}
    started = record_fields.pop("started")
    recorded = False
    try:
        async for line in resp.aiter_lines():
            if line.startswith("data:"):
                data = line[5:].strip()
                if data and data != "[DONE]":
                    obj = _safe_json(data)
                    if isinstance(obj, dict):
                        u = obj.get("usage")
                        if isinstance(u, dict) and u:
                            usage = _usage_from_openai(u)
                            if not client_include_usage and not obj.get("choices"):
                                continue  # 剥离 usage-only chunk
            yield (line + "\n").encode("utf-8")
    finally:
        try:
            await resp.aclose()
        except Exception:
            pass
        if not recorded:
            recorded = True
            fields = dict(record_fields)
            fields.update(usage)
            fields["duration_ms"] = int((time.monotonic() - started) * 1000)
            fields["status_code"] = 200
            try:
                # 客户端断开时任务已被取消，普通 await 会再次被取消，这里必须屏蔽
                with CancelScope(shield=True):
                    await _record(fields)
            except Exception:
                pass


def _bad_request(message: str, code: str = "TT.BadRequest") -> JSONResponse:
    return JSONResponse(
        status_code=400, content={"error": {"message": message, "code": code}}
    )


@router.post("/v1/chat/completions")
async def chat_completions(request: Request):
    settings = get_settings()
    payload = _safe_json(await request.body())
    if not isinstance(payload, dict):
        return _bad_request("请求体必须是 JSON 对象")

    requested_model = str(payload.get("model") or "").strip()
    tier_name, candidates = tier_router.resolve_candidates(requested_model)
    if not candidates:
        return _bad_request("缺少 model 参数（档位别名或具体模型名）")

    is_stream = bool(payload.get("stream"))
    client_include_usage = bool((payload.get("stream_options") or {}).get("include_usage"))
    first_choice = candidates[0]
    client: httpx.AsyncClient = request.app.state.http

    attempts: list[dict] = []
    switch_reason: str | None = None  # 记录触发切换的首个原因

    for model in candidates:
        status = await to_thread.run_sync(_precheck_sync, model)
        if status in SKIP_STATUSES:
            attempts.append({"model": model, "status": status, "skip_reason": f"precheck:{status}"})
            switch_reason = switch_reason or f"precheck:{status}"
            continue

        call_payload = dict(payload)
        call_payload["model"] = model
        if is_stream and not client_include_usage:
            so = dict(call_payload.get("stream_options") or {})
            so["include_usage"] = True
            call_payload["stream_options"] = so

        started = time.monotonic()
        switched = model != first_choice

        if is_stream:
            req = client.build_request(
                "POST", settings.chat_url, json=call_payload, headers=_auth_headers()
            )
            resp = await client.send(req, stream=True)
            if resp.status_code != 200:
                raw = await resp.aread()
                await resp.aclose()
                body = _safe_json(raw)
                code, message = _error_from_body(body)
                await _record({
                    "requested_model": requested_model, "actual_model": model,
                    "tier": tier_name, "switched": switched,
                    "switch_reason": code or None,
                    "duration_ms": int((time.monotonic() - started) * 1000),
                    "status_code": resp.status_code, "error_code": code, "stream": True,
                })
                attempts.append({"model": model, "status_code": resp.status_code, "error_code": code})
                if code in SWITCHABLE_ERROR_CODES:
                    await to_thread.run_sync(_mark_exhausted, model, True)
                    switch_reason = switch_reason or code
                    continue
                return JSONResponse(
                    status_code=resp.status_code,
                    content=body or {"error": {"message": message or "upstream error", "code": code}},
                    headers={"x-tt-actual-model": model},
                )

            record_fields = {
                "requested_model": requested_model, "actual_model": model,
                "tier": tier_name, "switched": switched,
                "switch_reason": switch_reason if switched else None,
                "error_code": None, "stream": True, "started": started,
            }
            return StreamingResponse(
                _sse_relay(resp, client_include_usage=client_include_usage, record_fields=record_fields),
                media_type="text/event-stream",
                headers={"x-tt-actual-model": model, "Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

        # 非流式
        resp = await client.post(settings.chat_url, json=call_payload, headers=_auth_headers())
        duration_ms = int((time.monotonic() - started) * 1000)
        body = _safe_json(resp.content)
        if resp.status_code == 200:
            usage = _usage_from_openai((body or {}).get("usage"))
            await _record({
                "requested_model": requested_model, "actual_model": model,
                "tier": tier_name, "switched": switched,
                "switch_reason": switch_reason if switched else None,
                **usage, "duration_ms": duration_ms,
                "status_code": 200, "error_code": None, "stream": False,
            })
            return JSONResponse(
                status_code=200, content=body, headers={"x-tt-actual-model": model}
            )

        code, message = _error_from_body(body)
        await _record({
            "requested_model": requested_model, "actual_model": model,
            "tier": tier_name, "switched": switched,
            "switch_reason": code or None,
            "duration_ms": duration_ms,
            "status_code": resp.status_code, "error_code": code, "stream": False,
        })
        attempts.append({"model": model, "status_code": resp.status_code, "error_code": code})
        if code in SWITCHABLE_ERROR_CODES:
            await to_thread.run_sync(_mark_exhausted, model, True)
            switch_reason = switch_reason or code
            continue
        return JSONResponse(
            status_code=resp.status_code,
            content=body or {"error": {"message": message or "upstream error", "code": code}},
            headers={"x-tt-actual-model": model},
        )

    return JSONResponse(
        status_code=409,
        content={
            "error": {
                "message": f"所有候选模型均不可用（请求模型: {requested_model}）",
                "code": "TT.AllCandidatesUnavailable",
                "requested_model": requested_model,
                "tier": tier_name,
                "candidates": attempts,
            }
        },
    )


@router.get("/v1/models")
async def list_models(request: Request):
    settings = get_settings()
    client: httpx.AsyncClient = request.app.state.http
    try:
        resp = await client.get(settings.models_url, headers=_auth_headers())
        body = _safe_json(resp.content)
        if body is not None:
            return JSONResponse(status_code=resp.status_code, content=body)
    except httpx.HTTPError:
        pass
    # 回退：本地目录
    def _local() -> list[str]:
        with SessionLocal() as db:
            return list(db.execute(select(CatalogModel.model)).scalars())

    rows = await to_thread.run_sync(_local)
    return {
        "object": "list",
        "data": [{"id": m, "object": "model", "owned_by": "bailian"} for m in rows],
    }
