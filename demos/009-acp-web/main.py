#!/usr/bin/env python3
"""Serve a local web chat backed by GitHub Copilot CLI over ACP."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncContextManager, AsyncIterator, Callable, Mapping, NoReturn

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from copilot_runtime import CopilotRuntime, RuntimeSetupError

import uvicorn
from acp import PROTOCOL_VERSION, Client, RequestPermissionResponse, spawn_agent_process, text_block
from acp.client import ClientSideConnection
from acp.exceptions import RequestError
from acp.interfaces import Agent
from acp.schema import (
    AgentPlanContentUpdate,
    AgentPlanRemovedUpdate,
    AgentPlanUpdate,
    AgentMessageChunk,
    AgentThoughtChunk,
    AllowedOutcome,
    AvailableCommandsUpdate,
    ConfigOptionUpdate,
    CreateTerminalResponse,
    CurrentModeUpdate,
    DeniedOutcome,
    KillTerminalResponse,
    PermissionOption,
    ReadTextFileResponse,
    ReleaseTerminalResponse,
    SessionInfoUpdate,
    TextContentBlock,
    TerminalOutputResponse,
    ToolCallProgress,
    ToolCallStart,
    ToolCallUpdate,
    UsageUpdate,
    UserMessageChunk,
    WaitForTerminalExitResponse,
    WriteTextFileResponse,
)
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator

SessionUpdate = (
    UserMessageChunk
    | AgentMessageChunk
    | AgentThoughtChunk
    | ToolCallStart
    | ToolCallProgress
    | AgentPlanUpdate
    | AgentPlanContentUpdate
    | AgentPlanRemovedUpdate
    | AvailableCommandsUpdate
    | CurrentModeUpdate
    | ConfigOptionUpdate
    | SessionInfoUpdate
    | UsageUpdate
)

DEMO_DIRECTORY = Path(__file__).resolve().parent
REPOSITORY_ROOT = DEMO_DIRECTORY.parents[1]
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
MAX_ACTIVE_SESSIONS = 2
MAX_PROMPT_CHARACTERS = 1200
ACP_PROMPT_TIMEOUT_SECONDS = 180
ACP_STARTUP_TIMEOUT_SECONDS = 30
READ_ONLY_TOOLS = ("view", "grep")

WEB_PAGE = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Copilot ACP Web Demo</title>
    <style>
      body { font: 16px system-ui, sans-serif; margin: 2rem auto; max-width: 52rem; padding: 0 1rem; }
      h1 { margin-bottom: .25rem; }
      p { color: #555; }
      #messages { border: 1px solid #ccc; min-height: 18rem; padding: 1rem; white-space: pre-wrap; }
      form { display: flex; gap: .5rem; margin-top: 1rem; }
      input { flex: 1; padding: .7rem; }
      button { padding: .7rem 1rem; }
      .status { color: #555; font-family: monospace; }
    </style>
  </head>
  <body>
    <h1>Copilot CLI over ACP</h1>
    <p>A local web client talks to a read-only Copilot CLI session using ACP over stdio.</p>
    <button id="start">Start a session</button>
    <button id="close" disabled>Close session</button>
    <p id="status" class="status">No session</p>
    <main id="messages" aria-live="polite"></main>
    <form id="prompt-form">
      <input id="prompt" maxlength="1200" placeholder="Ask Copilot to inspect this repository" disabled required>
      <button id="send" disabled>Send</button>
    </form>
    <script>
      let sessionId = null;
      let eventSource = null;
      const status = document.querySelector("#status");
      const messages = document.querySelector("#messages");
      const promptInput = document.querySelector("#prompt");
      const sendButton = document.querySelector("#send");
      const addLine = (label, text = "") => {
        const line = document.createElement("div");
        line.textContent = text ? `${label}: ${text}` : label;
        messages.append(line);
      };
      document.querySelector("#start").addEventListener("click", async () => {
        try {
          const response = await fetch("/api/sessions", { method: "POST" });
          const data = await response.json();
          if (!response.ok) throw new Error(data.detail || "Could not start a session");
          sessionId = data.session_id;
          status.textContent = `ACP session ${sessionId}`;
          promptInput.disabled = false;
          sendButton.disabled = false;
          document.querySelector("#start").disabled = true;
          document.querySelector("#close").disabled = false;
          addLine("Session ready; tools: view, grep");
        } catch (error) {
          status.textContent = error.message;
        }
      });
      document.querySelector("#prompt-form").addEventListener("submit", async (event) => {
        event.preventDefault();
        if (!sessionId || !promptInput.value.trim()) return;
        sendButton.disabled = true;
        eventSource?.close();
        eventSource = new EventSource(`/api/sessions/${sessionId}/events`);
        eventSource.onmessage = (message) => {
          const update = JSON.parse(message.data);
          if (update.type === "agent_message_chunk") addLine("Copilot", update.text);
          else addLine(update.type, update.title || "");
          if (update.type === "turn_complete") {
            eventSource.close();
            sendButton.disabled = false;
          }
        };
        eventSource.onerror = () => {
          status.textContent = "ACP event stream disconnected";
          eventSource.close();
          sendButton.disabled = false;
        };
        const text = promptInput.value.trim();
        promptInput.value = "";
        addLine("You", text);
        try {
          const response = await fetch(`/api/sessions/${sessionId}/messages`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ prompt: text })
          });
          const data = await response.json();
          if (!response.ok) throw new Error(data.detail || "Copilot request failed");
          status.textContent = `Turn complete: ${data.stop_reason}`;
        } catch (error) {
          status.textContent = error.message;
          eventSource.close();
          sendButton.disabled = false;
        }
      });
      document.querySelector("#close").addEventListener("click", async () => {
        if (!sessionId) return;
        const response = await fetch(`/api/sessions/${sessionId}`, { method: "DELETE" });
        if (!response.ok) {
          const data = await response.json();
          status.textContent = data.detail || "Could not close the session";
          return;
        }
        eventSource?.close();
        sessionId = null;
        promptInput.disabled = true;
        sendButton.disabled = true;
        document.querySelector("#start").disabled = false;
        document.querySelector("#close").disabled = true;
        status.textContent = "Session and Copilot CLI process closed";
        addLine("Session closed");
      });
    </script>
  </body>
</html>
"""


