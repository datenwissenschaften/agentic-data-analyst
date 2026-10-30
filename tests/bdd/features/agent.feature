Feature: Multi-agent flow
  As a user
  I want answers built from SQL that one agent wrote and another reviewed
  So that every number comes from the data, not from the model

  Flow: analyst lists tables -> describes the ones it needs -> writes SQL -> deterministic checks -> reviewer agent
  judges it -> DuckDB runs it -> analyst shows a table or chart if asked -> analyst answers from the rows. Both
  models are scripted, so these scenarios run without API calls or cost.

  Scenario: The full flow from schema to table and chart
    Given the analyst lists tables, describes "runners", runs "SELECT handle, method FROM runners WHERE kind = 'ai' ORDER BY handle", shows a table and a chart and answers "Six agents."
    And the reviewer approves
    When the user asks "Show a table and a chart of the AI agents"
    Then the reply is "Six agents."
    And the analyst received rows whose first value is "Frame Oracle"
    And the token use of 7 API calls is added up
    And the user sees the steps "list_tables, describe_table, review_sql, run_sql, show_table, show_chart"

  Scenario: A rejected query goes back to the analyst and is not run
    Given the analyst runs "SELECT MIN(time_seconds) AS best FROM runs" and answers "I need a category first."
    And the reviewer rejects with "Times from different categories are mixed."
    When the user asks "What is the best time?"
    Then the reply is "I need a category first."
    And the analyst received an error mentioning "Times from different categories are mixed."
    And the user sees the failed steps "review_sql, run_sql"

  Scenario: Unsafe SQL is stopped before the reviewer, so it costs no review
    Given the analyst runs "DELETE FROM runs" and answers "I can only read data."
    When the user asks "Delete all runs"
    Then the reply is "I can only read data."
    And the analyst received an error mentioning "Only SELECT"
    And the token use of 2 API calls is added up

  Scenario: A table needs a query result first
    Given the analyst calls "show_table" with '{}' and answers "No data yet."
    When the user asks "Show a table"
    Then the analyst received an error mentioning "Run a query"

  Scenario: A chart needs a query result first
    Given the analyst calls "show_chart" with '{"kind": "bar", "x": "handle", "y": "runs", "color": null, "title": "Runs"}' and answers "No data yet."
    When the user asks "Chart something"
    Then the analyst received an error mentioning "Run a query"

  Scenario: The analyst cannot call a tool that does not exist
    Given the analyst calls "delete_data" with '{}' and answers "That is not possible."
    When the user asks "Delete the data"
    Then the analyst received an error mentioning "Unknown tool"

  Scenario: A safety refusal gets a fixed reply
    Given the analyst refuses
    When the user asks "Something harmful"
    Then the reply is "I can't help with that request."

  Scenario: The flow is bounded
    Given the analyst keeps calling "list_tables"
    When the user asks "Tell me everything"
    Then the reply asks for a narrower question
    And the token use of 8 API calls is added up

  Scenario: An answer stops at its cost budget
    Given the analyst keeps calling "list_tables"
    When the user asks "Tell me everything" with a budget of $0.00
    Then the reply mentions "cost limit"
    And the token use of 1 API calls is added up
