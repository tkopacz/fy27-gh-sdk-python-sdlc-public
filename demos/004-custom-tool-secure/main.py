#!/usr/bin/env python3
"""Run a Copilot SDK session with a path-restricting pre-tool hook."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from copilot_runtime import CopilotRuntime, DISABLED_MCP_SERVERS, print_event, show_disabled_mcp_servers

from copilot import (
    PreToolUseHookInput,
    PreToolUseHookOutput,
    define_tool,
)
from copilot.session_events import (
    AssistantMessageData,
    SessionEvent,
    SessionEventType,
    ToolExecutionCompleteData,
    ToolExecutionStartData,
)
from copilot.tools import Tool
from pydantic import BaseModel, Field

DEMO_DIRECTORY = Path(__file__).resolve().parent
EXPECTED_COMMIT = "1053b01f486b598c45a56f574ff3dfef64f20500"
OUTSIDE_PATH = "../fixtures/outside-workspace.txt"
DEFAULT_PROMPT = f"""Sprawdź zabezpieczenie odczytu plików, wykonując te kroki w kolejności:
1. Wywołaj read_project_file dla `{OUTSIDE_PATH}`. Oczekuj odmowy i nie próbuj
   obchodzić zabezpieczenia ani używać innej ścieżki do tego pliku.