class DemoConfigurationError(ValueError):
    """The local ACP web demo cannot run with the supplied configuration."""


class ACPBridgeError(RuntimeError):
    """The Copilot CLI ACP subprocess could not complete an operation."""


class ACPSessionNotFound(ACPBridgeError):
    """The requested in-memory ACP session is not active."""


class PromptRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=MAX_PROMPT_CHARACTERS)

    @field_validator("prompt")
    @classmethod
    def prompt_must_contain_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("prompt must contain non-whitespace characters")
        return value


@dataclass
class DemoConfiguration:
    workspace_directory: Path = REPOSITORY_ROOT
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    max_active_sessions: int = MAX_ACTIVE_SESSIONS
    prompt_timeout_seconds: int = ACP_PROMPT_TIMEOUT_SECONDS

    def validate(self) -> Path:
        if self.host not in ("127.0.0.1", "localhost"):
            raise DemoConfigurationError(
                "This demo only binds to localhost. Add authentication and network "
                "isolation before exposing a web client remotely."
            )
        if not 1 <= self.port <= 65535:
            raise DemoConfigurationError("port must be between 1 and 65535.")
        if self.max_active_sessions < 1:
            raise DemoConfigurationError("max_active_sessions must be positive.")
        if self.prompt_timeout_seconds < 1:
            raise DemoConfigurationError("prompt_timeout_seconds must be positive.")
        workspace = self.workspace_directory.resolve()
        if not workspace.is_dir():
            raise DemoConfigurationError(f"Workspace directory does not exist: {workspace}")
        return workspace


