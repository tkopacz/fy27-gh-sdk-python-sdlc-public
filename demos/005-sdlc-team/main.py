#!/usr/bin/env python3
"""Combine prompt-driven SDLC delegation with an explicit SDK documentation step."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import math
import os
import re
import signal
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from importlib.metadata import PackageNotFoundError, version as package_version
from pathlib import Path
from typing import Awaitable, Callable, Mapping, TextIO
from uuid import uuid4

from copilot import CopilotClient
from copilot.generated.rpc import PermissionDecisionApproveOnce, PermissionDecisionReject
from copilot.session import CustomAgentConfig
from copilot.session_events import (
    AssistantMessageData,
    AssistantUsageData,
    PermissionRequestRead,
    PermissionRequestShell,
    PermissionRequestWrite,
    SessionEvent,
    SessionEventType,
    ToolExecutionCompleteData,
    ToolExecutionStartData,
)
from copilot.tools import Tool, ToolInvocation, ToolResult

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from copilot_runtime import CopilotRuntime, DISABLED_MCP_SERVERS, print_event, show_disabled_mcp_servers
from prepare_sdlc_team import ToolchainError, verify_demo_tools

DEMO_DIRECTORY = Path(__file__).resolve().parent
EXPECTED_COMMIT = "9747213802acb733ce53acc6e963f5961f47d6cd"
PYTHON_ANALYSIS_FILE = "beancount/parser/booking_full.py"
PYTHON_ANALYSIS_TOOL = "python_static_analysis"
ANALYZER_TIMEOUT_SECONDS = 120
CLEANUP_TIMEOUT_SECONDS = 10
MAX_FINDINGS_PER_ANALYZER = 80
MAX_REPORT_BYTES = 6000
TEST_COMMAND = (
    "python -m pytest beancount/parser/booking_full_test.py "
    "-k TestZeroUnitsWithTotalCost -q"
)
FULL_TEST_COMMAND = "python -m pytest beancount/parser/booking_full_test.py -q"
TEST_COMMANDS = (TEST_COMMAND, FULL_TEST_COMMAND)
SHELL_TOOL = "powershell" if os.name == "nt" else "bash"
DEFAULT_PROMPT = """Przygotuj analizę statyczną dla issue Beancount #1048: wpis 0 HOOL {{20.00 USD}} (zero
jednostek z kosztem całkowitym) kończy się nieobsłużonym decimal.DivisionByZero.
Najpierw zleć analitykowi uruchomienie Ruff i Pyright przez
python_static_analysis. Gdy zwróci raport JSON, przekaż go w całości agentowi
static-reviewer, który ma napisać recenzję wyłącznie na podstawie wyników
statycznych i zaznaczyć brak lub ucięcie wyników. Poczekaj na zakończenie
obu agentów i zwróć recenzję. To koniec tego etapu: nie zlecaj naprawy,
testów ani dokumentacji i nie edytuj plików."""

DEFAULT_REPAIR_PROMPT = """Teraz zrealizuj issue Beancount #1048, korzystając
z analizy i recenzji z poprzedniej tury. Zleć analizę problemu, projekt,
testy regresyjne, implementację i review odpowiednim specjalistom przez task.
Nie uruchamiaj ponownie Ruff/Pyright ani static-reviewer.
Najpierw test, potem poprawka i ponownie test.
Poprawka ma być lokalna: zero jednostek z kosztem całkowitym nie może dzielić
przez zero, a normalne koszty jednostkowe i całkowite mają działać bez zmian.
Tester powinien wykonać python -m pytest beancount/parser/booking_full_test.py -k TestZeroUnitsWithTotalCost -q.
Po poprawce tester ma też wykonać python -m pytest beancount/parser/booking_full_test.py -q,
aby sprawdzić zachowanie istniejących scenariuszy booking, i przekazać ewentualne
regresje programiście przed końcowym review.
Poczekaj na zakończenie wszystkich zadań. Nie wywołuj documentarian i nie
zmieniaj CHANGES: dokumentację uruchomi potem jawnie aplikacja.
Nie wykonuj commit ani push. Na końcu opisz rezultat i wynik testów.
Nie wykonuj samodzielnie rollbacku; zachowanie lub wycofanie zmian jest
decyzją aplikacji, a nie zadaniem modelu."""

DOCUMENTATION_PROMPT = """Udokumentuj zakończony etap naprawy na podstawie
poniższego podsumowania i aktualnych plików. Sprawdź poprawkę oraz testy
w beancount/parser/booking_full.py i beancount/parser/booking_full_test.py.
Zmień wyłącznie CHANGES, dodając krótką notkę o faktycznie wprowadzonej
korekcie. Nie twierdź, że testy przeszły, jeśli podsumowanie tego nie potwierdza.
Nie deleguj, nie wykonuj testów, commit, push ani rollbacku.

