from __future__ import annotations

import asyncio
import importlib.util
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from copilot.tools import ToolInvocation

MODULE_PATH = Path(__file__).with_name("main.py")
MODULE_SPEC = importlib.util.spec_from_file_location("secure_custom_tool_demo", MODULE_PATH)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
secure_demo = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules[MODULE_SPEC.name] = secure_demo
MODULE_SPEC.loader.exec_module(secure_demo)


class TestWorkspaceReadPolicy:
    def setup_method(self) -> None:
        self.policy = secure_demo.WorkspaceReadPolicy(
            secure_demo.CONFIGURATION.working_directory,
            (secure_demo.CONFIGURATION.working_directory,),
        )

    def test_relative_project_file_is_allowed(self) -> None:
        approved = self.policy.authorize("README.rst")

        assert approved == (
            secure_demo.CONFIGURATION.working_directory / "README.rst"
        ).resolve()

    @pytest.mark.parametrize(
        "requested_path",
        [
            secure_demo.OUTSIDE_PATH,
            str(secure_demo.CONFIGURATION.outside_fixture.resolve()),
            str(Path(sys.executable).resolve()),
        ],
    )
    def test_file_outside_allowed_directory_is_denied(
        self, requested_path: str
    ) -> None:
        with pytest.raises(
            secure_demo.PathAccessError,
            match="outside the allowed project directories",
        ):
            self.policy.authorize(requested_path)

    def test_missing_file_is_denied(self) -> None:
        with pytest.raises(
            secure_demo.PathAccessError,
            match="does not identify an existing file",
        ):
            self.policy.authorize("does-not-exist.txt")

    def test_symlink_escaping_the_workspace_is_denied(self, tmp_path: Path) -> None:
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        outside = tmp_path / "outside.txt"
        outside.write_text("not allowed", encoding="utf-8")
        (allowed / "escape.txt").symlink_to(outside)
        policy = secure_demo.WorkspaceReadPolicy(allowed, (allowed,))

        with pytest.raises(
            secure_demo.PathAccessError,
            match="outside the allowed project directories",
        ):
            policy.authorize("escape.txt")


class TestProjectReadGuard:
    def setup_method(self) -> None:
        self.output: list[str] = []
        self.policy = secure_demo.WorkspaceReadPolicy(
            secure_demo.CONFIGURATION.working_directory,
            (secure_demo.CONFIGURATION.working_directory,),
        )
        self.guard = secure_demo.ProjectReadGuard(
            self.policy,
            output=self.output.append,
        )

    def hook_input(self, path: object, *, tool_name: str = "read_project_file"):
        return {
            "sessionId": "hook-test",
            "timestamp": datetime.now(UTC),
            "workingDirectory": str(self.policy.working_directory),
            "toolName": tool_name,
            "toolArgs": {"path": path},
        }

    def test_hook_allows_a_file_inside_the_workspace(self) -> None:
        result = self.guard.check(self.hook_input("README.rst"), {})

        assert result["permissionDecision"] == "allow"
        assert self.output == [
            "[hook] allow tool=read_project_file path=README.rst"
        ]

    def test_hook_denies_a_file_outside_the_workspace(self) -> None:
        result = self.guard.check(self.hook_input(secure_demo.OUTSIDE_PATH), {})

        assert result["permissionDecision"] == "deny"
        assert "outside the allowed project directories" in result[
            "permissionDecisionReason"
        ]
        assert self.output == [
            f"[hook] deny tool=read_project_file path={secure_demo.OUTSIDE_PATH}"
        ]

    def test_hook_denies_malformed_arguments(self) -> None:
        result = self.guard.check(self.hook_input(42), {})

        assert result["permissionDecision"] == "deny"
        assert "requires one string path argument" in result[
            "permissionDecisionReason"
        ]

    def test_hook_denies_an_unapproved_tool(self) -> None:
        result = self.guard.check(
            self.hook_input("README.rst", tool_name="other_tool"),
            {},
        )

        assert result["permissionDecision"] == "deny"
        assert "not approved" in result["permissionDecisionReason"]

    @pytest.mark.parametrize("working_directory", [None, 42, "/does/not/exist"])
    def test_hook_denies_an_invalid_working_directory(
        self, working_directory: object
    ) -> None:
        hook_input = self.hook_input("README.rst")
        hook_input["workingDirectory"] = working_directory

        result = self.guard.check(hook_input, {})

        assert result["permissionDecision"] == "deny"
        assert "unexpected working directory" in result[
            "permissionDecisionReason"
        ]


