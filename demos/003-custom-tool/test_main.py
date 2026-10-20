from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

from copilot.tools import ToolInvocation
import pytest

MODULE_PATH = Path(__file__).with_name("main.py")
MODULE_SPEC = importlib.util.spec_from_file_location("custom_tool_demo", MODULE_PATH)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
custom_tool_demo = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules[MODULE_SPEC.name] = custom_tool_demo
MODULE_SPEC.loader.exec_module(custom_tool_demo)


class TestCustomToolDemo:
    @pytest.fixture(autouse=True)
    def setup_application(self) -> None:
        self.output: list[str] = []
        self.errors: list[str] = []
        self.application = custom_tool_demo.CustomToolApplication(
            output=self.output.append,
            error_output=self.errors.append,
        )

    def test_sdk_rejects_invalid_tool_arguments_before_the_handler(self) -> None:
        handler = custom_tool_demo.get_requirement.handler
        assert handler is not None
        assert handler is not None

        result = asyncio.run(
            handler(
                ToolInvocation(
                    tool_name="get_requirement",
                    arguments={"number": "not-an-issue"},
                )
            )
        )

        assert result.result_type == "failure"
        assert "Invalid tool arguments" in result.text_result_for_llm

    def test_define_tool_builds_schema_from_pydantic_model(self) -> None:
        schema = custom_tool_demo.get_requirement.parameters

        assert schema is not None
        assert schema is not None
        assert custom_tool_demo.get_requirement.name == "get_requirement"
        assert schema["properties"]["number"]["type"] == "integer"
        assert "number" in schema["required"]

    def test_catalog_returns_the_local_issue_snapshot(self) -> None:
        catalog = custom_tool_demo.RequirementCatalog(
            custom_tool_demo.ISSUE_FIXTURE
        )

        payload = json.loads(catalog.get(1048))

        assert payload["number"] == 1048
        assert payload["repository"] == "beancount/beancount"
        assert "DivisionByZero" in payload["body"]
        assert payload["acceptance_criteria"]

    def test_unknown_issue_number_is_rejected(self) -> None:
        catalog = custom_tool_demo.RequirementCatalog(
            custom_tool_demo.ISSUE_FIXTURE
        )

        with pytest.raises(ValueError) as context:
            catalog.get(9999)

        assert "9999" in str(context.value)
        assert "1048" in str(context.value)

    def test_missing_fixture_fails_with_setup_guidance(self) -> None:
        missing_fixture = MODULE_PATH.parent / "fixtures" / "missing-issue.json"
        configuration = replace(
            custom_tool_demo.CONFIGURATION,
            fixture_path=missing_fixture,
        )

        exit_code = self.application.run(configuration)

        assert exit_code == 2
        assert "Prepare the local issue snapshot" in self.errors[0]

    def test_empty_prompt_is_rejected(self) -> None:
        configuration = replace(custom_tool_demo.CONFIGURATION, prompt="   ")

        exit_code = self.application.run(configuration)

        assert exit_code == 2
        assert "prompt must not be empty" in self.errors[0]

    def test_requirement_tool_reads_the_configured_fixture(self) -> None:
        snapshot = json.loads(
            custom_tool_demo.ISSUE_FIXTURE.read_text(encoding="utf-8")
        )
        snapshot["title"] = "Configured fixture title"
        with tempfile.TemporaryDirectory() as directory:
            fixture_path = Path(directory) / "issue.json"
            fixture_path.write_text(
                json.dumps(snapshot),
                encoding="utf-8",
            )
            tool = custom_tool_demo.build_requirement_tool(fixture_path)
            assert tool.handler is not None
            assert tool.handler is not None
            result = asyncio.run(
                tool.handler(
                    ToolInvocation(
                        tool_name="get_requirement",
                        arguments={"number": 1048},
                    )
                )
            )

        payload = json.loads(result.text_result_for_llm)
        assert result.result_type == "success"
        assert payload["title"] == "Configured fixture title"

    def test_real_agent_uses_get_requirement_and_answers_from_the_fixture(self) -> None:
        exit_code = self.application.run(custom_tool_demo.CONFIGURATION)

        failure = (
            "The live GitHub Copilot SDK session failed. Verify network access, "
            "an active Copilot subscription, and CLI authentication with "
            "`copilot -p 'Reply with OK' --silent`.\n"
            + "\n".join(self.errors)
        )
        rendered = "\n".join(self.output)
        assert exit_code == 0, failure
        assert (
            "MCP server names disabled for this session: "
            + ", ".join(custom_tool_demo.DISABLED_MCP_SERVERS)
        ) in rendered
        assert "Model: auto" in rendered
        assert '"number": {' in rendered
        assert "[event] session.start" in rendered
        assert "[event] assistant.turn_start" in rendered
        assert "[event] tool.execution_start" in rendered
        assert "[event] tool.execution_complete" in rendered
        assert "[event] session.idle" in rendered
        assert "[tool] start get_requirement" in rendered
        assert "[tool] issue number 1048" in rendered
        assert "1048" in rendered
        assert "[tool] complete success=True" in rendered
        assert "[lifecycle] Session closed" in rendered
        assert "[lifecycle] Copilot client closed" in rendered
        assert "Copilot response:" in rendered
        assert rendered.count("[event] assistant.turn_start") >= \
            2, \
            "One session.send_and_wait() should run at least two model turns"
        response = rendered.split("Copilot response:", 1)[1].lower()
        assert "divisionbyzero" in response or "total cost" in response or "zero" in response, \
            "The final answer should use data returned by get_requirement"
