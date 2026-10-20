from __future__ import annotations

import asyncio
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("repository_demo_runner", ROOT / "demo_runner.py")
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def application(root: Path, demos: tuple[str, ...], output: list[str]):
    return runner.DemoSuiteApplication(
        root=root,
        demos=demos,
        environment=os.environ,
        output=output.append,
        error_output=output.append,
    )


@pytest.fixture
def suite(tmp_path: Path) -> Path:
    interpreter = runner.repository_interpreter(tmp_path)
    interpreter.parent.mkdir(parents=True)
    interpreter.symlink_to(sys.executable)
    for name in ("001-first", "002-second"):
        directory = tmp_path / "demos" / name
        directory.mkdir(parents=True)
        (directory / "main.py").write_text(
            f"from pathlib import Path\n"
            f"with Path('order.txt').open('a') as stream:\n"
            f"    stream.write('{name}\\n')\n",
            encoding="utf-8",
        )
        (directory / "test_main.py").write_text(
            "def test_real_child():\n"
            "    from pathlib import Path\n"
            "    assert Path.cwd().name\n",
            encoding="utf-8",
        )
    return tmp_path


@pytest.mark.parametrize("mode", ("tests", "examples"))
def test_registry_covers_every_current_demo(mode: str) -> None:
    app = application(ROOT, runner.DEMO_DIRECTORIES, [])
    assert app.validate(mode) == runner.repository_interpreter(ROOT)


def test_demo_numbers_are_consecutive_and_match_documentation() -> None:
    assert [
        name.split("-", 1)[0] for name in runner.DEMO_DIRECTORIES
    ] == [f"{number:03d}" for number in range(1, len(runner.DEMO_DIRECTORIES) + 1)]
    for name in runner.DEMO_DIRECTORIES:
        readme = (ROOT / "demos" / name / "README.md").read_text(encoding="utf-8")
        assert name[:3] in readme.splitlines()[0]
        assert f".venv/bin/python demos/{name}/main.py" in readme


def test_acp_web_precedes_the_cli_extension_and_uses_standard_runners() -> None:
    app = application(ROOT, runner.DEMO_DIRECTORIES, [])
    interpreter = ROOT / ".venv" / "bin" / "python"
    assert runner.DEMO_DIRECTORIES[-1] == "010-cli-extension"
    assert runner.DEMO_DIRECTORIES[-2] == "009-acp-web"
    assert app.command("examples", interpreter, "009-acp-web") == [
        str(interpreter), str(ROOT / "demos/009-acp-web/main.py"),
    ]
    assert app.command("tests", interpreter, "009-acp-web")[-1] == str(
        ROOT / "demos/009-acp-web"
    )
    assert app.command("examples", interpreter, "010-cli-extension") == [
        str(interpreter), str(ROOT / "demos/010-cli-extension/main.py"),
    ]
    assert app.command("tests", interpreter, "010-cli-extension")[-1] == str(
        ROOT / "demos/010-cli-extension"
    )


@pytest.mark.parametrize(
    ("names", "message"),
    (
        ((), "nonempty"),
        (("001-first", "001-first"), "duplicates"),
        (("../escape",), "Invalid demo directory"),
        (("missing",), "Missing demo entry point"),
        (("001-first",), "Add new demos"),
    ),
)
def test_invalid_registration_fails(suite: Path, names: tuple[str, ...], message: str) -> None:
    with pytest.raises(runner.SetupError, match=message):
        application(suite, names, []).validate("tests")


def test_missing_interpreter_and_invalid_mode_fail(suite: Path) -> None:
    app = application(suite, ("001-first", "002-second"), [])
    with pytest.raises(runner.SetupError, match="Mode must"):
        app.validate("invalid")
    runner.repository_interpreter(suite).unlink()
    with pytest.raises(runner.SetupError, match="Missing repository interpreter"):
        app.validate("tests")


def test_missing_tests_are_not_silently_omitted(suite: Path) -> None:
    (suite / "demos" / "001-first" / "test_main.py").unlink()
    with pytest.raises(runner.SetupError, match="Missing pytest tests"):
        application(suite, ("001-first", "002-second"), []).validate("tests")


def test_missing_cli_returns_setup_failure_without_running_children(suite: Path) -> None:
    output: list[str] = []
    app = runner.DemoSuiteApplication(
        root=suite,
        demos=("001-first", "002-second"),
        environment={"PATH": str(suite)},
        output=output.append,
        error_output=output.append,
    )
    assert app.run("examples") == 2
    assert "Copilot CLI is missing" in "\n".join(output)
    assert not (suite / "order.txt").exists()


