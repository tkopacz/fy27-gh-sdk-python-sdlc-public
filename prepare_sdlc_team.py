"""Prepare only Demo 005, using its bundled Git sources and this interpreter."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Callable, Mapping

from prepare_workspaces import ROOT, WorkspacePreparer


class ToolchainError(RuntimeError):
    """The selected interpreter cannot run the demo's mandatory tools."""


def verify_demo_tools(
    interpreter: Path, directory: Path, environment: Mapping[str, str],
) -> list[str]:
    versions = []
    failures = []
    for module in ("pytest", "ruff", "pyright"):
        try:
            result = subprocess.run(
                [str(interpreter), "-m", module, "--version"],
                cwd=directory, env=dict(environment), capture_output=True,
                text=True, check=False, timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            failures.append(f"{module}: {error}")
            continue
        version_line = next(
            (line for line in result.stdout.splitlines()
             if line.startswith(f"{module} ")),
            None,
        )
        if result.returncode != 0 or version_line is None:
            detail = " ".join((result.stderr or result.stdout).split())
            failures.append(
                f"{module}: exit {result.returncode}; "
                + (detail or "no version report")
            )
        else:
            versions.append(version_line)
    if failures:
        raise ToolchainError(
            f"Demo 005 toolchain is not ready for interpreter {interpreter} "
            f"in {directory}: " + "; ".join(failures)
            + f'. Install requirements.txt with this interpreter: "{interpreter}" '
            f'-m pip install -r "{ROOT / "requirements.txt"}" using the configured '
            "package registry, then rerun preparation. No Copilot session was started."
        )
    return versions


class SdlcTeamPreparer:
    def __init__(
        self, *, root: Path = ROOT, interpreter: Path = Path(sys.executable),
        environment: Mapping[str, str], output: Callable[[str], None] = print,
    ) -> None:
        self.root = root.resolve()
        self.interpreter = interpreter.resolve()
        self.environment = dict(environment)
        self.output = output

    def run(self) -> int:
        directory = self.root / "demos" / "005-sdlc-team" / "workspace"
        WorkspacePreparer(self.root, {"005-sdlc-team": "demo-base-1048"}).run()
        status = WorkspacePreparer.git(
            "-C", str(directory), "status", "--porcelain", "--untracked-files=no"
        )
        if status:
            raise SystemExit(
                "Demo 005 workspace has tracked edits. Preserve or restore them "
                "before preparing the base again; no files were reset."
            )
        environment = dict(self.environment)
        environment["PATH"] = os.pathsep.join(
            (str(self.interpreter.parent), environment.get("PATH", os.defpath))
        )
        versions = verify_demo_tools(self.interpreter, directory, environment)
        self.output("[setup] Toolchain verified: " + ", ".join(versions))
        self.output("[setup] Building the parser and installing this checkout editable.")
        subprocess.run(
            [str(self.interpreter), "-m", "pip", "install", "--no-build-isolation",
             "--editable", str(directory)],
            cwd=self.root, env=environment, check=True,
        )
        # The tester's SDK shell must import the code its agents edit, not a
        # globally installed Beancount or the read-only source snapshot.
        subprocess.run(
            [str(self.interpreter), "-c",
             "from pathlib import Path; import beancount.parser.booking_full as b; "
             "from beancount.parser import _parser; "
             f"expected = Path({str(directory)!r}).resolve(); "
             "actual = Path(b.__file__).resolve(); "
             "assert actual.is_relative_to(expected), "
             "f'Wrong Beancount import: {actual}; expected {expected}'; "
             "print('[setup] Checkout import verified; compiled parser loaded.')"],
            cwd=directory, env=environment, check=True,
        )
        return 0


def main() -> int:
    try:
        return SdlcTeamPreparer(environment=os.environ).run()
    except (OSError, subprocess.CalledProcessError, ToolchainError) as error:
        print(
            f"Demo 005 setup failed: {error}. Install requirements.txt using "
            "the configured package registry and provide a C compiler "
            "(on Windows use a Visual Studio developer terminal).",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
