# Agent Similar Case

## ADDED Requirements

### Requirement: SimilarCasePlanner

The system SHALL provide a `SimilarCasePlanner` agent that parses the user query and selects the optimal search strategy.

The planner MUST:
- Accept a user query string plus optional filter parameters
- Analyze the query to determine whether vector search, keyword search, or hybrid search is most appropriate
- Return an execution plan with the selected strategy, extracted keywords, and any filter parameters

#### Scenario: Planner selects vector strategy for semantic query

WHEN a user submits a natural-language query such as "labor contract dispute over unpaid overtime"
THEN `SimilarCasePlanner.run()` SHALL return an execution plan with strategy set to `vector`
AND the plan MUST include the original query text and any extracted filter constraints.

#### Scenario: Planner selects keyword strategy for citation query

WHEN a user submits a query containing specific law article numbers or case citation identifiers
THEN `SimilarCasePlanner.run()` SHALL return an execution plan with strategy set to `keyword`
AND the plan MUST include the extracted citation identifiers.

#### Scenario: Planner selects hybrid strategy for complex query

WHEN a user submits a query that combines semantic intent with specific legal terms
THEN `SimilarCasePlanner.run()` SHALL return an execution plan with strategy set to `hybrid`
AND the plan MUST include both the semantic query text and extracted keyword terms.

---

### Requirement: SimilarCaseExecutor

The system SHALL provide a `SimilarCaseExecutor` agent that runs retrieval, reranking, and similarity scoring.

The executor MUST:
- Accept the execution plan from `SimilarCasePlanner`
- Invoke the appropriate retrieval method from the existing `retrieval.py` service
- Apply reranking using the existing `similar_case_search.py` service
- Compute similarity scores for each result
- Return a raw result containing ranked cases with scores

#### Scenario: Executor retrieves and ranks cases

WHEN `SimilarCaseExecutor.run()` receives a plan with strategy `hybrid`
THEN it SHALL call both vector and keyword retrieval from `retrieval.py`
AND merge and rerank the results using the existing reranking pipeline
AND return results ordered by descending similarity score.

#### Scenario: Executor returns empty result for no matches

WHEN the retrieval step returns zero matching cases
THEN `SimilarCaseExecutor.run()` SHALL return a raw result with an empty cases list
AND the result MUST include a `total_found` field set to 0.

---

### Requirement: SimilarCaseValidator

The system SHALL provide a `SimilarCaseValidator` agent that validates results and enriches citations.

The validator MUST:
- Accept the raw result from `SimilarCaseExecutor`
- Verify that each result has traceable citations (court name, case number, date)
- Enrich missing citation fields where possible using available metadata
- Validate the result schema matches `SearchResponse`

#### Scenario: Validator approves results with complete citations

WHEN all retrieved cases have complete citation fields
THEN `SimilarCaseValidator.run()` SHALL return a validated output containing the results unchanged.

#### Scenario: Validator enriches incomplete citations

WHEN one or more cases are missing citation fields that can be derived from available metadata
THEN the validator SHALL populate those fields
AND include an enrichment log entry indicating which fields were added.

#### Scenario: Validator rejects results with untraceable citations

WHEN a case result has no identifiable court, case number, or date and enrichment is not possible
THEN the validator SHALL remove that case from the result set
AND log a validation warning indicating the removed case and the reason.

---

### Requirement: Integration with Existing Services

The similar case agent pipeline SHALL integrate with the existing `retrieval.py` and `similar_case_search.py` services without modifying their public APIs.

The pipeline MUST use the existing service functions as the retrieval backend and MUST NOT duplicate retrieval logic within agent code.

#### Scenario: Pipeline calls existing retrieval service

WHEN the executor runs a search step
THEN it SHALL call the existing retrieval functions from `retrieval.py` with the same parameters the current API uses
AND the function signatures invoked MUST match the current service API exactly.

#### Scenario: Pipeline calls existing reranking service

WHEN the executor runs a reranking step
THEN it SHALL call the existing reranking functions from `similar_case_search.py`
AND the reranking output MUST be identical to the current service output.

---

### Requirement: SearchResponse Schema Compatibility

The similar case agent pipeline SHALL return the same `SearchResponse` schema as the current `/api/search` endpoint.

Every validated output from `SimilarCaseValidator` MUST serialize to a `SearchResponse` object that is structurally identical to the response currently returned by the search router.

#### Scenario: Output schema matches current API

WHEN the pipeline produces a validated output
THEN the output SHALL be an instance of `SearchResponse`
AND all fields present in the current API response MUST be present with the same types and structure.

#### Scenario: Frontend receives identical response format

WHEN the frontend consumes the pipeline output via the API endpoint
THEN the response JSON structure SHALL be indistinguishable from the current `/api/search` response
AND no frontend changes SHALL be required to consume the new pipeline output.
