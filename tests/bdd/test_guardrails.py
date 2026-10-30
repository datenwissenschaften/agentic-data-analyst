from typing import Any

from pytest_bdd import parsers, scenarios, then, when

from agentic_data_analyst.agent import TOOLS
from agentic_data_analyst.guardrails import check_question

scenarios("features/guardrails.feature")


@when(parsers.parse("the user sends a message of {length:d} characters"), target_fixture="rejection")
def send_message(length: int) -> str | None:
    return check_question("a" * length)


@then(parsers.parse('it is rejected with "{reply}"'))
def rejected_with(rejection: str | None, reply: str) -> None:
    assert rejection == reply


@then("it is not rejected")
def not_rejected(rejection: str | None) -> None:
    assert rejection is None


def _objects(schema: dict[str, Any]) -> list[dict[str, Any]]:
    nested = [_objects(value) for value in schema.get("properties", {}).values() if value.get("type") == "object"]
    return [schema, *(item for objects in nested for item in objects)]


@then("every tool schema is strict and allows no extra arguments")
def tools_are_strict() -> None:
    for tool in TOOLS:
        assert tool.get("strict") is True
        for schema in _objects(dict(tool["input_schema"])):
            assert schema.get("additionalProperties") is False
            assert sorted(schema.get("required", [])) == sorted(schema.get("properties", {}))
