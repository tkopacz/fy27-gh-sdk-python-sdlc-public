from __future__ import annotations

import importlib.util
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("main.py")
MODULE_SPEC = importlib.util.spec_from_file_location("initial_session_demo", MODULE_PATH)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
initial_session_demo = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules[MODULE_SPEC.name] = initial_session_demo
MODULE_SPEC.loader.exec_module(initial_session_demo)


class TestInitialSessionIntegration:
    def setup_method(self) -> None:
        self.output: list[str] = []
        self.errors: list[str] = []
        self.application = initial_session_demo.InitialSessionApplication(
            output=self.output.append,
            error_output=self.errors.append,
        )

    @staticmethod
    def repository_status(repository: Path) -> str:
        result = subprocess.run(
            ["git", "-C", str(repository), "status", "--short"],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout

    def test_missing_repository_fails_with_setup_guidance(self) -> None:
        missing_repository = MODULE_PATH.parent / "workspace-not-prepared"
        configuration = replace(
            initial_session_demo.CONFIGURATION,
            working_directory=missing_repository,
        )

        exit_code = self.application.run(configuration)

        assert exit_code == 2
        assert "Prepare the pinned Beancount clone" in self.errors[0]

    def test_real_agent_reads_the_pinned_repository_without_changing_it(self) -> None:
        repository = initial_session_demo.CONFIGURATION.working_directory
        before = self.repository_status(repository)

        # This configuration starts a real CLI-backed session, lets `auto` choose
        # the model, and anchors built-in file tools to the pinned checkout. The
        # events below expose the agent loop; the final status check confirms that
        # the prompt's read-only instruction was honored before cleanup.
        exit_code = self.application.run(initial_session_demo.CONFIGURATION)

        failure = (
            "The live GitHub Copilot SDK session failed. Verify network access, "
            "an active Copilot subscription, and CLI authentication with "
            "`copilot -p 'Reply with OK' --silent`.\n"
            + "\n".join(self.errors)
        )
        rendered = "\n".join(self.output)
        assert exit_code == 0, failure
        assert (
            "MCP server names disabled for this session: "
            + ", ".join(initial_session_demo.DISABLED_MCP_SERVERS)
        ) in rendered
        assert "Model: auto" in rendered
        assert "[event] session.start" in rendered
        assert "[event] tool.execution_start" in rendered
        assert "[event] tool.execution_complete" in rendered
        assert "[event] session.idle" in rendered
        assert "[lifecycle] Session closed" in rendered
        assert "[lifecycle] Copilot client closed" in rendered
        assert "Copilot response:" in rendered
        assert self.repository_status(repository) == before
