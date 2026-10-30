from typing import Any

from pytest_bdd import parsers, scenarios, then, when

from agentic_data_analyst import settings
from agentic_data_analyst.settings import request_options
from agentic_data_analyst.usage import PRICES_PER_MILLION

scenarios("features/models.feature")


@when(parsers.parse('a request for "{model}" is prepared'), target_fixture="options")
def prepare(model: str) -> dict[str, Any]:
    return request_options(model, "low")


@then(parsers.parse("it {sends} an effort level and safety fallbacks"))
def sends_options(options: dict[str, Any], sends: str) -> None:
    if sends == "sends no":
        assert options == {}
    else:
        assert options["output_config"] == {"effort": "low"}
        assert options["fallbacks"] == "default"


@then(parsers.parse('the analyst defaults to "{analyst}" and the reviewer to "{reviewer}"'))
def defaults(analyst: str, reviewer: str) -> None:
    # The defaults, not MODEL: a local .env may override them.
    assert analyst == settings.DEFAULT_MODEL
    assert reviewer == settings.DEFAULT_REVIEWER_MODEL


@then(parsers.parse('"{model}" has a price'))
def has_price(model: str) -> None:
    assert model in PRICES_PER_MILLION
