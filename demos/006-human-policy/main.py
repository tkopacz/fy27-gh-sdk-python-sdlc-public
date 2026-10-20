#!/usr/bin/env python3
"""Keep safety decisions inside a Copilot SDK session."""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from copilot_runtime import (
    CopilotRuntime, RuntimeSetupError, DISABLED_MCP_SERVERS,
    print_event, show_disabled_mcp_servers,
)

from copilot import ElicitationContext, ElicitationResult
from copilot.generated.rpc import PermissionDecisionApproveOnce, PermissionDecisionReject
from copilot.session_events import AssistantMessageData, SessionEvent, SessionEventType

DEMO_DIRECTORY = Path(__file__).resolve().parent
TEST_COMMAND = "python -m pytest beancount/parser/booking_full_test.py -k TestZeroUnitsWithTotalCost -q"
ALLOWED_FILES = ("beancount/parser/booking_full.py", "beancount/parser/booking_full_test.py", "CHANGES")
CHOICES = {
    "reject": "Odrzuć wpis z kontrolowanym InterpolationError zamiast DivisionByZero.",
    "zero_cost": "Potraktuj koszt jako zero i pozwól księdze się załadować.",
    "keep_raising": "Zachowaj dotychczasowe zachowanie: niezłapany DivisionByZero.",
}
PROMPT = """Zrealizuj issue #1048 w Beancount: 0 HOOL {{20.00 USD}} (zero jednostek
z kosztem całkowitym) powoduje niezłapany decimal.DivisionByZero w loaderze.
Zanim zmienisz kod, zapytaj człowieka przez ask_user o pożądane zachowanie:
reject, zero_cost albo keep_raising. Potem uruchom
python -m pytest beancount/parser/booking_full_test.py -k TestZeroUnitsWithTotalCost -q,
popraw błędy i powtórz test. Nie uruchamiaj git push, release ani publikacji pakietu."""


@dataclass(frozen=True)
class DemoConfiguration:
    working_directory: Path = DEMO_DIRECTORY / "workspace"
    model: str = "auto"
    prompt: str = PROMPT
    timeout_seconds: float = 600.0


CONFIGURATION = DemoConfiguration()


class ConfigurationError(ValueError):
    """The local working copy or demo settings are not ready."""


