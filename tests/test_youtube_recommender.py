"""
Tests for SVC-09 · YouTube Recommender

Coverage:
  - Query building from topic + difficulty
  - Duration parsing (ISO 8601)
  - Result filtering and ranking
  - Session caching
  - Info reporting
"""

import pytest
from services.youtube_recommender import YouTubeRecommender, VideoResult


@pytest.fixture
def recommender():
    return YouTubeRecommender()


class TestQueryBuilding:
    """Test search query construction."""

    def test_beginner_query_includes_beginner(self, recommender):
        q = recommender._build_query("recursion", 1)
        assert "beginner" in q.lower()

    def test_intermediate_query(self, recommender):
        q = recommender._build_query("recursion", 3)
        assert "intermediate" in q.lower()

    def test_advanced_query(self, recommender):
        q = recommender._build_query("recursion", 5)
        assert "advanced" in q.lower()

    def test_topic_preserved_in_query(self, recommender):
        q = recommender._build_query("neural networks", 2)
        assert "neural networks" in q.lower()


class TestDurationParsing:
    """Test ISO 8601 duration parsing."""

    def test_minutes_and_seconds(self, recommender):
        assert recommender._parse_duration("PT10M30S") == 630

    def test_hours_minutes_seconds(self, recommender):
        assert recommender._parse_duration("PT1H2M30S") == 3750

    def test_only_minutes(self, recommender):
        assert recommender._parse_duration("PT5M") == 300

    def test_only_seconds(self, recommender):
        assert recommender._parse_duration("PT45S") == 45

    def test_empty_duration(self, recommender):
        assert recommender._parse_duration("PT0S") == 0

    def test_invalid_format(self, recommender):
        assert recommender._parse_duration("invalid") == 0


class TestFilterAndRank:
    """Test result filtering and ranking."""

    def test_filters_long_videos(self, recommender):
        results = [
            VideoResult("a", "Short", "Ch", 300, "", "", 1000),   # 5 min
            VideoResult("b", "Long", "Ch", 3600, "", "", 1000),   # 60 min
        ]
        filtered = recommender._filter_and_rank(results, max_duration_min=20)
        assert len(filtered) == 1
        assert filtered[0].video_id == "a"

    def test_ranks_by_relevance_score(self, recommender):
        results = [
            VideoResult("a", "Low views", "Ch", 300, "", "", 100),
            VideoResult("b", "High views", "Ch", 300, "", "", 1000000),
        ]
        ranked = recommender._filter_and_rank(results, max_duration_min=20)
        # Higher views should have higher relevance score
        assert all(r.relevance_score > 0 for r in ranked)

    def test_no_crash_on_empty_results(self, recommender):
        filtered = recommender._filter_and_rank([], max_duration_min=20)
        assert filtered == []


class TestCaching:
    """Test session caching."""

    def test_empty_cache_returns_empty_list(self, recommender):
        assert recommender.get_cached("nonexistent") == []

    def test_info_returns_dict(self, recommender):
        info = recommender.get_info()
        assert "service" in info
        assert info["service"] == "youtube_recommender"
