"""Chainlit entry point: `make run` (uv run chainlit run app.py)."""

import json
from pathlib import Path
from typing import Any, cast

import anthropic
import chainlit as cl
import pandas as pd
from anthropic.types.beta import BetaMessageParam
from loguru import logger

from agentic_data_analyst.agent import answer, parse_result
from agentic_data_analyst.charts import Chart, build_figure
from agentic_data_analyst.database import QueryResult, connect
from agentic_data_analyst.guardrails import check_question
from agentic_data_analyst.log import setup_logging
from agentic_data_analyst.settings import DATABASE_PATH, MODEL, REVIEWER_MODEL, SESSION_BUDGET_USD
from agentic_data_analyst.usage import PRICES_PER_MILLION, Usage, format_usage

setup_logging(Path(__file__).parent / "logs" / "analyst.log")

# The cost budgets need a price; without one every answer would stop after its first tool call.
for model in (MODEL, REVIEWER_MODEL):
    if model not in PRICES_PER_MILLION:
        raise SystemExit(f"No price for {model!r}: add it to PRICES_PER_MILLION in src/agentic_data_analyst/usage.py")

# One read-only connection per process; each query runs on its own cursor. The client reads ANTHROPIC_API_KEY from
# the env, which `agentic_data_analyst.settings` loads from `.env`.
DATABASE = connect(DATABASE_PATH)
CLIENT = anthropic.AsyncAnthropic()

# Shown on the empty chat; a welcome message would hide them. Tables and charts appear only when asked for, so the
# starters show a table, two chart types and a plain text answer.
STARTERS = [
    ("AI vs humans", "Show a table of who holds the best time in each game and category: an AI agent or a human?"),
    ("AI progress", "Plot how the best AI times in Serpent Scramble Any% improved per quarter."),
    ("Where AI wins", "Show a bar chart of the Serpent Scramble levels where AI agents gain the most time over humans."),
    ("Resets", "How often do humans reset compared to each AI method?"),
]


@cl.set_starters
async def set_starters() -> list[cl.Starter]:
    return [cl.Starter(label=label, message=message) for label, message in STARTERS]


@cl.on_chat_start
async def on_chat_start() -> None:
    cl.user_session.set("history", [])
    cl.user_session.set("usage", Usage())


class FlowView:
    """Shows one answer's flow as nested steps and a trail, and collects the tables and charts the analyst chose to show.

    Analyst -> list_tables -> describe_table -> SQL Reviewer -> DuckDB -> chart -> answer
    """

    def __init__(self) -> None:
        self.trail: list[str] = ["Analyst"]
        self.elements: list[cl.Element] = []
        self.latest: QueryResult | None = None

    async def show_step(self, name: str, arguments: dict[str, Any], output: str, failed: bool) -> None:
        mark = " ✗" if failed else ""
        match name:
            case "list_tables":
                await self._step("Analyst · list tables", "tool", "json", None, self._pretty(output, failed))
                self.trail.append(f"tables{mark}")
            case "describe_table":
                table = arguments.get("table", "?")
                await self._step(f"Analyst · describe {table}", "tool", "json", None, self._pretty(output, failed))
                self.trail.append(f"schema {table}{mark}")
            case "review_sql":
                # The generated SQL comes first, as the input the reviewer judged.
                verdict = f"Rejected: {output}" if failed else "Approved"
                await self._step("SQL Reviewer", "llm", "sql", arguments["sql"], verdict)
                self.trail.append("reviewer ✗" if failed else "reviewer ✓")
            case "run_sql":
                await self._show_query(arguments["sql"], output, failed)
            case "show_table":
                await self._show_table(output, failed)
            case "show_chart":
                await self._show_chart(arguments, output, failed)
            case _:
                await self._step(f"Analyst · {name}", "tool", None, None, output)
                self.trail.append(f"{name}{mark}")

    async def _show_query(self, sql: str, output: str, failed: bool) -> None:
        if failed:
            await self._step("DuckDB", "tool", "sql", sql, f"Not run: {output}")
            self.trail.append("DuckDB ✗")
            return
        result = parse_result(output)
        rows = f"{len(result.rows)} rows" + (" (truncated)" if result.truncated else "")
        await self._step("DuckDB", "tool", "sql", sql, rows)
        self.trail.append(f"DuckDB {rows}")
        self.latest = result

    async def _show_table(self, output: str, failed: bool) -> None:
        await self._step("Table", "tool", None, None, output)
        if failed or self.latest is None:
            self.trail.append("table ✗")
            return
        self.trail.append("table")
        frame = pd.DataFrame(self.latest.rows, columns=self.latest.columns)
        self.elements.append(cl.Dataframe(name=f"Table {len(self.elements) + 1}", data=frame))

    async def _show_chart(self, arguments: dict[str, Any], output: str, failed: bool) -> None:
        figure = None if failed or self.latest is None else build_figure(cast(Chart, arguments), self.latest)
        await self._step("Chart", "tool", None, None, output)
        self.trail.append(f"{arguments.get('kind', 'chart')} chart" + (" ✗" if figure is None else ""))
        if figure is not None:
            self.elements.append(cl.Plotly(name=f"Chart {len(self.elements) + 1}", figure=figure))

    @staticmethod
    async def _step(name: str, kind: str, language: str | None, step_input: str | None, output: str) -> None:
        async with cl.Step(name=name, type=kind, language=language) as step:
            if step_input is not None:
                step.input = step_input
            step.output = output

    @staticmethod
    def _pretty(output: str, failed: bool) -> str:
        return output if failed else json.dumps(json.loads(output), indent=2, ensure_ascii=False)


@cl.on_message
async def on_message(message: cl.Message) -> None:
    rejection = check_question(message.content)
    if rejection is not None:
        logger.info("Question rejected before the model: {}", rejection)
        await cl.Message(content=rejection).send()
        return
    spent: Usage = cl.user_session.get("usage")
    if spent.cost_usd is None or spent.cost_usd >= SESSION_BUDGET_USD:
        await cl.Message(content=f"This chat reached its cost limit of ${SESSION_BUDGET_USD:.2f}. Please start a new chat.").send()
        return
    history: list[BetaMessageParam] = cl.user_session.get("history")
    history.append({"role": "user", "content": message.content})
    view = FlowView()
    try:
        # Every step of the flow nests under this one, so the whole multi-agent run reads as one tree.
        async with cl.Step(name="Analyst", type="run") as flow:
            flow.input = message.content
            reply, usage = await answer(CLIENT, DATABASE, history, on_tool=view.show_step)
            flow.output = " → ".join(view.trail[1:]) or "answered directly"
    except anthropic.APIConnectionError:
        logger.exception("Claude API unreachable")
        await cl.Message(content="I can't reach the language model right now. Please try again in a moment.").send()
        return
    except anthropic.APIStatusError as error:
        logger.exception("Claude API error {}", error.status_code)
        await cl.Message(content="The language model returned an error. Please try again.").send()
        return
    session_usage = spent + usage
    cl.user_session.set("usage", session_usage)
    # The flow and the SQL stay in the collapsed Analyst step; the answer shows only the reply, tables and charts.
    await cl.Message(content=reply, elements=view.elements).send()
    # A separate message, because Chainlit renders inline elements below the text: this keeps the cost line last.
    await cl.Message(content=f"*{format_usage(usage, session_usage)}*").send()
