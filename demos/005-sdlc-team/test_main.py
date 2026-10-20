from __future__ import annotations

import asyncio
import importlib.util
import inspect
import json
import os
import subprocess
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from copilot.session_events import (
    AssistantUsageCopilotUsage, AssistantUsageData,
    PermissionRequestRead, PermissionRequestShell, PermissionRequestWrite,
    SessionEvent, SessionEventType,
)
from copilot.tools import Tool, ToolInvocation, ToolResult
import pytest
from prepare_workspaces import WorkspacePreparer

MODULE_PATH = Path(__file__).with_name("main.py")
SPEC = importlib.util.spec_from_file_location("sdlc_team_demo", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
demo = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = demo
SPEC.loader.exec_module(demo)


def test_changes_are_kept_by_default_and_rollback_can_be_selected_externally() -> None:
    assert demo.DemoConfiguration().keep_changes is True
    assert demo.CONFIGURATION.keep_changes is True
    assert replace(demo.CONFIGURATION, keep_changes=False).keep_changes is False


async def invoke_tool(tool: Tool) -> ToolResult:
    assert tool.handler is not None
    result = tool.handler(ToolInvocation())
    if inspect.isawaitable(result):
        return await result
    return result


def usage_event(amount: float | None, *, agent_id: str | None = None) -> SessionEvent:
    return SessionEvent(
        id=uuid4(), timestamp=datetime.now(timezone.utc),
        type=SessionEventType.ASSISTANT_USAGE, agent_id=agent_id,
        data=AssistantUsageData(
            model="accounting-test",
            copilot_usage=(
                AssistantUsageCopilotUsage(total_nano_aiu=float(amount))
                if amount is not None else None
            ),
            cost=999, input_tokens=100, output_tokens=50,
        ),
    )


def test_usage_sums_sdk_billing_for_orchestrator_and_agents_once() -> None:
    usage = demo.RunUsage()
    orchestrator = usage_event(1_250_000_000)
    analyst = usage_event(250_000_000, agent_id="analyst")
    assert usage.add(orchestrator)
    assert usage.add(analyst)
    assert not usage.add(analyst)
    assert usage.report() == {
        "status": "reported", "aic": "1.5", "total_nano_aiu": "1500000000.0",
        "reported_calls": 2, "calls_without_billing": 0, "usage_events": 2,
    }


@pytest.mark.parametrize("amount", [None, -1, float("nan"), float("inf")])
def test_usage_does_not_treat_missing_or_invalid_billing_as_zero(
    amount: float | None,
) -> None:
    usage = demo.RunUsage()
    assert usage.report()["status"] == "unavailable"
    assert usage.report()["aic"] is None
    usage.add(usage_event(amount))
    assert usage.report()["aic"] is None
    assert usage.report()["calls_without_billing"] == 1
    usage.add(usage_event(0))
    assert usage.report()["aic"] == "0.0"
    assert usage.report()["status"] == "partial"


def test_summary_is_bounded_redacted_flushed_and_matches_detailed_log(tmp_path: Path) -> None:
    with demo.ActivityLog(tmp_path, {"API_KEY": "sensitive-marker"}) as log:
        assert log.path is not None and log.summary_path is not None
        assert log.summary_path.name == "summary" + log.path.name.removeprefix("sdlc-")
        log.write("RUN", "started")
        log.write("HANDOFF", "task requested", arguments={
            "agent_type": "analyst", "prompt": "sensitive-marker " + "word " * 300,
        })
        log.write("CUSTOM TOOL", "ruff started", tool_call_id="call-1")
        log.write("CUSTOM TOOL", "ruff process output", stdout="large raw report")
        log.write("CUSTOM TOOL", "ruff completed", report={"status": "findings"})
        log.write("AGENT OUTPUT", "assistant.message", content="sensitive-marker done")
        log.write("CONSOLE", "output", message="[event] assistant.message_delta")
        log.write("CONSOLE", "output", message="[lifecycle] Session closed")
        log.write("CONSOLE", "output", message="[stage] Selecting SDK agent: documentarian")
        log.write("USAGE", "run total", aic="1.5", status="reported")
        log.write("USAGE", "missing billing", aic=None, status="unavailable")
        summary = log.summary_path.read_text(encoding="utf-8")
        detailed = log.path.read_text(encoding="utf-8")
        assert "[HANDOFF] task requested" in summary
        assert "[CUSTOM TOOL] ruff completed" in summary
        assert "[AGENT OUTPUT] assistant.message" in summary
        assert "[USAGE] run total" in summary
        assert "[lifecycle] Session closed" in summary
        assert "[stage] Selecting SDK agent: documentarian" in summary
        assert "aic: 1.5" in summary
        assert "aic: null" in summary
        assert "sensitive-marker" not in summary
        assert "[REDACTED]" in summary
        assert "[truncated; see detailed log]" in summary
        assert "large raw report" not in summary
        assert "assistant.message_delta" not in summary
        assert "large raw report" in detailed
        assert len(summary) < len(detailed)
    assert log.summary_stream is None


def test_invalid_summary_directory_does_not_open_streams(tmp_path: Path) -> None:
    # A real filesystem failure, without replacing streams or SDK collaborators.
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("preserve", encoding="utf-8")
    log = demo.ActivityLog(blocked, {})
    with pytest.raises(OSError):
        with log:
            pytest.fail("An invalid log directory must not open either log.")
    assert log.stream is None
    assert log.summary_stream is None


class TestSdlcTeam:
    def setup_method(self) -> None:
        self.output: list[str] = []
        self.errors: list[str] = []
        self.application = demo.SdlcTeamApplication(
            output=self.output.append, error_output=self.errors.append
        )

    def test_activity_log_is_readable_flushed_redacted_and_unique(
        self, tmp_path: Path
    ) -> None:
        with demo.ActivityLog(
            tmp_path, {"DEMO_API_KEY": "example-sensitive-marker"}
        ) as log:
            log.write(
                "AGENT OUTPUT", "analyst completed",
                content="First line\nDruga linia: zażółć\nexample-sensitive-marker",
                token="ghp_exampleTokenNotARealCredential",
                authorization="Bearer example.header.signature",
            )
            assert log.path is not None
            first_path = log.path
            text = first_path.read_text(encoding="utf-8")
            assert "[AGENT OUTPUT] analyst completed" in text
            assert "#00001" in text
            assert "First line\n    Druga linia: zażółć" in text
            assert "example-sensitive-marker" not in text
            assert "ghp_example" not in text
            assert "example.header.signature" not in text
            assert text.count("[REDACTED]") == 3
        assert log.stream is None
        assert log.summary_stream is None
        with pytest.raises(RuntimeError, match="not open"):
            log.write("RUN", "too late")
        with demo.ActivityLog(tmp_path, {}) as next_log:
            assert next_log.path != first_path
        assert first_path.read_text(encoding="utf-8") == text

    def test_activity_log_failure_is_explicit_before_runtime_starts(
        self, tmp_path: Path
    ) -> None:
        blocked = tmp_path / "not-a-directory"
        blocked.write_text("preserve me", encoding="utf-8")
        config = replace(demo.CONFIGURATION, log_directory=blocked)
        assert self.application.run(config) == 1
        assert any("Copilot session failed:" in message for message in self.errors)
        assert blocked.read_text(encoding="utf-8") == "preserve me"
        assert not any("runtime connected" in message for message in self.output)

    def test_configuration_failure_is_preserved_in_activity_log(
        self, tmp_path: Path
    ) -> None:
        config = replace(
            demo.CONFIGURATION, model="", log_directory=tmp_path / "logs",
        )
        assert self.application.run(config) == 2
        text = next(config.log_directory.glob("sdlc-*.log")).read_text(encoding="utf-8")
        assert "[RUN] started" in text
        assert "[RUN] failed" in text
        assert "ConfigurationError" in text
        assert "model and prompt must not be empty" in text
        assert "[RUN] completed" not in text
        summary = next(config.log_directory.glob("summary*.log")).read_text(encoding="utf-8")
        assert "[RUN] failed" in summary
        assert "[USAGE] run total" in summary
        assert "aic: null" in summary
        assert self.application.usage.report()["usage_events"] == 0

    def test_log_directory_cannot_dirty_the_rollback_workspace(
        self, tmp_path: Path
    ) -> None:
        config = replace(
            demo.CONFIGURATION, working_directory=tmp_path,
            log_directory=tmp_path / "logs",
        )
        assert self.application.run(config) == 2
        assert "outside the rollback workspace" in self.errors[0]
        assert not config.log_directory.exists()

    def test_custom_agents_have_distinct_least_privilege_tool_sets(self) -> None:
        roles = {role["name"]: role for role in demo.AGENTS}
        assert set(roles) == \
            {"analyst", "architect", "programmer", "tester",
             "reviewer", "documentarian", "static-reviewer"}
        for name, role in roles.items():
            assert role["description"], name
            assert role["prompt"], name
            if name != "static-reviewer":
                assert role["tools"], name
        for name in ("analyst", "architect"):
            if name == "analyst":
                assert roles[name]["tools"] == [
                    "grep", "view", demo.PYTHON_ANALYSIS_TOOL
                ]
            else:
                assert roles[name]["tools"] == ["grep", "view"]
        assert demo.PYTHON_ANALYSIS_TOOL not in roles["architect"]["tools"]
        assert roles["static-reviewer"]["tools"] == []
        assert "exclusively" in roles["static-reviewer"]["prompt"]
        assert roles["reviewer"]["tools"] == ["grep", "view", "git_diff"]
        for name in ("programmer", "documentarian"):
            assert "apply_patch" in roles[name]["tools"]
            assert "edit" in roles[name]["tools"]
            assert "bash" not in roles[name]["tools"]
            assert "powershell" not in roles[name]["tools"]
        assert demo.SHELL_TOOL in roles["tester"]["tools"]
        assert demo.TEST_COMMAND in roles["tester"]["prompt"]
        assert demo.FULL_TEST_COMMAND in roles["tester"]["prompt"]
        assert "pytest-style" in roles["tester"]["prompt"]
        assert "0 HOOL {{20.00 USD}}" in roles["tester"]["prompt"]
        assert "python_static_analysis" in roles["analyst"]["prompt"]

    def test_runtime_shell_uses_the_repository_interpreter(self) -> None:
        application = demo.SdlcTeamApplication(environment={"PATH": os.defpath})
        assert application.environment["PATH"].split(os.pathsep)[0] == str(
            Path(sys.executable).parent
        )
        assert application.environment["PATH"].endswith(os.defpath)

    def test_broken_tool_environment_stops_before_copilot_starts(
        self, tmp_path: Path
    ) -> None:
        environment = dict(os.environ)
        environment["PYTHONHOME"] = str(tmp_path)
        application = demo.SdlcTeamApplication(
            environment=environment,
            output=self.output.append, error_output=self.errors.append,
        )
        WorkspacePreparer(tmp_path, {"005-sdlc-team": "demo-base-1048"}).run()
        config = replace(
            demo.CONFIGURATION, log_directory=tmp_path / "logs",
            working_directory=tmp_path / "demos" / "005-sdlc-team" / "workspace",
        )
        before = self.repository_status(config.working_directory)
        assert application.run(config) == 2
        assert "toolchain is not ready" in self.errors[0]
        assert str(Path(sys.executable)) in self.errors[0]
        for module in ("pytest", "ruff", "pyright"):
            assert f"{module}: exit " in self.errors[0]
        assert not any("runtime connected" in message for message in self.output)
        text = next(config.log_directory.glob("sdlc-*.log")).read_text(encoding="utf-8")
        assert "ConfigurationError" in text
        assert "No Copilot session was started" in text
        assert self.repository_status(config.working_directory) == before

    def test_static_analysis_tool_runs_ruff_and_pyright_and_compacts_report(self) -> None:
        messages: list[str] = []
        tool = demo.build_python_static_analysis_tool(
            demo.CONFIGURATION.working_directory, output=messages.append
        )

        assert tool.name == demo.PYTHON_ANALYSIS_TOOL
        assert tool.parameters["properties"] == {}
        assert tool.handler is not None
        result = asyncio.run(invoke_tool(tool))

        assert result.result_type == "success"
        report = json.loads(result.text_result_for_llm)
        assert report["scope"] == "beancount/"
        assert set(report["analyzers"]) == {"ruff", "pyright"}
        assert json.dumps(
            report, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ) == result.text_result_for_llm
        assert len(result.text_result_for_llm.encode("utf-8")) <= demo.MAX_REPORT_BYTES
        assert report["filters"]["json_bytes_limit"] == demo.MAX_REPORT_BYTES
        for analyzer in report["analyzers"].values():
            assert analyzer["status"] in {"clean", "findings"}
            assert analyzer["finding_count"] >= len(analyzer["findings"])
            assert len(analyzer["findings"]) <= demo.MAX_FINDINGS_PER_ANALYZER
            assert analyzer["omitted_findings"] == (
                analyzer["finding_count"] - len(analyzer["findings"])
            )
            for finding in analyzer["findings"]:
                assert finding["message"] == " ".join(finding["message"].split())
                assert not Path(finding["file"]).is_absolute()
        assert report["filters"]["whitespace"] == \
            "Collapsed repeated whitespace in messages."
        assert messages[0].startswith("[analysis] Ruff/Pyright report:")
        assert demo.compact_report_text("finding   with\nextra    whitespace") == \
            "finding with extra whitespace"

    def test_static_analysis_tool_reports_workspace_execution_failures(
        self, tmp_path: Path
    ) -> None:
        missing_directory = tmp_path / "not-created"
        tool = demo.build_python_static_analysis_tool(missing_directory)
        assert tool.handler is not None

        result = asyncio.run(invoke_tool(tool))

        assert result.result_type == "failure"
        assert result.text_result_for_llm.startswith("Static analysis incomplete;")
        prefix = "Static analysis incomplete; do not treat this as a clean review. "
        report = json.loads(result.text_result_for_llm.removeprefix(prefix))
        assert all(
            analyzer["status"] == "failed"
            for analyzer in report["analyzers"].values()
        )

    def test_static_analysis_reports_real_configuration_error(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "beancount").mkdir()
        (tmp_path / "beancount" / "example.py").write_text("value = 1\n")
        (tmp_path / "ruff.toml").write_text('select = ["NOT_A_RUFF_RULE"]\n')
        with demo.ActivityLog(tmp_path / "logs", {}) as log:
            tool = demo.build_python_static_analysis_tool(
                tmp_path, activity_log=log,
            )
            result = asyncio.run(invoke_tool(tool))
            assert log.path is not None
            text = log.path.read_text(encoding="utf-8")
        assert "[CUSTOM TOOL] ruff process output" in text
        assert "Unknown rule selector" in text
        assert "[CUSTOM TOOL] static analysis failed" in text

        assert result.result_type == "failure"
        prefix = "Static analysis incomplete; do not treat this as a clean review. "
        report = json.loads(result.text_result_for_llm.removeprefix(prefix))
        ruff = report["analyzers"]["ruff"]
        assert ruff["status"] == "failed"
        assert ruff["exit_code"] == 2
        assert "Unknown rule selector" in ruff["error"]
        assert "invalid JSON" not in ruff["error"]
        assert report["analyzers"]["pyright"]["status"] == "clean"

    @pytest.mark.parametrize(
        ("name", "stdout", "return_code", "expected"),
        [
            ("ruff", "[]", 0, []),
            ("ruff", '[{"code":"F401"}]', 1, [{"code": "F401"}]),
            ("pyright", '{"generalDiagnostics":[]}', 0, {"generalDiagnostics": []}),
            ("pyright", '{"generalDiagnostics":[{}]}', 1, {"generalDiagnostics": [{}]}),
        ],
    )
    def test_decode_analyzer_output_accepts_json_reports(
        self, name: str, stdout: str, return_code: int, expected: object
    ) -> None:
        assert demo.decode_analyzer_output(
            name, stdout, "non-fatal warning", return_code
        ) == expected

    @pytest.mark.parametrize(
        ("stdout", "stderr", "return_code", "message"),
        [
            ("", "Invalid configuration\n details", 2, "exited with code 2"),
            ("{}", "Fatal analyzer error", 3, "exited with code 3"),
            ("", "", 0, "returned no JSON report"),
            (" \n\t", "No report produced", 1, "returned no JSON report"),
            ("not JSON", "Analyzer warning", 0, "invalid JSON at character 0"),
            ('{"diagnostics":', "", 1, "invalid JSON at character"),
            ("[]\ntrailing output", "", 0, "Extra data"),
        ],
    )
    def test_decode_analyzer_output_rejects_failed_or_invalid_reports(
        self, stdout: str, stderr: str, return_code: int, message: str
    ) -> None:
        with pytest.raises(demo.StaticAnalysisError) as caught:
            demo.decode_analyzer_output("ruff", stdout, stderr, return_code)

        assert message in str(caught.value)
        if stderr:
            assert demo.compact_report_text(stderr) in str(caught.value)

    def test_reviewer_diff_tool_reads_the_checkout(self, tmp_path: Path) -> None:
        directory = demo.CONFIGURATION.working_directory
        if not directory.is_dir():
            pytest.fail("Prepare the pinned checkout as described in README.md.")
        with demo.ActivityLog(tmp_path / "logs", {}) as log:
            tool = demo.build_diff_tool(directory, activity_log=log)
            assert tool.name == "git_diff"
            assert tool.parameters["properties"] == {}
            assert tool.handler is not None
            result = asyncio.run(invoke_tool(tool))
            assert log.path is not None
            text = log.path.read_text(encoding="utf-8")
        assert "[CUSTOM TOOL] git_diff started" in text
        assert "[CUSTOM TOOL] git_diff completed" in text
        assert "exit_code:\n    0" in text
        assert result.result_type == "success"
        assert result.text_result_for_llm

    def test_static_analysis_keeps_event_loop_responsive(self) -> None:
        async def analyze() -> int:
            tool = demo.build_python_static_analysis_tool(
                demo.CONFIGURATION.working_directory
            )
            pending = asyncio.create_task(invoke_tool(tool))
            ticks = 0
            while not pending.done():
                await asyncio.sleep(0.01)
                ticks += 1
            result = await pending
            assert result.result_type == "success"
            return ticks

        assert asyncio.run(analyze()) > 1, \
            "Local analyzers blocked SDK events, deadlines and cancellation."

    def test_local_tool_timeout_and_cancellation_reap_the_process(
        self, tmp_path: Path
    ) -> None:
        marker = tmp_path / "tool.pid"
        command = [
            sys.executable, "-c",
            "import os, pathlib, time; "
            f"pathlib.Path({str(marker)!r}).write_text(str(os.getpid())); "
            "time.sleep(60)",
        ]

        def assert_reaped() -> None:
            pid = int(marker.read_text())
            with pytest.raises(ProcessLookupError):
                os.kill(pid, 0)

        async def run() -> None:
            with pytest.raises(subprocess.TimeoutExpired):
                await demo.run_tool_command(command, MODULE_PATH.parent, 0.5)
            assert_reaped()
            marker.unlink()
            pending = asyncio.create_task(
                demo.run_tool_command(command, MODULE_PATH.parent, 60)
            )
            async with asyncio.timeout(5):
                while not marker.exists():
                    await asyncio.sleep(0.01)
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
            assert_reaped()

        asyncio.run(run())

    def test_sdk_permission_policy_enforces_per_role_write_paths(self) -> None:
        self.application.permission_directory = demo.CONFIGURATION.working_directory.resolve()
        self.application.tool_roles.update(
            {"programmer-call": "programmer", "tester-call": "tester",
             "writer-call": "documentarian", "review-call": "reviewer"}
        )

        def write(path: str, call: str | None, **options: object) -> PermissionRequestWrite:
            return PermissionRequestWrite(
                can_offer_session_approval=False, diff="", file_name=path,
                intention="edit", tool_call_id=call, **options,
            )

        for call, path in (
            ("programmer-call", "beancount/parser/booking_full.py"),
            ("tester-call", "beancount/parser/booking_full_test.py"),
            ("writer-call", "CHANGES"),
        ):
            assert self.application.decide_permission(write(path, call), {}).kind == \
                "approve-once"
        for call, path in (
            ("programmer-call", "beancount/parser/booking_full_test.py"),
            ("tester-call", "beancount/parser/booking_full.py"),
            ("writer-call", "beancount/parser/booking_full.py"),
            ("review-call", "CHANGES"),
            ("unknown-call", "beancount/parser/booking_full_test.py"),
            ("programmer-call", "../more.py"),
            ("programmer-call", "beancount/../beancount/parser/booking_full_test.py"),
        ):
            assert self.application.decide_permission(write(path, call), {}).kind == \
                "reject"
        assert self.application.decide_permission(
                write("beancount/parser/booking_full.py", "programmer-call",
                      resolved_path=str(MODULE_PATH)), {}
            ).kind == "reject"
        assert self.application.decide_permission(
                write("beancount/parser/booking_full.py", "programmer-call",
                      request_sandbox_bypass=True), {}
            ).kind == "reject"
        assert self.application.decide_permission(
                write("beancount/parser/booking_full.py", None), {}
            ).kind == "reject"
        assert self.application.decide_permission(
                PermissionRequestRead(intention="read", path="beancount/parser/booking_full.py"),
                {},
            ).kind == "approve-once"

    def test_sdk_permission_policy_allows_only_exact_tester_command(self) -> None:
        directory = demo.CONFIGURATION.working_directory.resolve()
        self.application.permission_directory = directory
        self.application.tool_roles.update(
            {"tester-call": "tester", "review-call": "reviewer"}
        )
        self.application.tool_arguments.update({
            "tester-call": {"command": demo.TEST_COMMAND},
            "review-call": {"command": demo.TEST_COMMAND},
        })

        def shell(command: str, call: str = "tester-call",
                  **options: object) -> PermissionRequestShell:
            fields = {
                "can_offer_session_approval": False, "commands": [],
                "full_command_text": command, "has_write_file_redirection": False,
                "intention": "test", "possible_paths": [], "possible_urls": [],
                "resolved_working_directory": str(directory), "tool_call_id": call,
            }
            fields.update(options)
            return PermissionRequestShell(**fields)

        assert self.application.decide_permission(shell(demo.TEST_COMMAND), {}).kind == \
            "approve-once"
        assert self.application.decide_permission(
                shell(demo.TEST_COMMAND, resolved_working_directory=None), {}
            ).kind == "approve-once"
        self.application.tool_arguments["tester-call"]["command"] = demo.FULL_TEST_COMMAND
        assert self.application.decide_permission(
                shell(demo.FULL_TEST_COMMAND), {}
            ).kind == "approve-once"
        assert self.application.decide_permission(
                shell(demo.TEST_COMMAND), {}
            ).kind == "reject"
        self.application.tool_arguments["tester-call"]["command"] = demo.TEST_COMMAND
        for request in (
            shell(demo.TEST_COMMAND + "; echo unsafe"),
            shell(demo.TEST_COMMAND + "\npython -c 'print(1)'"),
            shell("python -m pytest beancount -q"),
            shell("git commit -am demo"),
            shell("git push"),
            shell(demo.TEST_COMMAND, call="review-call"),
            shell(demo.TEST_COMMAND, call="unknown-call"),
            shell(demo.TEST_COMMAND, has_write_file_redirection=True),
            shell(demo.TEST_COMMAND, resolved_working_directory=str(MODULE_PATH.parent)),
            shell(demo.TEST_COMMAND, request_sandbox_bypass=True),
        ):
            assert self.application.decide_permission(request, {}).kind == "reject"
        self.application.tool_arguments["tester-call"] = {
            "command": demo.TEST_COMMAND, "cwd": str(MODULE_PATH.parent),
        }
        assert self.application.decide_permission(
                shell(demo.TEST_COMMAND, resolved_working_directory=None), {}
            ).kind == "reject"

    def test_missing_pinned_checkout_fails_before_connecting(self) -> None:
        config = replace(
            demo.CONFIGURATION,
            working_directory=MODULE_PATH.parent / "missing-checkout",
        )
        assert self.application.run(config) == 2
        assert "Prepare the Beancount clone" in self.errors[0]

    @pytest.mark.parametrize("change", ["tracked", "staged", "untracked"])
    def test_dirty_workspace_is_preserved_before_connecting(
        self, tmp_path: Path, change: str
    ) -> None:
        WorkspacePreparer(tmp_path, {"005-sdlc-team": "demo-base-1048"}).run()
        directory = tmp_path / "demos" / "005-sdlc-team" / "workspace"
        source = directory / (
            "presenter.txt" if change == "untracked" else demo.PYTHON_ANALYSIS_FILE
        )
        source.write_text("presenter work\n")
        if change == "staged":
            WorkspacePreparer.git("-C", str(directory), "add", demo.PYTHON_ANALYSIS_FILE)
        before = self.repository_status(directory)

        assert self.application.run(
            replace(demo.CONFIGURATION, working_directory=directory)
        ) == 2

        assert "requires a clean workspace" in self.errors[0]
        assert source.read_text() == "presenter work\n"
        assert self.repository_status(directory) == before

    def test_rollback_restores_only_approved_files_without_moving_head(
        self, tmp_path: Path
    ) -> None:
        WorkspacePreparer(tmp_path, {"005-sdlc-team": "demo-base-1048"}).run()
        directory = tmp_path / "demos" / "005-sdlc-team" / "workspace"
        originals = {
            name: (directory / name).read_bytes()
            for name in demo.WRITE_PATHS.values()
        }
        for name in originals:
            (directory / name).write_text("demo edits\n")

        self.application.rollback(directory, demo.EXPECTED_COMMIT)

        assert all((directory / name).read_bytes() == data for name, data in originals.items())
        assert self.repository_status(directory) == ""
        assert WorkspacePreparer.git("-C", str(directory), "rev-parse", "HEAD") == demo.EXPECTED_COMMIT
        assert "[rollback] Base restored; workspace clean. No commit or push." in self.output

    def test_rollback_reports_remaining_changes_without_deleting_them(
        self, tmp_path: Path
    ) -> None:
        WorkspacePreparer(tmp_path, {"005-sdlc-team": "demo-base-1048"}).run()
        directory = tmp_path / "demos" / "005-sdlc-team" / "workspace"
        extra = directory / "presenter.txt"
        extra.write_text("keep me\n")
        with pytest.raises(RuntimeError, match="not clean after rollback"):
            self.application.rollback(directory, demo.EXPECTED_COMMIT)
        assert extra.read_text() == "keep me\n"
        assert self.errors[0].startswith("[rollback] Failed:")

    def test_rollback_reports_git_failure(self, tmp_path: Path) -> None:
        with pytest.raises(subprocess.CalledProcessError):
            self.application.rollback(tmp_path, demo.EXPECTED_COMMIT)
        assert self.errors[0].startswith("[rollback] Failed:")

    def test_invalid_settings_are_rejected_before_connecting(self) -> None:
        for change in (
            {"model": " "}, {"prompt": " "}, {"timeout_seconds": 0},
            {"timeout_seconds": float("inf")},
            {"progress_interval_seconds": 0},
            {"progress_interval_seconds": float("nan")},
            {"fallback_agent": "unknown"},
            {"repair_prompt": " "},
            {"keep_changes": "false"},
        ):
            self.errors.clear()
            assert self.application.run(replace(demo.CONFIGURATION, **change)) == 2
            assert "Configuration error:" in self.errors[0]

    @staticmethod
    def repository_status(directory: Path) -> str:
        return subprocess.run(
            ["git", "-C", str(directory), "status", "--short"],
            check=True, capture_output=True, text=True,
        ).stdout

    def test_live_sdk_delegates_read_only_analysis(self, tmp_path: Path) -> None:
        WorkspacePreparer(tmp_path, {"005-sdlc-team": "demo-base-1048"}).run()
        config = replace(
            demo.CONFIGURATION,
            keep_changes=False,
            repair_prompt=None,
            working_directory=tmp_path / "demos" / "005-sdlc-team" / "workspace",
            prompt=(
                "Delegate to analyst through task and require it to call "
                "python_static_analysis once and return its complete JSON "
                "immediately. This is only a report handoff check: tell analyst "
                "not to inspect source or solve the issue. After "
                "analyst completes, YOU must delegate to static-reviewer "
                "using task with that JSON, asking for at most five sentences of "
                "project review exclusively from Ruff/Pyright findings. Do "
                "not edit files or run any other commands."
            ),
            timeout_seconds=240,
            log_directory=tmp_path / "logs",
        )
        # A missing checkout or CLI login must fail visibly, not silently skip
        # the actual SDK/runtime integration test.
        try:
            before = self.repository_status(config.working_directory)
        except (OSError, subprocess.CalledProcessError) as error:
            pytest.fail(
                "Prepare the Beancount clone as described in "
                f"README.md before running the live SDK test: {error}"
            )
        exit_code = self.application.run(config)
        failure = (
            "Live Copilot SDK test requires the pinned checkout, network, an "
            "active subscription and GitHub Copilot CLI login; verify with "
            "`copilot -p 'Reply with OK' --silent`.\n" + "\n".join(self.errors)
        )
        assert exit_code == 0, failure
        rendered = "\n".join(self.output)
        assert "[event] session.start" in rendered
        assert "[event] session.idle" in rendered
        assert self.application.delegated, "Runtime did not delegate to analyst."
        assert "analyst" in self.application.tool_roles.values()
        assert "[fallback]" not in rendered
        assert "[stage] orchestrator: prompt 2" not in rendered
        assert "[stage] Selecting SDK agent: documentarian" not in rendered
        assert "[event] subagent.started" in rendered
        assert "[event] subagent.completed" in rendered
        assert "[tool] start python_static_analysis" in rendered
        assert "[tool] complete success=True" in rendered
        assert "[analysis] Ruff/Pyright report:" in rendered
        assert "static-reviewer" in self.application.agent_roles.values()
        assert "[lifecycle] Session closed" in rendered
        assert "[lifecycle] Copilot client closed" in rendered
        assert "Copilot response:" in rendered
        assert self.repository_status(config.working_directory) == before
        text = next(config.log_directory.glob("sdlc-*.log")).read_text(encoding="utf-8")
        for expected in (
            "[RUN] started", "[RUN] completed", "[SESSION] create requested",
            "[HANDOFF] user prompt sent", "[HANDOFF] task requested",
            "[HANDOFF] task returned", "[AGENT] subagent.started",
            "[AGENT] subagent.completed", "[AGENT OUTPUT]",
            "[CUSTOM TOOL] ruff started", "[CUSTOM TOOL] ruff process output",
            "[CUSTOM TOOL] ruff completed", "[CUSTOM TOOL] pyright started",
            "[CUSTOM TOOL] pyright completed",
            "[CUSTOM TOOL] static analysis returned to caller",
            "tool_call_id:", "agent_id:", "recipient:",
            "static-reviewer", "[ARTIFACT] diff before rollback",
            "[rollback] Base restored",
        ):
            assert expected in text, expected
        assert text.index("ruff started") < text.index("ruff completed")
        assert text.index("diff before rollback") < text.index("[rollback] Base restored")
        assert self.application.activity_log is None
        summary = next(config.log_directory.glob("summary*.log")).read_text(encoding="utf-8")
        for expected in (
            "[RUN] started", "[RUN] completed", "[AGENT] subagent.started",
            "[AGENT] subagent.completed", "[HANDOFF] task requested",
            "[HANDOFF] task returned", "[CUSTOM TOOL] ruff started",
            "[CUSTOM TOOL] pyright completed", "[USAGE] run total",
            "[rollback] Base restored", "static-reviewer",
        ):
            assert expected in summary, expected
        assert "ruff process output" not in summary
        assert len(summary) < len(text)
        assert self.application.usage.report()["usage_events"] > 0

    def test_live_hybrid_workflow_repairs_then_explicitly_documents(
        self, tmp_path: Path
    ) -> None:
        config = replace(demo.CONFIGURATION, keep_changes=False, log_directory=tmp_path / "logs")
        before = self.repository_status(config.working_directory)
        verification: list[subprocess.CompletedProcess[str]] = []

        def observe(message: str) -> None:
            self.output.append(message)
            if message == "[stage] Selecting SDK agent: documentarian":
                # Verify the real edited checkout before documentation/rollback;
                # a successful tool event alone does not prove pytest passed.
                for selection in (["-k", "TestZeroUnitsWithTotalCost"], []):
                    verification.append(subprocess.run(
                        [sys.executable, "-m", "pytest",
                         "beancount/parser/booking_full_test.py", "-q", *selection],
                        cwd=config.working_directory, env=self.application.environment,
                        capture_output=True, text=True, timeout=120, check=False,
                    ))

        self.application.output = observe
        assert self.application.run(config) == 0, (
            "The full workflow requires the prepared checkout, compiled parser, "
            "Copilot CLI login, network and subscription.\n" + "\n".join(self.errors)
        )
        text = next(config.log_directory.glob("sdlc-*.log")).read_text(encoding="utf-8")
        first = text.index("[stage] orchestrator: prompt 1")
        second = text.index("[stage] orchestrator: prompt 2")
        documentation = text.index("[stage] Selecting SDK agent: documentarian")
        assert first < second < documentation
        analysis = demo.compact_report_text(text[first:second])
        repair = demo.compact_report_text(text[second:documentation])
        assert "[CUSTOM TOOL] ruff started" in analysis
        assert "[CUSTOM TOOL] pyright started" in analysis
        assert "agent_name: static-reviewer" in analysis
        assert "[CUSTOM TOOL] ruff started" not in repair
        assert "agent_name: programmer" in repair
        assert "agent_name: reviewer" in repair
        assert len(self.application.passed_test_calls) >= 2
        assert len(verification) == 2
        for result in verification:
            assert result.returncode == 0, result.stdout + result.stderr
            assert "passed" in result.stdout
        assert "role: documentarian" not in demo.compact_report_text(text[:documentation])
        assert "role: documentarian" in demo.compact_report_text(text[documentation:])
        assert text.count("[SESSION] create requested") == 2
        diff = text[text.index("[ARTIFACT] diff before rollback"):]
        for path in demo.WRITE_PATHS.values():
            assert f"diff --git a/{path} b/{path}" in diff
        assert self.repository_status(config.working_directory) == before
        assert "[rollback] Base restored" in text

    def test_live_sdk_timeout_aborts_and_reports_progress(self, tmp_path: Path) -> None:
        WorkspacePreparer(tmp_path, {"005-sdlc-team": "demo-base-1048"}).run()
        config = replace(
            demo.CONFIGURATION,
            working_directory=tmp_path / "demos" / "005-sdlc-team" / "workspace",
            prompt="Reply exactly READY. Do not use tools or delegate.",
            keep_changes=False,
            timeout_seconds=0.1,
            progress_interval_seconds=0.02,
            log_directory=tmp_path / "logs",
        )
        before = self.repository_status(config.working_directory)
        assert self.application.run(config) == 1
        rendered = "\n".join(self.output)
        assert "[progress] Waiting for session.idle:" in rendered
        assert "[lifecycle] Aborting active Copilot request" in rendered
        assert "[lifecycle] Copilot client closed" not in rendered
        assert "[stage] orchestrator: prompt 2" not in rendered
        assert "[stage] Selecting SDK agent: documentarian" not in rendered
        assert any("Copilot request timed out after 0.1s" in line for line in self.errors)
        assert not any("Copilot session failed:" in line for line in self.errors)
        assert self.repository_status(config.working_directory) == before
        assert "[rollback] Base restored; workspace clean. No commit or push." in rendered
        text = next(config.log_directory.glob("sdlc-*.log")).read_text(encoding="utf-8")
        assert "[RUN] failed" in text
        summary = next(config.log_directory.glob("summary*.log")).read_text(encoding="utf-8")
        assert "[RUN] failed" in summary
        assert "[USAGE] run total" in summary
        assert "TimeoutError" in text
        assert "Aborting active Copilot request" in text
        assert "[RUN] completed" not in text

    def test_live_sdk_ctrl_c_preserves_cancelled_exit(self) -> None:
        import pexpect

        before = self.repository_status(demo.CONFIGURATION.working_directory)
        script = (
            "import runpy; from dataclasses import replace; "
            f"demo = runpy.run_path({str(MODULE_PATH)!r}); "
            "config = replace(demo['CONFIGURATION'], "
            "prompt='Reply exactly READY. Do not use tools or delegate.', repair_prompt=None); "
            "raise SystemExit(demo['SdlcTeamApplication']().run(config))"
        )
        # A PTY sends real Ctrl+C to the foreground process group, including
        # the SDK-owned CLI, reproducing its shutdown race without mocking.
        with pexpect.spawn(
            sys.executable, ["-u", "-c", script], encoding="utf-8", timeout=120
        ) as child:
            child.expect_exact("[event] model.call_start")
            child.sendintr()
            child.expect_exact("Cancelled.", timeout=40)
            child.expect(pexpect.EOF, timeout=15)
            transcript = child.before
            child.close()
            assert child.exitstatus == 130
            assert "Copilot session failed:" not in transcript
        assert self.repository_status(demo.CONFIGURATION.working_directory) == before

    def test_live_sdk_explicit_agent_fallback_is_read_only(self, tmp_path: Path) -> None:
        WorkspacePreparer(tmp_path, {"005-sdlc-team": "demo-base-1048"}).run()
        config = replace(
            demo.CONFIGURATION,
            prompt="Reply exactly READY. Do not use tools or delegate.",
            repair_prompt=None,
            timeout_seconds=240,
            fallback_agent="analyst",
            working_directory=tmp_path / "demos" / "005-sdlc-team" / "workspace",
            log_directory=tmp_path / "logs",
        )
        try:
            before = self.repository_status(config.working_directory)
        except (OSError, subprocess.CalledProcessError) as error:
            pytest.fail(
                "Prepare the pinned checkout as described in README.md "
                f"before running the live SDK test: {error}"
            )
        exit_code = self.application.run(config)
        assert exit_code == 0, \
            "Live Copilot SDK fallback requires network, a Copilot subscription " \
            "and CLI authentication (`copilot -p 'Reply with OK' --silent`).\n" \
            + "\n".join(self.errors)
        rendered = "\n".join(self.output)
        assert "[fallback] Selecting SDK agent: analyst" in rendered
        assert "[event] subagent.selected" in rendered
        assert self.repository_status(config.working_directory) == before
        detailed = next(config.log_directory.glob("sdlc-*.log")).read_text(encoding="utf-8")
        assert detailed.count("[SESSION] create requested") == 2
        assert detailed.count("[USAGE] assistant.usage") == (
            self.application.usage.report()["usage_events"]
        )
        assert self.application.usage.report()["usage_events"] >= 2
        summary = next(config.log_directory.glob("summary*.log")).read_text(encoding="utf-8")
        assert "[fallback] Selecting SDK agent: analyst" in summary
        assert summary.count("[USAGE] run total") == 1

    def test_live_sdk_does_not_fallback_without_opt_in(self, tmp_path: Path) -> None:
        WorkspacePreparer(tmp_path, {"005-sdlc-team": "demo-base-1048"}).run()
        config = replace(
            demo.CONFIGURATION,
            prompt="Reply exactly READY. Do not use tools or delegate.",
            repair_prompt=None,
            timeout_seconds=120,
            working_directory=tmp_path / "demos" / "005-sdlc-team" / "workspace",
            log_directory=tmp_path / "logs",
        )
        exit_code = self.application.run(config)
        assert exit_code == 0, \
            "Live Copilot SDK requires network, a Copilot subscription and CLI " \
            "authentication (`copilot -p 'Reply with OK' --silent`).\n" \
            + "\n".join(self.errors)
        rendered = "\n".join(self.output)
        assert "[event] session.idle" in rendered
        assert (
            "MCP server names disabled for this session: "
            + ", ".join(demo.DISABLED_MCP_SERVERS)
        ) in rendered
        assert "[fallback]" not in rendered
        assert "[lifecycle] Session closed" in rendered
        assert rendered.index("[setup] Toolchain verified:") < rendered.index(
            "[lifecycle] Copilot CLI runtime connected"
        )
        assert self.application.usage.report()["usage_events"] > 0
        assert "[usage] AIC=" in rendered
        summary = next(config.log_directory.glob("summary*.log")).read_text(encoding="utf-8")
        assert "[USAGE] run total" in summary
        assert self.application.usage.report()["status"] in {
            "reported", "partial", "unavailable",
        }

    @pytest.mark.parametrize("command", demo.TEST_COMMANDS)
    def test_live_tester_runs_focused_command_with_sdk_permission(self, command: str) -> None:
        config = replace(demo.CONFIGURATION, timeout_seconds=240)
        directory = self.application.validate_configuration(config)
        before = self.repository_status(directory)

        async def run_tester() -> str:
            self.application.permission_directory = directory
            # agent= explicitly selects a single specialist through the SDK;
            # the permission callback still checks its runtime tool-call ID.
            async with demo.CopilotRuntime(
                environment=self.application.environment,
                output=self.output.append,
            ).create_client() as client:
                return await self.application.ask(
                    client, config, directory, agent="tester",
                    prompt=f"Run exactly {command} in the checkout, "
                           "even if the test class does not exist yet. "
                           "Do not edit files or invoke other commands. "
                           "Report the result briefly.",
                )

        try:
            response = asyncio.run(run_tester())
        except Exception as error:
            pytest.fail(
                "Live tester requires a pinned checkout, network, Copilot "
                "subscription and CLI authentication (`copilot -p 'Reply with "
                f"OK' --silent`): {error}"
            )
        assert response
        assert "tester" in self.application.tool_roles.values()
        assert self.application.approved_test_calls, \
            "The real SDK tester never requested the exact focused command."
        assert self.application.passed_test_calls, \
            "The focused test command did not complete successfully."
        assert self.repository_status(directory) == before

    @pytest.mark.parametrize("keep_changes", [True, False])
    @pytest.mark.parametrize("cancel_after_edit", [False, True])
    def test_live_programmer_edits_only_its_assigned_source(
        self, tmp_path: Path, cancel_after_edit: bool, keep_changes: bool
    ) -> None:
        WorkspacePreparer(tmp_path, {"005-sdlc-team": "demo-base-1048"}).run()
        directory = tmp_path / "demos" / "005-sdlc-team" / "workspace"
        marker = "# SDK editor integration probe"
        config = replace(
            demo.CONFIGURATION, working_directory=directory, timeout_seconds=120,
            keep_changes=keep_changes,
            repair_prompt=None,
            log_directory=tmp_path / "logs",
            prompt="Delegate to programmer using task. Require it to use its available "
                   "editing tool (apply_patch or edit) "
                   f"to append exactly {marker!r} as a new line at the end of "
                   "beancount/parser/booking_full.py. This is a temporary editor "
                   "integration check, not the issue fix. Do not use other agents, "
                   "edit other files or run shell commands.",
        )
        # Automatic delegation must expose the editor and retain the specialist's
        # runtime identity, not merely work with an explicitly selected agent.
        observed_edits: list[str] = []
        pending: asyncio.Task[None] | None = None

        def observe(message: str) -> None:
            self.output.append(message)
            if (
                cancel_after_edit and pending is not None and not pending.cancelling()
                and message == "[tool] complete success=True"
                and marker in (directory / demo.PYTHON_ANALYSIS_FILE).read_text()
            ):
                observed_edits.append((directory / demo.PYTHON_ANALYSIS_FILE).read_text())
                pending.cancel()
            if message == "[lifecycle] Session closed":
                observed_edits.append((directory / demo.PYTHON_ANALYSIS_FILE).read_text())

        self.application.output = observe
        if cancel_after_edit:
            async def cancel_during_live_work() -> None:
                nonlocal pending
                pending = asyncio.create_task(self.application.execute(config))
                with pytest.raises(asyncio.CancelledError):
                    await pending

            asyncio.run(cancel_during_live_work())
            assert "[lifecycle] Aborting active Copilot request" in self.output
        else:
            assert self.application.run(config) == 0, "\n".join(self.errors)
        assert any(marker in content for content in observed_edits), (
            "\n".join(self.output)
        )
        assert self.application.delegated
        assert any(
            f"[tool] start {name}" in "\n".join(self.output)
            for name in ("apply_patch", "edit")
        )
        assert (marker in (directory / demo.PYTHON_ANALYSIS_FILE).read_text()) == keep_changes
        if keep_changes:
            assert self.repository_status(directory).strip() == "M beancount/parser/booking_full.py"
            assert any("[rollback] Disabled:" in message for message in self.output)
            with pytest.raises(demo.ConfigurationError, match="requires a clean workspace"):
                self.application.validate_configuration(config)
        else:
            assert self.repository_status(directory) == ""
            assert "[rollback] Base restored; workspace clean. No commit or push." in self.output
        assert WorkspacePreparer.git("-C", str(directory), "rev-parse", "HEAD") == demo.EXPECTED_COMMIT
        text = next(config.log_directory.glob("sdlc-*.log")).read_text(encoding="utf-8")
        assert "[PERMISSION] PermissionDecisionApproveOnce" in text
        assert "[ARTIFACT] diff before rollback" in text
        assert f"+{marker}" in text
        assert "programmer" in text
        assert "[RUN] interrupted" in text if cancel_after_edit else "[RUN] completed" in text
