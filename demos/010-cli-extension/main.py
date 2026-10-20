"""Launch the real Copilot CLI with a project-scoped extension in a scratch repo."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable, Iterator, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from copilot_runtime import CopilotRuntime, RuntimeSetupError, DISABLED_MCP_SERVERS, show_disabled_mcp_servers

EXTENSION_SOURCE = Path(__file__).with_name("extension.mjs")


class SetupError(ValueError):
    """A required local CLI demo prerequisite is missing."""


class CliExtensionApplication:
    def __init__(
        self,
        *,
        environment: Mapping[str, str],
        extension_source: Path = EXTENSION_SOURCE,
        output: Callable[[str], None] = print,
        error_output: Callable[[str], None] | None = None,
    ) -> None:
        self.environment = dict(environment)
        self.extension_source = extension_source
        self.output = output
        self.error_output = error_output or (lambda text: print(text, file=sys.stderr))

    def validate(self) -> dict[str, str]:
        runtime = CopilotRuntime(environment=self.environment, output=self.output)
        self.environment = runtime.prepare_environment()
        programs: dict[str, str] = {"copilot": self.environment["COPILOT_CLI_PATH"]}
        for name in ("node", "git"):
            path = shutil.which(name, path=self.environment.get("PATH", ""))
            if path is None:
                raise SetupError(f"Missing {name} on PATH. See this demo's README prerequisites.")
            programs[name] = path
        if not self.extension_source.is_file():
            raise SetupError(f"Missing extension source: {self.extension_source}")
        return programs

    @contextmanager
    def workspace(self, git: str) -> Iterator[Path]:
        with TemporaryDirectory(prefix="copilot-cli-extension-") as directory:
            root = Path(directory)
            subprocess.run(
                [git, "init", "--quiet", str(root)], env=self.environment, check=True,
            )
            # CLI discovers extensions relative to the Git root, not the demo's
            # directory inside a larger repository. Install only in this scratch repo.
            destination = root / ".github" / "extensions" / "demo-observer"
            destination.mkdir(parents=True)
            shutil.copyfile(self.extension_source, destination / "extension.mjs")
            yield root

    def run(self) -> int:
        try:
            programs = self.validate()
            if not sys.stdin.isatty() or not sys.stdout.isatty():
                raise SetupError(
                    "An interactive terminal is required: /demo is a CLI slash command, "
                    "not a prompt for copilot -p."
                )
            with self.workspace(programs["git"]) as root:
                self.output(f"Temporary demo repository: {root}")
                self.output("Trust this directory only for this session when CLI asks.")
                self.output("Wait for [demo] READY; try /demo, /demo joke, /demo stats, then /exit.")
                show_disabled_mcp_servers(self.output, cli=True)
                # Reuse local CLI login; no credentials are read or printed here.
                # The built-in switch and exact-name flags block MCPs for this
                # CLI run without changing the extension's tool permissions.
                # Screen-reader mode makes event lines easier to follow live.
                cli_arguments = [
                    *CopilotRuntime(environment=self.environment).command(programs["copilot"]),
                    "--no-custom-instructions",
                    "--disable-builtin-mcps",
                    "--screen-reader",
                ]
                for server in DISABLED_MCP_SERVERS:
                    cli_arguments.extend(("--disable-mcp-server", server))
                result = subprocess.run(
                    cli_arguments,
                    # The extension's isolated SDK client needs an absolute CLI
                    # path; SDK connection paths are not resolved through PATH.
                    cwd=root,
                    env=self.environment | {"COPILOT_CLI_PATH": programs["copilot"]},
                    check=False,
                )
            self.output("CLI exited; temporary extension repository removed.")
            return result.returncode if result.returncode >= 0 else 128 - result.returncode
        except (SetupError, RuntimeSetupError, OSError, subprocess.CalledProcessError) as error:
            self.error_output(f"Setup failed: {error}")
            return 2
        except KeyboardInterrupt:
            self.error_output("Interrupted; temporary extension repository removed.")
            return 130


if __name__ == "__main__":
    raise SystemExit(CliExtensionApplication(environment=os.environ).run())
