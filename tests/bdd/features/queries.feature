Feature: Guarded execution of generated SQL
  As an operator
  I want generated SQL to only ever read the speedrun data
  So that a wrong or malicious query cannot change data, read files, leak secrets or run forever

  These checks are deterministic: they hold whatever the model or the reviewer agent decides.

  Scenario: A SELECT returns rows
    When the analyst runs "SELECT kind, COUNT(*) AS runners FROM runners GROUP BY kind ORDER BY kind"
    Then the result has the columns "kind, runners"
    And the first row is "ai, 6"

  Scenario: Common table expressions and generators are allowed
    When the analyst runs "WITH q AS (SELECT * FROM range(3) t(n)) SELECT COUNT(*) AS n FROM q"
    Then the first row is "3"

  Scenario Outline: Anything but one SELECT over the data tables is rejected before it runs
    When the analyst runs "<sql>"
    Then the query is rejected with "<reason>"

    Examples:
      | sql                                        | reason                  |
      | DELETE FROM runs                           | Only SELECT             |
      | UPDATE runs SET time_seconds = 1           | Only SELECT             |
      | DROP TABLE runs                            | Only SELECT             |
      | COPY runs TO 'stolen.csv'                  | Only SELECT             |
      | ATTACH 'other.duckdb'                      | Only SELECT             |
      | SET threads = 1                            | Only SELECT             |
      | INSTALL httpfs                             | Only SELECT             |
      | SELECT 1; DELETE FROM runs                 | exactly one             |
      | SELEC 1                                    | syntax error            |
      | SELECT * FROM read_csv('pyproject.toml')   | Table functions         |
      | SELECT * FROM read_text('.env')            | Table functions         |
      | SELECT * FROM duckdb_settings()            | Table functions         |
      | SELECT * FROM 'pyproject.toml'             | Only the tables         |
      | SELECT * FROM information_schema.tables    | Only the tables         |

  Scenario Outline: The database itself blocks what the allowlist cannot see
    When the database runs "<sql>" without the allowlist
    Then the query is rejected

    Examples:
      | sql                                            |
      | SELECT * FROM read_csv('pyproject.toml')       |
      | SELECT * FROM read_json('https://example.com') |
      | SELECT getenv('ANTHROPIC_API_KEY')             |
      | SET memory_limit = '100GB'                     |
      | INSERT INTO runners VALUES (99, 'x', 'ai', 'x', NULL, DATE '2026-01-01') |

  Scenario: Large results are cut off
    When the analyst runs "SELECT * FROM splits"
    Then the result has 200 rows and is marked as truncated

  Scenario: Slow queries are stopped
    When the analyst runs "SELECT COUNT(*) FROM range(100000000000)" with a timeout of 0.2 seconds
    Then the query is rejected with "longer than"