class HumanPolicyApplication:
    def __init__(
        self,
        *,
        environment: Mapping[str, str],
        output: Callable[[str], None] = print,
        error_output: Callable[[str], None] | None = None,
        ask: Callable[[str], str] = input,
    ) -> None:
        self.output = output
        self.error_output = error_output or (lambda text: print(text, file=sys.stderr))
        self.ask = ask
        self.environment = dict(environment)
        self.working_directory = CONFIGURATION.working_directory

    def validate(self, configuration: DemoConfiguration) -> None:
        if not configuration.model or not configuration.prompt.strip():
            raise ConfigurationError("model and prompt must not be empty.")
        if configuration.timeout_seconds <= 0:
            raise ConfigurationError("timeout_seconds must be greater than zero.")
        root = configuration.working_directory.resolve()
        for relative in ALLOWED_FILES:
            if not (root / relative).is_file():
                raise ConfigurationError(f"Prepare the Beancount clone (demos/006-human-policy/workspace, tag demo-red-1048): missing {relative}")
        self.working_directory = root

    def resolve_cli(self) -> str:
        return CopilotRuntime(environment=self.environment, output=self.output).resolve_cli()

    def pre_tool_use(self, request: dict, _context: dict) -> dict:
        name, args = request["toolName"], request.get("toolArgs") or {}
        command = args.get("command", "") if isinstance(args, dict) else ""
        if name == "ask_user":
            return {"permissionDecision": "allow"}
        if name in {"view", "read", "rg", "glob", "grep"}:
            return {"permissionDecision": "allow"}
        if name in {"bash", "shell", "run_in_terminal"} and command == TEST_COMMAND:
            if isinstance(args, dict) and any(
                args.get(key) not in (None, str(self.working_directory))
                for key in ("cwd", "workdir", "working_directory")
            ):
                return {
                    "permissionDecision": "deny",
                    "permissionDecisionReason": "Focused tests must run in the reviewed checkout.",
                }
            # This gates the agent's shell request, not subprocesses launched
            # by the tests; only run reviewed tests in this trusted checkout.
            return {"permissionDecision": "allow"}
        if name in {"bash", "shell", "run_in_terminal"}:
            self.output("[policy] blocked shell command")
            return {
                "permissionDecision": "deny",
                "permissionDecisionReason": "Only the focused pytest command is permitted; no push, release or publish.",
            }
        return {"permissionDecision": "ask"}

    def permission(self, request, _invocation):
        # Copilot asks this handler before writing; resolved paths prevent a
        # relative or symlinked path from silently escaping the three-file scope.
        if request.kind == "read":
            return PermissionDecisionApproveOnce()
        if request.kind == "custom-tool" and request.tool_name == "ask_user":
            return PermissionDecisionApproveOnce()
        if (
            request.kind == "shell"
            and request.full_command_text == TEST_COMMAND
            and (
                request.resolved_working_directory is None
                or Path(request.resolved_working_directory).resolve() == self.working_directory
            )
        ):
            return PermissionDecisionApproveOnce()
        if request.kind == "write":
            allowed = {
                self.working_directory / name
                for name in ALLOWED_FILES
            }
            path = Path(request.resolved_path or request.file_name).resolve()
            if path in allowed and not path.is_symlink():
                return PermissionDecisionApproveOnce()
            self.output("[permission] write outside approved files")
            if self.ask(f"Allow writing {path}? [yes/no] ").strip().lower() == "yes":
                return PermissionDecisionApproveOnce()
        return PermissionDecisionReject(feedback="Permission denied by the demo's human policy.")

    def elicit(self, context: ElicitationContext) -> ElicitationResult:
        # ask_user_variant="elicitation" routes the model's question to this
        # callback; the selected answer returns directly to the same agent loop.
        #
        # Elicitation (wywołanie) asks, “Which behavior do you choose?”, 
        # while permission asks, “Is this operation allowed?”
        self.output("[elicitation] zero-units semantics:")
        for key, description in CHOICES.items():
            self.output(f"  {key}: {description}")
        answer = self.ask("Choose reject, zero_cost or keep_raising: ").strip()
        if answer not in CHOICES:
            self.output("[elicitation] invalid choice; request declined")
            return {"action": "decline"}
        schema = context.get("requestedSchema", {})
        properties = schema.get("properties", {})
        if not properties:
            self.output("[elicitation] missing form fields; request declined")
            return {"action": "decline"}
        field = next(iter(properties))
        return {"action": "accept", "content": {field: answer}}

    def post_tool_failure(self, request: dict, _context: dict) -> dict | None:
        if request["toolName"] in {"bash", "shell", "run_in_terminal"}:
            # The runtime returns this context to the model alongside the failed
            # tool result, so the model can fix a red test without a second send.
            return {"additionalContext": "The focused TestZeroUnitsWithTotalCost failed. Read its tool result, fix the code and rerun it."}
        return None

    def show_event(self, event: SessionEvent) -> None:
        if event.type in {
            SessionEventType.TOOL_EXECUTION_START,
            SessionEventType.TOOL_EXECUTION_COMPLETE,
            SessionEventType.SESSION_IDLE,
        }:
            print_event(event, self.output)
        if event.type == SessionEventType.TOOL_EXECUTION_COMPLETE:
            self.output(f"[tool] {getattr(event.data, 'tool_name', 'unknown')} success={getattr(event.data, 'success', False)}")

    async def execute(self, configuration: DemoConfiguration) -> None:
        self.validate(configuration)
        show_disabled_mcp_servers(self.output)
        # Pin the installed CLI instead of the SDK-downloaded runtime so the
        # elicitation protocol matches the CLI version checked by the presenter.
        # CLI login is reused; exiting the context closes the runtime on failure.
        async with CopilotRuntime(environment=self.environment, output=self.output).create_client() as client:
            # Hooks act before and after SDK tool calls, while permissions and
            # elicitation are runtime callbacks, not a hand-written agent loop.
            async with await client.create_session(
                model=configuration.model,
                working_directory=str(self.working_directory),
                # Matching MCP servers are blocked before startup/authentication
                # for this session, without changing CLI-wide settings.
                disabled_mcp_servers=list(DISABLED_MCP_SERVERS),
                hooks=cast(Any, {
                    "on_pre_tool_use": self.pre_tool_use,
                    "on_post_tool_use_failure": self.post_tool_failure,
                }),
                on_permission_request=self.permission,
                # Register only structured elicitation; a legacy input handler
                # would also enable the older requestUserInput protocol.
                ask_user_variant="elicitation",
                on_elicitation_request=self.elicit,
                on_event=self.show_event,
            ) as session:
                self.output(f"[session] {session.session_id}")
                # A single prompt lets Copilot invoke tools, ask the person and
                # continue with the answer before session.idle is reached.
                response = await session.send_and_wait(
                    configuration.prompt, timeout=configuration.timeout_seconds
                )
                if response is None or not isinstance(response.data, AssistantMessageData):
                    raise RuntimeError("Copilot reached idle without a final answer.")
                self.output(f"Copilot response:\n{response.data.content}")

    def run(self, configuration: DemoConfiguration) -> int:
        try:
            asyncio.run(self.execute(configuration))
        except (ConfigurationError, RuntimeSetupError) as error:
            self.error_output(f"Configuration error: {error}")
            return 2
        except KeyboardInterrupt:
            self.error_output("Cancelled.")
            return 130
        except OSError as error:
            if getattr(error, "winerror", None) == 193:
                self.error_output(
                    "Copilot runtime is not a valid Windows executable (WinError 193). "
                    "Set COPILOT_CLI_PATH to a Windows copilot.exe matching this machine's "
                    "architecture; verify it with `& $env:COPILOT_CLI_PATH --version`."
                )
            else:
                self.error_output(f"Copilot session failed: {error}")
            return 1
        except Exception as error:
            self.error_output(f"Copilot session failed: {error}")
            return 1
        return 0


def main() -> int:
    return HumanPolicyApplication(environment=os.environ).run(CONFIGURATION)


if __name__ == "__main__":
    raise SystemExit(main())
