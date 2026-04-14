# Research Pipeline Plan

## Architecture: The Hybrid Loop
The pipeline blends zero-trust human initiation with an autonomous, self-healing research loop.

1. **Stage 1: Identity (Human-Gated)**
   - Resolves company input into a verified legal name, official website, and identifiers (e.g., ticker).
   - Pauses for user confirmation to explicitly prevent entity mix-ups before deep research starts.

2. **Stages 2–5: The Autonomous Loop**
   - **Source Discovery:** Dynamically locates official pages, reputable references, and recent news (default: 90-day window).
   - **Content Fetching:** Grabs text and generates content hashes to handle deduplication and recency natively.
   - **Fact & News Extraction:** Synthesizes the core profile and summarizes recent developments.
   - **Dynamic Feedback:** If extraction reveals missing facts or contradictions, the agent autonomously triggers new, targeted discovery and fetching to fill gaps.

3. **Stage 6: Final Output (Human-Gated)**
   - Generates the final, cited Markdown report (`final.md`) and structured JSON (`report_draft.json` & `final.json`).
   - Presents to the human for final approval, refinement, or tone adjustments.

## Core Engineering Rules
To ensure no hallucinations and high debuggability, the system enforces:

- **First-Class Provenance:** Every major claim must attach a standard `citation` object (`source_id`, `canonical_url`, `published_at`, `excerpt`).
- **Artifact-Driven State:** The pipeline persists state as intermediate JSON records (`identity.json`, `sources.json`, `profile_draft.json`, `news_draft.json`).
- **Auto-Invalidation:** If the agent dynamically alters upstream context, downstream artifacts referencing older inputs are immediately marked stale and re-executed.
- **Zero Guessing:** If a fact is unknown, the agent executes targeted searches. If still unsupported, it explicitly surfaces "Unknown" or contradictory statements.

## Data Models
Data models are stored as JSON artifacts. Key concepts:

- **Identity Draft:** `resolved_name`, `legal_name`, `aliases`, `website`, `jurisdiction`, `entity_type`, `identifiers`, `ambiguities`.
- **Fetched Content:** `source_id`, `url`, `canonical_url`, `title`, `published_at`, `content_hash`.
- **Company Profile Draft:** Each extracted field (e.g., `company_name`, `industry`, `hq`) is an object with standard `citations[]` provenance.
- **News Draft:** Each item contains `headline`, `date`, `summary`, `topic`, and `citations[]`.
