from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class Citation(BaseModel):
    source_id: str
    canonical_url: str
    published_at: Optional[str] = None
    excerpt: str


class IdentityDraft(BaseModel):
    resolved_name: str
    legal_name: Optional[str] = None
    aliases: List[str] = Field(default_factory=list)
    website: Optional[str] = None
    jurisdiction: Optional[str] = None
    entity_type: Optional[str] = None
    identifiers: Dict[str, str] = Field(default_factory=dict)
    ambiguities: List[str] = Field(default_factory=list)


class Source(BaseModel):
    source_id: str
    url: str
    query_used: Optional[str] = None
    category: str  # "official", "news", "reference"


class FetchedContent(BaseModel):
    source_id: str
    url: str
    canonical_url: str
    title: Optional[str] = None
    published_at: Optional[str] = None
    content_hash: str
    markdown: str


class CitedField(BaseModel):
    value: Optional[str] = None
    citations: List[Citation] = Field(default_factory=list)


class CompanyProfileDraft(BaseModel):
    company_name: CitedField = Field(default_factory=CitedField)
    industry: CitedField = Field(default_factory=CitedField)
    hq: CitedField = Field(default_factory=CitedField)
    founded: CitedField = Field(default_factory=CitedField)
    employee_count: CitedField = Field(default_factory=CitedField)
    description: CitedField = Field(default_factory=CitedField)
    products_services: CitedField = Field(default_factory=CitedField)
    key_leadership: CitedField = Field(default_factory=CitedField)
    financials: CitedField = Field(default_factory=CitedField)


class NewsItem(BaseModel):
    headline: str
    date: Optional[str] = None
    summary: str
    topic: str
    citations: List[Citation] = Field(default_factory=list)


class NewsDraft(BaseModel):
    items: List[NewsItem] = Field(default_factory=list)


class FeedbackResult(BaseModel):
    has_gaps: bool
    missing_fields: List[str] = Field(default_factory=list)
    follow_up_queries: List[str] = Field(default_factory=list)
    notes: str = ""


class SearchResult(BaseModel):
    url: str
    title: Optional[str] = None
    snippet: Optional[str] = None
