"""Shared CLI startup, MCP denylist, and safe event output for the demos."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Mapping

if TYPE_CHECKING:
    from copilot import CopilotClient
    from copilot.session_events import SessionEvent

DISABLED_MCP_SERVERS = (
    "azure",
    "azure-devops",
    "azure-devops-mcp-server",
    "azure-mcp-server",
    "github",
    "github-mcp-server",
    "io.github.github/github-mcp-server",
    "microsoft/playwright-mcp",
    "microsoftdocs/mcp",
    "playwright",
    "tavily",
    "workiq",
    "webiq",
    "computer-use"
)


def show_disabled_mcp_servers(
    output: Callable[[str], None], *, cli: bool = False,
) -> None:
    # Exact-name blocking is session/CLI-run scoped, never a global config edit.
    scope = "CLI run" if cli else "session"
    output(f"MCP server names disabled for this {scope}: " + ", ".join(DISABLED_MCP_SERVERS))


def print_event(
    event: SessionEvent, output: Callable[[str], None], *, symbolic: bool = False,
) -> None:
    # Event payloads may contain prompts, tool results or credentials. Only the
    # SDK's symbolic/wire names belong in this shared presentation output.
    name = event.type.value
    label = f"{event.type.name} -> {name}" if symbolic else name
    output(f"[event] {label}")


class RuntimeSetupError(ValueError):
    """The installed Copilot CLI cannot be launched with the supplied environment."""


class CopilotRuntime:
    def __init__(
        self,
        *,
        environment: Mapping[str, str],
        output: Callable[[str], None] = print,
    ) -> None:
        self.environment = dict(environment)
        self.output = output

    def resolve_cli(self) -> str:
        selected = self.environment.get("COPILOT_CLI_PATH") or "copilot"
        path = (
            str(Path(selected).resolve())
            if Path(selected).is_file()
            else shutil.which(selected, path=self.environment.get("PATH", os.defpath))
        )
        if path is None:
            raise RuntimeSetupError(
                "Copilot CLI is missing or COPILOT_CLI_PATH is invalid. "
                "Install Copilot CLI and run `copilot login`; "
                "set COPILOT_CLI_PATH to its executable if it is not on PATH."
            )
        if sys.platform == "win32" and Path(path).suffix.lower() not in {".exe", ".js"}:
            launcher = Path(path)
            if (
                launcher.name.lower() in {"copilot", "copilot.ps1", "copilot.bat"}
                and tuple(part.lower() for part in launcher.parent.parts[-3:])
                == ("globalstorage", "github.copilot-chat", "copilotcli")
            ):
                # VS Code's bootstrapper finds a separately installed CLI.
                # SDK/ACP stdio must launch it directly, without a shell wrapper.
                search_path = os.pathsep.join(
                    entry for entry in self.environment.get("PATH", os.defpath).split(os.pathsep)
                    if Path(entry.strip('"')).resolve() != launcher.parent.resolve()
                )
                executable = shutil.which("copilot.exe", path=search_path)
                if executable is None:
                    raise RuntimeSetupError(
                        f"VS Code Copilot launcher {path} has no native copilot.exe on PATH. "
                        "Install the Windows Copilot CLI and run `copilot login`."
                    )
                self.output(f"VS Code Copilot launcher: {path}; using installed CLI: {executable}")
                return executable
            raise RuntimeSetupError(
                f"Unsupported Copilot launcher: {path}. "
                "On Windows, COPILOT_CLI_PATH must select copilot.exe or the CLI's "
                ".js entry point (requires Node.js), not a .cmd/.bat/PowerShell launcher."
            )
        return path

    def prepare_environment(self) -> dict[str, str]:
        environment = dict(self.environment)
        cli = self.resolve_cli()
        # Child SDKs (including a CLI extension's client) must reuse this runtime,
        # not inherit VS Code's bootstrapper or download another SDK runtime.
        environment["COPILOT_CLI_PATH"] = cli
        self.output(f"Copilot CLI: {cli}")
        return environment

    def command(self, cli: str) -> list[str]:
        if Path(cli).suffix.lower() == ".js":
            node = shutil.which("node", path=self.environment.get("PATH", os.defpath))
            if node is None:
                raise RuntimeSetupError("Node.js is required for the Copilot CLI .js entry point.")
            return [node, cli]
        return [cli]

    def create_client(self, *, use_logged_in_user: bool = True) -> CopilotClient:
        from copilot import CopilotClient, RuntimeConnection

        environment = self.prepare_environment()
        cli = environment["COPILOT_CLI_PATH"]
        self.command(cli)  # Validate Node.js before the SDK tries a .js entry point.
        # Explicit stdio pins the installed CLI. The caller chooses whether CLI
        # GitHub login is allowed (False for BYOK) and owns start/stop or context exit.
        return CopilotClient(
            connection=RuntimeConnection.for_stdio(path=cli),
            env=environment,
            use_logged_in_user=use_logged_in_user,
        )
