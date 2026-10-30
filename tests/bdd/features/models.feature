Feature: Model options
  As an operator
  I want each model to get only the request options it accepts
  So that switching to the cheapest model does not break the requests

  Scenario Outline: Effort and safety fallbacks are sent only where the model supports them
    When a request for "<model>" is prepared
    Then it <sends> an effort level and safety fallbacks

    Examples:
      | model                     | sends         |
      | claude-haiku-4-5          | sends no      |
      | claude-haiku-4-5-20251001 | sends no      |
      | claude-sonnet-5-5         | sends         |
      | claude-opus-5-5           | sends         |

  Scenario: The cheapest model is the default and has a price
    Then both agents default to "claude-haiku-4-5"
    And "claude-haiku-4-5" has a price
