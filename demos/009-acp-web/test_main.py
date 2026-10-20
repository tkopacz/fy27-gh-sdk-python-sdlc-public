from __future__ import annotations

import asyncio
import importlib.util
import os
import shutil
import socket
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

MODULE_PATH = Path(__file__).with_name("main.py")
MODULE_SPEC = importlib.util.spec_from_file_location("acp_web_demo", MODULE_PATH)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
acp_web_demo = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules[MODULE_SPEC.name] = acp_web_demo
MODULE_SPEC.loader.exec_module(acp_web_demo)


def request_in_process(
    app: FastAPI,
    method: str,
    path: str,
    *,
    json_body: dict[str, str] | None = None,
) -> httpx.Response:
    async def send() -> httpx.Response:
        async with app.router.lifespan_context(app):
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://testserver",
            ) as client:
                return await client.request(method, path, json=json_body)

    return asyncio.run(send())


def test_homepage_explains_local_acp_client_and_read_only_scope() -> None:
    response = request_in_process(acp_web_demo.create_app(), "GET", "/")

    assert response.status_code == 200
    assert "Copilot CLI over ACP" in response.text
    assert "view, grep" in response.text
    assert "textContent" in response.text


def test_prompt_validation_rejects_empty_oversized_and_unknown_sessions() -> None:
    app = acp_web_demo.create_app()
    empty = request_in_process(
        app,
        "POST",
        "/api/sessions/not-a-session/messages",
        json_body={"prompt": "   "},
    )
    oversized = request_in_process(
        app,
        "POST",
        "/api/sessions/not-a-session/messages",
        json_body={"prompt": "x" * (acp_web_demo.MAX_PROMPT_CHARACTERS + 1)},
    )
    unknown = request_in_process(
        app,
        "POST",
        "/api/sessions/not-a-session/messages",
        json_body={"prompt": "Reply with OK"},
    )

    assert empty.status_code == 422
    assert oversized.status_code == 422
    assert unknown.status_code == 404
    assert "not found" in unknown.json()["detail"]


def test_session_creation_fails_clearly_when_copilot_cli_is_not_on_path() -> None:
    app = acp_web_demo.create_app(environment={"PATH": ""})
    response = request_in_process(app, "POST", "/api/sessions")

    assert response.status_code == 503
    assert "Copilot CLI is missing" in response.json()["detail"]
    assert not app.state.session_manager.sessions


def test_configuration_refuses_non_loopback_bind_address() -> None:
    configuration = acp_web_demo.DemoConfiguration(
        host="0.0.0.0",
    )

    with pytest.raises(
        acp_web_demo.DemoConfigurationError,
        match="only binds to localhost",
    ):
        configuration.validate()


@pytest.mark.parametrize(
    ("kind", "options", "allowed"),
    (
        ("read", ("allow_once", "allow_always"), True),
        ("search", ("allow_once",), True),
        ("execute", ("allow_once",), False),
        ("read", ("allow_always",), False),
    ),
)
def test_permission_handler_grants_only_one_time_read_and_search(
    kind: str,
    options: tuple[str, ...],
    allowed: bool,
) -> None:
    client = acp_web_demo.ACPWebClient(asyncio.Queue())
    permission_options = [
        acp_web_demo.PermissionOption(
            option_id=option_kind,
            name=option_kind,
            kind=option_kind,
        )
        for option_kind in options
    ]
    response = asyncio.run(
        client.request_permission(
            "demo-session",
            acp_web_demo.ToolCallUpdate(tool_call_id="demo-call", kind=kind),
            permission_options,
        )
    )

    if allowed:
        assert isinstance(response.outcome, acp_web_demo.AllowedOutcome)
        assert response.outcome.option_id == "allow_once"
    else:
        assert isinstance(response.outcome, acp_web_demo.DeniedOutcome)
        assert response.outcome.outcome == "cancelled"


def test_live_http_acp_flow_streams_response_and_closes_cli_process() -> None:
    def available_port() -> int:
        with socket.socket() as probe:
            probe.bind((acp_web_demo.DEFAULT_HOST, 0))
            return int(probe.getsockname()[1])

    async def exercise_live_flow(port: int) -> tuple[int, str, str, list[str], list[str]]:
        configuration = acp_web_demo.DemoConfiguration()
        configuration.port = port
        server_output: list[str] = []
        app = acp_web_demo.create_app(
            configuration,
            environment=os.environ,
            output=server_output.append,
        )
        server = uvicorn.Server(
            uvicorn.Config(
                app,
                host=acp_web_demo.DEFAULT_HOST,
                port=port,
                log_level="error",
            )
        )
        server_thread = threading.Thread(target=server.run, daemon=True)
        server_thread.start()
        base_url = f"http://{acp_web_demo.DEFAULT_HOST}:{port}"
        try:
            async with AsyncClient(
                base_url=base_url,
                timeout=acp_web_demo.ACP_PROMPT_TIMEOUT_SECONDS + 30,
                trust_env=False,
            ) as client:
                deadline = time.monotonic() + 15
                ready: httpx.Response | None = None
                while time.monotonic() < deadline:
                    try:
                        ready = await client.get("/")
                        if ready.status_code == 200:
                            break
                    except httpx.ConnectError:
                        # Wait briefly while Uvicorn opens its loopback socket.
                        pass
                    await asyncio.sleep(0.05)
                if ready is None:
                    raise AssertionError(
                        "The live ACP demo server did not start on loopback."
                    )
                if ready.status_code != 200:
                    raise AssertionError(
                        f"The live ACP demo server returned HTTP {ready.status_code}."
                    )
                created = await client.post("/api/sessions")
                assert created.status_code == 201, (
                    "The live HTTP → ACP → Copilot CLI integration requires an "
                    "installed Copilot CLI, local CLI authentication (`copilot login`), "
                    "network access, and an active Copilot subscription. "
                    f"Received: {created.text}"
                )
                session_id = created.json()["session_id"]
                stream_task = asyncio.create_task(
                    client.get(f"/api/sessions/{session_id}/events")
                )
                response = await client.post(
                    f"/api/sessions/{session_id}/messages",
                    json={"prompt": "Reply with exactly ACP_OK. Do not use tools."},
                )
                streamed = await stream_task
                assert response.status_code == 200, (
                    response.text + "\n" + "\n".join(server_output)
                )
                assert streamed.status_code == 200, streamed.text
                closed = await client.delete(f"/api/sessions/{session_id}")
                result = (
                    closed.status_code,
                    response.json()["stop_reason"],
                    response.json()["assistant_message"],
                    streamed.text.splitlines(),
                )
        finally:
            server.should_exit = True
            server_thread.join(timeout=10)
            if server_thread.is_alive():
                pytest.fail("The live ACP demo server did not stop cleanly.")
        return (*result, list(app.state.session_manager.sessions))

    if shutil.which("copilot") is None:
        pytest.fail(
            "The live ACP integration requires GitHub Copilot CLI on PATH and "
            "local authentication via `copilot login`."
        )

    closed_status, stop_reason, answer, stream_lines, remaining_sessions = asyncio.run(
        exercise_live_flow(available_port())
    )
    assert stop_reason == "end_turn"
    assert "ACP_OK" in answer
    assert any('"type": "agent_message_chunk"' in line for line in stream_lines)
    assert any('"type": "turn_complete"' in line for line in stream_lines)
    assert closed_status == 204
    assert remaining_sessions == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