Podsumowanie zespołu:
"""


@dataclass(frozen=True)
class DemoConfiguration:
    working_directory: Path = (
        DEMO_DIRECTORY / "workspace"
    )
    expected_commit: str = EXPECTED_COMMIT
    model: str = "auto"
    prompt: str = DEFAULT_PROMPT
    # None runs only the first prompt, useful for isolated live SDK checks.
    repair_prompt: str | None = DEFAULT_REPAIR_PROMPT
    keep_changes: bool = True
    timeout_seconds: float = 900.0
    progress_interval_seconds: float = 15.0
    # Opt in for a controlled demonstration if automatic delegation is absent.
    fallback_agent: str | None = None
    log_directory: Path = DEMO_DIRECTORY / "logs"


CONFIGURATION = DemoConfiguration()


class ConfigurationError(ValueError):
    """The pinned checkout or program settings are not ready."""


class StaticAnalysisError(ValueError):
    """A static analyzer returned an invalid or unusable report."""


class RunUsage:
    """Accumulate only billing values actually reported by the SDK."""

    def __init__(self) -> None:
        self.event_ids: set[str] = set()
        self.nano_aiu = Decimal(0)
        self.reported_calls = 0
        self.missing_calls = 0

    def add(self, event: SessionEvent) -> bool:
        if not isinstance(event.data, AssistantUsageData):
            return False
        identity = str(event.id)
        if identity in self.event_ids:
            return False
        self.event_ids.add(identity)
        usage = event.data.copilot_usage
        amount = Decimal(str(usage.total_nano_aiu)) if usage is not None else None
        if amount is None or not amount.is_finite() or amount < 0:
            self.missing_calls += 1
        else:
            # copilot_usage is per request, including subagent requests.
            # cost and session quota snapshots are not additional AIC charges.
            self.nano_aiu += amount
            self.reported_calls += 1
        return True

    def report(self) -> dict[str, object]:
        return {
            "status": (
                "unavailable" if not self.reported_calls
                else "partial" if self.missing_calls else "reported"
            ),
            "aic": str(self.nano_aiu / Decimal(1_000_000_000))
            if self.reported_calls else None,
            "total_nano_aiu": str(self.nano_aiu) if self.reported_calls else None,
            "reported_calls": self.reported_calls,
            "calls_without_billing": self.missing_calls,
            "usage_events": len(self.event_ids),
        }


class ActivityLog:
    """Keep a flushed, presentation-friendly history without raw SDK payloads."""

    def __init__(self, directory: Path, environment: Mapping[str, str]) -> None:
        self.directory = directory
        self.path: Path | None = None
        self.stream: TextIO | None = None
        self.summary_path: Path | None = None
        self.summary_stream: TextIO | None = None
        self.sequence = 0
        self.failure: OSError | None = None
        self.secrets = sorted(
            {
                value for name, value in environment.items()
                if value and re.search(
                    r"token|secret|password|api_?key|credential|authorization",
                    name, re.IGNORECASE,
                )
            },
            key=len, reverse=True,
        )

    def __enter__(self) -> ActivityLog:
        self.directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        suffix = f"{stamp}-{uuid4().hex[:8]}.log"
        self.path = self.directory / f"sdlc-{suffix}"
        self.summary_path = self.directory / f"summary{suffix}"
        self.stream = self.path.open("x", encoding="utf-8")
        try:
            self.summary_stream = self.summary_path.open("x", encoding="utf-8")
        except OSError:
            self.stream.close()
            self.stream = None
            raise
        return self

    def __exit__(self, *_exception: object) -> None:
        try:
            if self.summary_stream is not None:
                self.summary_stream.close()
        finally:
            self.summary_stream = None
            if self.stream is not None:
                self.stream.close()
                self.stream = None

    def redact(self, text: str) -> str:
        for secret in self.secrets:
            text = text.replace(secret, "[REDACTED]")
        return re.sub(
            r"(?i)\b(?:gh[pousr]_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+|"
            r"bearer\s+[A-Za-z0-9._~+/-]+=*)",
            "[REDACTED]", text,
        )

    def write(self, category: str, action: str, **details: object) -> None:
        if self.stream is None:
            raise RuntimeError("Activity log is not open.")
        self.sequence += 1
        header = (
            f"\n{datetime.now(timezone.utc).isoformat()} "
            f"#{self.sequence:05d} [{category}] {action}\n"
        )
        lines = [header]
        for key, value in details.items():
            text = value if isinstance(value, str) else json.dumps(
                value, ensure_ascii=False, indent=2, default=str
            )
            lines.append(f"  {key}:\n")
            lines.extend(f"    {line}\n" for line in text.splitlines())
        try:
            self.stream.write(self.redact("".join(lines)))
            self.stream.flush()
            self.write_summary(header, category, action, details)
        except OSError as error:
            self.failure = error
            raise

    def write_summary(
        self, header: str, category: str, action: str, details: dict[str, object],
    ) -> None:
        if self.summary_stream is None:
            raise RuntimeError("Summary log is not open.")
        if category == "CONSOLE":
            message = str(details.get("message", ""))
            if not message.startswith((
                "[lifecycle]", "[setup]", "[rollback]", "[fallback]", "[stage]",
            )):
                return
        elif category == "CUSTOM TOOL" and action.endswith("process output"):
            return
        elif category == "TOOL RESULT":
            if not action.startswith((PYTHON_ANALYSIS_TOOL, "git_diff")):
                return
        elif category not in {
            "RUN", "SESSION", "AGENT", "AGENT OUTPUT", "HANDOFF",
            "CUSTOM TOOL", "ERROR", "USAGE",
        }:
            return
        selected = {
            key: value for key, value in details.items()
            if (value is not None or category == "USAGE") and key not in {
                "agents", "detailed_content", "stdout", "stderr", "sdk_timestamp",
                "event_id", "parent_event_id",
            }
        }
        # Redact before truncating so a shortened secret cannot escape masking.
        parts = []
        for key, value in selected.items():
            text = self.redact(
                value if isinstance(value, str)
                else json.dumps(value, ensure_ascii=False, default=str)
            )
            text = compact_report_text(text)
            if len(text) > 400:
                text = text[:400] + " ... [truncated; see detailed log]"
            parts.append(f"  {key}: {text}\n")
        self.summary_stream.write(self.redact(header) + "".join(parts))
        self.summary_stream.flush()


def compact_report_text(value: str) -> str:
    return " ".join(value.split())


def decode_analyzer_output(
    name: str, stdout: str, stderr: str, return_code: int
) -> object:
    detail = compact_report_text(stderr)
    suffix = f" stderr: {detail}" if detail else ""
    if return_code not in (0, 1):
        raise StaticAnalysisError(
            f"{name} exited with code {return_code}; analysis did not complete."
            + suffix
        )
    if not stdout.strip():
        raise StaticAnalysisError(
            f"{name} returned no JSON report (exit code {return_code})." + suffix
        )
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as error:
        raise StaticAnalysisError(
            f"{name} returned invalid JSON at character {error.pos} "
            f"(line {error.lineno}, column {error.colno}; "
            f"exit code {return_code}): {error.msg}." + suffix
        ) from error


async def run_tool_command(
    arguments: list[str], directory: Path, timeout: float
) -> subprocess.CompletedProcess[str]:
    process = await asyncio.create_subprocess_exec(
        *arguments, cwd=directory,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        start_new_session=os.name == "posix",
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout)
        return_code = process.returncode
        if return_code is None:
            raise RuntimeError("Local tool completed without a process exit code.")
        return subprocess.CompletedProcess(
            arguments, return_code, stdout.decode(), stderr.decode()
        )
    except TimeoutError as error:
        raise subprocess.TimeoutExpired(arguments, timeout) from error
    finally:
        if process.returncode is None:
            # Kill only this invocation's process group, including Pyright's
            # Node child, so cancellation cannot leave analysis running.
            try:
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
            except ProcessLookupError:
                pass
            await process.wait()


# These are runtime tool names, not application-side function calls. Only the
# programmer/doc writer can edit production files; only the tester can run tests.
READ_TOOLS = ["grep", "view"]
# The runtime resolves editors per model; task-delegated agents may expose
# edit even when an explicitly selected SDK agent exposes apply_patch.
WRITE_TOOLS = [*READ_TOOLS, "apply_patch", "edit"]
AGENTS: tuple[CustomAgentConfig, ...] = (
    {
        "name": "analyst",
        "description": "Analyze issue #1048 and acceptance criteria without editing.",
        "prompt": (
            "When asked for static analysis, call python_static_analysis and "
            "return the complete JSON report verbatim for handoff to "
            "static-reviewer. When asked for issue analysis, reuse the existing "
            "report without rerunning analyzers. Read the booking "
            "code and tests in booking_full.py and booking_full_test.py only; "
            "report the 0 HOOL {{20.00 USD}} reproduction and "
            "acceptance invariants. Do not edit."
        ),
        "tools": [*READ_TOOLS, PYTHON_ANALYSIS_TOOL],
    },
    {
        "name": "static-reviewer",
        "description": "Write a project review based only on Ruff and Pyright output.",
        "prompt": (
            "Write a concise project review based exclusively on the complete "
            "Ruff/Pyright JSON report in the task. Do not inspect source or "
            "invent findings. Separate observed diagnostics from interpretation; "
            "mention clean analyzers, failures and omitted findings explicitly."
        ),
        "tools": [],
    },
    {
        "name": "architect",
        "description": "Design a safe zero-units total-cost fix without editing.",
        "prompt": (
            "Compare guarding the total-cost to per-unit conversion with rejecting "
            "the entry; evaluate error reporting, booking methods and "
            "non-zero units. Do not edit."
        ),
        "tools": READ_TOOLS,
    },
    {
        "name": "programmer",
        "description": "Implement the fix in beancount/parser/booking_full.py.",
        "prompt": (
            "Change only beancount/parser/booking_full.py. Preserve normal "
            "per-unit and total-cost booking, including existing zero-unit FIFO/LIFO "
            "cases without an explicit total cost; do not change tests or docs. "
            "Use the editing tool exposed by your model: apply_patch or edit."
        ),
        "tools": WRITE_TOOLS,
    },
    {
        "name": "tester",
        "description": "Add a regression and verify both focused and existing booking tests.",
        "prompt": (
            "Edit only beancount/parser/booking_full_test.py: add class "
            "TestZeroUnitsWithTotalCost using pytest-style methods, not unittest.TestCase. "
            "Call the real loader.load_string on a ledger with open accounts. "
            "Use exactly 0 HOOL {{20.00 USD}} for the regression and "
            "2 HOOL {{20.00 USD}} with -20.00 USD cash for the control; "
            "do not substitute {# cost}, which does not reproduce this issue. "
            "The regression must require a controlled domain error, not accept "
            "DivisionByZero as success. Use the available editor: apply_patch or edit. "
            "Run exactly " + TEST_COMMAND + " first; after the fix also run exactly "
            + FULL_TEST_COMMAND + " to detect existing booking regressions. "
            "Report failures and final results. Do not edit production code."
        ),
        "tools": [*WRITE_TOOLS, SHELL_TOOL],
    },
    {
        "name": "reviewer",
        "description": "Review the booking change and test results, never edit.",
        "prompt": (
            "Use git_diff to review changes and test results. Check zero and "
            "non-zero units, per-unit vs total cost and error handling; never edit."
        ),
        "tools": [*READ_TOOLS, "git_diff"],
    },
    {
        "name": "documentarian",
        "description": "Document the reviewed Beancount fix.",
        "prompt": (
            "After review, update only CHANGES with a short note describing the "
            "user-visible correction. Do not edit source or tests."
        ),
        "tools": WRITE_TOOLS,
    },
)
AGENT_NAMES = frozenset(agent["name"] for agent in AGENTS)
WRITE_PATHS = {
    "programmer": "beancount/parser/booking_full.py",
    "tester": "beancount/parser/booking_full_test.py",
    "documentarian": "CHANGES",
}


def build_diff_tool(directory: Path, *, activity_log: ActivityLog | None = None) -> Tool:
    # SDK exposes only this bounded, read-only diff to the reviewer. It does
    # not grant a general shell; the runtime sends the result back to the agent.
    async def git_diff(invocation: ToolInvocation) -> ToolResult:
        if activity_log is not None:
            activity_log.write(
                "CUSTOM TOOL", "git_diff started", tool_call_id=invocation.tool_call_id,
            )
        result = await run_tool_command(
            ["git", "diff", "HEAD", "--",
             "beancount/parser/booking_full.py",
             "beancount/parser/booking_full_test.py", "CHANGES"],
            directory, CLEANUP_TIMEOUT_SECONDS,
        )
        if activity_log is not None:
            activity_log.write(
                "CUSTOM TOOL", "git_diff completed",
                tool_call_id=invocation.tool_call_id, exit_code=result.returncode,
                stdout=result.stdout, stderr=result.stderr,
            )
        if result.returncode:
            return ToolResult(result_type="failure", text_result_for_llm="git diff failed")
        return ToolResult(text_result_for_llm=result.stdout or "No changes in target files.")

    # skip_permission is safe here because the handler executes only git diff
    # for approved paths; unlike the tester's shell, it cannot mutate files.
    return Tool(
        name="git_diff",
        description="Read the working-tree diff of the three approved SDLC files.",
        handler=git_diff,
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        skip_permission=True,
    )


def build_python_static_analysis_tool(
    directory: Path,
    *,
    output: Callable[[str], None] = print,
    activity_log: ActivityLog | None = None,
) -> Tool:
    def relative_path(value: str) -> str:
        path = Path(value)
        if not path.is_absolute():
            return path.as_posix()
        try:
            return path.resolve().relative_to(directory.resolve()).as_posix()
        except ValueError:
            return path.name

    def parse_report(
        name: str, stdout: str, stderr: str, return_code: int
    ) -> dict[str, object]:
        decoded = decode_analyzer_output(name, stdout, stderr, return_code)

        findings: list[dict[str, object]] = []
        if name == "ruff":
            if not isinstance(decoded, list):
                raise StaticAnalysisError("Ruff JSON output must be a list.")
            for item in decoded:
                if not isinstance(item, dict) or not isinstance(
                    item.get("location"), dict
                ):
                    raise StaticAnalysisError("Ruff returned an invalid diagnostic.")
                location = item["location"]
                findings.append({
                    "file": relative_path(str(item.get("filename", ""))),
                    "line": location.get("row"),
                    "column": location.get("column"),
                    "rule": item.get("code"),
                    "message": compact_report_text(str(item.get("message", ""))),
                })
        else:
            if not isinstance(decoded, dict) or not isinstance(
                decoded.get("generalDiagnostics"), list
            ):
                raise StaticAnalysisError("Pyright JSON output has no diagnostics list.")
            for item in decoded["generalDiagnostics"]:
                if not isinstance(item, dict):
                    raise StaticAnalysisError("Pyright returned an invalid diagnostic.")
                diagnostic_range = item.get("range")
                if not isinstance(diagnostic_range, dict):
                    raise StaticAnalysisError("Pyright returned a diagnostic without a range.")
                location = diagnostic_range.get("start")
                if not isinstance(location, dict):
                    raise StaticAnalysisError("Pyright returned a diagnostic without a start.")
                findings.append({
                    "file": relative_path(str(item.get("file", ""))),
                    "line": location.get("line", 0) + 1,
                    "column": location.get("character", 0) + 1,
                    "severity": item.get("severity"),
                    "rule": item.get("rule"),
                    "message": compact_report_text(str(item.get("message", ""))),
                })

        findings.sort(key=lambda finding: (
            str(finding.get("file", "")),
            str(finding.get("line", 0)),
            str(finding.get("rule", "")),
            str(finding.get("message", "")),
        ))
        total_findings = len(findings)
        return {
            "status": "clean" if return_code == 0 else "findings",
            "exit_code": return_code,
            "finding_count": total_findings,
            "findings": findings[:MAX_FINDINGS_PER_ANALYZER],
            "omitted_findings": max(0, total_findings - MAX_FINDINGS_PER_ANALYZER),
        }

    async def collect_analyzer(
        name: str, module_name: str, arguments: list[str], tool_call_id: str
    ) -> dict[str, object]:
        if importlib.util.find_spec(module_name) is None:
            return {
                "status": "failed",
                "error": (
                    f"{name} is not installed for the active Python interpreter."
                ),
                "finding_count": 0,
                "findings": [],
                "omitted_findings": 0,
            }
        try:
            result = await run_tool_command(
                [sys.executable, "-m", module_name, *arguments],
                directory, ANALYZER_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return {
                "status": "failed",
                "error": f"{name} exceeded {ANALYZER_TIMEOUT_SECONDS} seconds.",
                "finding_count": 0,
                "findings": [],
                "omitted_findings": 0,
            }
        except OSError as error:
            return {
                "status": "failed",
                "error": f"{name} could not run: {compact_report_text(str(error))}",
                "finding_count": 0,
                "findings": [],
                "omitted_findings": 0,
            }
        except UnicodeError:
            return {
                "status": "failed",
                "error": f"{name} output could not be decoded as text.",
                "finding_count": 0,
                "findings": [],
                "omitted_findings": 0,
            }
        if activity_log is not None:
            activity_log.write(
                "CUSTOM TOOL", f"{name} process output",
                tool_call_id=tool_call_id, exit_code=result.returncode,
                stdout=result.stdout, stderr=result.stderr,
            )
        try:
            report = parse_report(
                name, result.stdout, result.stderr, result.returncode
            )
        except StaticAnalysisError as error:
            return {
                "status": "failed",
                "error": str(error),
                "exit_code": result.returncode,
                "finding_count": 0,
                "findings": [],
                "omitted_findings": 0,
            }
        try:
            report["version"] = package_version(name)
        except PackageNotFoundError:
            report["status"] = "failed"
            report["error"] = f"{name} package version metadata is missing."
            return report
        return report

    async def analyze(invocation: ToolInvocation) -> ToolResult:
        async def run_analyzer(
            name: str, module_name: str, arguments: list[str]
        ) -> dict[str, object]:
            if activity_log is not None:
                activity_log.write(
                    "CUSTOM TOOL", f"{name} started",
                    tool=PYTHON_ANALYSIS_TOOL, tool_call_id=invocation.tool_call_id,
                    command=[sys.executable, "-m", module_name, *arguments],
                )
            try:
                report = await collect_analyzer(
                    name, module_name, arguments, invocation.tool_call_id,
                )
            except BaseException as error:
                if activity_log is not None:
                    activity_log.write(
                        "CUSTOM TOOL", f"{name} interrupted",
                        tool_call_id=invocation.tool_call_id,
                        error_type=type(error).__name__, message=str(error),
                    )
                raise
            if activity_log is not None:
                activity_log.write(
                    "CUSTOM TOOL", f"{name} completed",
                    tool=PYTHON_ANALYSIS_TOOL, tool_call_id=invocation.tool_call_id,
                    report=report,
                )
            return report

        root = str(directory.resolve())
        reports = {
            "ruff": await run_analyzer(
                "ruff", "ruff", ["check", "--output-format=json", "beancount"]
            ),
            "pyright": await run_analyzer(
                "pyright", "pyright", ["--outputjson", "beancount"]
            ),
        }
        payload = {
            "scope": "beancount/",
            "analyzers": reports,
            "filters": {
                "whitespace": "Collapsed repeated whitespace in messages.",
                "paths": f"Paths are relative to {Path(root).name}/.",
                "findings_limit": MAX_FINDINGS_PER_ANALYZER,
                "json": "Compact separators; findings sorted by file, line, rule.",
                "json_bytes_limit": MAX_REPORT_BYTES,
            },
        }
        failed = [
            name for name, report in reports.items()
            if report["status"] == "failed"
        ]
        summaries = ", ".join(
            f"{name}={report['status']}:{report['finding_count']}"
            for name, report in reports.items()
        )
        output(f"[analysis] Ruff/Pyright report: {summaries}.")
        # Compact JSON plus normalized messages removes formatting noise before
        # the report is handed to the next agent, reducing prompt tokens.
        report_json = json.dumps(
            payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        )
        # Runtime tool output can be offloaded to a file. The tool-free reviewer
        # needs the whole JSON inline, so cap encoded bytes as well as item count.
        while len(report_json.encode("utf-8")) > MAX_REPORT_BYTES:
            candidates = []
            for report in reports.values():
                findings = report["findings"]
                if isinstance(findings, list) and findings:
                    candidates.append((report, findings))
            if not candidates:
                raise StaticAnalysisError(
                    f"Static report metadata exceeds the {MAX_REPORT_BYTES}-byte limit."
                )
            report, findings = max(
                candidates, key=lambda candidate: len(json.dumps(candidate[1]))
            )
            findings.pop()
            omitted = report["omitted_findings"]
            if not isinstance(omitted, int):
                raise StaticAnalysisError("Invalid omitted findings count.")
            report["omitted_findings"] = omitted + 1
            report_json = json.dumps(
                payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
            )
        if failed:
            if activity_log is not None:
                activity_log.write(
                    "CUSTOM TOOL", "static analysis failed",
                    tool_call_id=invocation.tool_call_id, report=report_json,
                )
            return ToolResult(
                result_type="failure",
                text_result_for_llm=(
                    "Static analysis incomplete; do not treat this as a clean "
                    "review. " + report_json
                ),
            )
        if activity_log is not None:
            activity_log.write(
                "CUSTOM TOOL", "static analysis returned to caller",
                tool_call_id=invocation.tool_call_id, report=report_json,
            )
        return ToolResult(text_result_for_llm=report_json)

    # SDK awaits this async handler while continuing to deliver events and
    # permissions. Blocking subprocess.run here would freeze that dispatch.
    return Tool(
        name=PYTHON_ANALYSIS_TOOL,
        description=(
            "Run Ruff and Pyright against the beancount Python package and "
            "return compact structured diagnostics. Read-only; no source changes."
        ),
        handler=analyze,
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        skip_permission=True,
    )


class SdlcTeamApplication:
    """Let prompts delegate the team, then select the documentarian in code."""

    def __init__(
        self,
        *,
        output: Callable[[str], None] = print,
        error_output: Callable[[str], None] | None = None,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        self.environment = dict(os.environ if environment is None else environment)
        self.environment["PATH"] = os.pathsep.join(
            (str(Path(sys.executable).parent), self.environment.get("PATH", os.defpath))
        )
        self.output = output
        self.error_output = error_output or (
            lambda message: print(message, file=sys.stderr)
        )
        self.delegated = False
        self.failed = False
        self.agent_roles: dict[str, str] = {}
        self.tool_roles: dict[str, str] = {}
        self.tool_arguments: dict[str, object] = {}
        self.tool_names: dict[str, str] = {}
        self.activity_log: ActivityLog | None = None
        self.usage = RunUsage()
        self.explicit_agent: str | None = None
        self.selected_session_agent: str | None = None
        self.approved_test_calls: set[str] = set()
        self.passed_test_calls: set[str] = set()
        self.permission_directory: Path | None = None
        self.last_event = "session created"
        self.last_event_time = 0.0

    async def report_progress(
        self, configuration: DemoConfiguration
    ) -> None:
        loop = asyncio.get_running_loop()
        started = loop.time()
        while True:
            await asyncio.sleep(configuration.progress_interval_seconds)
            now = loop.time()
            self.output(
                f"[progress] Waiting for session.idle: {now - started:.0f}s elapsed; "
                f"last event={self.last_event} ({now - self.last_event_time:.0f}s ago); "
                f"limit={configuration.timeout_seconds:g}s. Ctrl+C cancels."
            )

    async def cleanup(
        self, label: str, operation: Callable[[], Awaitable[None]]
    ) -> None:
        # Cleanup RPCs can fail if Ctrl+C already stopped the child CLI. Report
        # those failures separately rather than replacing cancellation/timeout.
        try:
            async with asyncio.timeout(CLEANUP_TIMEOUT_SECONDS):
                await operation()
        except Exception as error:
            self.error_output(f"[cleanup] {label} failed: {type(error).__name__}: {error}")
            raise

    def decide_permission(self, request: object, _invocation: object) -> (
        PermissionDecisionApproveOnce | PermissionDecisionReject
    ):
        decision = self.evaluate_permission(request)
        self.record(
            "PERMISSION", type(decision).__name__,
            tool_call_id=getattr(request, "tool_call_id", None),
            role=self.tool_roles.get(getattr(request, "tool_call_id", "")),
            request_type=type(request).__name__,
            feedback=getattr(decision, "feedback", None),
        )
        return decision

    def evaluate_permission(self, request: object) -> (
        PermissionDecisionApproveOnce | PermissionDecisionReject
    ):
        # Permission requests carry a tool_call_id, not a role. Correlate it
        # with SDK tool-start events from the isolated subagent before allowing
        # writes or a shell command; unknown requests fail closed.
        if (
            self.permission_directory is None
            or getattr(request, "managed_approval_required", False)
            or getattr(request, "request_sandbox_bypass", False)
            or getattr(request, "request_sandbox_permissive", False)
        ):
            return PermissionDecisionReject(feedback="Permission policy denied this request.")
        if isinstance(request, PermissionRequestRead):
            return PermissionDecisionApproveOnce()
        tool_call_id = getattr(request, "tool_call_id", None)
        if not isinstance(tool_call_id, str):
            return PermissionDecisionReject(feedback="Missing runtime tool-call identity.")
        role = self.tool_roles.get(tool_call_id)
        if isinstance(request, PermissionRequestWrite) and role in WRITE_PATHS:
            expected = (self.permission_directory / WRITE_PATHS[role]).resolve()
            supplied = Path(request.file_name)
            actual = (
                supplied if supplied.is_absolute()
                else self.permission_directory / supplied
            ).resolve()
            resolved = (
                Path(request.resolved_path).resolve()
                if request.resolved_path
                else actual
            )
            if actual == expected and resolved == expected:
                return PermissionDecisionApproveOnce()
        arguments = self.tool_arguments.get(tool_call_id)
        if (
            isinstance(request, PermissionRequestShell)
            and role == "tester"
            and request.full_command_text in TEST_COMMANDS
            and not request.has_write_file_redirection
            and not request.possible_urls
            and isinstance(arguments, dict)
            and arguments.get("command") == request.full_command_text
        ):
            # The runtime may omit resolved_working_directory when the shell
            # inherits create_session(working_directory). If the tool supplies
            # a cwd override, that override must also resolve to the checkout.
            directories = [
                request.resolved_working_directory,
                *(arguments.get(key) for key in ("workdir", "cwd", "working_directory")
                  if key in arguments),
            ]
            if all(
                value is None
                or (
                    isinstance(value, str)
                    and Path(value).resolve() == self.permission_directory
                )
                for value in directories
            ):
                self.approved_test_calls.add(tool_call_id)
                return PermissionDecisionApproveOnce()
        return PermissionDecisionReject(
            feedback="Only the assigned file or one of the two exact booking test commands is permitted."
        )

    def validate_configuration(self, configuration: DemoConfiguration) -> Path:
        if not configuration.model.strip() or not configuration.prompt.strip():
            raise ConfigurationError("model and prompt must not be empty.")
        if configuration.repair_prompt is not None and not configuration.repair_prompt.strip():
            raise ConfigurationError("repair_prompt must not be empty when enabled.")
        if not isinstance(configuration.keep_changes, bool):
            raise ConfigurationError("keep_changes must be True or False.")
        for name in ("timeout_seconds", "progress_interval_seconds"):
            value = getattr(configuration, name)
            if not math.isfinite(value) or value <= 0:
                raise ConfigurationError(f"{name} must be finite and greater than zero.")
        if (
            configuration.fallback_agent is not None
            and configuration.fallback_agent not in AGENT_NAMES
        ):
            raise ConfigurationError("fallback_agent must name a configured agent.")
        directory = configuration.working_directory.resolve()
        for relative in (PYTHON_ANALYSIS_FILE, "beancount/parser/booking_full_test.py"):
            if not (directory / relative).is_file():
                raise ConfigurationError(
                    "Prepare the Beancount clone (demos/005-sdlc-team/workspace, tag demo-base-1048) first; missing: "
                    + str(directory / relative)
                )
        result = subprocess.run(
            ["git", "-C", str(directory), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode or result.stdout.strip() != configuration.expected_commit:
            raise ConfigurationError(
                "Prepare the Beancount clone at tag demo-base-1048, commit "
                + configuration.expected_commit
                + " before running Demo 005."
            )
        status = subprocess.run(
            ["git", "-C", str(directory), "status", "--porcelain", "--untracked-files=all"],
            capture_output=True, text=True, check=True,
        )
        if status.stdout.strip():
            raise ConfigurationError(
                "Demo 005 requires a clean workspace before starting. "
                "Preserve existing edits and untracked files first; no files were reset."
            )
        # Check executable modules before opening the SDK client: discovering
        # a package alone does not prove the analyst/tester can actually run it.
        try:
            versions = verify_demo_tools(Path(sys.executable), directory, self.environment)
        except ToolchainError as error:
            raise ConfigurationError(str(error)) from error
        self.output("[setup] Toolchain verified: " + ", ".join(versions))
        return directory

    def rollback(self, directory: Path, expected_commit: str) -> None:
        try:
            subprocess.run(
                ["git", "-C", str(directory), "restore", "--source", expected_commit,
                 "--worktree", "--", *dict.fromkeys(WRITE_PATHS.values())],
                capture_output=True, text=True, check=True,
            )
            result = subprocess.run(
                ["git", "-C", str(directory), "status", "--porcelain",
                 "--untracked-files=all"],
                capture_output=True, text=True, check=True,
            )
            if result.stdout.strip():
                raise RuntimeError(
                    "Workspace is not clean after rollback; inspect remaining changes. "
                    "Only the three approved files were restored."
                )
        except (OSError, subprocess.CalledProcessError, RuntimeError) as error:
            self.error_output(f"[rollback] Failed: {error}")
            raise
        self.output("[rollback] Base restored; workspace clean. No commit or push.")

    def record(self, category: str, action: str, **details: object) -> None:
        if self.activity_log is not None:
            self.activity_log.write(category, action, **details)

    def record_event(self, event: SessionEvent) -> None:
        data = event.data
        role = (
            (self.selected_session_agent or self.explicit_agent or "orchestrator")
            if event.agent_id is None
            else self.agent_roles.get(event.agent_id, "unresolved")
        )
        context = {
            "event_id": str(event.id), "parent_event_id": str(event.parent_id),
            "sdk_timestamp": event.timestamp.isoformat(),
            "agent_id": event.agent_id, "role": role,
            "tool_call_id": getattr(data, "tool_call_id", None),
            "parent_tool_call_id": getattr(data, "parent_tool_call_id", None),
        }
        if isinstance(data, AssistantUsageData):
            # assistant.usage includes delegated agents. Count each event once,
            # across all sessions in this run; never infer AIC from token counts.
            if self.usage.add(event):
                self.record(
                    "USAGE", "assistant.usage", **context, model=data.model,
                    request_nano_aiu=(
                        data.copilot_usage.total_nano_aiu
                        if data.copilot_usage is not None else None
                    ),
                    totals=self.usage.report(),
                )
        elif event.type.value.startswith("subagent."):
            self.record(
                "AGENT", event.type.value, **context,
                agent_name=getattr(data, "agent_name", None),
                error=getattr(data, "error", None),
                cancelled=getattr(data, "cancelled", None),
                duration=str(getattr(data, "duration", None)),
            )
        elif isinstance(data, AssistantMessageData):
            # Log the public answer, never reasoning, opaque state or credentials.
            self.record(
                "AGENT OUTPUT", "assistant.message", **context,
                message_id=data.message_id, content=data.content,
            )
        elif isinstance(data, ToolExecutionStartData):
            self.tool_names[data.tool_call_id] = data.tool_name
            category = (
                "CUSTOM TOOL" if data.tool_name in (PYTHON_ANALYSIS_TOOL, "git_diff")
                else "HANDOFF" if data.tool_name in ("task", "read_agent", "list_agents")
                else "RUNTIME TOOL"
            )
            self.record(
                category, f"{data.tool_name} requested", **context,
                arguments=data.arguments,
            )
        elif isinstance(data, ToolExecutionCompleteData):
            tool_name = self.tool_names.get(data.tool_call_id, "unresolved")
            self.record(
                "HANDOFF" if tool_name in ("task", "read_agent") else "TOOL RESULT",
                f"{tool_name} returned", **context,
                recipient=self.tool_roles.get(data.tool_call_id, role),
                success=data.success,
                content=getattr(data.result, "content", None),
                detailed_content=getattr(data.result, "detailed_content", None),
                error=getattr(data.error, "message", None),
            )
        elif event.type == SessionEventType.SESSION_ERROR:
            self.record(
                "ERROR", "session.error", **context,
                message=getattr(data, "message", None),
            )

    def show_event(self, event: SessionEvent) -> None:
        # Keep the console compact. The local activity log records public
        # messages and tool results separately, with runtime correlation IDs.
        name = getattr(event.type, "value", str(event.type))
        self.last_event = name
        self.last_event_time = asyncio.get_running_loop().time()
        print_event(event, self.output)
        if event.type in (
            SessionEventType.SUBAGENT_SELECTED,
            SessionEventType.SUBAGENT_STARTED,
            SessionEventType.SUBAGENT_COMPLETED,
            SessionEventType.SUBAGENT_FAILED,
        ):
            agent_name = getattr(event.data, "agent_name", None)
            if isinstance(agent_name, str) and agent_name in AGENT_NAMES:
                self.output(f"[subagent] {name}: {agent_name}")
                if event.agent_id is not None:
                    self.agent_roles[event.agent_id] = agent_name
                elif (
                    event.type == SessionEventType.SUBAGENT_SELECTED
                    and agent_name == self.explicit_agent
                ):
                    self.selected_session_agent = agent_name
            if event.type == SessionEventType.SUBAGENT_STARTED:
                self.delegated = True
            if event.type == SessionEventType.SUBAGENT_FAILED:
                self.failed = True
        if event.type == SessionEventType.TOOL_EXECUTION_START and isinstance(
            event.data, ToolExecutionStartData
        ):
            self.output(f"[tool] start {event.data.tool_name}")
            role = (
                self.selected_session_agent if event.agent_id is None
                else self.agent_roles.get(event.agent_id)
            )
            if role is not None:
                self.tool_roles[event.data.tool_call_id] = role
                self.tool_arguments[event.data.tool_call_id] = event.data.arguments
            else:
                self.tool_roles[event.data.tool_call_id] = (
                    "orchestrator" if event.agent_id is None else "unresolved"
                )
        if event.type == SessionEventType.TOOL_EXECUTION_COMPLETE and isinstance(
            event.data, ToolExecutionCompleteData
        ):
            self.output(f"[tool] complete success={event.data.success}")
            if event.data.success and event.data.tool_call_id in self.approved_test_calls:
                self.passed_test_calls.add(event.data.tool_call_id)
        self.record_event(event)

    async def ask(self, client: CopilotClient, configuration: DemoConfiguration,
                  directory: Path, *, agent: str | None = None,
                  prompt: str | None = None) -> str:
        # The built-in task tool delegates within the runtime, where each custom
        # agent receives an isolated context and its own tool allowlist. Selecting
        # agent explicitly selects a specialist in code instead of asking the
        # orchestrator to choose it. Documentation uses this path on every run.
        self.explicit_agent = agent
        self.selected_session_agent = None
        # The orchestrator cannot delegate documentation before Python reaches
        # the final stage: that role is registered only in its explicit session.
        agents = [
            role.copy() for role in AGENTS
            if role.get("name") != "documentarian" or agent == "documentarian"
        ]
        self.record(
            "SESSION", "create requested", agent=agent or "orchestrator",
            model=configuration.model,
            agents=agents,
        )
        show_disabled_mcp_servers(self.output)
        session = await client.create_session(
            model=configuration.model,
            working_directory=str(directory),
            # Exact matches are blocked before startup/authentication, scoped to
            # this SDK session and independent of each agent's tool allowlist.
            disabled_mcp_servers=list(DISABLED_MCP_SERVERS),
            custom_agents=agents,
            # tools= registers deterministic local logic with the SDK runtime;
            # only the analyst's allowlist exposes the static analyzers.
            tools=[
                build_diff_tool(directory, activity_log=self.activity_log),
                build_python_static_analysis_tool(
                    directory, output=self.output, activity_log=self.activity_log,
                ),
            ],
            default_agent={"excluded_tools": [
                "bash", "powershell", "apply_patch", "edit", "grep", "view", "git_diff",
                PYTHON_ANALYSIS_TOOL,
            ]},
            available_tools=["task", "read_agent", "list_agents",
                             "grep", "view", "apply_patch", "edit", SHELL_TOOL,
                             "git_diff", PYTHON_ANALYSIS_TOOL],
            agent=agent,
            # The SDK asks this callback for each sensitive operation. Roles
            # and approved paths/command are enforced here, not by prompts.
            on_permission_request=self.decide_permission,
            on_event=self.show_event,
        )
        self.last_event = "session created"
        self.last_event_time = asyncio.get_running_loop().time()
        progress = asyncio.create_task(self.report_progress(configuration))
        interrupted = False
        content: str | None = None
        try:
            self.output(f"[lifecycle] Session created: {session.session_id}")
            prompts = [prompt if prompt is not None else configuration.prompt]
            if agent is None and prompt is None and configuration.repair_prompt is not None:
                prompts.append(configuration.repair_prompt)
            for turn, message in enumerate(prompts, start=1):
                self.output(f"[stage] {agent or 'orchestrator'}: prompt {turn}")
                self.record(
                    "HANDOFF", "user prompt sent", session_id=session.session_id,
                    recipient=agent or "orchestrator", turn=turn, prompt=message,
                )
                # Each send waits for session.idle; the next prompt reuses this
                # session's history, including analysis and specialist replies.
                # SDK timeout stops waiting, not agent work: abort on timeout.
                async with asyncio.timeout(configuration.timeout_seconds):
                    response = await session.send_and_wait(
                        message, timeout=configuration.timeout_seconds,
                    )
                if response is None or not isinstance(response.data, AssistantMessageData):
                    raise RuntimeError(
                        "Copilot reached session.idle without a final assistant message."
                    )
                self.output("[lifecycle] Session idle")
                content = response.data.content
                if self.activity_log is not None and self.activity_log.failure is not None:
                    raise self.activity_log.failure
                self.record("AGENT OUTPUT", "final response", turn=turn, content=content)
                if self.failed:
                    raise RuntimeError("A specialist failed; subsequent stages were not started.")
        except (TimeoutError, asyncio.CancelledError):
            interrupted = True
            self.output("[lifecycle] Aborting active Copilot request")
            try:
                await self.cleanup("Session abort", session.abort)
            except Exception:
                pass  # Already reported; preserve timeout or cancellation.
            raise
        except BaseException:
            interrupted = True
            raise
        finally:
            progress.cancel()
            await asyncio.gather(progress, return_exceptions=True)
            try:
                await self.cleanup("Session disconnect", session.disconnect)
            except Exception:
                if not interrupted:
                    raise
        self.output("[lifecycle] Session closed")
        if content is None:
            raise RuntimeError("Copilot session completed without a response.")
        return content

    async def execute(self, configuration: DemoConfiguration) -> None:
        log_directory = configuration.log_directory.resolve()
        if log_directory.is_relative_to(configuration.working_directory.resolve()):
            raise ConfigurationError("log_directory must be outside the rollback workspace.")
        original_output, original_error = self.output, self.error_output
        self.usage = RunUsage()
        with ActivityLog(log_directory, self.environment) as activity_log:
            self.activity_log = activity_log

            def logged_output(message: str) -> None:
                activity_log.write("CONSOLE", "output", message=message)
                original_output(message)

            def logged_error(message: str) -> None:
                activity_log.write("ERROR", "output", message=message)
                original_error(message)

            self.output, self.error_output = logged_output, logged_error
            try:
                self.output(f"[log] Activity log: {activity_log.path}")
                self.output(f"[log] Summary log: {activity_log.summary_path}")
                self.record("RUN", "started")
                await self.execute_team(configuration)
                self.record("RUN", "completed", subagent_failed=self.failed)
            except BaseException as error:
                self.record(
                    "RUN", "interrupted" if isinstance(
                        error, (asyncio.CancelledError, KeyboardInterrupt)
                    ) else "failed",
                    error_type=type(error).__name__, message=str(error),
                )
                raise
            finally:
                try:
                    report = self.usage.report()
                    self.record("USAGE", "run total", **report)
                    aic = report["aic"] if report["aic"] is not None else "unavailable"
                    self.output(
                        f"[usage] AIC={aic}; status={report['status']}; "
                        f"reported calls={report['reported_calls']}; "
                        f"calls without billing={report['calls_without_billing']}. "
                        "SDK-reported usage, not a billing invoice."
                    )
                finally:
                    self.output, self.error_output = original_output, original_error
                    self.activity_log = None

    async def execute_team(self, configuration: DemoConfiguration) -> None:
        directory = self.validate_configuration(configuration)
        self.delegated = False
        self.failed = False
        self.agent_roles.clear()
        self.tool_roles.clear()
        self.tool_arguments.clear()
        self.tool_names.clear()
        self.approved_test_calls.clear()
        self.passed_test_calls.clear()
        self.explicit_agent = None
        self.selected_session_agent = None
        self.permission_directory = directory
        self.output(f"Model: {configuration.model}")
        self.output(f"Working directory: {directory}")
        self.output(f"[setup] Keep workspace changes: {configuration.keep_changes}")
        self.output("Custom agents: " + ", ".join(sorted(AGENT_NAMES)))
        # use_logged_in_user reads CLI-managed GitHub login, not VS Code auth.
        # Exiting the client also closes the spawned Copilot CLI runtime.
        # Runtime shells inherit the repository interpreter first on PATH.
        # The tester therefore sees the editable checkout prepared for Demo 005.
        client = CopilotRuntime(environment=self.environment, output=self.output).create_client()
        interrupted = False
        runtime_stopped = False
        try:
            await client.start()
            self.output("[lifecycle] Copilot CLI runtime connected")
            content = await self.ask(client, configuration, directory)
            if (
                not self.delegated
                and not self.failed
                and configuration.fallback_agent is not None
            ):
                # Explicitly opt into one role only when runtime did not delegate.
                # This separate session does not replay a six-stage workflow.
                agent = configuration.fallback_agent
                self.output(f"[fallback] Selecting SDK agent: {agent}")
                content = await self.ask(
                    client, configuration, directory, agent=agent,
                    prompt="Read the zero-units total-cost booking path and report its acceptance "
                           "invariants only. Do not edit files.",
                )
            if configuration.repair_prompt is not None:
                # This transition is deterministic Python control flow, not task
                # delegation. A fresh SDK session needs the team's result inline;
                # agent= selects the role and the same permission policy applies.
                self.output("[stage] Selecting SDK agent: documentarian")
                content = await self.ask(
                    client, configuration, directory, agent="documentarian",
                    prompt=DOCUMENTATION_PROMPT + content,
                )
            self.output("\nCopilot response:")
            self.output(content)
        except BaseException:
            interrupted = True
            raise
        finally:
            try:
                await self.cleanup("Copilot client stop", client.stop)
                runtime_stopped = True
            except Exception:
                # Force-stop targets only this SDK client's owned runtime.
                try:
                    await self.cleanup("Copilot client force-stop", client.force_stop)
                    runtime_stopped = True
                except Exception:
                    if not interrupted:
                        raise
                if not interrupted:
                    raise
            finally:
                self.permission_directory = None
                # Stop the SDK-owned runtime before restoring files: delegated
                # editors must not race with rollback, including after abort.
                if runtime_stopped:
                    try:
                        # Record generated changes before optional rollback;
                        # this is evidence, not a claim of reviewer approval.
                        if self.activity_log is not None:
                            diff = subprocess.run(
                                ["git", "-C", str(directory), "diff", "HEAD", "--",
                                 *dict.fromkeys(WRITE_PATHS.values())],
                                capture_output=True, text=True, encoding="utf-8",
                                check=True,
                            )
                            self.record("ARTIFACT", "diff before rollback", diff=diff.stdout)
                    finally:
                        if configuration.keep_changes:
                            self.output(
                                "[rollback] Disabled: workspace changes kept for inspection. "
                                "No commit or push."
                            )
                        else:
                            self.rollback(directory, configuration.expected_commit)
                else:
                    self.error_output(
                        "[rollback] Not attempted: runtime shutdown could not be confirmed. "
                        "Stop the demo runtime before restoring the approved files."
                    )
        self.output("[lifecycle] Copilot client closed")

    def run(self, configuration: DemoConfiguration) -> int:
        try:
            asyncio.run(self.execute(configuration))
        except ConfigurationError as error:
            self.error_output(f"Configuration error: {error}")
            return 2
        except KeyboardInterrupt:
            self.error_output("\nCancelled.")
            return 130
        except TimeoutError:
            self.error_output(
                f"Copilot request timed out after {configuration.timeout_seconds:g}s "
                f"(last event: {self.last_event}). Active work was aborted; "
                "check the [rollback] result before retrying."
            )
            return 1
        except Exception as error:
            self.error_output(f"Copilot session failed: {error}")
            return 1
        return 0


def main(configuration: DemoConfiguration = CONFIGURATION) -> int:
    return SdlcTeamApplication().run(configuration)


if __name__ == "__main__":
    raise SystemExit(main())
