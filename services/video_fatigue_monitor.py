"""SVC-08 · Video Fatigue Monitor Agent
Port: 8006 | Tracks fatigue from video player events

Receives player events (play, pause, seek, speed_change) and maintains
a rolling fatigue score. Each struggle event adds fatigue; each
positive event reduces it. Score is clamped to [0.0, 1.0].

Labels: ENGAGED (0-0.25), NEUTRAL (0.25-0.50), STRUGGLING (0.50-0.75), CRITICAL (0.75-1.0)
Summary trigger: score >= 0.50
"""

import time
import math
from dataclasses import dataclass, field, asdict
from collections import defaultdict


# ─── Event Impact Scores ──────────────────────────────────────────────
# Positive = increases fatigue, Negative = decreases fatigue
# Each button press causes a small ~5-10% visible change in gauge
EVENT_IMPACTS = {
    "speed_increase":     -0.06,   # Engaged — content is easy (small recovery)
    "skip_forward":       -0.03,   # Already knows the material
    "play":               -0.04,   # Slight positive — user re-engaged
    "short_pause":         0.08,   # Note-taking or brief distraction
    "long_pause":          0.14,   # Zoned out or overwhelmed
    "speed_decrease":      0.10,   # Content became difficult
    "seek_backward":       0.12,   # Confusion — couldn't process first time
    "repeated_backward":   0.14,   # Slightly higher — but NOT a spike
}

FATIGUE_LABELS = {
    (0.00, 0.25): "ENGAGED",
    (0.25, 0.50): "NEUTRAL",
    (0.50, 0.75): "STRUGGLING",
    (0.75, 1.00): "CRITICAL",
}

# Summary trigger — when fatigue score >= this, generate a video summary
SUMMARY_TRIGGER_THRESHOLD = 0.75

# ─── Constants ─────────────────────────────────────────────────────────
DECAY_LAMBDA = 0.02          # Slow decay — events stay relevant longer
BACKWARD_REPEAT_WINDOW = 30  # Seconds window for "repeated backward" detection
BACKWARD_REPEAT_COUNT = 5    # Need 5 backward seeks in same area = repeated
SHORT_PAUSE_THRESHOLD = 10   # Seconds — shorter = short_pause
LONG_PAUSE_THRESHOLD = 30    # Seconds — longer = long_pause


@dataclass
class VideoEvent:
    """A single player event."""
    event_type: str        # play, pause, seek, speed_change
    position_sec: int      # Current position in video
    playback_rate: float   # e.g. 1.0, 1.5, 2.0
    seek_delta_sec: int    # Negative = backward seek
    timestamp: float       # Unix timestamp of event
    impact: float = 0.0    # Computed fatigue impact


@dataclass
class VideoFatigueState:
    """Current video fatigue assessment."""
    score: float
    label: str
    trigger_summary: bool
    current_position_sec: int
    recommended_action: str
    event_count: int
    recent_events: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