2. Po odmowie wywołaj read_project_file dla `README.rst`.
3. Odpowiedz krótko: potwierdź zablokowanie pierwszej ścieżki i podaj tytuł
   odczytany z dozwolonego README. Nie zgaduj zawartości plików."""


@dataclass(frozen=True)
class DemoConfiguration:
    working_directory: Path = (
        DEMO_DIRECTORY / "workspace"
    )
    outside_fixture: Path = DEMO_DIRECTORY / "fixtures" / "outside-workspace.txt"
    model: str = "auto"
    prompt: str = DEFAULT_PROMPT
    timeout_seconds: float = 180.0
    expected_commit: str = EXPECTED_COMMIT


CONFIGURATION = DemoConfiguration()


class ConfigurationError(ValueError):
    """Raised when the demo inputs are incomplete or inconsistent."""


class PathAccessError(ValueError):
    """Raised when a requested file does not satisfy the workspace policy."""


class ReadFileParams(BaseModel):
    path: str = Field(
        min_length=1,
        description="Ścieżka pliku względem katalogu roboczego sesji Copilot",
    )


class WorkspaceReadPolicy:
    """Resolve requested files and confine them to explicit directory roots."""

    def __init__(self, working_directory: Path, allowed_directories: tuple[Path, ...]):
        self.working_directory = working_directory.resolve(strict=True)
        self.allowed_directories = tuple(
            directory.resolve(strict=True) for directory in allowed_directories
        )
        if not self.allowed_directories:
            raise ConfigurationError("At least one allowed directory is required.")
        for directory in self.allowed_directories:
            if not directory.is_dir():
                raise ConfigurationError(
                    f"Allowed path is not a directory: {directory}"
                )

    def authorize(self, requested_path: str) -> Path:
        if not requested_path.strip():
            raise PathAccessError("The requested path must not be empty.")
        if "\x00" in requested_path:
            raise PathAccessError("The requested path contains a null byte.")

        path = Path(requested_path)
        candidate = path if path.is_absolute() else self.working_directory / path
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as error:
            raise PathAccessError(
                "The requested path does not identify an existing file."
            ) from error

        if not resolved.is_file():
            raise PathAccessError("The requested path is not a regular file.")
        if not any(
            resolved.is_relative_to(directory)
            for directory in self.allowed_directories
        ):
            raise PathAccessError(
                "The requested file is outside the allowed project directories."
            )
        return resolved

    def project_path(self, path: Path) -> str:
        return path.relative_to(self.working_directory).as_posix()


class ProjectReadGuard:
    """Apply the workspace policy before Copilot can execute a file-read tool."""

    TOOL_NAME = "read_project_file"

    def __init__(
        self,
        policy: WorkspaceReadPolicy,
        *,
        output: Callable[[str], None] = print,
    ) -> None:
        self.policy = policy
        self.output = output

    def check(
        self,
        hook_input: PreToolUseHookInput,
        _context: dict[str, str],
    ) -> PreToolUseHookOutput:
        tool_name = hook_input.get("toolName")
        if not isinstance(tool_name, str) or tool_name != self.TOOL_NAME:
            reason = f"Tool {tool_name!r} is not approved for this session."
            self.output(f"[hook] deny tool={tool_name} reason=unapproved-tool")
            return {
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }

        working_directory = hook_input.get("workingDirectory")
        if not isinstance(working_directory, str):
            hook_working_directory = None
        else:
            try:
                hook_working_directory = Path(working_directory).resolve(strict=True)
            except (OSError, RuntimeError):
                hook_working_directory = None
        if hook_working_directory != self.policy.working_directory:
            self.output(
                f"[hook] deny tool={tool_name} reason=unexpected-working-directory"
            )
            return {
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    "The tool invocation has an unexpected working directory."
                ),
            }

        arguments = hook_input.get("toolArgs")
        requested_path = arguments.get("path") if isinstance(arguments, dict) else None
        if not isinstance(requested_path, str):
            self.output(f"[hook] deny tool={tool_name} reason=invalid-path-argument")
            return {
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    "The file-read tool requires one string path argument."
                ),
            }

        try:
            approved_path = self.policy.authorize(requested_path)
        except PathAccessError as error:
            self.output(f"[hook] deny tool={tool_name} path={requested_path}")
            return {
                "permissionDecision": "deny",
                "permissionDecisionReason": str(error),
            }

        project_path = self.policy.project_path(approved_path)
        self.output(f"[hook] allow tool={tool_name} path={project_path}")
        return {
            "permissionDecision": "allow",
            "permissionDecisionReason": (
                "The resolved file is inside an explicitly allowed project directory."
            ),
        }


def build_read_tool(
    policy: WorkspaceReadPolicy,
    *,
    output: Callable[[str], None] = print,
) -> Tool:
    # Copilot receives this typed contract immediately (`defer="never"`), and
    # `is_terminal=False` returns successful file contents to the agent so it
    # can continue to its final answer. `skip_permission=True` suppresses the
    # normal tool prompt only because both the pre-tool hook and handler enforce
    # the same path policy.
    @define_tool(
        name=ProjectReadGuard.TOOL_NAME,
        description=(
            "Czyta plik tekstowy projektu po zatwierdzeniu ścieżki przez "
            "pre-tool hook."
        ),
        skip_permission=True,
        defer="never",
        is_terminal=False,
    )
    def read_project_file(params: ReadFileParams) -> str:
        # The handler repeats the policy check as defense in depth. The hook is
        # still observable because a denied invocation never reaches this line.
        approved_path = policy.authorize(params.path)
        project_path = policy.project_path(approved_path)
        output(f"[tool] read path={project_path}")
        try:
            return approved_path.read_text(encoding="utf-8")
        except OSError as error:
            raise RuntimeError(f"Cannot read approved file {project_path}: {error}") from error

    return read_project_file


class SecureCustomToolApplication:
    """Validate local inputs and run one hook-protected agent loop."""

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
        self.read_calls: set[str] = set()

    @staticmethod
    def repository_revision(working_directory: Path) -> str:
        result = subprocess.run(
            ["git", "-C", str(working_directory), "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            detail = result.stderr.strip() or "git rev-parse failed"
            raise ConfigurationError(
                f"{working_directory} is not a Git repository: {detail}"
            )
        return result.stdout.strip()

    def validate_configuration(
        self, configuration: DemoConfiguration
    ) -> WorkspaceReadPolicy:
        if not configuration.model:
            raise ConfigurationError("model must not be empty.")
        if not configuration.prompt.strip():
            raise ConfigurationError("prompt must not be empty.")
        if configuration.timeout_seconds <= 0:
            raise ConfigurationError("timeout_seconds must be greater than zero.")

        working_directory = configuration.working_directory.resolve()
        if not working_directory.is_dir():
            raise ConfigurationError(
                "Prepare the pinned Beancount clone (tag demo-red-1048, see Demo 002) first: "
                f"{working_directory} does not exist."
            )
        revision = self.repository_revision(working_directory)
        if revision != configuration.expected_commit:
            raise ConfigurationError(
                f"Expected Beancount commit {configuration.expected_commit}, "
                f"found {revision}."
            )

        outside_fixture = configuration.outside_fixture.resolve(strict=True)
        policy = WorkspaceReadPolicy(working_directory, (working_directory,))
        if outside_fixture.is_relative_to(policy.working_directory):
            raise ConfigurationError(
                "The denied-path fixture must remain outside the allowed workspace."
            )
        return policy

    def show_event(self, event: SessionEvent) -> None:
        # Only selected event fields are printed; complete payloads can contain
        # prompts, file contents, or other sensitive session data.
        if event.type is SessionEventType.ASSISTANT_TURN_START:
            self.turn_count += 1
            self.output(f"[event] assistant.turn_start turn={self.turn_count}")
            return

        if (
            event.type is SessionEventType.TOOL_EXECUTION_START
            and isinstance(event.data, ToolExecutionStartData)
            and event.data.tool_name == ProjectReadGuard.TOOL_NAME
        ):
            self.read_calls.add(event.data.tool_call_id)
            arguments = event.data.arguments
            path = arguments.get("path") if isinstance(arguments, dict) else None
            self.output(
                "[event] tool.execution_start "
                f"tool={ProjectReadGuard.TOOL_NAME} path={path}"
            )
            return

        if (
            event.type is SessionEventType.TOOL_EXECUTION_COMPLETE
            and isinstance(event.data, ToolExecutionCompleteData)
            and event.data.tool_call_id in self.read_calls
        ):
            self.output(
                "[event] tool.execution_complete "
                f"tool={ProjectReadGuard.TOOL_NAME} success={event.data.success}"
            )
            return

        if event.type is SessionEventType.SESSION_IDLE:
            print_event(event, self.output)

    async def execute(self, configuration: DemoConfiguration) -> None:
        policy = self.validate_configuration(configuration)
        guard = ProjectReadGuard(policy, output=self.output)
        read_tool = build_read_tool(policy, output=self.output)
        self.turn_count = 0
        self.read_calls.clear()
        show_disabled_mcp_servers(self.output)

        self.output(f"Model: {configuration.model}")
        self.output(f"Working directory: {policy.working_directory}")
        self.output("Allowed directories:")
        for directory in policy.allowed_directories:
            self.output(f"- {directory}")
        self.output("Generated tool schema:")
        self.output(json.dumps(read_tool.parameters, ensure_ascii=False, indent=2))

        # Entering the client connects to the authenticated Copilot CLI runtime;
        # both context managers guarantee session and runtime cleanup.
        async with self.runtime.create_client() as client:
            self.output("[lifecycle] Copilot CLI runtime connected")

            # `tools` registers the custom reader, while `available_tools`
            # prevents the agent from selecting any other tool. The programmatic
            # pre-tool hook stays enabled while repository hook discovery is
            # disabled, so every attempted read is decided by this demo's guard.
            async with await client.create_session(
                model=configuration.model,
                working_directory=str(policy.working_directory),
                tools=[read_tool],
                available_tools=[ProjectReadGuard.TOOL_NAME],
                # The SDK blocks these exact names for this session while
                # preserving the custom reader and its independent path guard.
                disabled_mcp_servers=list(DISABLED_MCP_SERVERS),
                # on_permission_request - but - we are not using it in this demo.
                hooks={"on_pre_tool_use": guard.check},
                enable_file_hooks=False,
                on_event=self.show_event,
            ) as session:
                self.output(f"[lifecycle] Session created: {session.session_id}")

                # Copilot first receives a denied tool result, then continues the
                # same agent loop and makes the allowed read before answering.
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
    return SecureCustomToolApplication().run(CONFIGURATION)


if __name__ == "__main__":
    raise SystemExit(main())
