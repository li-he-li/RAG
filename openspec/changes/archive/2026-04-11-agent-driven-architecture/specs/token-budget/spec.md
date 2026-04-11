# Token Budget

## ADDED Requirements

### Requirement: TokenBudgetManager

The system SHALL provide a `TokenBudgetManager` that estimates token counts before API calls using `tiktoken`.

The manager MUST provide a method to estimate the token count for any string input using the appropriate tokenizer for the target model.

#### Scenario: Estimate tokens for a string

WHEN `TokenBudgetManager.estimate_tokens("Analyze this contract clause", model="deepseek-chat")` is called
THEN the method SHALL return an integer token count estimated by tiktoken (cl100k_base)
AND the count SHALL be treated as an approximation with a configurable safety margin applied.

#### Scenario: Estimate tokens for empty string

WHEN `TokenBudgetManager.estimate_tokens("", model="deepseek-chat")` is called
THEN the method SHALL return 0.

#### Scenario: Unsupported model falls back to default tokenizer

WHEN an unrecognized model name is provided
THEN the manager SHALL fall back to the `cl100k_base` tokenizer
AND log a warning that the model-specific tokenizer was not found.

#### Scenario: Safety margin applied to all estimates

WHEN a token count is estimated
THEN the manager SHALL apply a default safety margin of 25% (i.e., effective budget = context_window × 0.75)
AND the safety margin SHALL be configurable via application settings.

> **Design note**: DeepSeek-V2/V3 uses a custom BPE tokenizer that diverges significantly from cl100k_base on Chinese text (measured deviation up to 20–30%). The 25% margin absorbs this gap. If exact counting is needed, the TokenBudgetManager interface supports swapping in the DeepSeek official tokenizer (`transformers.AutoTokenizer`) without changing callers.

---

### Requirement: Budget Allocation

The `TokenBudgetManager` SHALL divide available tokens among system_prompt, retrieval_context, and generation segments.

The allocation MUST respect configurable percentage thresholds for each segment.

#### Scenario: Default allocation splits tokens evenly

WHEN a budget of 8000 tokens is allocated with default settings
THEN the manager SHALL assign tokens to system_prompt, retrieval_context, and generation segments
AND the sum of all segment allocations SHALL NOT exceed 8000 tokens.

#### Scenario: Custom allocation respects percentages

WHEN custom allocation ratios are specified (e.g., system_prompt=10%, retrieval_context=50%, generation=40%)
THEN the manager SHALL allocate tokens proportional to the given percentages
AND round down to ensure the total does not exceed the context window.

#### Scenario: Allocation accounts for fixed system prompt

WHEN the system prompt has a known token count (from cache or prior estimate)
THEN the manager SHALL subtract the system prompt tokens from the available budget first
AND allocate the remaining tokens among retrieval_context and generation.

---

### Requirement: Hard Limit Enforcement

The `TokenBudgetManager` SHALL refuse requests if the estimated total tokens exceed the model's context window.

Any request that would exceed the context window MUST be rejected before the API call is made.

#### Scenario: Request within budget is allowed

WHEN the estimated total tokens (system + context + generation) is less than the model context window
THEN the manager SHALL return a budget allocation and allow the request to proceed.

#### Scenario: Request exceeding budget is rejected

WHEN the estimated total tokens exceed the model context window
THEN the manager SHALL raise a `TokenBudgetExceededError`
AND the error MUST include the estimated total, the context window size, and the excess amount.

#### Scenario: Truncation suggestion on budget overflow

WHEN the retrieval context alone causes the budget overflow
THEN the manager SHALL suggest a truncation target for the retrieval context
AND the suggestion MUST specify the maximum number of context tokens that would fit within budget.

---

### Requirement: LRU Cache for Static Prompt Segments

The `TokenBudgetManager` SHALL maintain an LRU cache for token counts of static prompt segments to avoid repeated counting.

Segments that have not changed since the last count MUST be served from cache.

#### Scenario: Cache hit for unchanged prompt

WHEN the same prompt text is estimated twice
THEN the second call SHALL return the cached token count
AND tiktoken SHALL NOT be invoked a second time.

#### Scenario: Cache invalidation on prompt change

WHEN a prompt segment is modified (e.g., hot-reloaded template)
THEN the cached token count for that segment SHALL be invalidated
AND the next estimate call SHALL recompute the count using tiktoken.

#### Scenario: Cache eviction under memory pressure

WHEN the cache exceeds its configured maximum entry count
THEN the least-recently-used entry SHALL be evicted
AND the eviction MUST NOT affect correctness of future estimates.

---

### Requirement: Token Usage Tracking

The `TokenBudgetManager` SHALL record actual token usage after each API call.

The actual usage from the LLM API response MUST be stored and compared against the estimated budget.

#### Scenario: Record actual usage after API call

WHEN an LLM API call completes and returns `usage.prompt_tokens` and `usage.completion_tokens`
THEN the manager SHALL record the actual usage with a timestamp and correlation ID
AND the record MUST include both prompt and completion token counts.

#### Scenario: Compare actual vs estimated usage

WHEN actual usage is recorded
THEN the manager SHALL compute the delta between estimated and actual tokens
AND log a warning if the actual usage exceeds the estimate by more than 15%.

#### Scenario: Adaptive calibration adjusts safety margin

WHEN the ratio of actual-to-estimated token counts deviates by more than 15% consistently over the last 20 requests
THEN the manager SHALL automatically adjust the calibration coefficient for subsequent estimates
AND the adjustment SHALL be logged as a telemetry event with old and new coefficients.

#### Scenario: Usage statistics queryable by time range

WHEN a query is made for token usage within a time range
THEN the manager SHALL return aggregated usage statistics including: total_tokens, avg_per_request, max_single_request, avg_estimation_accuracy
AND the statistics MUST be filterable by agent name or pipeline type.
