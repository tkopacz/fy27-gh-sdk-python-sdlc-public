"""Build the real bundled parser without changing the repository installation."""

import os
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

import pytest

from prepare_sdlc_team import SdlcTeamPreparer, ToolchainError, verify_demo_tools
from prepare_workspaces import ROOT, SDLC_BUNDLE, WorkspacePreparer


def test_toolchain_runs_real_modules_in_the_workspace() -> None:
    directory = ROOT / "demos" / "005-sdlc-team" / "workspace"
    versions = verify_demo_tools(Path(sys.executable), directory, os.environ)
    assert len(versions) == 3
    for module, version in zip(("pytest", "ruff", "pyright"), versions, strict=True):
        assert version.startswith(f"{module} ")


def test_toolchain_reports_all_missing_tools_with_repair_command(tmp_path: Path) -> None:
    environment_path = tmp_path / ".venv"
    subprocess.run(
        [sys.executable, "-m", "venv", "--without-pip", str(environment_path)],
        check=True,
    )
    interpreter = environment_path / (
        Path("Scripts") / "python.exe" if os.name == "nt" else Path("bin") / "python"
    )
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    with pytest.raises(ToolchainError) as caught:
        verify_demo_tools(interpreter, tmp_path, environment)
    message = str(caught.value)
    for module in ("pytest", "ruff", "pyright"):
        assert f"{module}: exit " in message
        assert f"No module named {module}" in message
    assert str(interpreter) in message
    assert str(ROOT / "requirements.txt") in message
    assert "-m pip install -r" in message
    assert "No Copilot session was started" in message


def test_toolchain_rejects_ruff_module_without_its_executable(tmp_path: Path) -> None:
    environment_path = tmp_path / ".venv"
    subprocess.run(
        [sys.executable, "-m", "venv", "--without-pip", str(environment_path)],
        check=True,
    )
    interpreter = environment_path / (
        Path("Scripts") / "python.exe" if os.name == "nt" else Path("bin") / "python"
    )
    environment = dict(os.environ)
    environment["PYTHONPATH"] = sysconfig.get_path("purelib")
    with pytest.raises(ToolchainError) as caught:
        verify_demo_tools(interpreter, tmp_path, environment)
    message = str(caught.value)
    assert "ruff: exit " in message
    assert "FileNotFoundError" in message
    assert "pytest: exit " not in message
    assert "pyright: exit " not in message


def test_preparer_builds_checkout_and_preserves_the_demo_bug(tmp_path: Path) -> None:
    environment_path = tmp_path / ".venv"
    subprocess.run(
        [sys.executable, "-m", "venv", "--system-site-packages", str(environment_path)],
        check=True,
    )
    interpreter = environment_path / (
        Path("Scripts") / "python.exe" if os.name == "nt" else Path("bin") / "python"
    )
    # Ruff's installed module locates its real binary in this venv's scripts.
    # Reuse the local executable as well as packages, without a registry fetch.
    ruff = Path(sys.executable).with_name("ruff.exe" if os.name == "nt" else "ruff")
    shutil.copy2(ruff, interpreter.parent / ruff.name)
    environment = dict(os.environ)
    # Reuse already installed build dependencies without reinstalling the
    # repository's editable package or contacting a package registry.
    isolated_packages = subprocess.check_output(
        [str(interpreter), "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
        text=True,
    ).strip()
    environment["PYTHONPATH"] = os.pathsep.join(
        (isolated_packages, sysconfig.get_path("purelib"))
    )
    environment["PATH"] = os.pathsep.join(
        (str(Path(sys.executable).parent), environment.get("PATH", os.defpath))
    )
    preparer = SdlcTeamPreparer(
        root=tmp_path, interpreter=interpreter, environment=environment,
    )
    if os.name == "nt":
        demo = tmp_path / "demos" / "005-sdlc-team"
        demo.mkdir(parents=True)
        script = demo / "prepare-beancount.ps1"
        shutil.copy2(ROOT / "demos" / "005-sdlc-team" / script.name, script)
        shutil.copy2(SDLC_BUNDLE, demo / SDLC_BUNDLE.name)
        for name in ("prepare_sdlc_team.py", "prepare_workspaces.py"):
            shutil.copy2(ROOT / name, tmp_path / name)
        for _ in range(2):
            result = subprocess.run(
                ["pwsh", "-NoProfile", "-File", str(script)],
                cwd=environment_path, env=environment,
                capture_output=True, text=True, check=False,
            )
            assert result.returncode == 0, result.stdout + result.stderr
            assert "[setup] Toolchain verified: pytest " in result.stdout
            assert "[setup] Checkout import verified; compiled parser loaded." in result.stdout
            assert "[setup] Ready." in result.stdout
        source = demo / "workspace" / "beancount" / "parser" / "booking_full.py"
        original = source.read_bytes()
        source.write_bytes(original + b"\n# presenter work\n")
        result = subprocess.run(
            ["pwsh", "-NoProfile", "-File", str(script)],
            env=environment, capture_output=True, text=True, check=False,
        )
        assert result.returncode != 0
        assert "workspace has tracked edits" in result.stdout + result.stderr
        assert "[setup] Ready." not in result.stdout
        assert source.read_bytes() == original + b"\n# presenter work\n"
        source.write_bytes(original)
    else:
        assert preparer.run() == 0
    directory = tmp_path / "demos" / "005-sdlc-team" / "workspace"
    result = subprocess.run(
        [str(interpreter), "-c", """
from decimal import DivisionByZero
from beancount import loader
ledger = '''2024-01-01 open Assets:S HOOL
2024-01-01 open Assets:Cash USD
2024-02-01 * "zero units, total cost"
  Assets:S      0 HOOL {{20.00 USD}}
  Assets:Cash  -20.00 USD
'''
try:
    loader.load_string(ledger)
except DivisionByZero:
    print("BASE_BUG_REPRODUCED")
else:
    raise AssertionError("The base must retain issue #1048 for the SDLC agents.")
entries, errors, _ = loader.load_string(ledger.replace("0 HOOL", "2 HOOL"))
assert not errors, errors
assert entries[-1].postings[0].cost.number == 10
print("NONZERO_CONTROL_PASSED")
"""],
        cwd=directory, env=environment,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "BASE_BUG_REPRODUCED" in result.stdout
    assert "NONZERO_CONTROL_PASSED" in result.stdout
    assert WorkspacePreparer.git(
        "-C", str(directory), "status", "--porcelain", "--untracked-files=no"
    ) == ""


def test_preparer_rejects_tracked_edits_without_overwriting_them(tmp_path: Path) -> None:
    WorkspacePreparer(tmp_path, {"005-sdlc-team": "demo-base-1048"}).run()
    source = (
        tmp_path / "demos" / "005-sdlc-team" / "workspace"
        / "beancount" / "parser" / "booking_full.py"
    )
    source.write_text(source.read_text() + "\n# presenter edit\n")
    before = source.read_bytes()
    with pytest.raises(SystemExit, match="workspace has tracked edits"):
        SdlcTeamPreparer(root=tmp_path, environment=os.environ).run()
    assert source.read_bytes() == before