class TestReadToolContract:
    def setup_method(self) -> None:
        self.output: list[str] = []
        policy = secure_demo.WorkspaceReadPolicy(
            secure_demo.CONFIGURATION.working_directory,
            (secure_demo.CONFIGURATION.working_directory,),
        )
        self.tool = secure_demo.build_read_tool(policy, output=self.output.append)
        assert self.tool.handler is not None

    def invoke(self, arguments: object):
        assert self.tool.handler is not None
        # Invoking the SDK wrapper exercises its generated argument schema
        # before the request can reach the demo's tool handler.
        invocation = ToolInvocation(
            session_id="contract-test",
            tool_call_id="read-call",
            tool_name=self.tool.name,
            arguments=arguments,
        )
        return asyncio.run(self.tool.handler(invocation))

    def test_schema_requires_a_nonempty_path(self) -> None:
        assert self.tool.name == "read_project_file"
        assert self.tool.is_terminal is False
        assert self.tool.defer == "never"
        assert self.tool.parameters is not None
        assert self.tool.parameters["required"] == ["path"]
        assert self.tool.parameters["properties"]["path"]["minLength"] == 1

    def test_allowed_file_is_read_through_the_sdk_tool_wrapper(self) -> None:
        result = self.invoke({"path": "README.rst"})

        assert result.result_type == "success"
        assert "Double-Entry Accounting" in result.text_result_for_llm
        assert self.output == ["[tool] read path=README.rst"]

    def test_empty_path_is_rejected_before_the_handler(self) -> None:
        result = self.invoke({"path": ""})

        assert result.result_type == "failure"
        assert "Invalid tool arguments" in result.text_result_for_llm
        assert self.output == []

    def test_outside_file_is_rejected_by_defense_in_depth(self) -> None:
        result = self.invoke({"path": secure_demo.OUTSIDE_PATH})

        assert result.result_type == "failure"
        assert result.error is not None
        assert "outside the allowed project directories" in result.error
        assert self.output == []


class TestSecureCustomToolIntegration:
    def setup_method(self) -> None:
        self.output: list[str] = []
        self.errors: list[str] = []
        self.application = secure_demo.SecureCustomToolApplication(
            output=self.output.append,
            error_output=self.errors.append,
        )

    @staticmethod
    def repository_status(repository: Path) -> str:
        result = subprocess.run(
            ["git", "-C", str(repository), "status", "--short"],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout

    def test_empty_prompt_fails_before_starting_copilot(self) -> None:
        configuration = replace(secure_demo.CONFIGURATION, prompt=" ")

        exit_code = self.application.run(configuration)

        assert exit_code == 2
        assert self.errors == ["Configuration error: prompt must not be empty."]

    def test_real_agent_blocks_outside_read_then_reads_project_file(self) -> None:
        repository = secure_demo.CONFIGURATION.working_directory
        before = self.repository_status(repository)

        # This live test crosses the installed SDK and authenticated Copilot
        # runtime. It proves the hook denies one call before the handler, allows
        # the project read, and lets the agent continue to a final response.
        exit_code = self.application.run(secure_demo.CONFIGURATION)

        failure = (
            "The live GitHub Copilot SDK session failed. Verify network access, "
            "an active Copilot subscription, CLI authentication, and the Demo 002 "
            "pinned checkout.\n" + "\n".join(self.errors)
        )
        rendered = "\n".join(self.output)
        assert exit_code == 0, failure
        assert (
            "MCP server names disabled for this session: "
            + ", ".join(secure_demo.DISABLED_MCP_SERVERS)
        ) in rendered
        assert (
            f"[hook] deny tool=read_project_file path={secure_demo.OUTSIDE_PATH}"
            in rendered
        )
        assert (
            f"[tool] read path={secure_demo.OUTSIDE_PATH}"
            not in rendered
        )
        assert "[hook] allow tool=read_project_file path=README.rst" in rendered
        assert "[tool] read path=README.rst" in rendered
        assert rendered.count("[event] tool.execution_start") >= 2
        assert "[event] session.idle" in rendered
        assert "Copilot response:" in rendered
        response = rendered.split("Copilot response:", maxsplit=1)[1]
        assert "Double-Entry Accounting" in response
        assert "[lifecycle] Session closed" in rendered
        assert "[lifecycle] Copilot client closed" in rendered
        assert self.repository_status(repository) == before
