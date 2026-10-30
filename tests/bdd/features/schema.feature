Feature: Schema inspection
  As the analyst agent
  I want the database to describe itself, one small piece at a time
  So that I can write correct SQL without seeing any rows

  Scenario: The tables describe themselves
    When the analyst lists the tables
    Then it sees the tables "categories, games, levels, runners, runs, splits"
    And every table has a description

  Scenario: A table describes its columns and keys
    When the analyst describes the table "runs"
    Then every column that is not a key has a description
    And it sees the key "FOREIGN KEY (runner_id) REFERENCES runners (runner_id)"
    And it sees no rows of data

  Scenario: A composite key is shown as one key
    When the analyst describes the table "splits"
    Then it sees the key "PRIMARY KEY (run_id, level_id)"

  Scenario: Only data tables can be described
    When the analyst describes the table "duckdb_settings"
    Then it is told the table is unknown
