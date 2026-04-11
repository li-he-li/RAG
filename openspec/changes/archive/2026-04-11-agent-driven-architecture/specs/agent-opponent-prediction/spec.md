# Agent Opponent Prediction

## ADDED Requirements

### Requirement: PredictionPlanner

The system SHALL provide a `PredictionPlanner` agent that builds a case profile and infers dispute intents.

The planner MUST:
- Accept case description, uploaded documents, and optional user context
- Construct a structured case profile summarizing key facts, parties, and legal domain
- Infer the likely dispute intents and argument directions for the opposing party
- Return an execution plan with the case profile, inferred intents, and analysis steps

#### Scenario: Planner builds case profile from description

WHEN a user submits a case description with party details and dispute summary
THEN `PredictionPlanner.run()` SHALL return an execution plan containing a structured `CaseProfile`
AND the profile MUST include fields for: plaintiff, defendant, dispute_type, key_facts, legal_domain.

#### Scenario: Planner infers opponent intents

WHEN the case profile is constructed
THEN the planner SHALL generate a list of inferred opponent intents
AND each intent MUST include a description, confidence score, and supporting evidence hints.

#### Scenario: Planner handles incomplete case information

WHEN the case description lacks key information (e.g., no opposing party identified)
THEN the planner SHALL flag the missing information in the execution plan
AND include a clarification step requesting the user to provide the missing details.

---

### Requirement: PredictionExecutor

The system SHALL provide a `PredictionExecutor` agent that generates arguments, retrieves evidence, and ranks arguments.

The executor MUST:
- Accept the execution plan from `PredictionPlanner`
- Generate predicted opponent arguments based on the inferred intents
- Retrieve supporting evidence from the knowledge base for each argument
- Rank arguments by strength and relevance
- Return a raw result containing ranked arguments with evidence links

#### Scenario: Executor generates opponent arguments

WHEN `PredictionExecutor.run()` receives a plan with 3 inferred intents
THEN it SHALL generate at least one predicted argument per intent
AND each argument MUST include: argument_text, supporting_evidence_ids, strength_score.

#### Scenario: Executor retrieves evidence for arguments

WHEN an argument is generated
THEN the executor SHALL query the knowledge base for supporting evidence
AND attach the top-N evidence items to each argument, ranked by relevance.

#### Scenario: Executor ranks arguments by strength

WHEN all arguments and evidence are collected
THEN the executor SHALL sort arguments by descending strength score
AND the strength score MUST factor in: evidence quantity, evidence relevance, and legal precedence weight.

---

### Requirement: PredictionValidator

The system SHALL provide a `PredictionValidator` agent that validates report completeness and checks evidence links.

The validator MUST:
- Accept the raw result from `PredictionExecutor`
- Verify that every inferred intent has at least one corresponding argument
- Check that all evidence IDs referenced in arguments resolve to valid evidence records
- Validate that the output conforms to the `OpponentPredictionReport` schema

#### Scenario: Validator confirms complete report

WHEN all intents have arguments, all evidence links resolve, and the schema is valid
THEN `PredictionValidator.run()` SHALL return a validated `OpponentPredictionReport`.

#### Scenario: Validator detects unresolved evidence references

WHEN an argument references an evidence ID that does not exist in the knowledge base
THEN the validator SHALL remove the invalid reference
AND log a validation warning with the argument index and the invalid evidence ID.

#### Scenario: Validator detects missing arguments for intent

WHEN an inferred intent has no corresponding argument in the result
THEN the validator SHALL add a placeholder argument with status `no_prediction_generated`
AND flag the intent as incompletely analyzed.

---

### Requirement: Integration with Existing Prediction Service

The opponent prediction agent pipeline SHALL integrate with the existing `opponent_prediction.py` service.

The pipeline MUST reuse the existing service's LLM call patterns, knowledge base queries, and report generation logic.

#### Scenario: Pipeline reuses existing LLM calls

WHEN the executor generates opponent arguments
THEN it SHALL invoke the same LLM functions used by `opponent_prediction.py`
AND the prompt construction MUST follow the existing service's prompt template format.

#### Scenario: Pipeline reuses existing knowledge base queries

WHEN the executor retrieves evidence
THEN it SHALL use the same retrieval functions as the existing service
AND the retrieved evidence MUST be formatted identically to the current output.

---

### Requirement: OpponentPredictionReport Schema Compatibility

The opponent prediction agent pipeline SHALL return the same `OpponentPredictionReport` schema as the current API.

Every validated output MUST serialize to a `OpponentPredictionReport` object that is structurally identical to the response currently returned by the prediction router.

#### Scenario: Output matches current API schema

WHEN the pipeline produces a validated output
THEN the output SHALL be an instance of `OpponentPredictionReport`
AND all fields present in the current API response MUST be present with the same types and nesting.

#### Scenario: Frontend renders prediction report identically

WHEN the frontend receives the pipeline output
THEN the prediction report SHALL render without any code changes
AND the visual layout and data display MUST be identical to the current implementation.
