#!/usr/bin/env python3
"""Compare GitHub login and BYOK authentication for the Copilot SDK."""

from __future__ import annotations

import asyncio
import json
import os #aaaa
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from copilot_runtime import CopilotRuntime, DISABLED_MCP_SERVERS, print_event, show_disabled_mcp_servers

DEFAULT_PROMPT = "Reply with exactly: Authentication works."
GITHUB_TOKEN_VARIABLES = (
    "COPILOT_GITHUB_TOKEN",
    "GH_TOKEN",
    "GITHUB_TOKEN",
)


@dataclass(frozen=True)
class DemoConfiguration:
    operation: str = "status"
    authentication: str = "logged-in"
    model: str = "auto"
    prompt: str = DEFAULT_PROMPT
    dry_run: bool = True
    provider_type: str = "openai"
    provider_base_url: str = "https://api.openai.com/v1"
    provider_wire_api: str = "completions"
    api_key_variable: str | None = "COPILOT_BYOK_API_KEY"
    azure_api_version: str | None = None


CONFIGURATION = DemoConfiguration(
    operation="request",
    authentication="logged-in",
    model="auto",
    prompt=DEFAULT_PROMPT,
    dry_run=False,
)


class ConfigurationError(ValueError):
    """Raised when the selected authentication mode is incomplete."""


class CopilotSdkAdapter:
    """Isolate lazy SDK imports and runtime construction from application logic."""

    def __init__(self, runtime: CopilotRuntime) -> None:
        self.runtime = runtime

    @staticmethod
    def _missing_sdk(error: ModuleNotFoundError) -> ConfigurationError:
        return ConfigurationError(
            "github-copilot-sdk is not installed; rebuild the dev container or run "
            "`pip install github-copilot-sdk`."
        )

    def event_types(self) -> tuple[Any, ...]:
        try:
            # Reading the SDK enum keeps the demo aligned when new runtime events ship.
            from copilot.session_events import SessionEventType
        except ModuleNotFoundError as error:
            raise self._missing_sdk(error) from error

        return tuple(SessionEventType)

    def create_client(self, *, use_logged_in_user: bool) -> Any:
        try:
            # Preserve the authentication choice while sharing executable selection.
            return self.runtime.create_client(use_logged_in_user=use_logged_in_user)
        except ModuleNotFoundError as error:
            raise self._missing_sdk(error) from error

    def approve_all_permissions(self) -> Any:
        try:
            from copilot.session import PermissionHandler
        except ModuleNotFoundError as error:
            raise self._missing_sdk(error) from error

        return PermissionHandler.approve_all


