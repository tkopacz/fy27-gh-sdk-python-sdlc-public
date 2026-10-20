#!/usr/bin/env python3
"""Register a domain tool and let the Copilot SDK run the agent loop."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from copilot_runtime import CopilotRuntime, DISABLED_MCP_SERVERS, print_event, show_disabled_mcp_servers

from copilot import PermissionHandler, define_tool
from copilot.session_events import (
    AssistantMessageData,
    AssistantTurnStartData,
    SessionEvent,
    SessionEventType,
    ToolExecutionCompleteData,
    ToolExecutionStartData,
)
from copilot.tools import Tool
from pydantic import BaseModel, Field

DEMO_DIRECTORY = Path(__file__).resolve().parent
ISSUE_FIXTURE = DEMO_DIRECTORY / "fixtures" / "beancount-1048.json"
ISSUE_NUMBER = 1048
REQUIRED_SNAPSHOT_FIELDS = (
    "repository",
    "number",
    "title",
    "body",
    "acceptance_criteria",
)
DEFAULT_PROMPT = """Podaj kryteria akceptacji issue #1048.
Użyj narzędzia get_requirement, żeby odczytać lokalny snapshot.
Nie zgaduj treści issue i nie wywołuj innych narzędzi."""


@dataclass(frozen=True)
class DemoConfiguration:
    fixture_path: Path = ISSUE_FIXTURE
    model: str = "auto"
    prompt: str = DEFAULT_PROMPT
    timeout_seconds: float = 180.0
    expected_issue_number: int = ISSUE_NUMBER


CONFIGURATION = DemoConfiguration()


class ConfigurationError(ValueError):
    """Raised when the local issue snapshot or demo settings are not ready."""


class IssueParams(BaseModel):
    number: int = Field(description="Numer issue w repozytorium beancount")


class RequirementCatalog:
    """Read the approved issue snapshot from disk."""

    def __init__(self, fixture_path: Path) -> None:
        self.fixture_path = fixture_path

    def load(self) -> dict[str, Any]:
        if not self.fixture_path.is_file():
            raise ConfigurationError(
                "Prepare the local issue snapshot first; missing: "
                + str(self.fixture_path)
            )
        try:
            snapshot = json.loads(self.fixture_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ConfigurationError(
                f"{self.fixture_path} is not valid JSON: {error.msg}"
            ) from error
        if not isinstance(snapshot, dict):
            raise ConfigurationError(
                f"{self.fixture_path} must contain a JSON object."
            )
        missing_fields = [
            field for field in REQUIRED_SNAPSHOT_FIELDS if field not in snapshot
        ]
        if missing_fields:
            raise ConfigurationError(
                f"{self.fixture_path} is missing: " + ", ".join(missing_fields)
            )
        return snapshot

    def get(self, number: int) -> str:
        snapshot = self.load()
        stored_number = snapshot["number"]
        if stored_number != number:
            raise ValueError(
                f"Issue {number} is not in the local fixture; "
                f"only {stored_number} is available."
            )
        return json.dumps(snapshot, ensure_ascii=False, indent=2)


def build_requirement_tool(fixture_path: Path) -> Tool:
    # Copilot publishes this JSON schema to the model. defer="never" keeps the
    # tool in the first turn instead of hiding it behind tool search.
    # skip_permission lets this read-only lookup run without a permission
    # prompt; do not copy that flag onto tools that change files or call
    # external systems.
    @define_tool(
        description=(
            "Pobiera zatwierdzone wymaganie i kryteria akceptacji z lokalnego "
            "snapshotu issue beancount."
        ),
        defer="never",
        skip_permission=True,
    )
    def get_requirement(params: IssueParams) -> str:
        return RequirementCatalog(fixture_path).get(params.number)

    return get_requirement


get_requirement = build_requirement_tool(ISSUE_FIXTURE)


class CustomToolApplication:
    """Show a domain tool and let Copilot run the model-and-tool loop."""

    def __init__(
        self,
        *,
        environment: Mapping[str, str] | None = None,
        output: Callable[[str], None] = print,
        error_output: Callable[[str], None] | None = None,
    ) -> None:
        self.output = output
        self.runtime = CopilotRuntime(environment=os.environ if environment is None else environment, output=output)
        self.error_output = error_output or (
            lambda message: print(message, file=sys.stderr)
        )
        self.turn_count = 0

    def validate_configuration(self, configuration: DemoConfiguration) -> dict[str, Any]:
        if not configuration.model:
            raise ConfigurationError("model must not be empty.")
        if not configuration.prompt.strip():
            raise ConfigurationError("prompt must not be empty.")
        if configuration.timeout_seconds <= 0:
            raise ConfigurationError("timeout_seconds must be greater than zero.")
        if configuration.expected_issue_number <= 0:
            raise ConfigurationError("expected_issue_number must be greater than zero.")
        snapshot = RequirementCatalog(configuration.fixture_path).load()
        if snapshot["number"] != configuration.expected_issue_number:
            raise ConfigurationError(
                "Expected issue "
                f"{configuration.expected_issue_number}, found {snapshot['number']}."
            )
        return snapshot

    def show_tool_schema(self, tool: Tool) -> None:
        self.output(f"Tool: {tool.name}")
        self.output("Pydantic schema:")
        self.output(json.dumps(tool.parameters, indent=2))

    def show_event(self, event: SessionEvent) -> None:
        event_type = event.type
        print_event(event, self.output)

        if event_type == SessionEventType.ASSISTANT_TURN_START:
            self.turn_count += 1
            turn_id = ""
            if isinstance(event.data, AssistantTurnStartData):
                turn_id = event.data.turn_id
            self.output(f"[turn] start {turn_id}")
            return

        if event_type == SessionEventType.TOOL_EXECUTION_START:
            tool_name = "unknown"
            if isinstance(event.data, ToolExecutionStartData):
                tool_name = event.data.tool_name
            self.output(f"[tool] start {tool_name}")
            # The custom tool's only argument is a public issue number, so it is
            # safe to show the value the model chose before the handler runs.
            if (
                isinstance(event.data, ToolExecutionStartData)
                and event.data.tool_name == "get_requirement"
            ):
                try:
                    number = IssueParams.model_validate(event.data.arguments).number
                except ValueError:
                    self.output("[tool] arguments invalid")
                else:
                    self.output(f"[tool] issue number {number}")
            return

        if event_type == SessionEventType.TOOL_EXECUTION_COMPLETE:
            success = False
            if isinstance(event.data, ToolExecutionCompleteData):
                success = event.data.success
            self.output(f"[tool] complete success={success}")

    async def execute(self, configuration: DemoConfiguration) -> None:
        snapshot = self.validate_configuration(configuration)
        tool = build_requirement_tool(configuration.fixture_path)
        self.turn_count = 0
        self.output(f"Model: {configuration.model}")
        self.output(f"Fixture: {configuration.fixture_path}")
        self.output(f"Issue: {snapshot['number']}")
        self.output(f"Prompt:\n{configuration.prompt}")
        show_disabled_mcp_servers(self.output)
        self.show_tool_schema(tool)

        # Entering the client starts and connects to the Copilot CLI runtime. This
        # option reuses CLI-managed GitHub credentials, not the VS Code login; the
        # matching context exit closes the connection without hand-written RPC.
        async with self.runtime.create_client() as client:
            self.output("[lifecycle] Copilot CLI runtime connected")

            # tools= registers the domain handler. available_tools allowlists only
            # that name so Copilot must call get_requirement instead of reading
            # files or searching the web. approve_all is limited to this demo.
            async with await client.create_session(
                model=configuration.model,
                # Exact matches cannot start/authenticate in this session; this
                # does not change CLI-wide settings or the custom-tool allowlist.
                disabled_mcp_servers=list(DISABLED_MCP_SERVERS),
                tools=[tool],
                available_tools=[tool.name],
                on_permission_request=PermissionHandler.approve_all,
                on_event=self.show_event,
            ) as session:
                self.output(f"[lifecycle] Session created: {session.session_id}")

                # send_and_wait is one user send. Copilot still runs as many model
                # turns and tool executions as it needs, then returns after
                # session.idle with the final assistant message.
                response = await session.send_and_wait(
                    configuration.prompt,
                    timeout=configuration.timeout_seconds,
                )
                if response is None or not isinstance(
                    response.data, AssistantMessageData
                ):
                    raise RuntimeError(
                        "Copilot reached session.idle without a final assistant message."
                    )
                self.output("[lifecycle] Session idle")
                self.output(f"[lifecycle] Assistant turns: {self.turn_count}")
                self.output("\nCopilot response:")
                self.output(response.data.content)

            self.output("[lifecycle] Session closed")

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
        except Exception as error:
            self.error_output(f"Copilot session failed: {error}")
            return 1
        return 0


def main() -> int:
    return CustomToolApplication().run(CONFIGURATION)


if __name__ == "__main__":
    raise SystemExit(main())
