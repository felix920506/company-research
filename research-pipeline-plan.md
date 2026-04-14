# Research Pipeline Plan

## Goal
Build the research pipeline first as the core of the system: given a company name, produce a basic introduction to the company with a strong emphasis on what it has been doing lately, backed by recent news and source links.

This plan intentionally focuses only on the research pipeline. API design, persistence details, and the rest of the application can be finalized after the pipeline is solid.

## v1 Scope
The pipeline should produce:
- company identity and official website
- short company overview
- industry / category
- headquarters
- leadership
- products or services
- recent news and notable developments
- source links for all major claims
- open questions or unresolved details

The pipeline should not yet focus on:
- deep financial analysis
- competitor analysis
- browser automation
- UI details beyond what the pipeline needs
- advanced multi-agent complexity without a clear benefit

## Core Principle
The pipeline is anchored by initial zero-trust validation, followed by an autonomous, dynamic research loop.

Workflow:
1. **Human-Gated Initiation:** The user confirms the exact company identity (Stage 1).
2. **Autonomous Research Loop:** Stages 2 through 5 operate dynamically without pauses. The agent discovers sources, fetches content, and extracts facts. If the extracted data reveals gaps or leads to new inquiries (e.g., finding a subsidiary that requires its own search), the system autonomously loops back to discover and fetch more data.
3. **Artifact-Driven State:** The system continually updates intermediate drafts, preserving provenance at each step for debuggability, but does not block on human approval.
4. **Final Approval:** The drafted report is presented for human review (Stage 6).

This hybrid approach ensures high initial accuracy (preventing entity mixups) while allowing the agent the freedom to perform deep, iterative research.

## Stage Overview
1. Identity resolution
2. Source discovery
3. Content gathering
4. Company profile extraction
5. Recent news extraction
6. Final report drafting

## Stage 1: Identity Resolution
### Purpose
Confirm the exact company being researched.

### Inputs
- company name
- optional website hint
- optional location hint

### Tasks
- normalize the company name, including legal name and aliases
- identify the official website and jurisdiction
- resolve entity type and standard identifiers (e.g., ticker, wikidata)
- detect ambiguous matches and assign confidence
- produce a short description seed

### Outputs
- resolved company name, legal name, and aliases
- official website
- jurisdiction and entity type
- structured identifiers
- description seed
- ambiguity notes with candidates

### Review Gate
The user can:
- approve the company identity
- edit the resolved details
- reject and retry with better hints

### Exit Criteria
Proceed only when the correct company has been confirmed.

## Stage 2: Source Discovery
### Purpose
Select the best sources for a basic introduction and recent news.

### Inputs
- resolved company identity
- target date window for news (default 90 days)

### Source Priority
1. official company website
2. about page
3. newsroom / press page
4. recent reputable news articles
5. reference pages such as Wikipedia or Wikidata if useful
6. official social or company profile pages if accessible and helpful

### Tasks
- discover relevant URLs
- rank sources by trust and usefulness
- group sources by type: official, reference, news
- filter out spammy, duplicate, or low-value sources

### Outputs
- selected official sources
- selected reference sources
- selected news sources

### Autonomous Flow
This stage runs autonomously. The system may continuously refine the source list, appending new URLs as later data gathering or extraction stages uncover gaps in knowledge.

## Stage 3: Content Gathering
### Purpose
Fetch and normalize the selected sources so later stages work from clean input.

### Tasks
- fetch approved URLs
- extract clean page text and generate content hash
- record titles, URLs, canonical URLs, published timestamps, and access timestamps
- detect failures, duplicates (using hashes or URLs), or thin-content pages

### Outputs
- fetched source records
- cleaned content previews
- failed source list

### Autonomous Flow
This stage runs autonomously. Failed or thin content triggers automatic retry or alternative source discovery without human intervention.

## Stage 4: Company Profile Extraction
### Purpose
Create a basic company introduction from the approved content.

### Fields
- company name
- website
- one-paragraph description
- industry / category
- headquarters
- leadership
- products or services
- source links for each major claim

### Tasks
- extract supported facts only
- attach citations to each major field with excerpt/span provenance, allowing multiple competing citations
- mark uncertain or unresolved fields
- avoid inventing missing information

### Outputs
- structured company profile draft
- confidence notes
- unresolved questions

### Autonomous Flow
This stage operates dynamically. If extraction reveals that key facts are missing or poorly supported, the agent can trigger new searches (looping back to Stages 2 and 3) to fill the gaps autonomously.

## Stage 5: Recent News Extraction
### Purpose
Capture what the company has been up to lately.

### Default Focus
Recent developments within a user-defined or default date window, such as the last 90 days.

### News Item Fields
- headline
- date
- source name or URL
- short summary
- topic tag such as product, funding, partnership, acquisition, legal, hiring, or launch

### Tasks
- identify recent relevant news from approved sources
- summarize each item in 1 to 3 sentences
- remove duplicates covering the same event
- prefer high-signal items over low-value mentions

### Outputs
- reviewed list of recent news items
- topic tags
- date window used

### Autonomous Flow
This stage dynamically aggregates news. The system can independently expand the date window or launch new specific queries if the initial sweep fails to uncover substantial developments.

## Stage 6: Final Report Drafting
### Purpose
Generate the final research output from approved profile and news artifacts.

### Sections
- company snapshot
- what the company does
- headquarters and leadership
- what it has been doing lately
- key recent developments
- sources
- open questions

