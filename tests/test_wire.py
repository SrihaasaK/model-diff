"""What actually goes over the wire, checked with the real SDK and a mock transport (no network).

The 1.x SDK dropped temperature from messages.create(); this proves arms A and C
still send it, on both the direct path and the batch path.
"""

import json

import anthropic
import httpx2

from model_diff.api import sdk_kwargs

MESSAGE = {
    "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-sonnet-4-5-20250929",
    "content": [{"type": "text", "text": "{}"}], "stop_reason": "end_turn", "stop_sequence": None,
    "usage": {"input_tokens": 1, "output_tokens": 1},
}
BATCH = {
    "id": "msgbatch_1", "type": "message_batch", "processing_status": "in_progress",
    "request_counts": {"processing": 1, "succeeded": 0, "errored": 0, "canceled": 0, "expired": 0},
    "ended_at": None, "created_at": "2026-10-12T00:00:00Z", "expires_at": "2026-10-13T00:00:00Z",
    "archived_at": None, "cancel_initiated_at": None, "results_url": None,
}


def capturing_client():
    sent = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(json.loads(request.content))
        return httpx2.Response(200, json=BATCH if request.url.path.endswith("/batches") else MESSAGE)

    client = anthropic.Anthropic(
        api_key="test-key-not-real", max_retries=0,
        http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handler)),
    )
    return client, sent


REQUEST = {
    "model": "claude-sonnet-4-5-20250929", "max_tokens": 512, "temperature": 0,
    "system": "s", "messages": [{"role": "user", "content": "u"}],
}


def test_direct_calls_send_temperature_through_extra_body():
    client, sent = capturing_client()
    client.messages.create(**sdk_kwargs(REQUEST))
    assert sent[0]["temperature"] == 0
    assert {k: sent[0][k] for k in REQUEST} == REQUEST


def test_batch_requests_forward_temperature_in_params():
    client, sent = capturing_client()
    client.messages.batches.create(requests=[{"custom_id": "A-0-00000", "params": REQUEST}])
    assert sent[0]["requests"][0]["params"]["temperature"] == 0
    assert sent[0]["requests"][0]["params"] == REQUEST


def test_requests_without_sampling_parameters_send_none():
    client, sent = capturing_client()
    request = {k: v for k, v in REQUEST.items() if k != "temperature"} | {"model": "claude-sonnet-5-5"}
    client.messages.create(**sdk_kwargs(request))
    assert "temperature" not in sent[0]
