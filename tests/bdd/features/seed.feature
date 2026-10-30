Feature: Synthetic speedrun data
  As a developer
  I want realistic, reproducible seed data
  So that demos and tests tell the same story every time

  Scenario: The seed is deterministic
    When the seed is generated twice
    Then both databases contain the same rows

  Scenario: Only completed runs have a time
    Then every completed run has a time and frames
    And no reset or DNF run has a time

  Scenario: Humans and AI agents are told apart
    Then human runners have a country and AI agents do not
    And the AI methods are "imitation_learning, llm_agent, reinforcement_learning, tas_search"

  Scenario: Splits add up to the run time
    Then the last split of every completed run equals its time

  Scenario: Tool-assisted search beats the best human
    Then in every category the best "tas_search" time is lower than the best human time
