# ADR-0002: Research through web-grounded LLM endpoints; no search-provider key

Date: M0. Status: accepted (user directive).

## Context
The original spec suggested RAG plus general search APIs requiring extra provider keys
(Tavily/Serper/Bing). User directed: research MUST use online LLM capabilities for facts and
accuracy; accuracy and efficiency outrank speed.

## Decision
The researcher role routes exclusively to web-grounded LLM endpoints via LiteLLM
(e.g., Perplexity Sonar family, Gemini with Google Search grounding, any OpenAI-compatible
endpoint exposing web search). Free keyless direct fetches (arXiv API, cited documentation URLs)
supplement citations with full text. No separate search-provider key exists anywhere in the product.
Settings validates that the researcher role maps to a web-grounded endpoint and warns otherwise.

## Accuracy-over-speed posture
- Claim-level fact sheets; every quantitative claim carries >= 2 independent citations.
- Isolated reasoner-role adversarial verifier cross-examines claims against sources; numerals
  must match exactly; contradictions force re-retrieval; loop capped at 5 rounds.
- Cite-or-cut: unresolved claims are dropped and reported; nothing unsourced reaches narration.
- Efficiency guards (waste elimination, not corner-cutting): query deduplication, per-topic
  research cache reused across jobs, batched extraction calls, hard per-stage token ceilings.
