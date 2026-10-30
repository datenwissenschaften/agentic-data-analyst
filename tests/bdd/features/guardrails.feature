Feature: Guardrails
  As an operator
  I want the analyst to resist misuse
  So that users never get invented numbers and attackers get nothing

  Attacks that need the model (prompt injection, prompt leaks) can only be tested against the real model. The
  deterministic database boundary that limits their damage is covered in queries.feature.

  Scenario Outline: Unusable messages are rejected before they reach the model
    When the user sends a message of <length> characters
    Then it is rejected with "<reply>"

    Examples:
      | length | reply                                             |
      | 0      | Please type a question about the speedrun data.   |
      | 2001   | Please keep your question under 2,000 characters. |

  Scenario: A normal question reaches the model
    When the user sends a message of 2000 characters
    Then it is not rejected

  Scenario: The model can only call the tools with valid arguments
    Then every tool schema is strict and allows no extra arguments
