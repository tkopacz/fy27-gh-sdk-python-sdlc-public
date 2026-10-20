from __future__ import annotations

import importlib.util
import os
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

from copilot.session_events import SessionEventType

MODULE_PATH = Path(__file__).with_name("main.py")
MODULE_SPEC = importlib.util.spec_from_file_location("auth_demo", MODULE_PATH)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
auth_demo = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules[MODULE_SPEC.name] = auth_demo
MODULE_SPEC.loader.exec_module(auth_demo)

LIVE_PROMPT = "Reply with exactly this text and nothing else: LIVE_COPILOT_SDK_OK"
EXPECTED_RESPONSE = "LIVE_COPILOT_SDK_OK"


class TestAuthDemoIntegration:
    def setup_method(self) -> None:
        self.output: list[str] = []
        self.errors: list[str] = []
        self.application = auth_demo.AuthDemoApplication(
            output=self.output.append,
            error_output=self.errors.append,
        )

    @staticmethod
    def make_configuration(**changes: Any) -> Any:
        return replace(auth_demo.CONFIGURATION, **changes)

    def test_installed_sdk_exposes_its_real_event_catalog(self) -> None:
        # The events operation reads the installed SDK's catalog without starting
        # a session, so the output reflects the event names this SDK can emit.
        exit_code = self.application.run(
            self.make_configuration(operation="events")
        )

        rendered = "\n".join(self.output)
        assert exit_code == 0, "\n".join(self.errors)
        assert f"GitHub Copilot SDK session events ({len(SessionEventType)})" in rendered
        for event_type in SessionEventType:
            assert f"{event_type.name} -> {event_type.value}" in rendered

    def test_status_inspects_the_real_cli_environment_without_exposing_secrets(
        self,
    ) -> None:
        exit_code = self.application.run(
            self.make_configuration(operation="status")
        )

        rendered = "\n".join(self.output)
        assert exit_code == 0, "\n".join(self.errors)
        assert "Copilot CLI: found" in rendered
        for variable in (*auth_demo.GITHUB_TOKEN_VARIABLES, "COPILOT_BYOK_API_KEY"):
            secret = os.environ.get(variable)
            if secret:
                assert secret not in rendered

    def test_invalid_program_configuration_is_rejected(self) -> None:
        exit_code = self.application.run(
            self.make_configuration(operation="unsupported")
        )

        assert exit_code == 2
        assert "operation" in self.errors[0]

    def test_real_github_login_completes_a_copilot_sdk_request(self) -> None:
        # `logged-in` reuses Copilot CLI authentication, `auto` delegates model
        # selection, and disabling dry-run makes the runtime send the prompt.
        # SESSION_START and SESSION_IDLE below show the real session completed.
        exit_code = self.application.run(
            self.make_configuration(
                operation="request",
                authentication="logged-in",
                model="auto",
                prompt=LIVE_PROMPT,
                dry_run=False,
            )
        )

        failure = (
            "The live GitHub Copilot SDK request failed. A VS Code Copilot login "
            "does not authenticate Copilot CLI. Verify CLI authentication with "
            "`copilot -p 'Reply with OK' --silent`; if needed, run `copilot login`, "
            "confirm that the account has a Copilot subscription, and retry.\n"
            + "\n".join(self.errors)
        )
        rendered = "\n".join(self.output)
        assert exit_code == 0, failure
        assert "[event] SESSION_START" in rendered
        assert "[event] SESSION_IDLE" in rendered
        assert f"Prompt: {LIVE_PROMPT}" in rendered
        assert "Copilot response:" in rendered
        assert EXPECTED_RESPONSE in rendered
        assert "MCP server names disabled for this session:" in rendered
        active_denied_servers = {
            name: status
            for name, status in self.application.mcp_server_statuses.items()
            if name in auth_demo.DISABLED_MCP_SERVERS
            and status not in {"disabled", "not_configured", "stopped"}
        }
        assert not active_denied_servers, (
            "The live SDK session reported denylisted MCP servers as active: "
            f"{active_denied_servers}"
        )