class VideoFatigueMonitor:
    """
    Maintains a rolling fatigue score from video player events.

    Uses exponential decay so older events contribute less to the score.
    Detects "repeated backward seeks" on the same video segment as a
    CRITICAL fatigue signal.
    """

    def __init__(self):
        # session_id → list of VideoEvent
        self.sessions: dict[str, list[VideoEvent]] = defaultdict(list)
        # session_id → last known playback rate
        self.last_rate: dict[str, float] = {}
        # session_id → last pause timestamp (for pause duration)
        self.pause_start: dict[str, float] = {}

    def process_event(
        self,
        session_id: str,
        event_type: str,
        position_sec: int = 0,
        playback_rate: float = 1.0,
        seek_delta_sec: int = 0,
    ) -> VideoFatigueState:
        """
        Process a video player event and return updated fatigue state.

        Args:
            session_id: Learner session identifier
            event_type: One of: play, pause, seek, speed_change
            position_sec: Current video position in seconds
            playback_rate: Current playback speed (1.0, 1.5, 2.0, etc.)
            seek_delta_sec: Seek amount (negative = backward)
        """
        now = time.time()
        classified = self._classify_event(
            session_id, event_type, position_sec, playback_rate, seek_delta_sec, now
        )

        event = VideoEvent(
            event_type=event_type,
            position_sec=position_sec,
            playback_rate=playback_rate,
            seek_delta_sec=seek_delta_sec,
            timestamp=now,
            impact=EVENT_IMPACTS.get(classified, 0.0),
        )
        self.sessions[session_id].append(event)

        # Update last rate
        if event_type == "speed_change":
            self.last_rate[session_id] = playback_rate

        # Compute fatigue score
        score = self._compute_score(session_id, now)
        label = self._score_to_label(score)
        trigger = score >= SUMMARY_TRIGGER_THRESHOLD
        action = self._get_action(label, classified)

        return VideoFatigueState(
            score=round(score, 3),
            label=label,
            trigger_summary=trigger,
            current_position_sec=position_sec,
            recommended_action=action,
            event_count=len(self.sessions[session_id]),
            recent_events=[e.event_type for e in self.sessions[session_id][-5:]],
        )

    def _classify_event(
        self, session_id: str, event_type: str,
        position_sec: int, playback_rate: float,
        seek_delta_sec: int, now: float
    ) -> str:
        """Classify raw event into a fatigue signal category."""

        if event_type == "speed_change":
            prev_rate = self.last_rate.get(session_id, 1.0)
            if playback_rate > prev_rate:
                return "speed_increase"
            elif playback_rate < prev_rate:
                return "speed_decrease"
            return "play"  # No change

        if event_type == "pause":
            self.pause_start[session_id] = now
            return "short_pause"  # Initial classification

        if event_type == "play":
            # Check if resuming from a pause
            pause_ts = self.pause_start.pop(session_id, None)
            if pause_ts:
                pause_duration = now - pause_ts
                if pause_duration >= LONG_PAUSE_THRESHOLD:
                    return "long_pause"
                elif pause_duration >= SHORT_PAUSE_THRESHOLD:
                    return "short_pause"
            return "play"

        if event_type == "seek":
            if seek_delta_sec < 0:
                # Backward seek — check for repeated backward seeks
                if self._is_repeated_backward(session_id, position_sec, now):
                    return "repeated_backward"
                return "seek_backward"
            else:
                return "skip_forward"

        return "play"

    def _is_repeated_backward(self, session_id: str, position: int, now: float) -> bool:
        """Check if there are multiple backward seeks near the same position."""
        events = self.sessions.get(session_id, [])
        recent_backward = [
            e for e in events
            if e.seek_delta_sec < 0
            and (now - e.timestamp) < BACKWARD_REPEAT_WINDOW
            and abs(e.position_sec - position) < 60  # Within 60s of same spot
        ]
        return len(recent_backward) >= BACKWARD_REPEAT_COUNT

    def _compute_score(self, session_id: str, now: float) -> float:
        """
        Compute fatigue score using cumulative impact with decay.

        Each event adds or subtracts from a running score.
        Older events decay towards zero so fatigue can recover over time.
        Score is clamped to [0.0, 1.0].
        """
        events = self.sessions.get(session_id, [])
        if not events:
            return 0.0

        # Sum all impacts with exponential decay on older events
        cumulative = 0.0
        for event in events:
            age = now - event.timestamp
            decay = math.exp(-DECAY_LAMBDA * age)
            cumulative += event.impact * decay

        # cumulative can be negative (lots of play/speed_increase)
        # or positive (lots of backward seeks/pauses)
        # Map to [0, 1]: 5.0 cumulative = full fatigue (100%)
        # Each 0.12 backward seek = ~2.4% → ~30 clicks to reach 70%
        score = cumulative / 7.0
        return max(0.0, min(1.0, score))

    @staticmethod
    def _score_to_label(score: float) -> str:
        """Map score to fatigue label."""
        if score < 0.25:
            return "ENGAGED"
        elif score < 0.50:
            return "NEUTRAL"
        elif score < 0.75:
            return "STRUGGLING"
        else:
            return "CRITICAL"

    @staticmethod
    def _get_action(label: str, event_class: str) -> str:
        """Determine recommended action based on fatigue state."""
        if label == "CRITICAL":
            return "show_summary"
        elif label == "STRUGGLING":
            return "show_summary"
        elif label == "NEUTRAL":
            if event_class in ("seek_backward", "speed_decrease"):
                return "suggest_slowdown"
            return "none"
        else:
            return "none"

    def get_history(self, session_id: str) -> list[dict]:
        """Get full event history for a session."""
        return [
            {
                "event_type": e.event_type,
                "position_sec": e.position_sec,
                "playback_rate": e.playback_rate,
                "seek_delta_sec": e.seek_delta_sec,
                "impact": e.impact,
                "timestamp": e.timestamp,
            }
            for e in self.sessions.get(session_id, [])
        ]

    def reset(self, session_id: str) -> dict:
        """Reset event history for a session."""
        self.sessions.pop(session_id, None)
        self.last_rate.pop(session_id, None)
        self.pause_start.pop(session_id, None)
        return {"status": "reset", "session_id": session_id}

    def get_fatigue_timeline(self, session_id: str) -> list[dict]:
        """Get fatigue score at each event for timeline visualization."""
        events = self.sessions.get(session_id, [])
        timeline = []
        for i, event in enumerate(events):
            # Recompute score at each event's timestamp (cumulative model)
            sub_events = events[:i+1]
            cumulative = 0.0
            for e in sub_events:
                age = event.timestamp - e.timestamp
                decay = math.exp(-DECAY_LAMBDA * age)
                cumulative += e.impact * decay

            score = max(0.0, min(1.0, cumulative / 7.0))

            timeline.append({
                "position_sec": event.position_sec,
                "score": round(score, 3),
                "label": self._score_to_label(score),
                "event_type": event.event_type,
            })
        return timeline


# ─── CLI Test ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    monitor = VideoFatigueMonitor()
    sid = "test-session"

    print("=== Video Fatigue Monitor — CLI Test ===\n")

    # Simulate a learning session
    test_events = [
        ("play", 0, 1.0, 0),
        ("speed_change", 30, 1.5, 0),     # speed up → engaged
        ("seek", 120, 1.5, 60),            # skip forward → confident
        ("speed_change", 180, 1.0, 0),     # slow down → harder
        ("pause", 200, 1.0, 0),            # pause
        ("seek", 190, 1.0, -30),           # seek backward → confused
        ("seek", 185, 1.0, -20),           # again → repeated backward
        ("seek", 188, 1.0, -15),           # again → critical
    ]

    for event_type, pos, rate, delta in test_events:
        import time as _t; _t.sleep(0.1)
        state = monitor.process_event(sid, event_type, pos, rate, delta)
        print(f"  {event_type:18s} @ {pos:3d}s | rate={rate} | "
              f"score={state.score:.3f} {state.label:12s} | action={state.recommended_action}")

    print(f"\nTotal events: {state.event_count}")
    print(f"Trigger summary: {state.trigger_summary}")
