from __future__ import annotations

import asyncio
import importlib.util
import os
import subprocess
import sys
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from copilot.generated.rpc import PermissionDecisionApproveOnce, PermissionDecisionDeniedInteractivelyByUser
from copilot.session_events import (
    PermissionRequestCustomTool, PermissionRequestMcp, SessionEvent, SessionEventType,
    ToolExecutionCompleteData, ToolExecutionCompleteResult, ToolExecutionStartData,
)
from copilot.tools import ToolInvocation
import pytest
import re

MODULE_PATH = Path(__file__).with_name("main.py")
SPEC = importlib.util.spec_from_file_location("mcp_resume_demo", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
demo = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = demo
SPEC.loader.exec_module(demo)


class TestMcpResume:
    def setup_method(self) -> None:
        self.output: list[str] = []
        self.errors: list[str] = []
        self.app = demo.McpResumeApplication(
            environment={}, output=self.output.append, error_output=self.errors.append
        )

    def request(self, tool: str, args: dict, *, read_only: bool = True):
        return PermissionRequestMcp(
            server_name="github-mcp-server", tool_name=tool, tool_title=tool,
            read_only=read_only, args=args,
        )

    def test_invalid_settings_fail_before_starting_runtime(self) -> None:
        for config in (
            replace(demo.CONFIGURATION, session_id=""),
            replace(demo.CONFIGURATION, max_ai_credits=0),
            replace(demo.CONFIGURATION, timeout_seconds=-1),
            replace(demo.CONFIGURATION, publish_draft=True),
        ):
            assert self.app.run(config) == 2
        assert "DEMO_007_APPROVE_DRAFT_PR" in self.errors[-1]

    def test_ready_configuration_names_existing_fork_without_a_token(self) -> None:
        assert self.app.validate(demo.CONFIGURATION) == "tkopacz"
        assert demo.CONFIGURATION.resume is None
        assert not demo.CONFIGURATION.remote_mcp
        assert not demo.CONFIGURATION.prepare_draft
        assert not demo.CONFIGURATION.publish_draft
        assert not self.errors

    def test_publish_requires_explicit_approval_and_fork(self) -> None:
        self.app.environment = {"DEMO_007_FORK_OWNER": "beancount"}
        assert self.app.run(replace(demo.CONFIGURATION, publish_draft=True)) == 2
        self.app.environment = {"DEMO_007_FORK_OWNER": "my-fork"}
        assert self.app.run(replace(demo.CONFIGURATION, publish_draft=True)) == 2
        assert "DEMO_007_APPROVE_DRAFT_PR" in self.errors[-1]

    def test_explicit_http_mcp_requires_its_own_token(self) -> None:
        assert self.app.run(replace(demo.CONFIGURATION, remote_mcp=True)) == 2
        assert "DEMO_007_GITHUB_MCP_TOKEN" in self.errors[-1]
        assert "CLI login alone" in self.errors[-1]
        config = replace(demo.CONFIGURATION, remote_mcp=True)
        assert self.app.allowed(
            demo.REMOTE_SERVER, f"{demo.REMOTE_SERVER}-issue_read",
            {"owner": "beancount", "repo": "beancount", "issue_number": 1048},
            True, None, config,
        )
        assert not self.app.allowed(
            demo.SERVER, f"{demo.SERVER}-issue_read",
            {"owner": "beancount", "repo": "beancount", "issue_number": 1048},
            True, None, config,
        )

    def test_prepare_requires_real_fork_checkout_on_approved_branch(self) -> None:
        self.app.environment = {"DEMO_007_FORK_OWNER": "my-fork"}
        config = replace(demo.CONFIGURATION, prepare_draft=True)
        missing = MODULE_PATH.parent / "no-such-checkout"
        assert self.app.run(replace(config, fork_checkout=missing)) == 2
        assert "Prepare a local fork checkout" in self.errors[-1]
        # The shared clone belongs to tkopacz, so another owner must be refused.
        assert self.app.run(config) == 2
        assert "fork branch" in self.errors[-1] or "named fork" in self.errors[-1]

    def test_documentalist_sdk_tool_schema_rejects_bad_note_without_writing(self) -> None:
        tool = self.app.documentalist_tool(demo.CONFIGURATION, "my-fork")
        assert tool.name == demo.UPDATE_DOCS
        assert "note" in tool.parameters["required"]
        with pytest.raises(ValueError, match="DivisionByZero"):
            self.app.validate_note("Unrelated changelog entry")
        assert self.app.tool_guard("my-fork", replace(demo.CONFIGURATION, prepare_draft=True))(
                {"toolName": demo.UPDATE_DOCS, "toolArgs": {"note": "Unrelated changelog entry"}}, {}
            )["permissionDecision"] == "deny"
        result = asyncio.run(tool.handler(ToolInvocation(
            tool_name=demo.UPDATE_DOCS, arguments={"note": "Unrelated changelog entry"}
        )))
        assert result.result_type == "failure"
        assert not self.app.doc_updated

    def test_documentalist_custom_tool_requires_opt_in_permission(self) -> None:
        request = PermissionRequestCustomTool(
            tool_description="Update versions", tool_name=demo.UPDATE_DOCS,
            args={"note": "Proposed DivisionByZero 0 HOOL {{20.00 USD}} issue #1048."},
        )
        assert isinstance(self.app.permission(None, demo.CONFIGURATION)(request, {}), PermissionDecisionDeniedInteractivelyByUser)
        assert isinstance(self.app.permission("my-fork", replace(demo.CONFIGURATION, prepare_draft=True))(request, {}), PermissionDecisionApproveOnce)

    def test_documentalist_note_matches_publish_marker_and_has_one_bounded_line(self) -> None:
        note = (
            "Proposed documentation for issue #1048: explain DivisionByZero with "
            "0 HOOL {{20.00 USD}} and the expected booking error."
        )
        assert self.app.validate_note(note) == note
        config = replace(demo.CONFIGURATION, prepare_draft=True)
        guard = self.app.tool_guard("tkopacz", config)
        assert guard(
            {"toolName": demo.UPDATE_DOCS, "toolArgs": {"note": note}}, {},
        )["permissionDecision"] == "allow"
        for invalid in (
            None, 1048, note + "\nsecond line", note + "x" * 240,
            note.replace("issue #1048", "#1048"), note.replace("Proposed", "Fixed"),
        ):
            assert guard(
                {"toolName": demo.UPDATE_DOCS, "toolArgs": {"note": invalid}}, {},
            )["permissionDecision"] == "deny"

    def test_sdk_permission_boundary_scopes_mcp_reads_and_fork_draft(self) -> None:
        config = replace(demo.CONFIGURATION, publish_draft=True)
        decide = self.app.permission("my-fork", config)
        allowed = (
            ("issue_read", {"owner": "beancount", "repo": "beancount", "issue_number": 1048}, True),
            ("get_file_contents", {"owner": "beancount", "repo": "beancount", "path": "CHANGES"}, True),
            ("create_pull_request", {"owner": "my-fork", "repo": "beancount", "head": config.fork_branch, "base": config.base_branch, "draft": True}, False),
        )
        for tool, args, read_only in allowed:
            assert isinstance(decide(self.request(tool, args, read_only=read_only), {}), PermissionDecisionApproveOnce)
        denied = (
            self.request("issue_read", {"owner": "private", "repo": "private", "issue_number": 1048}),
            self.request("issue_read", {"owner": "beancount", "repo": "beancount", "issue_number": 1049}),
            self.request("get_file_contents", {"owner": "beancount", "repo": "beancount", "path": ".env"}),
            self.request("create_pull_request", {"owner": "beancount", "repo": "beancount", "head": config.fork_branch, "base": config.base_branch, "draft": True}, read_only=False),
            self.request("create_pull_request", {"owner": "my-fork", "repo": "beancount", "head": config.fork_branch, "base": config.base_branch, "draft": False}, read_only=False),
            self.request("push_files", {"owner": "my-fork", "repo": "beancount"}, read_only=False),
        )
        for request in denied:
            assert isinstance(decide(request, {}), PermissionDecisionDeniedInteractivelyByUser)
        assert isinstance(self.app.permission(None, demo.CONFIGURATION)(self.request(
                "create_pull_request", allowed[-1][1], read_only=False
            ), {}), PermissionDecisionDeniedInteractivelyByUser)

    def test_fork_pr_discovery_is_scoped_in_both_transports(self) -> None:
        for remote in (False, True):
            config = replace(demo.CONFIGURATION, remote_mcp=remote)
            server = demo.REMOTE_SERVER if remote else demo.SERVER
            for owner, permitted in (("tkopacz", True), ("beancount", False), ("other", False)):
                args = {"owner": owner, "repo": "beancount", "head": "tkopacz:demo/beancount-1048"}
                assert self.app.allowed(
                    server, f"{server}-list_pull_requests", args, True, "tkopacz", config,
                ) is permitted
            assert not self.app.allowed(
                server, f"{server}-list_pull_requests",
                {"owner": "tkopacz", "repo": "another-repo"}, True, "tkopacz", config,
            )

    def test_pre_tool_hook_denies_unscoped_reads_and_unapproved_pushes(self) -> None:
        config = demo.CONFIGURATION
        guard = self.app.tool_guard(None, config)
        def decision(name: str, args: dict) -> str:
            return guard({"toolName": name, "toolArgs": args}, {})["permissionDecision"]

        assert decision(
            "github-mcp-server-issue_read",
            {"owner": "beancount", "repo": "beancount", "issue_number": 1048},
        ) == "allow"
        assert decision(
            "github-mcp-server-get_file_contents",
            {"owner": "beancount", "repo": "beancount", "path": "CHANGES"},
        ) == "allow"
        assert decision(
            "github-mcp-server-issue_read",
            {"owner": "beancount", "repo": "beancount", "issue_number": 99},
        ) == "deny"
        assert decision(
            "github-mcp-server-get_file_contents",
            {"owner": "other", "repo": "private", "path": "CHANGES"},
        ) == "deny"
        assert decision(
            "github-mcp-server-push_files", {"owner": "my-fork", "repo": "beancount"},
        ) == "deny"
        assert decision("shell", {"command": "git push"}) == "deny"
        assert decision(
            "github-mcp-server-create_pull_request",
            {"owner": "my-fork", "repo": "beancount", "head": config.fork_branch,
             "base": config.base_branch, "draft": True},
        ) == "deny"

    def test_only_successful_scoped_mcp_completions_count_as_reads(self) -> None:
        def event(event_type, data):
            return SessionEvent(
                type=event_type, data=data, id=uuid.uuid4(),
                timestamp=datetime.now(timezone.utc),
            )

        for name, args, call_id in (
            ("issue_read", {"owner": "beancount", "repo": "beancount", "issue_number": 1048}, "issue-failed"),
            ("get_file_contents", {"owner": "beancount", "repo": "beancount", "path": "CHANGES"}, "docs-ok"),
            ("issue_read", {"owner": "another", "repo": "private", "issue_number": 1048}, "unscoped"),
        ):
            self.app.show_event(event(
                SessionEventType.TOOL_EXECUTION_START,
                ToolExecutionStartData(
                    tool_call_id=call_id,
                    tool_name=f"{demo.SERVER}-{name}",
                    mcp_server_name=demo.SERVER, arguments=args,
                ),
            ))
        self.app.show_event(event(
            SessionEventType.TOOL_EXECUTION_COMPLETE,
            ToolExecutionCompleteData(success=False, tool_call_id="issue-failed"),
        ))
        self.app.show_event(event(
            SessionEventType.TOOL_EXECUTION_COMPLETE,
            ToolExecutionCompleteData(
                success=True, tool_call_id="docs-ok",
                result=ToolExecutionCompleteResult(content="Public docs response"),
            ),
        ))
        self.app.show_event(event(
            SessionEventType.TOOL_EXECUTION_COMPLETE,
            ToolExecutionCompleteData(
                success=True, tool_call_id="unscoped",
                result=ToolExecutionCompleteResult(content="Private response"),
            ),
        ))
        assert self.app.successful_reads == {"get_file_contents"}
        assert not self.app.pending_reads

    def test_live_sdk_creates_then_resumes_after_client_restart(self) -> None:
        # Two separate run() calls launch independent Copilot CLI clients. No
        # SDK, MCP, auth, network or persisted-history collaborator is mocked.
        self.app.environment = dict(os.environ)
        config = replace(demo.CONFIGURATION, session_id=f"demo-007-test-{uuid.uuid4().hex}")
        failure = (
            "Live SDK/MCP test requires Copilot CLI login (`copilot login`), "
            "network, subscription and GitHub MCP issue/file access: "
        )
        assert self.app.run(config) == 0, failure + "\n".join(self.errors)
        first = "\n".join(self.output)
        assert f"[session] created {config.session_id}" in first
        assert "[mcp] github-mcp-server status=connected" in first
        assert "[history] events_after=" in first
        assert "[tool] github-mcp-server-issue_read" in first
        assert "[tool] github-mcp-server-get_file_contents" in first
        assert "[event] tool.execution_start" in first
        assert "[event] tool.execution_complete" in first
        assert "Copilot response:" in first
        self.output.clear()
        assert self.app.run(config) == 0, failure + "\n".join(self.errors)
        second = "\n".join(self.output)
        assert f"[session] resumed {config.session_id}" in second
        assert re.search(r"\[history\] events_before=[1-9]\d*", second)
        assert "[event] assistant.usage" in first + second
        assert "[tool] arguments=" not in first + second

    def test_live_documentalist_edits_only_changes_in_real_fork_clone(self, tmp_path: Path) -> None:
        # Fetch real fork sources into an isolated checkout, so the live SDK
        # can edit its baseline without touching the presenter's prepared note.
        checkout = tmp_path / "beancount"
        source = demo.CONFIGURATION.fork_checkout
        base = self.app.git(source, "rev-parse", "origin/master")
        commands = (
            ["git", "init", "--quiet", str(checkout)],
            ["git", "-C", str(checkout), "fetch", "--quiet", "--depth=1", str(source), base],
            ["git", "-C", str(checkout), "switch", "--quiet", "--create",
             demo.CONFIGURATION.fork_branch, "FETCH_HEAD"],
            ["git", "-C", str(checkout), "remote", "add", "origin",
             "https://github.com/tkopacz/beancount.git"],
        )
        for command in commands:
            subprocess.run(
                command,
                check=True, capture_output=True, text=True,
            )
        document = checkout / "CHANGES"
        original = document.read_text(encoding="utf-8")
        self.app.environment = dict(os.environ)
        config = replace(
            demo.CONFIGURATION, session_id=f"demo-007-prepare-{uuid.uuid4().hex}",
            fork_checkout=checkout, prepare_draft=True, resume=False,
        )
        assert self.app.run(config) == 0, "\n".join(self.errors + self.output)
        revised = document.read_text(encoding="utf-8")
        anchor = "The master branch will rely on the Git repository history.\n\n\n"
        note = revised.split(anchor, 1)[1].splitlines()[0]
        assert note.startswith("- Proposed")
        self.app.validate_note(note.removeprefix("- "))
        assert revised.replace(note + "\n\n", "", 1) == original
        assert self.app.git(checkout, "status", "--porcelain").splitlines() == [" M CHANGES"]
        assert self.app.successful_reads >= {"issue_read", "get_file_contents"}
        assert self.app.run(config) == 2
        assert "working tree" in self.errors[-1] or "Review" in self.errors[-1]
