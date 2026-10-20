"""Exercise the reset command against real bundled Git checkouts, without SDK calls."""

import shutil
import subprocess
from pathlib import Path

import pytest

from prepare_workspaces import ROOT, SDLC_BASE_COMMIT, WorkspacePreparer


@pytest.fixture
def reset_demo(tmp_path: Path) -> tuple[Path, Path]:
    WorkspacePreparer(tmp_path, {"005-sdlc-team": "demo-base-1048"}).run()
    demo = tmp_path / "demos" / "005-sdlc-team"
    shutil.copy2(ROOT / "demos" / "005-sdlc-team" / "reset-workspace.ps1", demo)
    return demo, demo / "workspace"


def run_reset(demo: Path, answer: str = "") -> subprocess.CompletedProcess[str]:
    shell = shutil.which("pwsh")
    assert shell, "Install PowerShell 7 (pwsh) to run the real workspace-reset tests."
    return subprocess.run(
        [shell, "-NoProfile", "-File", str(demo / "reset-workspace.ps1")],
        cwd=demo.parent, input=answer + "\n", capture_output=True, text=True,
        check=False,
    )


@pytest.mark.parametrize("answer", ["", "reset", "no"])
def test_reset_cancellation_preserves_changes(reset_demo, answer):
    demo, workspace = reset_demo
    source = workspace / "CHANGES"
    source.write_bytes(source.read_bytes() + b"\npresenter edit\n")
    before = source.read_bytes()
    untracked = workspace / "presenter-notes.txt"
    untracked.write_text("keep me")
    result = run_reset(demo, answer)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "[reset] Cancelled. No files changed." in result.stdout
    assert source.read_bytes() == before
    assert untracked.read_text() == "keep me"


def test_reset_discards_staged_unstaged_and_untracked_but_keeps_ignored(reset_demo):
    demo, workspace = reset_demo
    git = WorkspacePreparer.git
    (workspace / "CHANGES").write_text("discard staged edit\n")
    (workspace / "new-file.txt").write_text("discard staged addition\n")
    git("-C", str(workspace), "add", "CHANGES", "new-file.txt")
    (workspace / "COPYING").unlink()
    untracked = workspace / "presenter-notes" / "notes.txt"
    untracked.parent.mkdir()
    untracked.write_text("discard untracked directory\n")
    ignored = workspace / "reset-test-build"
    ignored.mkdir()
    (workspace / ".git" / "info" / "exclude").write_text("reset-test-build/\n")
    (ignored / "parser.bin").write_bytes(b"preserve compiled parser")
    log = demo / "logs" / "presenter.log"
    log.parent.mkdir()
    log.write_text("preserve activity log")
    parent_file = demo.parent / "presenter.txt"
    parent_file.write_text("preserve parent")
    result = run_reset(demo, "RESET")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "[reset] Base restored; workspace clean." in result.stdout
    assert not (workspace / "new-file.txt").exists()
    assert not untracked.parent.exists()
    assert (workspace / "COPYING").is_file()
    assert (ignored / "parser.bin").read_bytes() == b"preserve compiled parser"
    assert log.read_text() == "preserve activity log"
    assert parent_file.read_text() == "preserve parent"
    assert git("-C", str(workspace), "status", "--porcelain", "--untracked-files=all") == ""
    assert git("-C", str(workspace), "rev-parse", "HEAD") == SDLC_BASE_COMMIT
    again = run_reset(demo)
    assert again.returncode == 0, again.stdout + again.stderr
    assert "[reset] Workspace already clean." in again.stdout


def test_reset_refuses_wrong_head_without_touching_edits(reset_demo):
    demo, workspace = reset_demo
    WorkspacePreparer.git(
        "-C", str(workspace), "-c", "user.name=Tomasz Kopacz",
        "-c", "user.email=tkopacz@tomaszkopacz.com",
        "commit", "--allow-empty", "-m",
        "Preserve a presenter checkpoint so reset cannot discard a different history",
    )
    source = workspace / "CHANGES"
    source.write_text("keep this edit")
    result = run_reset(demo, "RESET")
    assert result.returncode != 0
    assert "requires HEAD" in result.stdout + result.stderr
    assert source.read_text() == "keep this edit"


def test_reset_refuses_missing_checkout_instead_of_using_parent_repository(tmp_path):
    WorkspacePreparer.git("init", "--quiet", str(tmp_path))
    demo = tmp_path / "demo"
    (demo / "workspace").mkdir(parents=True)
    shutil.copy2(ROOT / "demos" / "005-sdlc-team" / "reset-workspace.ps1", demo)
    result = run_reset(demo, "RESET")
    assert result.returncode != 0
    assert "Missing standalone workspace checkout" in result.stdout + result.stderr


def test_reset_reports_nested_repository_instead_of_claiming_success(reset_demo):
    demo, workspace = reset_demo
    nested = workspace / "presenter-repo"
    WorkspacePreparer.git("init", "--quiet", str(nested))
    (nested / "notes.txt").write_text("keep nested repository")
    result = run_reset(demo, "RESET")
    assert result.returncode != 0
    assert "Workspace is not clean after reset" in result.stdout + result.stderr
    assert "[reset] Base restored; workspace clean." not in result.stdout
    assert (nested / "notes.txt").read_text() == "keep nested repository"


def test_reset_preserves_files_ignored_before_ignore_rules_are_restored(reset_demo):
    demo, workspace = reset_demo
    ignore = workspace / ".gitignore"
    ignore.write_bytes(ignore.read_bytes() + b"\npresenter-build.bin\n")
    artifact = workspace / "presenter-build.bin"
    artifact.write_bytes(b"preserve ignored build")
    result = run_reset(demo, "RESET")
    assert result.returncode != 0
    assert "Workspace is not clean after reset" in result.stdout + result.stderr
    assert artifact.read_bytes() == b"preserve ignored build"
    assert "presenter-build.bin" not in ignore.read_text()
