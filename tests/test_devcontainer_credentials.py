from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import unittest
import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / ".devcontainer/copilot-credentials.sh"
PYTHON_ENVIRONMENT_HELPER = ROOT / ".devcontainer/python-environment.sh"
TOKEN_VARIABLES = ("COPILOT_GITHUB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN")


class CredentialTestCase:
    def setup_method(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.destination = self.directory / "copilot.env"

    def teardown_method(self) -> None:
        self.temporary.cleanup()

    def invoke(
        self, function: str, environment: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", "-c", f'source "$1"; {function} "$2"',
             "credential-test", str(HELPER), str(self.destination)],
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )


class TestCredentialFile(CredentialTestCase):
    def test_initialize_creates_a_private_file_without_empty_token_override(self) -> None:
        result = self.invoke("initialize_copilot_env")
        assert result.returncode == 0, result.stderr
        assert stat.S_IMODE(self.destination.stat().st_mode) == 0o600
        assert "COPILOT_GITHUB_TOKEN=" not in self.destination.read_text()
        assert "copilot login" in result.stdout

    def test_initialize_preserves_existing_content_and_repairs_permissions(self) -> None:
        original = "# Existing local configuration\n"
        self.destination.write_text(original)
        self.destination.chmod(0o644)
        result = self.invoke("initialize_copilot_env")
        assert result.returncode == 0, result.stderr
        assert self.destination.read_text() == original
        assert stat.S_IMODE(self.destination.stat().st_mode) == 0o600

    def test_initialize_rejects_symlinks_and_directories(self) -> None:
        target = self.directory / "target"
        target.write_text("Do not modify\n")
        self.destination.symlink_to(target)
        result = self.invoke("initialize_copilot_env")
        assert result.returncode != 0
        assert "regular file" in result.stderr
        assert target.read_text() == "Do not modify\n"
        self.destination.unlink()
        self.destination.mkdir()
        result = self.invoke("initialize_copilot_env")
        assert result.returncode != 0
        assert "regular file" in result.stderr

    @pytest.mark.parametrize("variable", TOKEN_VARIABLES)
    @pytest.mark.parametrize(
        "invalid",
        ("ghp_unsupported", "not-a-token", "gho_bad\nINJECTED=1"),
    )
    def test_invalid_tokens_fail_without_disclosure_or_file_replacement(
        self, variable: str, invalid: str
    ) -> None:
        original = "# Keep the previous configuration on failure\n"
        self.destination.write_text(original)
        for variable in TOKEN_VARIABLES:
            for invalid in ("ghp_unsupported", "not-a-token", "gho_bad\nINJECTED=1"):
                with self.subTest(variable=variable, invalid=invalid):
                    environment = dict(os.environ)
                    for name in TOKEN_VARIABLES:
                        environment.pop(name, None)
                    environment[variable] = invalid
                    result = self.invoke("write_copilot_env", environment)
                    assert result.returncode != 0
                    assert "Copilot Requests" in result.stderr
                    assert invalid not in result.stdout + result.stderr
                    assert self.destination.read_text() == original

    def test_missing_real_github_login_reports_setup_instructions(self) -> None:
        environment = dict(os.environ)
        for name in TOKEN_VARIABLES:
            environment.pop(name, None)
        # A real, empty gh configuration exercises the unauthenticated path;
        # no credential store, executable, or network response is mocked.
        environment["GH_CONFIG_DIR"] = str(self.directory / "gh")
        result = self.invoke("write_copilot_env", environment)
        assert result.returncode != 0
        assert "gh auth login" in result.stderr
        assert not self.destination.exists()

    def test_container_reads_the_file_without_a_remote_environment_override(self) -> None:
        text = (ROOT / ".devcontainer/devcontainer.json").read_text()
        configuration = json.loads(re.sub(r"^\s*//.*$", "", text, flags=re.MULTILINE))
        assert configuration["runArgs"] == \
            ["--env-file", "${localWorkspaceFolder}/.devcontainer/copilot.env"]
        assert configuration["initializeCommand"] == \
            ["bash", "${localWorkspaceFolder}/.devcontainer/initialize.sh"]
        assert "COPILOT_GITHUB_TOKEN" not in configuration.get("remoteEnv", {})

    def test_credentials_are_excluded_from_git_and_the_image_build_context(self) -> None:
        for name in (".devcontainer/copilot.env", ".devcontainer/copilot.env.abc123"):
            result = subprocess.run(
                ["git", "check-ignore", "--quiet", name], cwd=ROOT, check=False
            )
            assert result.returncode == 0
        assert ".devcontainer/copilot.env*" in (ROOT / ".dockerignore").read_text().splitlines()


