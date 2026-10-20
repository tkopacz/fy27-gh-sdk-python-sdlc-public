#!/usr/bin/env python3
"""Run a repository-aware GitHub Copilot SDK session."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from copilot_runtime import CopilotRuntime, DISABLED_MCP_SERVERS, print_event, show_disabled_mcp_servers

from copilot import PermissionHandler
from copilot.session_events import AssistantMessageData, SessionEvent

DEMO_DIRECTORY = Path(__file__).resolve().parent
EXPECTED_COMMIT = "1053b01f486b598c45a56f574ff3dfef64f20500"
DEFAULT_PROMPT = """Przeczytaj `convert_costspec_to_cost` w beancount/parser/booking_full.py
i test TestZeroUnitsWithTotalCost w booking_full_test.py. Wyjaśnij, dlaczego
wpis `0 HOOL {{20.00 USD}}` z issue #1048 kończy się wyjątkiem
decimal.DivisionByZero zamiast błędem w liście errors. Nie zmieniaj plików."""


@dataclass(frozen=True)
class DemoConfiguration:
    working_directory: Path = DEMO_DIRECTORY / "workspace"
    model: str = "auto"
    prompt: str = DEFAULT_PROMPT
    timeout_seconds: float = 180.0
    expected_commit: str = EXPECTED_COMMIT


CONFIGURATION = DemoConfiguration()


class ConfigurationError(ValueError):
    """Raised when the local demo repository is not ready."""


class InitialSessionApplication:
    """Validate the workspace and run one complete Copilot agent session."""

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

    def validate_configuration(self, configuration: DemoConfiguration) -> Path:
        if not configuration.model:
            raise ConfigurationError("model must not be empty.")
        if not configuration.prompt.strip():
            raise ConfigurationError("prompt must not be empty.")
        if configuration.timeout_seconds <= 0:
            raise ConfigurationError("timeout_seconds must be greater than zero.")

        working_directory = configuration.working_directory.resolve()
        required_files = (
            working_directory / "beancount" / "parser" / "booking_full.py",
            working_directory / "beancount" / "parser" / "booking_full_test.py",
        )
        missing_files = [path for path in required_files if not path.is_file()]
        if missing_files:
            raise ConfigurationError(
                "Prepare the pinned Beancount clone first (see README); missing: "
                + ", ".join(str(path) for path in missing_files)
            )

        revision = self.repository_revision(working_directory)
        if revision != configuration.expected_commit:
            raise ConfigurationError(
                f"Expected Beancount commit (tag demo-red-1048) {configuration.expected_commit}, "
                f"found {revision}."
            )
        return working_directory

    def show_event(self, event: SessionEvent) -> None:
        print_event(event, self.output)

    async def execute(self, configuration: DemoConfiguration) -> None:
        working_directory = self.validate_configuration(configuration)
        self.output(f"Model: {configuration.model}")
        self.output(f"Working directory: {working_directory}")
        self.output(f"Prompt:\n{configuration.prompt}")
        show_disabled_mcp_servers(self.output)

        # Entering the client starts and connects to the Copilot CLI runtime. This
        # option reuses CLI-managed GitHub credentials, not the VS Code login; the
        # matching context exit closes the connection without hand-written RPC.
        async with self.runtime.create_client() as client:
            self.output("[lifecycle] Copilot CLI runtime connected")

            # The session supplies conversation history and the built-in agent tools.
            # `auto` selects an eligible model, the working directory anchors file
            # tools, the callback observes events, and approve_all avoids prompts only
            # for this controlled read-only run.
            async with await client.create_session(
                model=configuration.model,
                working_directory=str(working_directory),
                # The SDK blocks exact server names for this session before they
                # start or authenticate; it does not change CLI-wide settings.
                disabled_mcp_servers=list(DISABLED_MCP_SERVERS),
                on_permission_request=PermissionHandler.approve_all,
                on_event=self.show_event,
            ) as session:
                self.output(f"[lifecycle] Session created: {session.session_id}")

                # Intermediate events still reach on_event while this waits. After
                # session.idle, the returned event should hold the final assistant
                # message produced by the completed model-and-tool loop.
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
    return InitialSessionApplication().run(CONFIGURATION)


if __name__ == "__main__":
    raise SystemExit(main())