### Tasks
- compose concise Markdown output
- produce structured JSON output
- ensure all major claims are grounded in approved artifacts
- preserve unknowns rather than filling gaps with guesses

### Outputs
- Markdown report draft
- JSON report draft

### Review Gate
The user can:
- approve the final report
- request wording changes
- request a shorter or more business-style summary
- regenerate from the same approved facts

### Exit Criteria
Mark the pipeline complete after final approval.

## Artifact Model
The pipeline continuously updates its state representations (artifacts). Although Stages 2-5 run autonomously, the system must continually persist artifacts to maintain a verifiable debug trail and allow for transparent iterative updates.

### Artifact Lineage and Invalidation
To prevent stale contextual data from polluting downstream conclusions (especially during dynamic re-fetching), all artifacts must define standard base metadata:
- `artifact_id`: unique ID for this execution's output
- `parent_artifact_ids`: IDs of upstream inputs
- `status`: active, superseded, or stale
- `updated_at`: timestamp of internal modification
- `supersedes`: previous artifact ID if this is a rerun

If the agent dynamically alters upstream data (e.g., modifying source lists or refining search parameters), any corresponding artifact is updated and any downstream artifact referencing the old `artifact_id` in its `parent_artifact_ids` is immediately invalidated. The agent must then autonomously re-execute dependent downstream extractions.

Suggested artifact set:
- `identity.json`
- `sources.json`
- `fetched_content.json`
- `profile_draft.json`
- `news_draft.json`
- `report_draft.md`
- `report_draft.json`
- `final.json`
- `final.md`

## Recommended Data Shapes
### Identity Draft
```json
{
  "input_name": "",
  "resolved_name": "",
  "legal_name": "",
  "aliases": [],
  "website": "",
  "jurisdiction": "",
  "entity_type": "",
  "identifiers": {
    "ticker": "",
    "registry_id": "",
    "wikidata_id": ""
  },
  "description_seed": "",
  "ambiguities": [
    {
      "candidate_name": "",
      "confidence": ""
    }
  ]
}
```

### Source Selection
```json
{
  "official_sources": [],
  "reference_sources": [],
  "news_sources": []
}
```

### Fetched Content
```json
{
  "fetched_sources": [
    {
      "source_id": "",
      "url": "",
      "canonical_url": "",
      "title": "",
      "source_type": "",
      "published_at": "",
      "accessed_at": "",
      "content_preview": "",
      "content_hash": ""
    }
  ],
  "failed_sources": []
}
```

### Common Models
```json
"citation": {
  "source_id": "",
  "canonical_url": "",
  "published_at": "",
  "excerpt": ""
}
```

### Company Profile Draft
```json
{
  "company_name": { "value": "", "citations": [] },
  "website": { "value": "", "citations": [] },
  "description": { "value": "", "citations": [] },
  "industry": { "value": "", "citations": [] },
  "hq": { "value": "", "citations": [] },
  "leadership": [ { "name": "", "role": "", "citations": [] } ],
  "products_or_services": [ { "name": "", "description": "", "citations": [] } ],
  "open_questions": []
}
```

### News Draft
```json
{
  "date_window_days": 90,
  "items": [
    {
      "headline": "",
      "date": "",
      "summary": "",
      "topic": "",
      "citations": []
    }
  ]
}
```

## KohakuTerrarium Role Mapping
Keep the pipeline modular, allowing autonomous task delegation within the main research loop.

### Coordinator
Responsible for:
- initiating Stage 1 and pausing for identity confirmation
- launching and monitoring the autonomous Stage 2-5 loop
- deciding when information density is sufficient to proceed to Stage 6
- persisting and versioning artifacts dynamically

### Discovery Worker
Responsible for:
- finding official and recent-news sources
- ranking source quality

Likely tools:
- `web_search`

### Reader Worker
Responsible for:
- fetching approved sources
- cleaning page content

Likely tools:
- `web_fetch`

### Extractor Worker
Responsible for:
- extracting profile facts
- extracting recent news items
- returning structured outputs with citations

### Drafting Worker
Responsible for:
- producing final Markdown and JSON from approved artifacts only

## Pipeline Rules
- Never finalize raw results; intermediate artifacts drive all downstream steps.
- The pipeline can dynamically loop backwards to gather more context natively.
- Prefer official sources for company identity and description.
- Prefer recent reputable reporting for news.
- Every major claim should have a source.
- Unknown is better than guessed, but initiating a new search to find the answer is better than staying unknown.
- Duplicated news events should be merged.
- Contradictory facts should be surfaced, not silently resolved.

## Validation Strategy
The pipeline should be tested on a small set of companies with different profiles:
- public company
- private startup
- international company
- company with an ambiguous name
- company with sparse press coverage

For each test run, evaluate:
- correct company identity
- correct official website
- source quality
- news relevance
- citation coverage
- unsupported claim rate

## Recommended Build Order
1. Define stage artifacts and data models
2. Implement stage coordinator and the dynamic research loop
3. Implement identity resolution
4. Implement source discovery
5. Implement content gathering
6. Implement company profile extraction
7. Implement recent news extraction
8. Implement final report drafting
9. Test across several companies and tighten prompts

## Immediate Next Step
Start by specifying the pipeline contracts in code:
- stage names
- input and output schemas
- artifact formats
- rules for looping, internal state updates, and dynamic fetching

Once that is stable, implement the research stages themselves before returning to the rest of the HTTP API and app structure.
