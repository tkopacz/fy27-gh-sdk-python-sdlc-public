from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "cli_extension_demo", Path(__file__).with_name("main.py"),
)
assert SPEC is not None and SPEC.loader is not None
demo = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(demo)


def test_missing_program_fails_clearly(tmp_path: Path) -> None:
    errors: list[str] = []
    app = demo.CliExtensionApplication(
        environment={"PATH": str(tmp_path)}, error_output=errors.append,
    )
    assert app.run() == 2
    assert "Copilot CLI is missing" in errors[0]


def test_missing_source_fails_clearly(tmp_path: Path) -> None:
    app = demo.CliExtensionApplication(
        environment=os.environ, extension_source=tmp_path / "missing.mjs",
    )
    with pytest.raises(demo.SetupError, match="Missing extension source"):
        app.validate()


def test_real_workspace_installation_and_cleanup() -> None:
    app = demo.CliExtensionApplication(environment=os.environ)
    programs = app.validate()
    with app.workspace(programs["git"]) as root:
        installed = root / ".github/extensions/demo-observer/extension.mjs"
        assert installed.read_bytes() == demo.EXTENSION_SOURCE.read_bytes()
        assert (root / ".git").is_dir()
        subprocess.run([programs["node"], "--check", str(installed)], check=True)
    assert not root.exists()


def test_workspace_cleanup_on_failure() -> None:
    app = demo.CliExtensionApplication(environment=os.environ)
    programs = app.validate()
    root: Path | None = None
    with pytest.raises(RuntimeError, match="intentional"):
        with app.workspace(programs["git"]) as root:
            raise RuntimeError("intentional failure after real installation")
    assert root is not None and not root.exists()


