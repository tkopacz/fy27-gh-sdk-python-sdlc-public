"""Create one independent Beancount clone per demo, each on its own ref.

Run once before the demos: `.venv/bin/python prepare_workspaces.py`.
Existing workspaces are left untouched; delete a demo's `workspace/` folder
to recreate it. This script does not use the Copilot SDK.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FORK_URL = "https://github.com/tkopacz/beancount.git"
UPSTREAM_URL = "https://github.com/beancount/beancount.git"
# Optional local template clone: avoids a network download when present.
LOCAL_TEMPLATE = ROOT / "demos" / "beancount-workspace"
SDLC_BASE_COMMIT = "9747213802acb733ce53acc6e963f5961f47d6cd"
SDLC_BUNDLE = ROOT / "demos" / "005-sdlc-team" / "beancount-base.bundle"

# demo directory -> ref checked out (tags are detached, branches are attached)
WORKSPACES = {
    "002-initialsession": "demo-red-1048",
    "004-custom-tool-secure": "demo-red-1048",
    "005-sdlc-team": "demo-base-1048",
    "006-human-policy": "demo-red-1048",
    "007-mcp-resume": "demo/beancount-1048",
}


class WorkspacePreparer:
    def __init__(
        self, root: Path, workspaces: dict[str, str], *,
        sdlc_bundle: Path = SDLC_BUNDLE,
    ) -> None:
        self.root = root
        self.workspaces = workspaces
        self.sdlc_bundle = sdlc_bundle

    def run(self) -> int:
        for demo, ref in self.workspaces.items():
            self.prepare(self.root / "demos" / demo / "workspace", ref)
        return 0

    def prepare(self, target: Path, ref: str) -> None:
        bundled = target.parent.name == "005-sdlc-team" and ref == "demo-base-1048"
        if target.exists():
            if bundled:
                self.validate_sdlc_checkout(target)
            print(f"[skip] {target.relative_to(self.root)} already exists")
            return
        if bundled:
            if not self.sdlc_bundle.is_file():
                raise SystemExit(f"Missing bundled Beancount sources: {self.sdlc_bundle}")
            self.git("init", "--quiet", str(target))
            self.git("-C", str(target), "bundle", "unbundle", str(self.sdlc_bundle))
            self.git("-C", str(target), "update-ref", f"refs/tags/{ref}", SDLC_BASE_COMMIT)
            # The bundle contains the original commit and its entire source
            # tree, not 100 MB of unrelated history. Mark that history boundary
            # before checkout so Git never traverses the omitted parents.
            (target / ".git" / "shallow").write_text(SDLC_BASE_COMMIT + "\n", encoding="ascii")
            self.git("-C", str(target), "checkout", "--quiet", "--detach", ref)
            self.git("-C", str(target), "remote", "add", "origin", FORK_URL)
        else:
            source = str(LOCAL_TEMPLATE) if LOCAL_TEMPLATE.is_dir() else FORK_URL
            self.git("clone", "--quiet", "--branch", ref, source, str(target))
            # Local template clones point at a path; the demos expect the fork.
            self.git("-C", str(target), "remote", "set-url", "origin", FORK_URL)
        self.git("-C", str(target), "remote", "add", "upstream", UPSTREAM_URL)
        if bundled:
            self.validate_sdlc_checkout(target)
        head = self.git("-C", str(target), "rev-parse", "--short", "HEAD")
        print(f"[ok]   {target.relative_to(self.root)} -> {ref} ({head})")

    def validate_sdlc_checkout(self, target: Path) -> None:
        head = self.git("-C", str(target), "rev-parse", "HEAD")
        if head != SDLC_BASE_COMMIT:
            raise SystemExit(
                f"Demo 005 requires {SDLC_BASE_COMMIT}, but {target} is at {head}. "
                "Preserve your work and prepare a fresh workspace; no files were reset."
            )

    @staticmethod
    def git(*arguments: str) -> str:
        completed = subprocess.run(
            ("git", *arguments), capture_output=True, text=True, check=False
        )
        if completed.returncode:
            raise SystemExit(f"git {' '.join(arguments)} failed: {completed.stderr}")
        return completed.stdout.strip()


if __name__ == "__main__":
    sys.exit(WorkspacePreparer(ROOT, WORKSPACES).run())