class AuthDemoApplication:
    """Coordinate authentication demo operations through replaceable boundaries."""

    def __init__(
        self,
        *,
        environ: Mapping[str, str] | None = None,
        sdk: CopilotSdkAdapter | None = None,
        command_locator: Callable[[str], str | None] = shutil.which,
        output: Callable[[str], None] = print,
        error_output: Callable[[str], None] | None = None,
    ) -> None:
        self.environ = os.environ if environ is None else environ
        self.sdk = (
            CopilotSdkAdapter(CopilotRuntime(environment=self.environ, output=output))
            if sdk is None else sdk
        )
        self.command_locator = command_locator
        self.output = output
        self.error_output = error_output or (
            lambda message: print(message, file=sys.stderr)
        )
        self.mcp_server_statuses: dict[str, str] = {}

    def copilot_home(self) -> Path:
        return Path(self.environ.get("COPILOT_HOME", "~/.copilot")).expanduser()

    def has_stored_login(self) -> bool:
        config_path = self.copilot_home() / "config.json"
        try:
            config_text = config_path.read_text(encoding="utf-8")
            # Copilot CLI owns this file and may prefix its JSON with // comments.
            config = json.loads(
                "\n".join(
                    line
                    for line in config_text.splitlines()
                    if not line.lstrip().startswith("//")
                )
            )
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return False

        return bool(config.get("loggedInUsers") or config.get("lastLoggedInUser"))

    def show_status(self, api_key_variable: str | None) -> None:
        self.output("GitHub Copilot authentication status")
        cli_status = "found" if self.command_locator("copilot") else "not found"
        self.output(f"  Copilot CLI: {cli_status}")
        for variable in GITHUB_TOKEN_VARIABLES:
            state = "set" if self.environ.get(variable) else "not set"
            self.output(f"  {variable}: {state}")
        login_state = "detected" if self.has_stored_login() else "not detected"
        self.output(f"  Stored Copilot login: {login_state}")
        if api_key_variable is None:
            self.output("  BYOK API key: not required")
            return
        key_state = "set" if self.environ.get(api_key_variable) else "not set"
        self.output(f"  {api_key_variable}: {key_state}")

    def print_event_placeholder(self, event: Any) -> None:
        print_event(event, self.output, symbolic=True)
        if event.type.value == "session.mcp_servers_loaded":
            for server in getattr(getattr(event, "data", None), "servers", ()):
                name = getattr(server, "name", None)
                status = getattr(getattr(server, "status", None), "value", None)
                if isinstance(name, str) and isinstance(status, str):
                    self.mcp_server_statuses[name] = status

    def show_event_catalog(self) -> None:
        event_types = self.sdk.event_types()
        self.output(f"GitHub Copilot SDK session events ({len(event_types)})")
        for event_type in event_types:
            self.output(f"  {event_type.name} -> {event_type.value}")

    @staticmethod
    def validate_configuration(configuration: DemoConfiguration) -> None:
        if configuration.operation not in {"status", "events", "request"}:
            raise ConfigurationError(
                "operation must be 'status', 'events', or 'request'."
            )
        if configuration.operation != "request":
            return
        if configuration.authentication not in {"logged-in", "byok"}:
            raise ConfigurationError(
                "authentication must be 'logged-in' or 'byok'."
            )
        if not configuration.model:
            raise ConfigurationError("model must not be empty.")
        if configuration.authentication == "byok":
            if configuration.provider_type not in {"openai", "azure", "anthropic"}:
                raise ConfigurationError(
                    "provider_type must be 'openai', 'azure', or 'anthropic'."
                )
            if not configuration.provider_base_url:
                raise ConfigurationError("provider_base_url must not be empty.")
            if configuration.provider_wire_api not in {"completions", "responses"}:
                raise ConfigurationError(
                    "provider_wire_api must be 'completions' or 'responses'."
                )

    def build_byok_provider(
        self, configuration: DemoConfiguration
    ) -> dict[str, Any]:
        # The runtime uses this provider schema to route model calls away from the
        # default Copilot service and speak the endpoint's selected wire protocol.
        provider: dict[str, Any] = {
            "type": configuration.provider_type,
            "base_url": configuration.provider_base_url,
            "wire_api": configuration.provider_wire_api,
        }

        if configuration.api_key_variable is not None:
            api_key = self.environ.get(configuration.api_key_variable)
            if not api_key:
                raise ConfigurationError(
                    f"Set {configuration.api_key_variable}, or set api_key_variable "
                    "to None for a local provider that does not require a key."
                )
            provider["api_key"] = api_key

        if configuration.azure_api_version:
            if configuration.provider_type != "azure":
                raise ConfigurationError(
                    "azure_api_version requires provider_type='azure'."
                )
            provider["azure"] = {"api_version": configuration.azure_api_version}

        return provider

    def print_configuration(
        self,
        *,
        mode: str,
        model: str,
        provider: Mapping[str, Any] | None = None,
    ) -> None:
        self.output(f"Authentication: {mode}")
        self.output(f"Model: {model}")
        show_disabled_mcp_servers(self.output)
        if provider:
            self.output(f"Provider type: {provider['type']}")
            self.output(f"Provider URL: {provider['base_url']}")
            self.output(f"Wire API: {provider['wire_api']}")
            key_state = "configured" if provider.get("api_key") else "not required"
            self.output(f"API key: {key_state}")

    async def run_request(
        self,
        *,
        model: str,
        prompt: str,
        use_logged_in_user: bool,
        provider: Mapping[str, Any] | None = None,
    ) -> None:
        self.output(f"Prompt: {prompt}")
        async with self.sdk.create_client(
            use_logged_in_user=use_logged_in_user
        ) as client:
            session_options: dict[str, Any] = {
                "model": model,
                # Auto-approval keeps this disposable demo moving; production hosts
                # should inspect each runtime permission request before deciding.
                "on_permission_request": self.sdk.approve_all_permissions(),
                # The SDK matches exact names and prevents matching MCP servers
                # from starting/authenticating in this session; this is not a
                # wildcard or a change to the CLI's global configuration.
                "disabled_mcp_servers": list(DISABLED_MCP_SERVERS),
                # The callback observes every emitted SDK event while deliberately
                # omitting payloads that could contain sensitive session data.
                "on_event": self.print_event_placeholder,
            }
            if provider is not None:
                # Supplying provider redirects this session's model calls to BYOK.
                session_options["provider"] = dict(provider)

            # A Copilot session owns conversation state and coordinates the runtime's
            # model turns, tool executions, permission requests, and event stream.
            async with await client.create_session(**session_options) as session:
                # The SDK still delivers events while waiting and returns after the
                # runtime emits session.idle, with the final assistant message if any.
                response = await session.send_and_wait(prompt)

        if response is None:
            # An idle session can legitimately have no final assistant message event.
            self.output("Copilot completed without an assistant message.")
            return

        self.output("")
        self.output("Copilot response:")
        self.output(response.data.content)

    async def execute(self, configuration: DemoConfiguration) -> None:
        self.validate_configuration(configuration)

        if configuration.operation == "status":
            self.show_status(configuration.api_key_variable)
            return

        if configuration.operation == "events":
            self.show_event_catalog()
            return

        if configuration.authentication == "logged-in":
            self.print_configuration(
                mode="saved GitHub login", model=configuration.model
            )
            if not configuration.dry_run:
                await self.run_request(
                    model=configuration.model,
                    prompt=configuration.prompt,
                    use_logged_in_user=True,
                )
            return

        provider = self.build_byok_provider(configuration)
        self.print_configuration(
            mode="BYOK", model=configuration.model, provider=provider
        )
        if not configuration.dry_run:
            await self.run_request(
                model=configuration.model,
                prompt=configuration.prompt,
                use_logged_in_user=False,
                provider=provider,
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
            self.error_output(f"Copilot request failed: {error}")
            return 1
        return 0


def main() -> int:
    return AuthDemoApplication().run(CONFIGURATION)


if __name__ == "__main__":
    raise SystemExit(main())