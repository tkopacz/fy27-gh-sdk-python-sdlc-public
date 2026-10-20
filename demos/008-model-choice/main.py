#!/usr/bin/env python3
"""Compare model choices through the same GitHub Copilot SDK agent harness."""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Callable, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from copilot_runtime import CopilotRuntime, DISABLED_MCP_SERVERS, print_event, show_disabled_mcp_servers

from copilot import CopilotClient, PermissionHandler
from copilot.session_events import (
    AssistantMessageData,
    AssistantUsageData,
    SessionEvent,
    SessionEventType,
    SessionUsageCheckpointData,
)

DEMO_DIRECTORY = Path(__file__).resolve().parent
REPOSITORY_ROOT = DEMO_DIRECTORY.parents[1]
REVIEW_FILE = Path("demos/003-custom-tool/fixtures/beancount-1048.json")
DEFAULT_PROMPT = """Przeczytaj demos/003-custom-tool/fixtures/beancount-1048.json.
Zaproponuj dokładnie trzy przypadki brzegowe do testów poprawki
wpisów `0 HOOL {{20.00 USD}}`. Każdy przypadek opisz jako działanie, oczekiwany wynik i
uzasadnienie wynikające z kryteriów akceptacji. Niczego nie edytuj i nie
uruchamiaj poleceń."""


@dataclass(frozen=True)
class ModelChoice:
    model_id: str
    role: str


MODEL_CHOICES = (
    # ModelChoice(model_id="gpt-5.5", role="efektywność"),
    ModelChoice(model_id="gpt-6.1-sol", role="efektywność"),
    ModelChoice(model_id="gpt-6-astra", role="analiza"),
    ModelChoice(model_id="claude-opus-5.5", role="głębsza analiza"),
    ModelChoice(model_id="auto", role="auto"),
)


@dataclass(frozen=True)
class DemoConfiguration:
    working_directory: Path = REPOSITORY_ROOT
    models: tuple[ModelChoice, ...] = MODEL_CHOICES
    prompt: str = DEFAULT_PROMPT
    timeout_seconds: float = 180.0


CONFIGURATION = DemoConfiguration()


class ConfigurationError(ValueError):
    """The requested comparison cannot run with the local setup."""