class ACPWebClient(Client):
    """Collect only safe ACP event summaries for the browser."""

    def __init__(self, events: asyncio.Queue[dict[str, str]]) -> None:
        self.events = events
        self.assistant_chunks: list[str] = []

    async def session_update(
        self,
        session_id: str,
        update: SessionUpdate,
        **kwargs: Any,
    ) -> None:
        event_type = str(getattr(update, "sessionUpdate", "session_update"))
        event = {"type": event_type}
        if isinstance(update, AgentMessageChunk) and isinstance(update.content, TextContentBlock):
            self.assistant_chunks.append(update.content.text)
            event["text"] = update.content.text
        elif isinstance(update, (ToolCallStart, ToolCallProgress)):
            # Titles and kinds are enough to teach the event flow; raw tool
            # input/output may contain repository contents and stays private.
            event["title"] = update.title or ""
            event["kind"] = update.kind or ""
        await self.events.put(event)

    async def request_permission(
        self,
        session_id: str,
        tool_call: ToolCallUpdate,
        options: list[PermissionOption],
        **kwargs: Any,
    ) -> RequestPermissionResponse:
        if tool_call.kind in ("read", "search"):
            allow_once = next(
                (option for option in options if option.kind == "allow_once"),
                None,
            )
            if allow_once is not None:
                # Only read/search tools are exposed by the process-wide CLI
                # allowlist; choose a one-time grant rather than a persistent one.
                return RequestPermissionResponse(
                    outcome=AllowedOutcome(
                        outcome="selected",
                        option_id=allow_once.option_id,
                    )
                )
        return RequestPermissionResponse(
            outcome=DeniedOutcome(outcome="cancelled")
        )

    async def read_text_file(
        self,
        session_id: str,
        path: str,
        line: int | None = None,
        limit: int | None = None,
        **kwargs: Any,
    ) -> ReadTextFileResponse:
        raise ACPBridgeError("Client-side file reads are not enabled in this demo.")

    async def write_text_file(
        self,
        session_id: str,
        path: str,
        content: str,
        **kwargs: Any,
    ) -> WriteTextFileResponse | None:
        raise ACPBridgeError("Client-side file writes are not enabled in this demo.")

    async def create_terminal(
        self,
        session_id: str,
        command: str,
        args: list[str] | None = None,
        env: list[Any] | None = None,
        cwd: str | None = None,
        output_byte_limit: int | None = None,
        **kwargs: Any,
    ) -> CreateTerminalResponse:
        raise ACPBridgeError("Client-side terminals are not enabled in this demo.")

    async def terminal_output(
        self, session_id: str, terminal_id: str, **kwargs: Any
    ) -> TerminalOutputResponse:
        raise ACPBridgeError("Client-side terminals are not enabled in this demo.")

    async def release_terminal(
        self, session_id: str, terminal_id: str, **kwargs: Any
    ) -> ReleaseTerminalResponse | None:
        raise ACPBridgeError("Client-side terminals are not enabled in this demo.")

    async def wait_for_terminal_exit(
        self, session_id: str, terminal_id: str, **kwargs: Any
    ) -> WaitForTerminalExitResponse:
        raise ACPBridgeError("Client-side terminals are not enabled in this demo.")

    async def kill_terminal(
        self, session_id: str, terminal_id: str, **kwargs: Any
    ) -> KillTerminalResponse | None:
        raise ACPBridgeError("Client-side terminals are not enabled in this demo.")

    async def create_elicitation(
        self, message: str, mode: Any, **kwargs: Any
    ) -> NoReturn:
        raise ACPBridgeError("Client-side elicitation is not enabled in this demo.")

    async def complete_elicitation(
        self, elicitation_id: str, **kwargs: Any
    ) -> None:
        raise ACPBridgeError("Client-side elicitation is not enabled in this demo.")

    async def ext_method(
        self, method: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        raise ACPBridgeError("ACP extension methods are not enabled in this demo.")

    async def ext_notification(self, method: str, params: dict[str, Any]) -> None:
        raise ACPBridgeError("ACP extension notifications are not enabled in this demo.")

    def on_connect(self, conn: Agent) -> None:
        return None


@dataclass
class ACPSession:
    session_id: str
    connection: ClientSideConnection
    process_context: AsyncContextManager[tuple[ClientSideConnection, asyncio.subprocess.Process]]
    events: asyncio.Queue[dict[str, str]]
    client: ACPWebClient
    prompt_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class ACPSessionManager:
    def __init__(
        self,
        *,
        configuration: DemoConfiguration,
        environment: Mapping[str, str],
        output: Callable[[str], None] = print,
    ) -> None:
        self.configuration = configuration
        self.environment = dict(environment)
        self.output = output
        self.sessions: dict[str, ACPSession] = {}
        self.starting_sessions = 0

    def resolve_cli(self) -> str:
        try:
            return CopilotRuntime(environment=self.environment, output=self.output).resolve_cli()
        except RuntimeSetupError as error:
            raise ACPBridgeError(str(error)) from error

    async def create_session(self) -> ACPSession:
        workspace = self.configuration.validate()
        if len(self.sessions) + self.starting_sessions >= self.configuration.max_active_sessions:
            raise ACPBridgeError(
                f"At most {self.configuration.max_active_sessions} sessions may be active."
            )
        self.starting_sessions += 1
        try:
            return await self._start_session(workspace)
        except RuntimeSetupError as error:
            raise ACPBridgeError(str(error)) from error
        finally:
            self.starting_sessions -= 1

    async def _start_session(self, workspace: Path) -> ACPSession:
        events: asyncio.Queue[dict[str, str]] = asyncio.Queue()
        client = ACPWebClient(events)
        cli_path = self.resolve_cli()
        runtime = CopilotRuntime(environment=self.environment, output=self.output)
        command = runtime.command(cli_path)
        # ACP owns stdin/stdout as a newline-delimited JSON-RPC channel. The
        # CLI inherits its local login, while its startup allowlist keeps every
        # session limited to repository reading and search.
        process_context = spawn_agent_process(
            client,
            *command,
            "--acp",
            "--stdio",
            f"--available-tools={','.join(READ_ONLY_TOOLS)}",
            cwd=workspace,
            env=runtime.prepare_environment(),
        )
        entered = False
        try:
            connection, process = await asyncio.wait_for(
                process_context.__aenter__(),
                timeout=ACP_STARTUP_TIMEOUT_SECONDS,
            )
            entered = True
            # initialize negotiates the ACP schema version before any session
            # messages are sent; new_session creates an isolated CLI conversation.
            await asyncio.wait_for(
                connection.initialize(protocol_version=PROTOCOL_VERSION),
                timeout=ACP_STARTUP_TIMEOUT_SECONDS,
            )
            response = await asyncio.wait_for(
                connection.new_session(cwd=str(workspace), mcp_servers=[]),
                timeout=ACP_STARTUP_TIMEOUT_SECONDS,
            )
        except BaseException as error:
            if entered:
                await process_context.__aexit__(
                    type(error),
                    error,
                    error.__traceback__,
                )
            if isinstance(
                error,
                (RequestError, ConnectionError, OSError, TimeoutError),
            ):
                self.output(
                    f"ACP session setup failed ({type(error).__name__}): {error}"
                )
                raise ACPBridgeError(
                    "Could not initialize the Copilot ACP session. Verify CLI "
                    "authentication, network access, and CLI compatibility."
                ) from error
            raise

        session = ACPSession(
            session_id=response.session_id,
            connection=connection,
            process_context=process_context,
            events=events,
            client=client,
        )
        self.sessions[session.session_id] = session
        self.output(f"Started ACP session {session.session_id} with PID {process.pid}.")
        return session

    def get_session(self, session_id: str) -> ACPSession:
        session = self.sessions.get(session_id)
        if session is None:
            raise ACPSessionNotFound("ACP session not found or already closed.")
        return session

    async def send_prompt(self, session_id: str, prompt: str) -> dict[str, str]:
        session = self.get_session(session_id)
        async with session.prompt_lock:
            session.client.assistant_chunks.clear()
            try:
                # ACP sends the prompt as a text block; the agent's streamed
                # message chunks arrive separately through session_update.
                response = await asyncio.wait_for(
                    session.connection.prompt(
                        session_id=session.session_id,
                        prompt=[text_block(prompt)],
                    ),
                    timeout=self.configuration.prompt_timeout_seconds,
                )
            except TimeoutError as error:
                await session.connection.cancel(session.session_id)
                await session.events.put(
                    {"type": "turn_error", "message": "Copilot response timed out."}
                )
                raise ACPBridgeError("Copilot response timed out.") from error
            except (RequestError, ConnectionError, OSError) as error:
                await session.events.put(
                    {"type": "turn_error", "message": "Copilot ACP request failed."}
                )
                self.output(
                    f"ACP request failed ({type(error).__name__}): {error}"
                )
                raise ACPBridgeError(
                    "Copilot ACP request failed. Verify CLI authentication and network access."
                ) from error
            await session.events.put(
                {"type": "turn_complete", "stop_reason": response.stopReason}
            )
            return {
                "stop_reason": response.stopReason,
                "assistant_message": "".join(session.client.assistant_chunks),
            }

    async def close_session(self, session_id: str) -> None:
        session = self.get_session(session_id)
        async with session.prompt_lock:
            try:
                # Close the ACP conversation before exiting its subprocess
                # context so the browser's Close action also reaps the CLI.
                await session.connection.close_session(session.session_id)
            finally:
                await session.process_context.__aexit__(None, None, None)
                self.sessions.pop(session_id, None)
                await session.events.put({"type": "session_closed"})
                self.output(f"Closed ACP session {session_id}.")

    async def close_all(self) -> None:
        results = await asyncio.gather(
            *(self.close_session(session_id) for session_id in tuple(self.sessions)),
            return_exceptions=True,
        )
        failures = [result for result in results if isinstance(result, Exception)]
        if failures:
            raise RuntimeError(
                f"Failed to clean up {len(failures)} ACP session(s)."
            ) from failures[0]


def create_app(
    configuration: DemoConfiguration | None = None,
    *,
    environment: Mapping[str, str] | None = None,
    output: Callable[[str], None] = print,
) -> FastAPI:
    config = configuration or DemoConfiguration()
    config.validate()
    manager = ACPSessionManager(
        configuration=config,
        environment=os.environ if environment is None else environment,
        output=output,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await manager.close_all()

    app = FastAPI(title="Copilot ACP Web Demo", lifespan=lifespan)
    app.state.session_manager = manager

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return WEB_PAGE

    @app.post("/api/sessions", status_code=201)
    async def create_session() -> dict[str, str]:
        try:
            session = await manager.create_session()
        except ACPBridgeError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        return {"session_id": session.session_id}

    @app.post("/api/sessions/{session_id}/messages")
    async def send_message(session_id: str, request: PromptRequest) -> dict[str, str]:
        try:
            return await manager.send_prompt(session_id, request.prompt)
        except ACPSessionNotFound as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ACPBridgeError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error

    @app.get("/api/sessions/{session_id}/events")
    async def session_events(session_id: str, request: Request) -> StreamingResponse:
        try:
            session = manager.get_session(session_id)
        except ACPBridgeError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

        async def event_stream() -> AsyncIterator[str]:
            while not await request.is_disconnected():
                try:
                    event = await asyncio.wait_for(session.events.get(), timeout=15)
                except TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                if event["type"] in ("turn_complete", "turn_error", "session_closed"):
                    return

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.delete("/api/sessions/{session_id}", status_code=204)
    async def close_session(session_id: str) -> None:
        try:
            await manager.close_session(session_id)
        except ACPBridgeError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    return app


class ACPWebApplication:
    def __init__(
        self,
        *,
        configuration: DemoConfiguration,
        environment: Mapping[str, str],
        output: Callable[[str], None] = print,
        error_output: Callable[[str], None] | None = None,
    ) -> None:
        self.configuration = configuration
        self.environment = dict(environment)
        self.output = output
        self.error_output = error_output or (
            lambda message: print(message, file=sys.stderr, flush=True)
        )

    def run(self) -> int:
        try:
            self.configuration.validate()
            self.environment = CopilotRuntime(
                environment=self.environment, output=self.output,
            ).prepare_environment()
            self.output(
                f"Open http://{self.configuration.host}:{self.configuration.port}; "
                "the server is bound to localhost."
            )
            uvicorn.run(
                create_app(
                    self.configuration,
                    environment=self.environment,
                    output=self.output,
                ),
                host=self.configuration.host,
                port=self.configuration.port,
                log_level="info",
            )
        except (DemoConfigurationError, RuntimeSetupError) as error:
            self.error_output(f"Configuration error: {error}")
            return 2
        except KeyboardInterrupt:
            self.output("\nStopping the local ACP web demo.")
            return 130
        return 0


CONFIGURATION = DemoConfiguration()


def main() -> int:
    return ACPWebApplication(
        configuration=CONFIGURATION,
        environment=os.environ,
    ).run()


if __name__ == "__main__":
    raise SystemExit(main())