class TestPythonEnvironment:
    def test_devcontainer_uses_the_mandatory_repository_environment(self) -> None:
        text = (ROOT / ".devcontainer/devcontainer.json").read_text()
        configuration = json.loads(re.sub(r"^\s*//.*$", "", text, flags=re.MULTILINE))
        settings = configuration["customizations"]["vscode"]["settings"]

        assert settings["python.defaultInterpreterPath"] == \
            "${workspaceFolder}/.venv/bin/python"
        assert settings["python.terminal.activateEnvironment"]

        post_create = (ROOT / ".devcontainer/post-create.sh").read_text()
        assert 'create_python_environment "$repository_root"' in post_create
        assert '"$repository_root/.venv/bin/python" -m copilot download-runtime' in \
            post_create

    def test_workspace_recommends_every_devcontainer_extension(self) -> None:
        text = (ROOT / ".devcontainer/devcontainer.json").read_text()
        configuration = json.loads(re.sub(r"^\s*//.*$", "", text, flags=re.MULTILINE))
        installed_extensions = configuration["customizations"]["vscode"]["extensions"]
        recommended_extensions = json.loads(
            (ROOT / ".vscode/extensions.json").read_text()
        )["recommendations"]

        assert recommended_extensions == installed_extensions

    def test_python_debugger_launches_the_current_file_with_repository_venv(self) -> None:
        launch = json.loads((ROOT / ".vscode/launch.json").read_text())
        configuration = launch["configurations"][0]

        assert configuration["type"] == "debugpy"
        assert configuration["request"] == "launch"
        assert configuration["program"] == "${file}"
        assert configuration["python"] == "${workspaceFolder}${pathSeparator}.venv${pathSeparator}bin${pathSeparator}python"
        assert configuration["windows"]["python"] == "${workspaceFolder}\\.venv\\Scripts\\python.exe"
        assert configuration["cwd"] == "${fileDirname}"
        assert configuration["pythonArgs"] == ["-Xfrozen_modules=off"]
        assert configuration["subProcess"] is False
        assert len(launch["configurations"]) == 1

    def test_environment_creation_rejects_a_non_directory_venv_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository_root = Path(temporary)
            (repository_root / ".venv").write_text("not a directory")
            (repository_root / "requirements.txt").write_text(
                "github-copilot-sdk[telemetry]==1.0.14\n"
            )
            result = subprocess.run(
                [
                    "bash",
                    "-c",
                    'source "$1"; create_python_environment "$2"',
                    "python-environment-test",
                    str(PYTHON_ENVIRONMENT_HELPER),
                    str(repository_root),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

        assert result.returncode != 0
        assert "must be a directory" in result.stderr

    def test_environment_creation_rejects_a_missing_dependency_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run(
                [
                    "bash",
                    "-c",
                    'source "$1"; create_python_environment "$2"',
                    "python-environment-test",
                    str(PYTHON_ENVIRONMENT_HELPER),
                    temporary,
                ],
                capture_output=True,
                text=True,
                check=False,
            )

        assert result.returncode != 0
        assert "dependency manifest is missing" in result.stderr

    def test_pytest_discovers_repository_and_numbered_demo_tests(self) -> None:
        settings = json.loads((ROOT / ".vscode/settings.json").read_text())
        assert settings["python.testing.pytestEnabled"]
        assert not settings["python.testing.unittestEnabled"]
        assert settings["python.testing.pytestArgs"] == \
            ["--import-mode=importlib", "tests", "demos"]
        text = (ROOT / ".devcontainer/devcontainer.json").read_text()
        configuration = json.loads(re.sub(r"^\s*//.*$", "", text, flags=re.MULTILINE))
        container_settings = configuration["customizations"]["vscode"]["settings"]
        for name, value in settings.items():
            assert container_settings[name] == value
        discovery = subprocess.run(
            [
                str(ROOT / ".venv/bin/python"),
                "-m", "pytest", "--collect-only", "-q",
                *settings["python.testing.pytestArgs"],
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert discovery.returncode == 0, discovery.stdout + discovery.stderr
        for directory in (ROOT / "tests", ROOT / "demos"):
            for test_file in directory.rglob("test_*.py"):
                assert test_file.relative_to(ROOT).as_posix() in discovery.stdout

    def test_environment_creation_requires_the_beancount_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository_root = Path(temporary)
            (repository_root / "requirements.txt").write_text(
                "github-copilot-sdk[telemetry]==1.0.14\n"
            )
            result = subprocess.run(
                [
                    "bash",
                    "-c",
                    'source "$1"; create_python_environment "$2"',
                    "python-environment-test",
                    str(PYTHON_ENVIRONMENT_HELPER),
                    str(repository_root),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

        assert result.returncode != 0
        assert "required Beancount source snapshot is missing" in result.stderr

    def test_environment_creation_installs_required_packages(self) -> None:
        creation = subprocess.run(
            [
                "bash",
                "-c",
                'source "$1"; create_python_environment "$2"',
                "python-environment-test",
                str(PYTHON_ENVIRONMENT_HELPER),
                str(ROOT),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert creation.returncode == 0, creation.stderr

        environment_python = ROOT / ".venv/bin/python"
        assert environment_python.is_file(), \
            "Run .devcontainer/post-create.sh to create the mandatory .venv."
        result = subprocess.run(
            [
                str(environment_python),
                "-c",
                "import importlib.metadata; import pytest; "
                "print(importlib.metadata.version('github-copilot-sdk'))",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == \
            0, \
            "github-copilot-sdk or pytest is missing from .venv; " \
            "rerun the devcontainer post-create command.\n" \
            + result.stderr
        assert result.stdout.strip() == "1.0.14"


class TestSessionSynchronization:
    def test_devcontainer_shows_workspace_and_external_copilot_sessions(self) -> None:
        text = (ROOT / ".devcontainer/devcontainer.json").read_text()
        configuration = json.loads(re.sub(r"^\s*//.*$", "", text, flags=re.MULTILINE))
        settings = configuration["customizations"]["vscode"]["settings"]

        assert settings["chat.viewSessions.enabled"]
        assert settings["chat.agentSessions.showExternal"] == "all"

    def test_copilot_cloud_agent_creates_the_same_python_environment(self) -> None:
        workflow = (
            ROOT / ".github/workflows/copilot-setup-steps.yml"
        ).read_text()

        assert "copilot-setup-steps:" in workflow
        assert "python-version: \"3.12\"" in workflow
        assert "source .devcontainer/python-environment.sh" in \
            workflow
        assert 'create_python_environment "$PWD"' in workflow
        assert 'echo "$PWD/.venv/bin" >> "$GITHUB_PATH"' in workflow
        assert 'python -c "import copilot; print(\'Copilot SDK is ready\')"' in \
            workflow


class TestLiveCredential(CredentialTestCase):
    async def request_with_staged_token(self, token: str) -> None:
        try:
            from copilot import CopilotClient
        except ModuleNotFoundError:
            pytest.fail("Install github-copilot-sdk or rebuild the devcontainer before the live test.")

        environment = dict(os.environ)
        for name in TOKEN_VARIABLES:
            environment.pop(name, None)
        environment["COPILOT_GITHUB_TOKEN"] = token
        # Empty, real CLI stores prevent an existing login from concealing a
        # broken environment handoff during this test.
        environment["COPILOT_HOME"] = str(self.directory / "copilot")
        environment["GH_CONFIG_DIR"] = str(self.directory / "gh")
        assert not environment.get("COPILOT_PROVIDER_BASE_URL"), \
            "Unset COPILOT_PROVIDER_BASE_URL: this test must exercise GitHub Copilot, not BYOK."
        # Give the real runtime the same variable Docker/Podman load from the
        # env file. Do not use github_token=, which would bypass that path.
        # The context managers close the real session and runtime after the test.
        async with CopilotClient(env=environment) as client:
            # Ask the runtime to validate the staged GitHub credential before any
            # model call; a false result points to authentication or Copilot access.
            status = await client.get_auth_status()
            assert status.isAuthenticated, \
                "The staged token was rejected. Refresh host authentication and " \
                "confirm Copilot access and network connectivity."
            # No tools, hooks, or repository instructions are needed to prove
            # that this credential can complete a real Copilot model request.
            async with await client.create_session(
                model="auto",
                available_tools=[],
                skip_custom_instructions=True,
                enable_file_hooks=False,
                enable_skills=False,
            ) as session:
                # This waits for session.idle and returns the final assistant
                # message; the exact reply proves a real model request completed.
                response = await session.send_and_wait(
                    "Reply with exactly: DEVCONTAINER_AUTH_OK", timeout=90
                )
                assert response is not None
                assert response is not None
                assert response.data.content.strip() == "DEVCONTAINER_AUTH_OK"

    def test_real_host_token_survives_staging_and_authenticates_the_sdk(self) -> None:
        self.destination.write_text("# Replace a previous local configuration\n")
        result = self.invoke("write_copilot_env")
        assert result.returncode == 0, \
            "Live test requires a real COPILOT_GITHUB_TOKEN (or GH_TOKEN/GITHUB_TOKEN), " \
            "or gh auth login --hostname github.com, plus Copilot access and network. " \
            "Credentials are not mocked and this test is not skipped.\n" + result.stderr
        content = self.destination.read_text()
        variable, token = content.rstrip("\n").split("=", 1)
        assert variable == "COPILOT_GITHUB_TOKEN"
        assert token
        assert token not in result.stdout + result.stderr
        assert stat.S_IMODE(self.destination.stat().st_mode) == 0o600
        for name in TOKEN_VARIABLES:
            if os.environ.get(name):
                assert token == os.environ[name], "Token precedence changed."
                break
        result = self.invoke("initialize_copilot_env")
        assert result.returncode == 0, result.stderr
        assert self.destination.read_text() == content, "Initializer replaced token."
        assert list(self.directory.glob("copilot.env.*")) == []
        target = self.directory / "protected.env"
        self.destination.rename(target)
        self.destination.symlink_to(target)
        result = self.invoke("write_copilot_env")
        assert result.returncode != 0
        assert "regular file" in result.stderr
        assert token not in result.stdout + result.stderr
        assert target.read_text() == content, "Symlink target was modified."
        asyncio.run(self.request_with_staged_token(token))