def test_noninteractive_launcher_is_not_a_fake_slash_command() -> None:
    result = subprocess.run(
        [sys.executable, str(demo.EXTENSION_SOURCE.with_name("main.py"))],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 2
    assert "An interactive terminal is required" in result.stderr


def test_live_cli_observer_slash_command_and_reload() -> None:
    if sys.platform == "win32":
        pytest.fail("The real CLI terminal test requires Linux, WSL or macOS (pexpect/PTY).")
    try:
        import pexpect
        import pyte
    except ImportError:
        pytest.fail("Install requirements.txt: pexpect and pyte are required for the real CLI test.")
    demo.CliExtensionApplication(environment=os.environ).validate()
    # This is a real PTY and CLI, not an SDK mock. The CLI loads extension.mjs
    # and supplies its actual JS SDK. Local login and the selected model are reused.
    child = pexpect.spawn(
        sys.executable, [str(demo.EXTENSION_SOURCE.with_name("main.py"))],
        env=os.environ, encoding="utf-8", timeout=120, dimensions=(55, 220),
    )
    class TerminalScreen(pyte.Screen):
        def report_device_status(self, mode: int, **kwargs: bool) -> None:
            # pyte does not implement private terminal capability queries.
            # They do not draw content and the real CLI tolerates no reply.
            if not kwargs.get("private"):
                super().report_device_status(mode)

    screen = TerminalScreen(220, 55)
    terminal = pyte.Stream(screen)

    class Display:
        def write(self, text: str) -> None:
            terminal.feed(text)

        def flush(self) -> None:
            pass

    # CLI updates different screen positions between response chunks. A terminal
    # emulator verifies what the user sees, rather than concatenating raw bytes.
    child.logfile_read = Display()

    def expect(pattern: str) -> re.Match[str]:
        try:
            index = child.expect([pattern, "JOKE_ERROR"])
        except (pexpect.TIMEOUT, pexpect.EOF):
            pass
        else:
            if index == 1:
                pytest.fail(
                    "Joke pipeline reported JOKE_ERROR; check the CLI runtime and local login.",
                    pytrace=False,
                )
            match = child.match
            assert isinstance(match, re.Match)
            return match
        pytest.fail(
            f"Real CLI did not produce {pattern!r}. Check `copilot login`, network, "
            "model access, Node on PATH and extension support (/env). "
            "Raw terminal output is deliberately not included.",
            pytrace=False,
        )

    def command(text: str) -> None:
        child.send(text)
        child.send("\r")

    try:
        root = Path(expect(r"Temporary demo repository: ([^\r\n]+)").group(1))
        expect(r"MCP server names disabled for this CLI run:")
        for server in demo.DISABLED_MCP_SERVERS:
            assert server in "\n".join(screen.display)
        # Approve only this newly created repository, not persistent folder trust
        # or blanket tool permissions. Fail on unexpected CLI onboarding dialogs.
        expect(r"3\. No")
        child.send("\r")
        expect(r"READY /demo \| /demo stats")
        command("/demo stats")
        expect(r"STATS turns=0 chunks=0 tools=0 usage_reports=0")
        command("/demo invalid")
        expect("INVALID_ARGUMENT")
        command("/demo stats")
        expect(r"STATS turns=0 chunks=0 tools=0 usage_reports=0")

        command("/demo")
        expect("COMMAND sending a prompt to this session")
        expect("TURN_START count=1")
        usage = expect(r"USAGE input=(\d+) output=(\d+)")
        assert int(usage.group(1)) > 0
        assert int(usage.group(2)) > 0
        assert any(line.strip() == "DEMO_OK" for line in screen.display), (
            "The real assistant must answer the demo prompt."
        )
        idle = expect(r"IDLE turns=1 chunks=(\d+) tools=0 usage_reports=1")
        assert int(idle.group(1)) > 0
        command("/demo stats")
        expect(r"STATS turns=1 chunks=\d+ tools=0 usage_reports=1")

        # The extension runs two real isolated sessions in empty mode. Neither
        # should increment the foreground observer's counters or change its role.
        command("/demo joke")
        expect(r"JOKE_START model=\S+ mode=empty system=replace")
        expect("JOKE_STAGE language=cs tools=0")
        command("/demo joke")
        expect("JOKE_BUSY")
        expect("JOKE_CS")
        expect("JOKE_STAGE language=pl tools=0")
        czech_screen = "\n".join(screen.display)
        assert "počítač" in czech_screen.split("JOKE_CS", 1)[1].lower()
        expect("JOKE_PL")
        expect("JOKE_DONE sessions_deleted=2 runtime_stopped=true")
        polish_screen = "\n".join(screen.display)
        assert "komputer" in polish_screen.split("JOKE_PL", 1)[1].lower()
        command("/demo stats")
        expect(r"STATS turns=1 chunks=\d+ tools=0 usage_reports=1")
        command("/demo joke extra")
        expect("INVALID_ARGUMENT")

        # A normal user turn must also reach this observer. Use a safe real file,
        # not fake SDK events, to exercise tool start/complete notifications.
        (root / "sample.txt").write_text("OBSERVER_FILE_OK\n", encoding="utf-8")
        command("Use the view tool to read ./sample.txt. Reply with its contents. Do not edit files.")
        expect("TOOL_START")
        expect("TOOL_COMPLETE")
        expect(r"IDLE turns=\d+ chunks=\d+ tools=[1-9]\d* usage_reports=\d+")

        # CLI replaces the session and reloads the extension; process-local
        # counters must reset. It must not destroy the user session itself.
        command("/clear")
        expect(r"READY /demo \| /demo stats")
        command("/demo stats")
        expect(r"STATS turns=0 chunks=0 tools=0 usage_reports=0")
        command("/exit")
        expect("CLI exited; temporary extension repository removed.")
        child.expect(pexpect.EOF)
        child.close()
        assert child.exitstatus == 0
        assert not root.exists()
    finally:
        if child.isalive():
            child.sendcontrol("c")
            child.sendcontrol("c")
            child.expect([pexpect.EOF, pexpect.TIMEOUT], timeout=10)
        child.close(force=True)


@pytest.mark.parametrize(
    ("cli_path", "phase"),
    (("", "configuration"), ("/missing-demo-copilot-executable", "startup")),
)
def test_live_joke_setup_failure_leaves_observer_usable(cli_path: str, phase: str) -> None:
    if sys.platform == "win32":
        pytest.fail("This live CLI test requires Linux, WSL or macOS.")
    try:
        import pexpect
    except ImportError:
        pytest.fail("Install requirements.txt: the real CLI test requires pexpect.")
    app = demo.CliExtensionApplication(environment=os.environ)
    programs = app.validate()
    with app.workspace(programs["git"]) as root:
        # Install and launch the real extension manually, with an actually
        # missing client executable. No credentials, SDK or network are faked.
        env_program = shutil.which("env")
        assert env_program is not None, "The Unix env utility is required for this PTY test."
        child = pexpect.spawn(
            env_program,
            [
                f"COPILOT_CLI_PATH={cli_path}", programs["copilot"],
                "--no-custom-instructions", "--disable-builtin-mcps", "--screen-reader",
            ],
            cwd=str(root), env=os.environ, encoding="utf-8", timeout=60,
            dimensions=(55, 220),
        )
        failed = False
        try:
            child.expect(r"3\. No")
            child.send("\r")
            child.expect("READY /demo")
            child.send("/demo joke")
            child.send("\r")
            child.expect(f"JOKE_ERROR stage={phase}")
            child.send("/demo stats")
            child.send("\r")
            child.expect("STATS turns=0 chunks=0 tools=0 usage_reports=0")
            child.send("/exit")
            child.send("\r")
            child.expect(pexpect.EOF)
            child.close()
            assert child.exitstatus == 0
        except (pexpect.TIMEOUT, pexpect.EOF):
            failed = True
        finally:
            child.close(force=True)
        if failed:
            pytest.fail(
                "Expected real CLI setup error/recovery was not observed; check CLI and Node setup.",
                pytrace=False,
            )
