Feature: Charts
  As a user
  I want a fitting chart next to a result
  So that I see trends and comparisons at a glance

  Background:
    Given a result with the columns "quarter, kind, best_seconds"

  Scenario: A line chart shows one series per color value
    When the analyst asks for a "line" chart of "best_seconds" by "quarter" split by "kind"
    Then the figure has 2 series

  Scenario: A bar chart without a split has one series
    When the analyst asks for a "bar" chart of "best_seconds" by "kind"
    Then the figure has 1 series

  Scenario: A chart naming a missing column is rejected
    When the analyst asks for a "bar" chart of "time_seconds" by "quarter"
    Then the chart is rejected with "not in the result columns"
