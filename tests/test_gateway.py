import json

import httpx
import respx
from sqlalchemy import select

from app import quota
from app.db import SessionLocal
from app.models import UsageRecord

UPSTREAM = "http://upstream.test/compatible-mode/v1/chat/completions"
MSG = [{"role": "user", "content": "hi"}]


def _ok_body(model="qwen3.7-flash", prompt=10, completion=5):
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "ok"},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": prompt + completion,
            "prompt_tokens_details": {"cached_tokens": 3},
            "completion_tokens_details": {"reasoning_tokens": 1},
        },
    }


def _free_tier_only():
    return {
        "error": {
            "message": "free quota exhausted",
            "code": "AllocationQuota.FreeTierOnly",
            "type": "free_tier_only",
        }
    }


def _records():
    with SessionLocal() as db:
        return list(db.execute(select(UsageRecord)).scalars())


def _sent_body(route):
    return json.loads(route.calls.last.request.read())


@respx.mock
def test_nonstream_alias_success(client):
    from app.tier_router import load_tiers

    first = load_tiers()["fast"].models[0]
    route = respx.post(UPSTREAM).mock(return_value=httpx.Response(200, json=_ok_body()))
    resp = client.post("/v1/chat/completions", json={"model": "fast", "messages": MSG})
    assert resp.status_code == 200
    assert resp.headers["x-tt-actual-model"] == first
    assert _sent_body(route)["model"] == first
    recs = _records()
    assert len(recs) == 1
    assert recs[0].requested_model == "fast"
    assert recs[0].actual_model == first
    assert recs[0].tier == "fast"
    assert recs[0].total_tokens == 15
    assert recs[0].cached_tokens == 3
    assert recs[0].reasoning_tokens == 1
    assert recs[0].switched is False


@respx.mock
def test_switch_on_403_free_tier_only(client):
    from app.tier_router import load_tiers

    chain = load_tiers()["fast"].models
    first, second = chain[0], chain[1]
    route = respx.post(UPSTREAM).mock(
        side_effect=[
            httpx.Response(403, json=_free_tier_only()),
            httpx.Response(200, json=_ok_body()),
        ]
    )
    resp = client.post("/v1/chat/completions", json={"model": "fast", "messages": MSG})
    assert resp.status_code == 200
    assert resp.headers["x-tt-actual-model"] == second
    bodies = [_sent_body_call(c) for c in route.calls]
    assert [b["model"] for b in bodies] == [first, second]

    with SessionLocal() as db:
        assert quota.get_rule(db, first).exhausted is True

    recs = _records()
    assert len(recs) == 2
    success = [r for r in recs if r.status_code == 200][0]
    assert success.actual_model == second
    assert success.switched is True
    assert success.switch_reason == "AllocationQuota.FreeTierOnly"
    failed = [r for r in recs if r.status_code == 403][0]
    assert failed.error_code == "AllocationQuota.FreeTierOnly"


def _sent_body_call(call):
    return json.loads(call.request.read())


@respx.mock
def test_precheck_skips_marked_exhausted(client):
    from app.tier_router import load_tiers

    chain = load_tiers()["fast"].models
    with SessionLocal() as db:
        quota.upsert_rule(db, chain[0])
        quota.mark_exhausted(db, chain[0])
    respx.post(UPSTREAM).mock(return_value=httpx.Response(200, json=_ok_body()))
    resp = client.post("/v1/chat/completions", json={"model": "fast", "messages": MSG})
    assert resp.status_code == 200
    assert resp.headers["x-tt-actual-model"] == chain[1]
    recs = _records()
    assert len(recs) == 1  # 预检跳过不产生上游调用/记录
    assert recs[0].switched is True
    assert recs[0].switch_reason == "precheck:exhausted"


@respx.mock
def test_all_candidates_exhausted_returns_409(client):
    from app.tier_router import load_tiers

    chain = load_tiers()["fast"].models
    respx.post(UPSTREAM).mock(return_value=httpx.Response(403, json=_free_tier_only()))
    resp = client.post("/v1/chat/completions", json={"model": "fast", "messages": MSG})
    assert resp.status_code == 409
    err = resp.json()["error"]
    assert err["code"] == "TT.AllCandidatesUnavailable"
    assert len(err["candidates"]) == len(chain)
    with SessionLocal() as db:
        for m in chain:
            assert quota.get_rule(db, m).exhausted is True


@respx.mock
def test_non_switchable_error_passthrough(client):
    respx.post(UPSTREAM).mock(
        return_value=httpx.Response(400, json={"error": {"code": "InvalidParameter", "message": "bad"}})
    )
    resp = client.post("/v1/chat/completions", json={"model": "fast", "messages": MSG})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "InvalidParameter"
    recs = _records()
    assert len(recs) == 1 and recs[0].error_code == "InvalidParameter"


SSE_BODY = (
    b'data: {"id":"1","choices":[{"delta":{"content":"Hi"}}]}\n\n'
    b'data: {"id":"1","choices":[{"delta":{"content":" there"}}]}\n\n'
    b'data: {"id":"1","choices":[],"usage":{"prompt_tokens":5,"completion_tokens":2,"total_tokens":7}}\n\n'
    b"data: [DONE]\n\n"
)


@respx.mock
def test_stream_captures_usage_and_strips_usage_chunk(client):
    from app.tier_router import load_tiers

    first = load_tiers()["fast"].models[0]
    route = respx.post(UPSTREAM).mock(
        return_value=httpx.Response(200, content=SSE_BODY, headers={"Content-Type": "text/event-stream"})
    )
    resp = client.post(
        "/v1/chat/completions", json={"model": "fast", "stream": True, "messages": MSG}
    )
    assert resp.status_code == 200
    assert resp.headers["x-tt-actual-model"] == first
    assert "Hi" in resp.text and "[DONE]" in resp.text
    assert '"usage"' not in resp.text  # usage-only chunk 被剥离
    assert _sent_body(route)["stream_options"]["include_usage"] is True  # 自动注入
    recs = _records()
    assert len(recs) == 1
    assert recs[0].stream is True
    assert recs[0].total_tokens == 7
    assert recs[0].input_tokens == 5
    assert recs[0].output_tokens == 2


@respx.mock
def test_stream_keeps_usage_when_client_requests_it(client):
    respx.post(UPSTREAM).mock(
        return_value=httpx.Response(200, content=SSE_BODY, headers={"Content-Type": "text/event-stream"})
    )
    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "qwen3.8-flash",
            "stream": True,
            "stream_options": {"include_usage": True},
            "messages": MSG,
        },
    )
    assert resp.status_code == 200
    assert '"usage"' in resp.text  # 客户端要求的 usage chunk 原样保留
