from __future__ import annotations

import importlib.util
import subprocess
import sys
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
import re
from typing import Any

import pytest

MODULE_PATH = Path(__file__).with_name("main.py")
MODULE_SPEC = importlib.util.spec_from_file_location("model_choice_demo", MODULE_PATH)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
model_choice_demo = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules[MODULE_SPEC.name] = model_choice_demo
MODULE_SPEC.loader.exec_module(model_choice_demo)


class TestModelChoiceIntegration:
    def setup_method(self) -> None:
        self.output: list[str] = []
        self.errors: list[str] = []
        self.application = model_choice_demo.ModelChoiceApplication(
            output=self.output.append,
            error_output=self.errors.append,
        )

    @staticmethod
    def make_configuration(**changes: Any) -> Any:
        return replace(model_choice_demo.CONFIGURATION, **changes)

    def test_invalid_comparison_settings_fail_before_runtime_start(self) -> None:
        invalid_configurations = (
            (self.make_configuration(prompt=" "), "prompt"),
            (self.make_configuration(timeout_seconds=0), "timeout_seconds"),
            (
                self.make_configuration(models=(model_choice_demo.MODEL_CHOICES[0],)),
                "At least two models",
            ),
            (
                self.make_configuration(
                    models=(
                        model_choice_demo.MODEL_CHOICES[0],
                        model_choice_demo.MODEL_CHOICES[0],
                    )
                ),
                "unique",
            ),
        )

        for configuration, message in invalid_configurations:
            self.errors.clear()
            assert self.application.run(configuration) == 2
            assert message in self.errors[0]

    def test_repository_must_contain_the_review_fixture(self) -> None:
        configuration = self.make_configuration(
            working_directory=MODULE_PATH.parent / "missing-checkout"
        )

        assert self.application.run(configuration) == 2
        assert "beancount-1048.json" in self.errors[0]

    def test_unavailable_model_ids_fail_with_available_model_guidance(self) -> None:
        with pytest.raises(
            model_choice_demo.ConfigurationError,
            match="Choose IDs from the available-model list",
        ):
            self.application.validate_available_models(
                model_choice_demo.MODEL_CHOICES,
                {"some-other-model"},
            )

    @staticmethod
    def repository_status() -> str:
        return subprocess.run(
            ["git", "-C", str(model_choice_demo.REPOSITORY_ROOT), "status", "--short"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout

    def test_real_copilot_runtime_reports_actual_models(self) -> None:
        configuration = model_choice_demo.CONFIGURATION
        try:
            before = self.repository_status()
        except (OSError, subprocess.CalledProcessError) as error:
            pytest.fail(f"Cannot inspect the demo checkout before the live test: {error}")
        exit_code = self.application.run(configuration)

        failure = (
            "The live GitHub Copilot SDK comparison requires network access, "
            "CLI authentication, an active Copilot subscription, and access to "
            f"all configured models ({', '.join(choice.model_id for choice in configuration.models)}). "
            "Verify CLI authentication with "
            "`copilot -p 'Reply with OK' --silent`.\n"
            + "\n".join(self.errors)
        )
        rendered = "\n".join(self.output)
        assert exit_code == 0, failure
        assert rendered.count(
            "MCP server names disabled for this session: "
            + ", ".join(model_choice_demo.DISABLED_MCP_SERVERS)
        ) == len(configuration.models)
        assert "Available models:" in rendered
        assert "[lifecycle] Copilot CLI runtime connected" in rendered
        assert "[lifecycle] Copilot client closed" in rendered
        for choice in configuration.models:
            assert f"[model] {choice.role}: {choice.model_id}" in rendered
            response_header = next(
                line
                for line in rendered.splitlines()
                if line.startswith(f"[response] requested={choice.model_id};")
            )
            actual_model = (
                response_header.split("actual model=", 1)[1].split(";", 1)[0]
            )
            assert actual_model and actual_model != "not reported by runtime"
            if choice.model_id == "auto":
                assert actual_model != "auto"
            aiu = response_header.split("AIU=", 1)[1].removesuffix(":")
            assert aiu != "not fully reported by runtime"

            model_output_start = rendered.index(
                f"[model] {choice.role}: {choice.model_id}"
            )
            response_start = rendered.index(response_header)
            model_output = rendered[model_output_start:response_start].splitlines()
            checkpoint_lines = [
                line
                for line in model_output
                if line.startswith("[usage checkpoint] session total ")
            ]
            assert checkpoint_lines, (
                f"No session usage checkpoint reported for {choice.model_id}"
            )
            assert len(checkpoint_lines) == model_output.count(
                "[event] session.usage_checkpoint"
            )
            for line in checkpoint_lines:
                nano_aiu_text, aiu_text = line.split("nano_aiu=", 1)[1].split("; AIU=")
                assert Decimal(aiu_text) == (
                    Decimal(nano_aiu_text) / Decimal("1000000000")
                )
            usage_lines = [
                line
                for line in model_output
                if line.startswith("[usage] model=")
            ]
            assert usage_lines, f"No per-call AIU usage reported for {choice.model_id}"
            usage_aiu = []
            for line in usage_lines:
                match = re.search(r" AIU=([^ ]+)$", line)
                assert match is not None and match.group(1) != "not reported by runtime"
                usage_aiu.append(Decimal(match.group(1)))
            assert Decimal(aiu) == sum(usage_aiu, start=Decimal(0))
        assert rendered.count("[event] session.start") == len(configuration.models)
        assert rendered.count("[event] session.idle") == len(configuration.models)
        assert "This is a live demonstration, not a benchmark." in rendered
        assert self.repository_status() == before


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
