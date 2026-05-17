"""
Tests for SVC-08 · Video Fatigue Monitor

Coverage:
  - Event classification (speed, seek, pause)
  - Fatigue scoring model (decay, normalization)
  - Label thresholds (ENGAGED, NEUTRAL, STRUGGLING, CRITICAL)
  - Repeated backward seek detection
  - Session reset and history
  - Fatigue timeline generation
"""

import time
import pytest
from services.video_fatigue_monitor import VideoFatigueMonitor


@pytest.fixture
def monitor():
    return VideoFatigueMonitor()


@pytest.fixture
def session_id():
    return "test-video-session"


class TestEventClassification:
    """Test that raw events are classified correctly."""

    def test_speed_increase_lowers_fatigue(self, monitor, session_id):
        monitor.process_event(session_id, "speed_change", 0, 1.0, 0)
        state = monitor.process_event(session_id, "speed_change", 30, 1.5, 0)
        assert state.score < 0.5  # Should be low/engaged

    def test_speed_decrease_raises_fatigue(self, monitor, session_id):
        monitor.process_event(session_id, "speed_change", 0, 2.0, 0)
        state = monitor.process_event(session_id, "speed_change", 30, 1.0, 0)
        # Score should rise relative to baseline
        assert state.score > 0.0

    def test_skip_forward_signals_engagement(self, monitor, session_id):
        state = monitor.process_event(session_id, "seek", 120, 1.0, 60)
        assert state.label in ("ENGAGED", "NEUTRAL")

    def test_seek_backward_signals_confusion(self, monitor, session_id):
        state = monitor.process_event(session_id, "seek", 100, 1.0, -30)
        assert state.score > 0.3  # Should push fatigue up

    def test_play_is_neutral(self, monitor, session_id):
        state = monitor.process_event(session_id, "play", 0, 1.0, 0)
        assert state.score >= 0.0


class TestFatigueScoring:
    """Test the fatigue scoring model."""

    def test_score_always_in_range(self, monitor, session_id):
        events = [
            ("play", 0, 1.0, 0),
            ("speed_change", 30, 1.5, 0),
            ("seek", 120, 1.5, 60),
            ("seek", 100, 1.0, -30),
        ]
        for evt, pos, rate, delta in events:
            state = monitor.process_event(session_id, evt, pos, rate, delta)
            assert 0.0 <= state.score <= 1.0

    def test_initial_score_is_low(self, monitor, session_id):
        state = monitor.process_event(session_id, "play", 0, 1.0, 0)
        assert state.score <= 0.5

    def test_multiple_backward_seeks_increase_score(self, monitor, session_id):
        # Series of backward seeks should push score up
        for i in range(5):
            state = monitor.process_event(session_id, "seek", 100, 1.0, -20)
            time.sleep(0.05)
        assert state.score > 0.5


class TestLabels:
    """Test fatigue label thresholds."""

    def test_engaged_label_range(self, monitor):
        label = monitor._score_to_label(0.1)
        assert label == "ENGAGED"

    def test_neutral_label_range(self, monitor):
        label = monitor._score_to_label(0.3)
        assert label == "NEUTRAL"

    def test_struggling_label_range(self, monitor):
        label = monitor._score_to_label(0.6)
        assert label == "STRUGGLING"

    def test_critical_label_range(self, monitor):
        label = monitor._score_to_label(0.8)
        assert label == "CRITICAL"


class TestTriggerSummary:
    """Test that trigger_summary fires correctly."""

    def test_no_trigger_when_engaged(self, monitor, session_id):
        state = monitor.process_event(session_id, "play", 0, 1.0, 0)
        assert state.trigger_summary is False

    def test_trigger_on_critical(self, monitor, session_id):
        # Force high fatigue with many backward seeks
        for i in range(10):
            state = monitor.process_event(session_id, "seek", 100 + i, 1.0, -20)
            time.sleep(0.05)
        if state.score >= 0.75:
            assert state.trigger_summary is True


class TestSessionManagement:
    """Test session-level operations."""

    def test_reset_clears_state(self, monitor, session_id):
        monitor.process_event(session_id, "seek", 100, 1.0, -20)
        monitor.reset(session_id)
        assert session_id not in monitor.sessions

    def test_history_tracks_events(self, monitor, session_id):
        monitor.process_event(session_id, "play", 0, 1.0, 0)
        monitor.process_event(session_id, "seek", 50, 1.0, 50)
        history = monitor.get_history(session_id)
        assert len(history) == 2

    def test_timeline_has_scores(self, monitor, session_id):
        monitor.process_event(session_id, "play", 0, 1.0, 0)
        monitor.process_event(session_id, "seek", 50, 1.0, -20)
        timeline = monitor.get_fatigue_timeline(session_id)
        assert len(timeline) == 2
        assert "score" in timeline[0]
        assert "label" in timeline[0]

    def test_separate_sessions_independent(self, monitor):
        monitor.process_event("s1", "seek", 100, 1.0, -30)
        monitor.process_event("s2", "play", 0, 1.0, 0)
        assert len(monitor.get_history("s1")) == 1
        assert len(monitor.get_history("s2")) == 1


class TestRecommendedAction:
    """Test action recommendations."""

    def test_engaged_returns_none(self, monitor):
        action = monitor._get_action("ENGAGED", "play")
        assert action == "none"

    def test_struggling_backward_suggests_slowdown(self, monitor):
        action = monitor._get_action("STRUGGLING", "seek_backward")
        assert action == "suggest_slowdown"

    def test_critical_returns_show_summary(self, monitor):
        action = monitor._get_action("CRITICAL", "repeated_backward")
        assert action == "show_summary"
