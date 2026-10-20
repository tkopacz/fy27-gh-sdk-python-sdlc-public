from __future__ import annotations

import importlib.util
import json
import os
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from copilot.generated.rpc import PermissionDecisionApproveOnce, PermissionDecisionReject
from copilot.generated.session_events import PermissionRequestShell, PermissionRequestWrite

MODULE_PATH = Path(__file__).with_name("main.py")
SPEC = importlib.util.spec_from_file_location("human_policy_demo", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
demo = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = demo
SPEC.loader.exec_module(demo)
PROJECT = MODULE_PATH.parent / "workspace"


def vscode_launcher(name: str) -> Path:
    path = (
        Path(os.environ["APPDATA"]) / "Code" / "User" / "globalStorage"
        / "github.copilot-chat" / "copilotCli" / name
    )
    assert path.is_file(), "Install VS Code Copilot Chat CLI launchers for Windows debugger integration tests."
    return path


class TestHumanPolicy:
    def setup_method(self) -> None:
        self.output: list[str] = []
        self.errors: list[str] = []
        self.app = demo.HumanPolicyApplication(
            environment=os.environ,
            output=self.output.append, error_output=self.errors.append, ask=lambda _: "reject"
        )
        self.app.working_directory = PROJECT.resolve()

    def test_hooks_allow_only_focused_tests_and_reads(self) -> None:
        assert self.app.pre_tool_use(
            {"toolName": "shell", "toolArgs": {"command": demo.TEST_COMMAND}}, {}
        )["permissionDecision"] == "allow"
        assert self.app.pre_tool_use(
            {"toolName": "read", "toolArgs": {}}, {}
        )["permissionDecision"] == "allow"
        for command in ("git push origin main", "gh release create v1", "python -m build && twine upload dist/*", demo.TEST_COMMAND + "; git push"):
            assert self.app.pre_tool_use(
                {"toolName": "shell", "toolArgs": {"command": command}}, {}
            )["permissionDecision"] == "deny"
        assert self.app.pre_tool_use(
            {"toolName": "apply_patch", "toolArgs": {}}, {}
        )["permissionDecision"] == "ask"
        assert self.app.pre_tool_use(
            {"toolName": "shell", "toolArgs": {
                "command": demo.TEST_COMMAND, "cwd": "/tmp",
            }}, {}
        )["permissionDecision"] == "deny"

    def test_permission_denies_outside_files_and_allows_selected_file(self) -> None:
        def write(path: Path) -> PermissionRequestWrite:
            return PermissionRequestWrite(
                can_offer_session_approval=False, diff="", file_name=str(path),
                intention="test", resolved_path=str(path),
            )
        assert isinstance(self.app.permission(write(PROJECT / "beancount/parser/booking_full.py"), {}), PermissionDecisionApproveOnce)
        assert isinstance(self.app.permission(write(PROJECT / "pyproject.toml"), {}), PermissionDecisionReject)

    def test_focused_test_requires_the_reviewed_checkout(self) -> None:
        def shell(directory: Path) -> PermissionRequestShell:
            return PermissionRequestShell(
                can_offer_session_approval=False, commands=[],
                full_command_text=demo.TEST_COMMAND,
                has_write_file_redirection=False, intention="run focused tests",
                possible_paths=[], possible_urls=[],
                resolved_working_directory=str(directory),
            )
        assert isinstance(self.app.permission(shell(PROJECT.resolve()), {}), PermissionDecisionApproveOnce)
        assert isinstance(self.app.permission(shell(Path("/tmp")), {}), PermissionDecisionReject)

    @pytest.mark.parametrize("answer", ["reject", "zero_cost", "keep_raising"])
    def test_elicitation_returns_structured_choice(self, answer: str) -> None:
        app = demo.HumanPolicyApplication(environment=os.environ, output=self.output.append, ask=lambda _: answer)
        assert app.elicit({
            "session_id": "test",
            "message": "Choose the zero-units policy.",
            "requestedSchema": {"properties": {"choice": {"type": "string"}}},
        }) == {"action": "accept", "content": {"choice": answer}}

    def test_elicitation_declines_invalid_choice(self) -> None:
        app = demo.HumanPolicyApplication(environment=os.environ, output=self.output.append, ask=lambda _: "invalid")
        assert app.elicit({
            "session_id": "test",
            "message": "Choose the zero-units policy.",
            "requestedSchema": {"properties": {"choice": {"type": "string"}}},
        }) == {"action": "decline"}
        assert "[elicitation] invalid choice; request declined" in self.output

    def test_elicitation_declines_missing_form_with_guidance(self) -> None:
        assert self.app.elicit({
            "session_id": "test",
            "message": "Choose the zero-units policy.",
        }) == {"action": "decline"}
        assert "[elicitation] missing form fields; request declined" in self.output

    def test_failed_tool_context(self) -> None:
        assert self.app.post_tool_failure({"toolName": "read"}, {}) is None
        assert "TestZeroUnitsWithTotalCost" in self.app.post_tool_failure({"toolName": "shell"}, {})["additionalContext"]

    def test_missing_workspace_fails_with_guidance(self) -> None:
        config = replace(demo.CONFIGURATION, working_directory=MODULE_PATH.parent / "missing")
        assert self.app.run(config) == 2
        assert "Prepare the Beancount clone" in self.errors[0]

    def test_missing_cli_fails_with_setup_guidance(self) -> None:
        self.app.environment["COPILOT_CLI_PATH"] = str(MODULE_PATH.with_name("missing-copilot.exe"))
        assert self.app.run(demo.CONFIGURATION) == 2
        assert "Copilot CLI is missing" in self.errors[0]

    def test_debug_configuration_uses_demo_and_repository_interpreter(self) -> None:
        root = MODULE_PATH.parents[2]
        launch = json.loads((root / ".vscode" / "launch.json").read_text())
        assert len(launch["configurations"]) == 1
        configuration = launch["configurations"][0]
        assert configuration["name"] == "Python: Current File (.venv)"
        variables = {
            "${workspaceFolder}": str(root),
            "${pathSeparator}": os.sep,
            "${file}": str(MODULE_PATH),
            "${fileDirname}": str(MODULE_PATH.parent),
        }

        def expand(value: str) -> Path:
            for variable, replacement in variables.items():
                value = value.replace(variable, replacement)
            return Path(value)

        assert configuration["type"] == "debugpy"
        assert configuration["request"] == "launch"
        assert configuration["console"] == "integratedTerminal"
        assert configuration["pythonArgs"] == ["-Xfrozen_modules=off"]
        assert configuration["subProcess"] is False
        assert expand(configuration["program"]) == MODULE_PATH
        assert expand(configuration["cwd"]) == MODULE_PATH.parent
        if sys.platform == "win32":
            interpreter = configuration["windows"]["python"]
            expected = root / ".venv" / "Scripts" / "python.exe"
        else:
            interpreter = configuration["python"]
            expected = root / ".venv" / "bin" / "python"
        assert expand(interpreter) == expected
        assert expected.is_file(), "Prepare the repository .venv before debugging."

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows launcher validation")
    def test_windows_rejects_script_launcher(self) -> None:
        self.app.environment["COPILOT_CLI_PATH"] = str(MODULE_PATH)
        assert self.app.run(demo.CONFIGURATION) == 2
        assert "not a .cmd/.bat/PowerShell launcher" in self.errors[0]

    @pytest.mark.skipif(sys.platform != "win32", reason="VS Code Windows launcher")
    def test_vscode_launcher_without_native_cli_fails_with_guidance(self) -> None:
        launcher = vscode_launcher("copilot.ps1")
        self.app.environment["COPILOT_CLI_PATH"] = str(launcher)
        self.app.environment["PATH"] = str(launcher.parent)
        assert self.app.run(demo.CONFIGURATION) == 2
        assert "has no native copilot.exe on PATH" in self.errors[0]

    @pytest.mark.parametrize("runtime_source", [
        "path", "environment",
        *[
            pytest.param(name, marks=pytest.mark.skipif(
                sys.platform != "win32", reason="VS Code Windows launcher",
            ))
            for name in ("copilot.ps1", "copilot.bat", "copilot")
        ],
    ])
    def test_live_sdk_session_requests_human_choice(self, runtime_source: str) -> None:
        if runtime_source == "path":
            self.app.environment.pop("COPILOT_CLI_PATH", None)
        elif runtime_source == "environment":
            self.app.environment["COPILOT_CLI_PATH"] = self.app.resolve_cli()
        else:
            launcher = vscode_launcher(runtime_source)
            self.app.environment["PATH"] = str(launcher.parent) + os.pathsep + self.app.environment["PATH"]
            self.app.environment["COPILOT_CLI_PATH"] = str(launcher)
        config = replace(
            demo.CONFIGURATION,
            working_directory=PROJECT,
            prompt=(
                "Call the ask_user tool (not a plain-text question) to elicit the "
                "zero-units policy. Provide a form field 'choice' with options "
                "reject, zero_cost and keep_raising. Do not use other tools or edit "
                "files. Then reply with the selected option."
            ),
            timeout_seconds=180,
        )
        code = self.app.run(config)
        assert code == 0, "Live Copilot SDK request failed. Verify CLI login, subscription and network: " + "\n".join(self.errors)
        assert f"Copilot CLI: {self.app.resolve_cli()}" in self.output
        if runtime_source not in {"path", "environment"}:
            assert any("VS Code Copilot launcher:" in line for line in self.output)
            assert Path(self.app.resolve_cli()).suffix.lower() == ".exe"
        assert (
            "MCP server names disabled for this session: "
            + ", ".join(demo.DISABLED_MCP_SERVERS)
        ) in "\n".join(self.output)
        assert "[elicitation] zero-units semantics:" in self.output, \
            "Copilot must use structured elicitation. Use a CLI runtime supporting ask_user_variant='elicitation'."
        assert not any(line.startswith("[user input]") for line in self.output)
        assert "reject" in "\n".join(self.output)
