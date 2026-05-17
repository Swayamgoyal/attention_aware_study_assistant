"""
Tests for SVC-10 · Transcription Summary Agent

Coverage:
  - Summary result structure
  - Time formatting
  - Cache key generation
  - Concept extraction from markdown
  - Prerequisite extraction
"""

import pytest
from services.transcription_summary import TranscriptionSummaryAgent, SummaryResult


@pytest.fixture
def agent():
    return TranscriptionSummaryAgent()


class TestSummaryResult:
    """Test SummaryResult dataclass."""

    def test_to_dict_has_required_keys(self):
        result = SummaryResult(
            summary_markdown="# Summary",
            key_concepts=["concept1"],
            estimated_read_sec=60,
            video_section_covered="0:00 - 5:00",
            prerequisite_gaps=["algebra"],
            video_id="test123",
        )
        d = result.to_dict()
        assert "summary_markdown" in d
        assert "key_concepts" in d
        assert "estimated_read_sec" in d
        assert "video_section_covered" in d
        assert "prerequisite_gaps" in d
        assert "video_id" in d

    def test_cached_default_false(self):
        result = SummaryResult("", [], 0, "", [], "")
        assert result.cached is False


class TestTimeFormatting:
    """Test time formatting utilities."""

    def test_format_seconds(self):
        assert TranscriptionSummaryAgent._format_time(0) == "0:00"

    def test_format_minutes(self):
        assert TranscriptionSummaryAgent._format_time(90) == "1:30"

    def test_format_hours(self):
        assert TranscriptionSummaryAgent._format_time(3661) == "1:01:01"

    def test_format_time_range(self):
        result = TranscriptionSummaryAgent._format_time_range(60, 300)
        assert "1:00" in result
        assert "5:00" in result

    def test_format_time_range_to_end(self):
        result = TranscriptionSummaryAgent._format_time_range(120, 0)
        assert "end" in result


class TestConceptExtraction:
    """Test concept extraction from markdown text."""

    def test_extracts_bold_terms(self, agent):
        summary = "This covers **recursion** and **base case** in depth."
        concepts = agent._extract_concepts(summary)
        assert "recursion" in concepts
        assert "base case" in concepts

    def test_deduplicates_concepts(self, agent):
        summary = "**recursion** is key. Learn **recursion** well."
        concepts = agent._extract_concepts(summary)
        assert len([c for c in concepts if c.lower() == "recursion"]) == 1

    def test_limits_concept_count(self, agent):
        summary = " ".join([f"**concept{i}**" for i in range(20)])
        concepts = agent._extract_concepts(summary)
        assert len(concepts) <= 8

    def test_ignores_short_bold(self, agent):
        summary = "Use **a** and **be** for grammar."
        concepts = agent._extract_concepts(summary)
        assert len(concepts) == 0  # "a" and "be" are too short (<=2 chars)


class TestCacheKey:
    """Test cache key generation."""

    def test_cache_key_includes_video_id(self):
        key = TranscriptionSummaryAgent._cache_key("abc123", 0, 300)
        assert "abc123" in key

    def test_different_ranges_different_keys(self):
        k1 = TranscriptionSummaryAgent._cache_key("abc", 0, 300)
        k2 = TranscriptionSummaryAgent._cache_key("abc", 300, 600)
        assert k1 != k2


class TestAgentInit:
    """Test agent initialization."""

    def test_agent_has_llm(self, agent):
        assert agent.llm is not None

    def test_cached_returns_none_for_unknown(self, agent):
        result = agent.get_cached("nonexistent_video")
        assert result is None