def test_examples_run_sequentially_in_repository_root(suite: Path) -> None:
    output: list[str] = []
    app = application(suite, ("001-first", "002-second"), output)
    assert app.run_children("examples", Path(sys.executable), dict(os.environ)) == 0
    assert (suite / "order.txt").read_text().splitlines() == ["001-first", "002-second"]
    assert "PASS 001-first (exit 0)" in "\n".join(output)
    assert "PASS 002-second (exit 0)" in "\n".join(output)


def test_failure_does_not_prevent_next_example(suite: Path) -> None:
    (suite / "demos" / "001-first" / "main.py").write_text("raise SystemExit(7)\n")
    output: list[str] = []
    app = application(suite, ("001-first", "002-second"), output)
    assert app.run_children("examples", Path(sys.executable), dict(os.environ)) == 1
    assert (suite / "order.txt").read_text().splitlines() == ["002-second"]
    assert "FAIL 001-first (exit 7)" in "\n".join(output)
    assert "PASS 002-second (exit 0)" in "\n".join(output)


def test_interrupt_exit_stops_remaining_examples(suite: Path) -> None:
    (suite / "demos" / "001-first" / "main.py").write_text("raise SystemExit(130)\n")
    output: list[str] = []
    app = application(suite, ("001-first", "002-second"), output)
    assert app.run_children("examples", Path(sys.executable), dict(os.environ)) == 130
    assert not (suite / "order.txt").exists()
    assert "Not started: 1" in "\n".join(output)


def test_process_start_failure_is_reported_for_every_example(suite: Path) -> None:
    output: list[str] = []
    app = application(suite, ("001-first", "002-second"), output)
    assert app.run_children("examples", suite / "missing-python", dict(os.environ)) == 1
    assert sum("Cannot start" in line for line in output) == 2
    assert "FAIL 002-second (exit 2)" in "\n".join(output)


@pytest.mark.parametrize("fails", (False, True))
def test_real_pytest_children_exclude_workspace_and_aggregate_failures(
    suite: Path, fails: bool
) -> None:
    first = suite / "demos" / "001-first"
    workspace = first / "workspace"
    workspace.mkdir()
    (workspace / "test_upstream.py").write_text("raise RuntimeError('Must not be collected')\n")
    # A second test file must be collected too, not only the usual test_main.py.
    (first / "test_extra.py").write_text(f"def test_extra():\n    assert {not fails!r}\n")
    output: list[str] = []
    app = application(suite, ("001-first", "002-second"), output)
    assert app.run_children("tests", Path(sys.executable), dict(os.environ)) == (1 if fails else 0)
    assert "PASS 002-second (exit 0)" in "\n".join(output)
    assert f"{'FAIL' if fails else 'PASS'} 001-first" in "\n".join(output)


def test_real_local_cli_authentication_and_sdk_demo() -> None:
    output: list[str] = []
    app = application(ROOT, runner.DEMO_DIRECTORIES, output)
    environment = app.prepare_environment()
    assert Path(environment["COPILOT_CLI_PATH"]).is_file()
    # This runs the real local CLI/SDK handshake and then a real deterministic
    # request in demo 001. Missing login/network/subscription must fail the test.
    asyncio.run(app.verify_authentication(environment))
    auth_suite = application(ROOT, ("001-auth",), output)
    code = auth_suite.run_children("tests", runner.repository_interpreter(ROOT), environment)
    assert code == 0, (
        "Real Copilot integration failed: install requirements.txt, run `copilot login`, "
        "and check network/subscription access.\n" + "\n".join(output)
    )
    assert "authentication verified; preflight runtime closed" in "\n".join(output)
    assert "PASS 001-auth (exit 0)" in "\n".join(output)
    # The example launcher also crosses the real SDK boundary, with the demo's
    # default tool-free authentication prompt and its own session cleanup.
    assert auth_suite.run_children(
        "examples", runner.repository_interpreter(ROOT), environment
    ) == 0, "\n".join(output)


@pytest.mark.parametrize("script", ("run-all-tests.py", "run-all-demos.py"))
def test_launchers_reenter_venv_and_report_missing_cli_from_another_directory(
    tmp_path: Path, script: str
) -> None:
    environment = dict(os.environ)
    environment.pop("COPILOT_CLI_PATH", None)
    environment["PATH"] = str(tmp_path)
    result = subprocess.run(
        [sys._base_executable, str(ROOT / script)],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2, result.stdout + result.stderr
    assert "Copilot CLI is missing" in result.stderr
    assert "ModuleNotFoundError" not in result.stderr
