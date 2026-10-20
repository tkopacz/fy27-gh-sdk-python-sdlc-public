from __future__ import annotations

import asyncio
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from copilot_runtime import (
    CopilotRuntime, RuntimeSetupError, DISABLED_MCP_SERVERS,
    print_event, show_disabled_mcp_servers,
)
from demo_runner import DEMO_DIRECTORIES

ROOT = Path(__file__).resolve().parents[1]


def windows_launcher(name: str) -> Path:
    launcher = (
        Path(os.environ["APPDATA"]) / "Code" / "User" / "globalStorage"
        / "github.copilot-chat" / "copilotCli" / name
    )
    assert launcher.is_file(), "Install the VS Code Copilot Chat CLI launchers before this Windows integration test."
    return launcher


def test_missing_cli_does_not_fall_back_to_an_sdk_download(tmp_path: Path) -> None:
    runtime = CopilotRuntime(environment={"PATH": str(tmp_path)}, output=lambda _: None)
    with pytest.raises(RuntimeSetupError, match="Copilot CLI is missing"):
        runtime.create_client()


def test_invalid_override_is_not_silently_ignored() -> None:
    environment = dict(os.environ, COPILOT_CLI_PATH=str(ROOT / "missing-copilot.exe"))
    with pytest.raises(RuntimeSetupError, match="COPILOT_CLI_PATH is invalid"):
        CopilotRuntime(environment=environment).resolve_cli()


def test_js_entry_point_requires_node(tmp_path: Path) -> None:
    runtime = CopilotRuntime(environment={"PATH": str(tmp_path)})
    with pytest.raises(RuntimeSetupError, match="Node.js is required"):
        runtime.command("copilot.js")

@pytest.mark.parametrize("cli", [False, True])
def test_shared_mcp_announcement_keeps_exact_scope_and_names(cli: bool) -> None:
    output: list[str] = []
    show_disabled_mcp_servers(output.append, cli=cli)
    scope = "CLI run" if cli else "session"
    assert output == [
        f"MCP server names disabled for this {scope}: " + ", ".join(DISABLED_MCP_SERVERS)
    ]
    assert len(DISABLED_MCP_SERVERS) == len(set(DISABLED_MCP_SERVERS)) == 12


def test_live_shared_event_output_and_session_mcp_policy() -> None:
    from copilot import PermissionHandler
    from copilot.session_events import AssistantMessageData, SessionEvent

    wire: list[str] = []
    symbolic: list[str] = []

    def observe(event: SessionEvent) -> None:
        print_event(event, wire.append)
        print_event(event, symbolic.append, symbolic=True)

    async def request() -> None:
        async with CopilotRuntime(environment=os.environ).create_client() as client:
            async with await client.create_session(
                model="auto", available_tools=[],
                disabled_mcp_servers=list(DISABLED_MCP_SERVERS),
                on_permission_request=PermissionHandler.approve_all,
                on_event=observe,
            ) as session:
                response = await session.send_and_wait(
                    "Reply with exactly SHARED_EVENT_OUTPUT_OK. Do not use tools.", timeout=90,
                )
                assert response is not None and isinstance(response.data, AssistantMessageData)
                assert "SHARED_EVENT_OUTPUT_OK" in response.data.content

    asyncio.run(request())
    assert "[event] session.idle" in wire
    assert "[event] SESSION_IDLE -> session.idle" in symbolic
    assert len(wire) == len(symbolic)
    assert not any("SHARED_EVENT_OUTPUT_OK" in line for line in wire + symbolic)


@pytest.mark.parametrize("source", [
    "path", "environment",
    *[
        pytest.param(name, marks=pytest.mark.skipif(
            sys.platform != "win32", reason="VS Code Windows launcher",
        ))
        for name in ("copilot.ps1", "copilot.bat", "copilot")
    ],
])
def test_real_sdk_start_authentication_and_cleanup(source: str) -> None:
    environment = dict(os.environ)
    if source == "path":
        environment.pop("COPILOT_CLI_PATH", None)
    elif source == "environment":
        environment["COPILOT_CLI_PATH"] = CopilotRuntime(environment=environment).resolve_cli()
    else:
        launcher = windows_launcher(source)
        environment["COPILOT_CLI_PATH"] = str(launcher)
        environment["PATH"] = str(launcher.parent) + os.pathsep + environment["PATH"]
    original = dict(environment)
    output: list[str] = []
    runtime = CopilotRuntime(environment=environment, output=output.append)

    async def verify() -> None:
        # This real runtime handshake verifies CLI login without a model request.
        # The context must stop the child even when authentication fails.
        client = runtime.create_client()
        async with client:
            assert (await client.ping("shared-startup")).message == "pong: shared-startup"
            status = await client.get_auth_status()
            assert status.isAuthenticated, "Run `copilot login`; VS Code sign-in alone is insufficient."
        with pytest.raises(RuntimeError, match="Client is not connected"):
            _ = client.rpc

    asyncio.run(verify())
    assert environment == original
    assert any(line.startswith("Copilot CLI: ") for line in output)
    if source not in {"path", "environment"}:
        assert any(line.startswith("VS Code Copilot launcher: ") for line in output)


@pytest.mark.parametrize("name", DEMO_DIRECTORIES)
def test_every_demo_imports_when_started_in_its_own_directory(name: str) -> None:
    directory = ROOT / "demos" / name
    # A fresh process has only the demo directory on sys.path, as direct launch
    # and F5 do. Importing must find the shared runtime without PYTHONPATH setup.
    result = subprocess.run(
        [sys.executable, "-c", "import runpy; runpy.run_path('main.py', run_name='startup_check')"],
        cwd=directory, env=os.environ, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_cli_extension_validation_uses_the_same_native_runtime() -> None:
    spec = importlib.util.spec_from_file_location(
        "runtime_cli_extension", ROOT / "demos" / "010-cli-extension" / "main.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    environment = dict(os.environ)
    if sys.platform == "win32":
        launcher = windows_launcher("copilot.ps1")
        environment["COPILOT_CLI_PATH"] = str(launcher)
        environment["PATH"] = str(launcher.parent) + os.pathsep + environment["PATH"]
    app = module.CliExtensionApplication(environment=environment)
    programs = app.validate()
    assert programs["copilot"] == app.environment["COPILOT_CLI_PATH"]
    result = subprocess.run(
        [*CopilotRuntime(environment=app.environment).command(programs["copilot"]), "--version"],
        env=app.environment, capture_output=True, text=True, check=True, timeout=30,
    )
    assert "GitHub Copilot CLI" in result.stdout
