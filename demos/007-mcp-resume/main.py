#!/usr/bin/env python3
"""Inspect a public issue through scoped GitHub MCP and resume its SDK session."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from copilot_runtime import CopilotRuntime, RuntimeSetupError, print_event

from copilot import MCPServerConfig, PreToolUseHookInput, PreToolUseHookOutput, define_tool
from copilot.generated.rpc import (
    PermissionDecisionApproveOnce,
    PermissionDecisionDeniedInteractivelyByUser,
)
from copilot.session import GitHubMcpToolConfig, PermissionNoResult, SessionHooks
from copilot.session_events import (
    AssistantMessageData,
    AssistantUsageData,
    PermissionRequestMcp,
    PermissionRequestCustomTool,
    SessionEvent,
    SessionEventType,
    SessionUsageCheckpointData,
    SessionMcpServersLoadedData,
    SubagentCompletedData,
    ToolExecutionCompleteData,
    ToolExecutionStartData,
)
from pydantic import BaseModel, Field

READ_TOOLS = ("issue_read", "get_file_contents", "list_pull_requests", "pull_request_read")
CREATE_PR = "create_pull_request"
UPDATE_DOCS = "documentalist_update_versions"
SERVER = "github-mcp-server"
REMOTE_SERVER = "github-remote"
REMOTE_URL = "https://api.githubcopilot.com/mcp/"
MCP_TOKEN_VARIABLE = "DEMO_007_GITHUB_MCP_TOKEN"
SESSION_ID = "beancount-1048"
FORK_OWNER_VARIABLE = "DEMO_007_FORK_OWNER"
PUBLISH_APPROVAL_VARIABLE = "DEMO_007_APPROVE_DRAFT_PR"
PROMPT = (
    "Use GitHub MCP to read beancount/beancount issue #1048 and "
    "CHANGES. List pull requests on the configured fork with head "
    "'{owner}:demo/beancount-1048'; if a draft PR exists, inspect it. "
    "Summarize the issue, propose the documentation change and a draft PR "
    "description. Do not modify files, push, or create a PR."
)
RESUME_PROMPT = (
    "Using the earlier issue and docs context, summarize the proposed "
    "CHANGES edit as a proposal, not a claim that the bug is fixed, and the "
    "manual steps for a draft PR targeting ONLY the configured fork, never upstream. "
    "Do not modify files, push, or create a PR."
)
PUBLISH_PROMPT = (
    "Using the earlier issue and documentation context, create a DRAFT pull "
    "request ONLY in the configured fork, from the reviewed fork branch to "
    "the configured fork base branch. Never push or write to the upstream "
    "repository. If the fork branch is not already prepared, stop and explain."
)
PREPARE_PROMPT = (
    "Read beancount/beancount issue #1048 AND its CHANGES with GitHub MCP, "
    "then act as documentalist: call "
    "documentalist_update_versions once with this exact single-line note: "
    "'Proposed documentation for issue #1048: explain DivisionByZero with "
    "0 HOOL {{20.00 USD}} and the expected booking error.' "
    "The tool adds it at the top of the fork's local "
    "CHANGES. Do not claim the bug is fixed. Do not commit, push or "
    "create a PR; leave the changed file for human review."
)


class VersionNote(BaseModel):
    note: str = Field(
        description=(
            "One line starting with Proposed, mentioning issue #1048, "
            "DivisionByZero and the literal 0 HOOL {{20.00 USD}}; do not claim a fix."
        ),
        max_length=240,
        pattern=r"^Proposed[^\r\n]*$",
    )


@dataclass(frozen=True)
class DemoConfiguration:
    session_id: str = SESSION_ID
    model: str = "auto"
    timeout_seconds: float = 180.0
    max_ai_credits: float = 30.0
    # None discovers persisted SDK history: first run creates, later runs resume.
    # False/True explicitly select create/resume for a controlled presentation.
    resume: bool | None = None
    publish_draft: bool = False
    prepare_draft: bool = False
    remote_mcp: bool = False
    fork_owner: str = "tkopacz"
    fork_checkout: Path = Path(__file__).resolve().parent / "workspace"
    fork_repository: str = "beancount"
    fork_branch: str = "demo/beancount-1048"
    base_branch: str = "master"


CONFIGURATION = DemoConfiguration()


class ConfigurationError(ValueError):
    """A safety or setup prerequisite is missing."""


class McpResumeApplication:
    def __init__(
        self,
        *,
        environment: Mapping[str, str] | None = None,
        output: Callable[[str], None] = print,
        error_output: Callable[[str], None] | None = None,
    ) -> None:
        self.environment = environment if environment is not None else os.environ
        self.output = output
        self.error_output = error_output or (
            lambda message: print(message, file=sys.stderr)
        )
        self.successful_reads: set[str] = set()
        self.pending_reads: dict[str, str] = {}
        self.active_owner: str | None = None
        self.active_config = CONFIGURATION
        self.active_remote_mcp = False
        self.doc_updated = False

    def validate(self, config: DemoConfiguration) -> str | None:
        if not config.session_id.strip() or "/" in config.session_id:
            raise ConfigurationError("session_id must be a nonempty stable identifier.")
        if not config.model.strip() or config.timeout_seconds <= 0 or config.max_ai_credits < 30:
            raise ConfigurationError("model and timeout must be valid; Copilot requires at least 30 AI credits.")
        owner = self.environment.get(FORK_OWNER_VARIABLE, config.fork_owner).strip()
        if (owner or config.publish_draft or config.prepare_draft) and (
            not owner or owner == "beancount" or not owner.replace("-", "").isalnum()
        ):
            raise ConfigurationError(
                f"Set {FORK_OWNER_VARIABLE} to your fork owner (not beancount)."
            )
        if config.publish_draft and self.environment.get(PUBLISH_APPROVAL_VARIABLE) != "yes":
            raise ConfigurationError(
                f"Set {PUBLISH_APPROVAL_VARIABLE}=yes only after reviewing the fork branch and draft PR."
            )
        if (
            config.fork_repository != "beancount"
            or config.fork_branch != "demo/beancount-1048"
            or config.base_branch != "master"
        ):
            raise ConfigurationError("The fork repository and branch names must be configured.")
        if config.prepare_draft and config.publish_draft:
            raise ConfigurationError("Prepare and publish are separate review stages; enable only one.")
        if config.remote_mcp and not self.environment.get(MCP_TOKEN_VARIABLE):
            raise ConfigurationError(
                f"Set {MCP_TOKEN_VARIABLE} to a scoped GitHub token for the HTTP MCP "
                "server (https://github.com/settings/personal-access-tokens/new). "
                "CLI login alone does not supply HTTP Authorization headers. "
                "See this demo's README for the minimum permissions, or keep remote_mcp=False."
            )
        if config.prepare_draft or config.publish_draft:
            self.validate_fork(config, owner, require_clean=True)
        return owner or None

    @staticmethod
    def git(checkout: Path, *args: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(checkout), *args],
            capture_output=True, text=True, check=False,
        )
        if result.returncode:
            raise ConfigurationError(
                "Fork checkout is not ready; verify its Git remote, branch "
                "and working tree before enabling an opt-in stage."
            )
        # Preserve Git porcelain's leading status column when checking tool edits.
        return result.stdout.rstrip()

    def validate_fork(self, config: DemoConfiguration, owner: str, *, require_clean: bool) -> Path:
        checkout = config.fork_checkout.resolve()
        document = checkout / "CHANGES"
        if (
            not document.is_file()
            or document.is_symlink()
            or not document.resolve().is_relative_to(checkout)
        ):
            raise ConfigurationError(
                f"Prepare a local fork checkout with CHANGES at {checkout}."
            )
        if Path(self.git(checkout, "rev-parse", "--show-toplevel")).resolve() != checkout:
            raise ConfigurationError("The fork checkout must be the Git repository root.")
        if self.git(checkout, "branch", "--show-current") != config.fork_branch:
            raise ConfigurationError(f"Check out fork branch {config.fork_branch} first.")
        origin = self.git(checkout, "remote", "get-url", "origin")
        if origin not in (
            f"https://github.com/{owner}/beancount.git",
            f"git@github.com:{owner}/beancount.git",
        ):
            raise ConfigurationError("Git origin must point to the named fork, never upstream.")
        if self.git(checkout, "status", "--porcelain") and require_clean:
            raise ConfigurationError(
                "Review and commit existing changes; the fork working tree must "
                "be clean before preparing or publishing."
            )
        if config.publish_draft:
            if "issue #1048" not in document.read_text(encoding="utf-8").lower():
                raise ConfigurationError("Review and commit the issue #1048 documentation change first.")
            remote_head = self.git(checkout, "ls-remote", "--heads", "origin", config.fork_branch)
            if not remote_head:
                raise ConfigurationError("Push the reviewed fork branch before requesting a draft PR.")
            if remote_head.split()[0] != self.git(checkout, "rev-parse", "HEAD"):
                raise ConfigurationError("Push the latest reviewed fork commit before requesting a draft PR.")
        return document

    @staticmethod
    def validate_note(note: str) -> str:
        if not isinstance(note, str):
            raise ValueError("Note must be a single proposed changelog sentence.")
        value = note.strip()
        if (
            len(value) > 240 or "\n" in value or "\r" in value
            or "divisionbyzero" not in value.lower() or "0 hool {{20.00 usd}}" not in value.lower()
            or "issue #1048" not in value.lower() or not value.lower().startswith("proposed")
        ):
            raise ValueError("Note must start with Proposed and mention DivisionByZero, 0 HOOL {{20.00 USD}} and issue #1048.")
        return value

    def documentalist_tool(self, config: DemoConfiguration, owner: str):
        # Copilot sees this typed domain tool only during the explicit prepare
        # stage. Its handler edits one validated file in a fork checkout; the
        # model cannot choose a path, execute git, push or modify upstream.
        @define_tool(description="Add a proposed issue #1048 note to the fork's local CHANGES", defer="never")
        def documentalist_update_versions(params: VersionNote) -> str:
            note = self.validate_note(params.note)
            document = self.validate_fork(config, owner, require_clean=False)
            original = document.read_text(encoding="utf-8")
            anchor = "The master branch will rely on the Git repository history.\n\n\n"
            if original.count(anchor) != 1:
                raise ValueError("CHANGES header must have one expected anchor.")
            if "issue #1048" in original or "Issue #1048" in original:
                raise ValueError("Issue #1048 already has a changelog entry; review it manually.")
            revised = original.replace(anchor, anchor + f"- {note}\n\n", 1)
            document.write_text(revised, encoding="utf-8")
            self.doc_updated = True
            return "Updated fork CHANGES for review; no commit or push was made."

        return documentalist_update_versions

    def permission(self, owner: str | None, config: DemoConfiguration):
        def decide(request, invocation):
            # Copilot permission callbacks are a second boundary after the tool
            # allowlist: never approve shell, file writes, upstream MCP writes or
            # a push, even if a prompt or an MCP tool description asks for one.
            if getattr(request, "managed_approval_required", False):
                return PermissionNoResult()
            if isinstance(request, PermissionRequestCustomTool):
                if config.prepare_draft and request.tool_name == UPDATE_DOCS:
                    return PermissionDecisionApproveOnce()
                return PermissionDecisionDeniedInteractivelyByUser()
            if not isinstance(request, PermissionRequestMcp):
                return PermissionDecisionDeniedInteractivelyByUser()
            if self.allowed(
                request.server_name, request.tool_name, request.args,
                request.read_only, owner, config,
            ):
                return PermissionDecisionApproveOnce()
            return PermissionDecisionDeniedInteractivelyByUser()

        return decide

    @staticmethod
    def allowed(
        server: str, tool: str, args: object, read_only: bool,
        owner: str | None, config: DemoConfiguration,
    ) -> bool:
        expected_server = REMOTE_SERVER if config.remote_mcp else SERVER
        if server != expected_server or not isinstance(args, dict):
            return False
        name = tool.removeprefix(f"{expected_server}-")
        upstream = args.get("owner") == "beancount" and args.get("repo") == "beancount"
        if read_only:
            if name == "issue_read":
                return upstream and args.get("issue_number") == 1048
            if name == "get_file_contents":
                return upstream and args.get("path") == "CHANGES"
            if name in ("list_pull_requests", "pull_request_read"):
                return bool(owner and args.get("owner") == owner and args.get("repo") == config.fork_repository)
        return bool(
            name == CREATE_PR and owner and config.publish_draft
            and args.get("owner") == owner and args.get("repo") == config.fork_repository
            and args.get("head") == config.fork_branch
            and args.get("base") == config.base_branch and args.get("draft") is True
        )

    def tool_guard(self, owner: str | None, config: DemoConfiguration):
        def guard(event: PreToolUseHookInput, context: dict[str, str]) -> PreToolUseHookOutput:
            # Read-only MCP operations may run without a permission callback.
            # This SDK pre-tool hook enforces the same argument scope before
            # every invocation, including operations that bypass prompts.
            tool = event.get("toolName", "")
            expected_server = REMOTE_SERVER if config.remote_mcp else SERVER
            server = expected_server if tool.startswith(f"{expected_server}-") else ""
            name = tool.removeprefix(f"{expected_server}-")
            args = event.get("toolArgs")
            permitted = False
            if tool == UPDATE_DOCS and config.prepare_draft and isinstance(args, dict):
                try:
                    self.validate_note(args.get("note", ""))
                except ValueError as error:
                    # Only the fixed validation message is shown, never tool
                    # arguments; the model also gets the reason to correct it.
                    self.output(f"[guard] {UPDATE_DOCS} denied: {error}")
                    return {
                        "permissionDecision": "deny",
                        "permissionDecisionReason": str(error),
                    }
                else:
                    permitted = True
            else:
                permitted = self.allowed(
                    server, tool, args, name in READ_TOOLS, owner, config,
                )
            return {
                "permissionDecision": "allow" if permitted else "deny",
                "permissionDecisionReason": "Demo 007 scoped GitHub MCP boundary",
            }

        return guard

    def show_event(self, event: SessionEvent) -> None:
        # Only event names and numeric SDK metrics leave the callback; MCP
        # arguments, event payloads, credentials and repository content do not.
        print_event(event, self.output)
        if event.type == SessionEventType.SESSION_MCP_SERVERS_LOADED and isinstance(event.data, SessionMcpServersLoadedData):
            for server in event.data.servers:
                if server.name == SERVER or "github" in server.name.lower():
                    self.output(f"[mcp] {server.name} status={server.status.value}")
        if event.type == SessionEventType.TOOL_EXECUTION_START and isinstance(event.data, ToolExecutionStartData):
            self.output(f"[tool] {event.data.tool_name} server={event.data.mcp_server_name}")
            server = REMOTE_SERVER if self.active_remote_mcp else SERVER
            name = event.data.tool_name.removeprefix(f"{server}-")
            if name in READ_TOOLS and self.allowed(
                event.data.mcp_server_name or "", event.data.tool_name,
                event.data.arguments, True, self.active_owner, self.active_config,
            ):
                self.pending_reads[event.data.tool_call_id] = name
        elif event.type == SessionEventType.TOOL_EXECUTION_COMPLETE and isinstance(event.data, ToolExecutionCompleteData):
            self.output(f"[tool] success={event.data.success}")
            name = self.pending_reads.pop(event.data.tool_call_id, None)
            if name and event.data.success and event.data.error is None and event.data.result is not None:
                self.successful_reads.add(name)
        if event.type == SessionEventType.ASSISTANT_USAGE and isinstance(event.data, AssistantUsageData):
            self.output(
                f"[usage] model={event.data.model} input={event.data.input_tokens} "
                f"output={event.data.output_tokens}"
            )
        elif event.type == SessionEventType.SESSION_USAGE_CHECKPOINT and isinstance(
            event.data, SessionUsageCheckpointData
        ):
            self.output(f"[usage] nano_aiu={event.data.total_nano_aiu}")
        elif event.type == SessionEventType.SUBAGENT_COMPLETED and isinstance(
            event.data, SubagentCompletedData
        ):
            self.output(
                f"[subagent] tokens={event.data.total_tokens} "
                f"tool_calls={event.data.total_tool_calls}"
            )

    async def execute(self, config: DemoConfiguration) -> None:
        owner = self.validate(config)
        self.active_owner = owner
        self.active_config = config
        self.active_remote_mcp = config.remote_mcp
        tools: list[str] = list(READ_TOOLS)
        if config.publish_draft:
            tools.append(CREATE_PR)
        server = REMOTE_SERVER if config.remote_mcp else SERVER
        documentalist = None
        if config.prepare_draft:
            if owner is None:
                raise ConfigurationError(f"Set {FORK_OWNER_VARIABLE} before preparing a draft.")
            documentalist = self.documentalist_tool(config, owner)
        self.successful_reads.clear()
        self.pending_reads.clear()
        self.doc_updated = False
        # The CLI login authenticates Copilot and its managed GitHub MCP server;
        # a separately configured HTTP MCP server requires its own token.
        async with CopilotRuntime(environment=self.environment, output=self.output).create_client() as client:
            resume = config.resume
            if resume is None:
                # Discover the exact persisted ID; do not mask failed resumes by
                # creating a replacement session with missing conversation history.
                resume = any(
                    saved.session_id == config.session_id
                    for saved in await client.list_sessions()
                )
            # Resume reconnects to persisted history after a process restart;
            # create_session with the same explicit ID must not overwrite it.
            method = client.resume_session if resume else client.create_session
            mcp_servers: dict[str, MCPServerConfig] | None = None
            github_config = None
            if config.remote_mcp:
                # mcp_servers configures the actual remote HTTP transport and
                # its narrow server-side tool allowlist. Unlike the built-in
                # GitHub MCP integration, this connection cannot reuse CLI
                # login: read a token at runtime, never store or print it.
                mcp_servers = {
                    REMOTE_SERVER: {
                        "type": "http",
                        "url": REMOTE_URL,
                        "headers": {
                            "Authorization": "Bearer " + self.environment[MCP_TOKEN_VARIABLE],
                            # The remote server also filters its catalog, and
                            # read/prepare stages reject writes server-side.
                            "X-MCP-Tools": ",".join(tools),
                            **({"X-MCP-Readonly": "true"} if not config.publish_draft else {}),
                        },
                        "tools": tools,
                    }
                }
            else:
                # The CLI-managed remote GitHub MCP connection uses CLI auth.
                # Its tool config enables named tools, but is not a server-side
                # allowlist; available_tools and the hook enforce this mode.
                github_config = GitHubMcpToolConfig(
                    enable_all_tools=False, additional_tools=tools
                )
            # Both SDK methods accept session_id by keyword; only resume reads
            # persisted history. Keep the same scoped tools and callbacks.
            session = await method(
                session_id=config.session_id,
                model=config.model,
                # The model sees qualified names; the hook separately guards
                # every target/argument, including read-only MCP requests.
                available_tools=[f"{server}-{name}" for name in tools]
                + ([UPDATE_DOCS] if documentalist else []),
                tools=[documentalist] if documentalist else None,
                working_directory=str(config.fork_checkout.resolve()) if config.prepare_draft else None,
                session_limits={"max_ai_credits": config.max_ai_credits},
                hooks=SessionHooks(on_pre_tool_use=self.tool_guard(owner, config)),
                on_permission_request=self.permission(owner, config),
                on_event=self.show_event,
                mcp_servers=mcp_servers,
                github_mcp_tool_config=github_config,
            )
            async with session:
                self.output(f"[session] {'resumed' if resume else 'created'} {session.session_id}")
                self.output(f"[fork] {owner}/{config.fork_repository} branch={config.fork_branch}")
                # History is read from the SDK session store rather than from
                # cached application state; output redacts message bodies.
                before = await session.get_events()
                self.output(f"[history] events_before={len(before)}")
                prompt = (
                    f"{PUBLISH_PROMPT} owner={owner}, repo={config.fork_repository}, "
                    f"head={config.fork_branch}, base={config.base_branch}."
                    if config.publish_draft
                    else PREPARE_PROMPT if config.prepare_draft
                    else RESUME_PROMPT if resume else PROMPT.format(owner=owner)
                )
                prompt += (
                    f" Configured fork: {owner}/{config.fork_repository}, "
                    f"head={config.fork_branch}, base={config.base_branch}. "
                    "The upstream repository is read-only in this workshop."
                )
                result = await session.send_and_wait(prompt, timeout=config.timeout_seconds)
                if result is None or not isinstance(result.data, AssistantMessageData):
                    raise RuntimeError("Copilot reached idle without a final assistant response.")
                history = await session.get_events()
                self.output(f"[history] events_after={len(history)}")
                if len(history) <= len(before):
                    raise RuntimeError("Session history did not record the new turn.")
                # Show the operator's answer even when the model did not finish
                # a required MCP/tool step; event payloads remain redacted.
                self.output("Copilot response:")
                self.output(result.data.content)
                if (not resume or config.prepare_draft) and not {"issue_read", "get_file_contents"} <= self.successful_reads:
                    raise ConfigurationError(
                        "GitHub MCP did not complete scoped reads of issue #1048 and CHANGES. "
                        "Authorize GitHub MCP in the CLI and verify its issue_read "
                        "tool is available, then use a new session_id."
                    )
                if config.prepare_draft and not self.doc_updated:
                    raise ConfigurationError(
                        "Documentalist did not update fork CHANGES; review the "
                        "agent response before retrying with a new session_id."
                    )
                if config.prepare_draft and self.git(
                    config.fork_checkout.resolve(), "status", "--porcelain"
                ).splitlines() != [" M CHANGES"]:
                    raise ConfigurationError(
                        "Unexpected fork changes; review git status before proceeding."
                    )
                if config.prepare_draft:
                    self.output("[review] Inspect git diff in the fork, then commit and push manually.")
                # Publishing is additionally gated on the fork owner and exact
                # MCP permission arguments; the default run has no write tool.

    def run(self, config: DemoConfiguration) -> int:
        try:
            asyncio.run(self.execute(config))
        except (ConfigurationError, RuntimeSetupError) as error:
            self.error_output(f"Configuration error: {error}")
            return 2
        except KeyboardInterrupt:
            self.error_output("Cancelled.")
            return 130
        except Exception as error:
            self.error_output(
                f"Copilot/MCP failed ({type(error).__name__}). Check network, subscription, "
                "CLI login (`copilot login`), and GitHub MCP access; confirm the "
                "session exists before resuming. No upstream write is permitted."
            )
            return 1
        return 0


def main() -> int:
    return McpResumeApplication().run(CONFIGURATION)


if __name__ == "__main__":
    raise SystemExit(main())
