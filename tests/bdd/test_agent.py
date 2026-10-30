import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

import anthropic
import duckdb
import httpx2
from anthropic.types.beta import BetaMessageParam
from pytest_bdd import given, parsers, scenarios, then, when

from agentic_data_analyst.agent import answer
from agentic_data_analyst.usage import Usage

scenarios("features/agent.feature")

TOKENS_PER_CALL = 100


@dataclass
class ScriptedModels:
    """A real SDK client whose HTTP transport replays scripted responses for the analyst and the reviewer."""

    analyst: list[dict[str, Any]]
    verdicts: list[dict[str, Any]] = field(default_factory=list)
    repeat_last: bool = False
    analyst_requests: list[dict[str, Any]] = field(default_factory=list)
    reviewer_requests: list[dict[str, Any]] = field(default_factory=list)

    def client(self) -> anthropic.AsyncAnthropic:
        transport = httpx2.MockTransport(self._handle)
        return anthropic.AsyncAnthropic(api_key="test", max_retries=0, http_client=httpx2.AsyncClient(transport=transport))

    @property
    def calls(self) -> int:
        return len(self.analyst_requests) + len(self.reviewer_requests)

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        # The reviewer asks for structured output; the analyst uses tools.
        if "format" in body.get("output_config", {}):
            self.reviewer_requests.append(body)
            verdict = self.verdicts[len(self.reviewer_requests) - 1]
            return httpx2.Response(200, json=_message([{"type": "text", "text": json.dumps(verdict)}], "end_turn"))
        self.analyst_requests.append(body)
        count = len(self.analyst_requests)
        index = min(count, len(self.analyst)) - 1 if self.repeat_last else count - 1
        return httpx2.Response(200, json=self.analyst[index])


@dataclass(frozen=True)
class Outcome:
    reply: str
    usage: Usage
    history: list[BetaMessageParam]
    # (step name, failed) as reported to the UI, in order.
    steps: list[tuple[str, bool]]


def _message(content: list[dict[str, Any]], stop_reason: str) -> dict[str, Any]:
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-5-5",
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": TOKENS_PER_CALL, "output_tokens": 10},
    }


def _tool_call(name: str, arguments: dict[str, Any], call_id: str = "toolu_test") -> dict[str, Any]:
    return _message([{"type": "tool_use", "id": call_id, "name": name, "input": arguments}], "tool_use")


def _text(text: str) -> dict[str, Any]:
    return _message([{"type": "text", "text": text}], "end_turn")


def _tool_results(models: ScriptedModels) -> list[dict[str, Any]]:
    """Every tool result the analyst received, in order, from the conversation of its last request."""
    messages = models.analyst_requests[-1]["messages"]
    blocks = [block for message in messages if isinstance(message["content"], list) for block in message["content"]]
    return [block for block in blocks if block.get("type") == "tool_result"]


@given(
    parsers.parse('the analyst lists tables, describes "{table}", runs "{sql}", shows a table and a chart and answers "{text}"'),
    target_fixture="models",
)
def analyst_full_flow(table: str, sql: str, text: str) -> ScriptedModels:
    chart = {"kind": "bar", "x": "handle", "y": "method", "color": None, "title": "AI agents"}
    return ScriptedModels(
        [
            _tool_call("list_tables", {}, "toolu_tables"),
            _tool_call("describe_table", {"table": table}, "toolu_table"),
            _tool_call("run_sql", {"sql": sql}, "toolu_sql"),
            _tool_call("show_table", {}, "toolu_table_view"),
            _tool_call("show_chart", chart, "toolu_chart"),
            _text(text),
        ]
    )


@given(parsers.parse('the analyst runs "{sql}" and answers "{text}"'), target_fixture="models")
def analyst_runs(sql: str, text: str) -> ScriptedModels:
    return ScriptedModels([_tool_call("run_sql", {"sql": sql}), _text(text)])


@given(parsers.parse('the analyst calls "{tool}" with \'{arguments}\' and answers "{text}"'), target_fixture="models")
def analyst_calls(tool: str, arguments: str, text: str) -> ScriptedModels:
    return ScriptedModels([_tool_call(tool, json.loads(arguments)), _text(text)])


@given("the reviewer approves")
def reviewer_approves(models: ScriptedModels) -> None:
    models.verdicts.append({"approved": True, "issues": ""})


@given(parsers.parse('the reviewer rejects with "{issues}"'))
def reviewer_rejects(models: ScriptedModels, issues: str) -> None:
    models.verdicts.append({"approved": False, "issues": issues})


@given("the analyst refuses", target_fixture="models")
def analyst_refuses() -> ScriptedModels:
    return ScriptedModels([_message([], "refusal")])


@given(parsers.parse('the analyst keeps calling "{tool}"'), target_fixture="models")
def analyst_loops(tool: str) -> ScriptedModels:
    return ScriptedModels([_tool_call(tool, {})], repeat_last=True)


def _ask(models: ScriptedModels, con: duckdb.DuckDBPyConnection, question: str, budget_usd: float) -> Outcome:
    history: list[BetaMessageParam] = [{"role": "user", "content": question}]
    steps: list[tuple[str, bool]] = []

    async def show(name: str, arguments: dict[str, Any], output: str, failed: bool) -> None:
        steps.append((name, failed))

    reply, usage = asyncio.run(answer(models.client(), con, history, on_tool=show, budget_usd=budget_usd))
    return Outcome(reply, usage, history, steps)


@when(parsers.parse('the user asks "{question}"'), target_fixture="outcome")
def user_asks(models: ScriptedModels, con: duckdb.DuckDBPyConnection, question: str) -> Outcome:
    return _ask(models, con, question, budget_usd=100.0)


@when(parsers.parse('the user asks "{question}" with a budget of ${budget:f}'), target_fixture="outcome")
def user_asks_with_budget(models: ScriptedModels, con: duckdb.DuckDBPyConnection, question: str, budget: float) -> Outcome:
    return _ask(models, con, question, budget_usd=budget)


@then(parsers.parse('the reply is "{text}"'))
def reply_is(outcome: Outcome, text: str) -> None:
    assert outcome.reply == text


@then(parsers.parse('the reply mentions "{text}"'))
def reply_mentions(outcome: Outcome, text: str) -> None:
    assert text in outcome.reply


@then("the reply asks for a narrower question")
def reply_asks_for_narrower_question(outcome: Outcome) -> None:
    assert "narrower question" in outcome.reply


@then(parsers.parse('the analyst received rows whose first value is "{value}"'))
def received_rows(models: ScriptedModels, value: str) -> None:
    result = next(result for result in _tool_results(models) if result["tool_use_id"] == "toolu_sql")
    assert not result.get("is_error"), result
    assert json.loads(result["content"])["rows"][0][0] == value


@then(parsers.parse('the analyst received an error mentioning "{text}"'))
def received_error(models: ScriptedModels, text: str) -> None:
    result = _tool_results(models)[-1]
    assert result["is_error"] is True
    assert text in result["content"]


@then(parsers.parse("the token use of {calls:d} API calls is added up"))
def token_use_added_up(models: ScriptedModels, outcome: Outcome, calls: int) -> None:
    assert models.calls == calls
    assert outcome.usage.input_tokens == calls * TOKENS_PER_CALL


@then(parsers.parse('the user sees the steps "{names}"'))
def steps_shown(outcome: Outcome, names: str) -> None:
    assert outcome.steps == [(name, False) for name in names.split(", ")]


@then(parsers.parse('the user sees the failed steps "{names}"'))
def failed_steps_shown(outcome: Outcome, names: str) -> None:
    assert outcome.steps == [(name, True) for name in names.split(", ")]
