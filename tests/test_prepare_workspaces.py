"""Real-git tests for prepare_workspaces.py (no Copilot SDK involved)."""

import json
from pathlib import Path

import pytest

import prepare_workspaces as pw

ROOT = Path(pw.ROOT)


def test_every_mapped_demo_directory_exists():
    for demo in pw.WORKSPACES:
        assert (ROOT / "demos" / demo).is_dir()


def test_clones_sit_on_expected_refs_with_fork_origin(tmp_path):
    workspaces = {"demo-a": "demo-red-1048", "demo-b": "demo-base-1048"}
    for demo in workspaces:
        (tmp_path / "demos" / demo).mkdir(parents=True)
    assert pw.WorkspacePreparer(tmp_path, workspaces).run() == 0
    for demo, ref in workspaces.items():
        target = tmp_path / "demos" / demo / "workspace"
        def git(*arguments):
            return pw.WorkspacePreparer.git("-C", str(target), *arguments)
        assert git("rev-parse", "HEAD") == git("rev-parse", f"{ref}^{{commit}}")
        assert git("remote", "get-url", "origin") == pw.FORK_URL
        assert git("remote", "get-url", "upstream") == pw.UPSTREAM_URL
    # a second run leaves existing clones untouched
    assert pw.WorkspacePreparer(tmp_path, workspaces).run() == 0


def test_sdlc_bundle_restores_complete_sources_without_network(tmp_path):
    preparer = pw.WorkspacePreparer(tmp_path, {"005-sdlc-team": "demo-base-1048"})
    assert preparer.run() == 0
    target = tmp_path / "demos" / "005-sdlc-team" / "workspace"
    assert preparer.git("-C", str(target), "rev-parse", "HEAD") == pw.SDLC_BASE_COMMIT
    assert preparer.git("-C", str(target), "rev-parse", "--is-shallow-repository") == "true"
    assert preparer.git("-C", str(target), "remote", "get-url", "origin") == pw.FORK_URL
    assert preparer.git("-C", str(target), "remote", "get-url", "upstream") == pw.UPSTREAM_URL
    preparer.git("-C", str(target), "fsck", "--full")
    entries = preparer.git("-C", str(target), "ls-tree", "-r", "HEAD").splitlines()
    provenance = json.loads((ROOT / "src-beancount" / "SOURCE.json").read_text())
    assert len(entries) == provenance["tracked_source_files"] == 340
    assert provenance["commit"] == pw.SDLC_BASE_COMMIT
    # Hash through Git's checkout filters, including Windows newline handling.
    paths = [entry.split("\t", 1)[1] for entry in entries]
    expected = [entry.split()[2] for entry in entries]
    actual = []
    raw = []
    for start in range(0, len(paths), 40):
        actual.extend(preparer.git(
            "-C", str(ROOT), "hash-object",
            *(str(ROOT / "src-beancount" / path) for path in paths[start:start + 40]),
        ).splitlines())
        raw.extend(preparer.git(
            "-C", str(ROOT), "hash-object", "--no-filters",
            *(str(ROOT / "src-beancount" / path) for path in paths[start:start + 40]),
        ).splitlines())
    # Upstream's holdings-csv.output was committed with CRLF already; do not
    # reinterpret that original blob through core.autocrlf.
    for path, original, filtered, unfiltered in zip(paths, expected, actual, raw):
        assert original in (filtered, unfiltered), path
    source = target / "beancount" / "parser" / "booking_full.py"
    source.write_text(source.read_text() + "\n# preserved presenter edit\n")
    before = source.read_bytes()
    assert preparer.run() == 0
    assert source.read_bytes() == before


def test_missing_sdlc_bundle_fails_without_creating_workspace(tmp_path):
    preparer = pw.WorkspacePreparer(
        tmp_path, {"005-sdlc-team": "demo-base-1048"},
        sdlc_bundle=tmp_path / "missing.bundle",
    )
    with pytest.raises(SystemExit, match="Missing bundled Beancount sources"):
        preparer.run()
    assert not (tmp_path / "demos" / "005-sdlc-team" / "workspace").exists()


def test_sdlc_preparation_rejects_existing_wrong_commit_without_reset(tmp_path):
    preparer = pw.WorkspacePreparer(tmp_path, {"005-sdlc-team": "demo-base-1048"})
    preparer.run()
    target = tmp_path / "demos" / "005-sdlc-team" / "workspace"
    preparer.git(
        "-C", str(target), "-c", "user.name=Tomasz Kopacz",
        "-c", "user.email=tkopacz@tomaszkopacz.com",
        "commit", "--allow-empty", "-m", "Keep a presenter checkpoint for preparation tests",
    )
    head = preparer.git("-C", str(target), "rev-parse", "HEAD")
    with pytest.raises(SystemExit, match="no files were reset"):
        preparer.run()
    assert preparer.git("-C", str(target), "rev-parse", "HEAD") == head