class ModelChoiceApplication:
    """Run the same read-only task in separate sessions using selected models."""

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
    def validate_configuration(configuration: DemoConfiguration) -> Path:
        if not configuration.prompt.strip():
            raise ConfigurationError("prompt must not be empty.")
        if configuration.timeout_seconds <= 0:
            raise ConfigurationError("timeout_seconds must be greater than zero.")
        if len(configuration.models) < 2:
            raise ConfigurationError("At least two models are required.")
        model_ids = [choice.model_id.strip() for choice in configuration.models]
        if any(not model_id for model_id in model_ids):
            raise ConfigurationError("model IDs must not be empty.")
        if len(set(model_ids)) != len(model_ids):
            raise ConfigurationError("model IDs must be unique.")

        working_directory = configuration.working_directory.resolve()
        if not (working_directory / REVIEW_FILE).is_file():
            raise ConfigurationError(
                "Run this demo from a checkout containing "
                + str(REVIEW_FILE)
                + "."
            )
        return working_directory

    @staticmethod
    def format_aiu(total_nano_aiu: Decimal) -> str:
        aiu = total_nano_aiu / Decimal("1000000000")
        return format(aiu.normalize(), "f") if aiu else "0"

    def show_event(
        self,
        event: SessionEvent,
        used_models: list[str],
        usage_nano_aiu: list[Decimal | None],
    ) -> None:
        print_event(event, self.output)
        if (
            event.type == SessionEventType.ASSISTANT_USAGE
            and isinstance(event.data, AssistantUsageData)
        ):
            if event.data.model not in used_models:
                # Usage events report the resolved model for each API call,
                # unlike the requested "auto" selection in the session config.
                used_models.append(event.data.model)
            copilot_usage = event.data.copilot_usage
            if copilot_usage is None:
                usage_nano_aiu.append(None)
                self.output(
                    f"[usage] model={event.data.model} AIU=not reported by runtime"
                )
            else:
                nano_aiu = Decimal(str(copilot_usage.total_nano_aiu))
                usage_nano_aiu.append(nano_aiu)
                self.output(
                    f"[usage] model={event.data.model} "
                    f"AIU={self.format_aiu(nano_aiu)}"
                )
        elif (
            event.type == SessionEventType.SESSION_USAGE_CHECKPOINT
            and isinstance(event.data, SessionUsageCheckpointData)
        ):
            # The CLI emits a durable accounting snapshot for the whole session.
            # Unlike assistant.usage, total_nano_aiu here is cumulative, not the
            # charge for one API call. Never add successive checkpoints together
            # or append them to usage_nano_aiu: that would count usage twice.
            # On resume, this snapshot can include usage from earlier turns;
            # it must not be presented as the cost of just the latest response.
            # Show the raw SDK unit and its AIU conversion separately from the
            # per-response sum. This conversion alone does not establish AIC or
            # a dollar amount. Only numeric accounting data leaves this handler.
            nano_aiu = Decimal(str(event.data.total_nano_aiu))
            self.output(
                f"[usage checkpoint] session total nano_aiu={nano_aiu}; "
                f"AIU={self.format_aiu(nano_aiu)}"
            )

    @staticmethod
    def validate_available_models(
        choices: tuple[ModelChoice, ...], available_ids: set[str]
    ) -> None:
        missing = [
            choice.model_id
            for choice in choices
            if choice.model_id not in available_ids
        ]
        if missing:
            raise ConfigurationError(
                "Selected models are unavailable: "
                + ", ".join(missing)
                + ". Choose IDs from the available-model list above."
            )

    async def compare_model(
        self,
        client: CopilotClient,
        configuration: DemoConfiguration,
        working_directory: Path,
        choice: ModelChoice,
    ) -> tuple[str, tuple[str, ...], Decimal | None]:
        self.output(f"\n[model] {choice.role}: {choice.model_id}")
        show_disabled_mcp_servers(self.output)
        used_models: list[str] = []
        usage_nano_aiu: list[Decimal | None] = []
        # Each choice gets a fresh SDK session, but keeps the same prompt,
        # repository context, Copilot runtime and read-only tool allowlist.
        async with await client.create_session(
            model=choice.model_id,
            working_directory=str(working_directory),
            available_tools=["grep", "view"],
            # Exact matches are prevented from starting/authenticating in this
            # session, without changing CLI-wide settings.
            disabled_mcp_servers=list(DISABLED_MCP_SERVERS),
            # The allowlist excludes file writes and shell commands. Approving
            # the remaining read-only requests keeps this comparison repeatable.
            on_permission_request=PermissionHandler.approve_all,
            on_event=lambda event: self.show_event(
                event, used_models, usage_nano_aiu
            ),
        ) as session:
            self.output(f"[lifecycle] Session created: {session.session_id}")
            # send_and_wait preserves the SDK event stream and returns when the
            # full model-and-tool loop reaches session.idle.
            response = await session.send_and_wait(
                configuration.prompt,
                timeout=configuration.timeout_seconds,
            )
            if response is None or not isinstance(response.data, AssistantMessageData):
                raise RuntimeError(
                    f"{choice.model_id} reached session.idle without a final "
                    "assistant message."
                )
            content = response.data.content
            actual_models = tuple(used_models)
            if (
                not actual_models
                and response.data.model
                and response.data.model.lower() != "auto"
            ):
                actual_models = (response.data.model,)
            total_nano_aiu = (
                sum(
                    (value for value in usage_nano_aiu if value is not None),
                    start=Decimal(0),
                )
                if usage_nano_aiu and all(value is not None for value in usage_nano_aiu)
                else None
            )
        self.output("[lifecycle] Session closed")
        return content, actual_models, total_nano_aiu

    async def execute(self, configuration: DemoConfiguration) -> None:
        working_directory = self.validate_configuration(configuration)
        self.output(f"Working directory: {working_directory}")
        self.output("Read-only tools: grep, view")

        # One client owns the Copilot CLI runtime and reuses CLI-managed GitHub
        # authentication for both model-specific sessions.
        async with self.runtime.create_client() as client:
            self.output("[lifecycle] Copilot CLI runtime connected")
            # Runtime availability is account- and policy-specific; showing it
            # makes model choice concrete and prevents unsupported IDs silently
            # becoming a different comparison.
            available_models = await client.list_models()
            available_ids = {model.id for model in available_models}
            self.output("Available models:")
            for model in available_models:
                self.output(f"  {model.id} — {model.name}")
            self.validate_available_models(configuration.models, available_ids)

            self.output(f"Prompt:\n{configuration.prompt}")
            for choice in configuration.models:
                response, actual_models, total_nano_aiu = await self.compare_model(
                    client, configuration, working_directory, choice
                )
                actual_model_label = ", ".join(actual_models) or "not reported by runtime"
                aiu_label = (
                    self.format_aiu(total_nano_aiu)
                    if total_nano_aiu is not None
                    else "not fully reported by runtime"
                )
                self.output(
                    f"[response] requested={choice.model_id}; "
                    f"actual model={actual_model_label}; "
                    f"AIU={aiu_label}:\n{response}"
                )

        self.output("[lifecycle] Copilot client closed")
        self.output(
            "\nCompare how each model handles the same evidence and acceptance "
            "criteria. This is a live demonstration, not a benchmark."
        )

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
            self.error_output(f"Copilot model comparison failed: {error}")
            return 1
        return 0


def main() -> int:
    return ModelChoiceApplication().run(CONFIGURATION)


if __name__ == "__main__":
    raise SystemExit(main())
