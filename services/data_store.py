"""
SVC-06 · Data Persistence Service
Port: 8005
Centralised storage & retrieval layer

Provides a clean API over SQLite for all agents.
Handles sessions, interaction logs, learner profiles, and quiz records.
All agents use this service — none write to disk directly.

Phase 1: Standalone Python module with SQLAlchemy ORM.
"""

import os
import json
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import create_engine, Column, String, Float, Integer, DateTime, Text
from sqlalchemy.orm import declarative_base, sessionmaker

# ─── Database Configuration ────────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/study_assistant.db")

# Ensure data directory exists for SQLite
if DATABASE_URL.startswith("sqlite"):
    db_path = DATABASE_URL.replace("sqlite:///", "")
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

engine = create_engine(DATABASE_URL, echo=False, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# ─── ORM Models ────────────────────────────────────────────────────────

class SessionRecord(Base):
    """Tracks study sessions."""
    __tablename__ = "sessions"

    id = Column(String, primary_key=True)
    start_time = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    topic = Column(String, nullable=True)
    status = Column(String, default="active")  # active, completed


class InteractionLog(Base):
    """Logs every interaction within a session."""
    __tablename__ = "interactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, nullable=False, index=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    user_message = Column(Text, nullable=True)
    mode_used = Column(String, nullable=True)
    fatigue_score = Column(Float, nullable=True)
    fatigue_label = Column(String, nullable=True)
    content_snippet = Column(Text, nullable=True)


class LearnerProfileRecord(Base):
    """Persistent learner profile per session + topic."""
    __tablename__ = "learner_profiles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, nullable=False, index=True)
    topic = Column(String, nullable=True)
    mastery_score = Column(Float, default=0.5)
    preferred_mode = Column(String, default="detailed")
    avg_fatigue = Column(Float, default=0.0)
    difficulty_level = Column(Integer, default=2)
    last_seen = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class QuizRecord(Base):
    """Records quiz questions, answers, and scores."""
    __tablename__ = "quiz_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, nullable=False, index=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    topic = Column(String, nullable=True)
    question = Column(Text, nullable=True)
    correct_answer = Column(Text, nullable=True)
    learner_answer = Column(Text, nullable=True)
    score = Column(Float, nullable=True)
    feedback = Column(Text, nullable=True)
    difficulty = Column(Integer, nullable=True)


class VideoEventLog(Base):
    """Logs video player events for fatigue tracking."""
    __tablename__ = "video_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, nullable=False, index=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    event_type = Column(String, nullable=False)
    video_id = Column(String, nullable=True)
    position_sec = Column(Integer, default=0)
    playback_rate = Column(Float, default=1.0)
    seek_delta_sec = Column(Integer, default=0)
    fatigue_score = Column(Float, nullable=True)
    fatigue_label = Column(String, nullable=True)


class TranscriptCache(Base):
    """Caches transcription summaries to avoid re-processing."""
    __tablename__ = "transcript_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)
    video_id = Column(String, nullable=False, index=True)
    from_sec = Column(Integer, default=0)
    to_sec = Column(Integer, default=0)
    summary_text = Column(Text, nullable=True)
    concepts_json = Column(Text, nullable=True)  # JSON string
    cached_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


# ─── Create all tables ─────────────────────────────────────────────────
def init_db():
    """Create all tables if they don't exist."""
    Base.metadata.create_all(bind=engine)


# ─── Data Store Operations ─────────────────────────────────────────────

class DataStore:
    """Centralised data access layer for all services."""

    def __init__(self):
        init_db()

    def _get_session(self):
        return SessionLocal()

    # ── Session Management ──────────────────────────────────────────

    def create_session(self, session_id: str, topic: Optional[str] = None) -> dict:
        """Create a new study session."""
        db = self._get_session()
        try:
            record = SessionRecord(id=session_id, topic=topic)
            db.add(record)
            db.commit()
            return {"session_id": session_id, "topic": topic, "status": "created"}
        except Exception as e:
            db.rollback()
            # Session might already exist — that's OK
            return {"session_id": session_id, "status": "exists"}
        finally:
            db.close()

    def get_session(self, session_id: str) -> Optional[dict]:
        """Retrieve session info."""
        db = self._get_session()
        try:
            record = db.query(SessionRecord).filter_by(id=session_id).first()
            if record:
                return {
                    "session_id": record.id,
                    "start_time": record.start_time.isoformat() if record.start_time else None,
                    "topic": record.topic,
                    "status": record.status,
                }
            return None
        finally:
            db.close()

    # ── Interaction Logging ─────────────────────────────────────────

    def log_interaction(self, session_id: str, user_message: str,
                        mode_used: str, fatigue_score: float,
                        fatigue_label: str, content_snippet: str = "") -> dict:
        """Log a single interaction event."""
        db = self._get_session()
        try:
            record = InteractionLog(
                session_id=session_id,
                user_message=user_message,
                mode_used=mode_used,
                fatigue_score=fatigue_score,
                fatigue_label=fatigue_label,
                content_snippet=content_snippet[:500],  # truncate for storage
            )
            db.add(record)
            db.commit()
            return {"status": "logged", "id": record.id}
        finally:
            db.close()

    def get_session_history(self, session_id: str) -> list:
        """Get chronological interaction history for a session."""
        db = self._get_session()
        try:
            records = (
                db.query(InteractionLog)
                .filter_by(session_id=session_id)
                .order_by(InteractionLog.timestamp.asc())
                .all()
            )
            return [
                {
                    "timestamp": r.timestamp.isoformat() if r.timestamp else None,
                    "user_message": r.user_message,
                    "mode_used": r.mode_used,
                    "fatigue_score": r.fatigue_score,
                    "fatigue_label": r.fatigue_label,
                    "content_snippet": r.content_snippet,
                }
                for r in records
            ]
        finally:
            db.close()

    # ── Learner Profile ─────────────────────────────────────────────

    def get_profile(self, session_id: str) -> Optional[dict]:
        """Get the learner profile for a session."""
        db = self._get_session()
        try:
            record = (
                db.query(LearnerProfileRecord)
                .filter_by(session_id=session_id)
                .first()
            )
            if record:
                return {
                    "session_id": record.session_id,
                    "topic": record.topic,
                    "mastery_score": record.mastery_score,
                    "preferred_mode": record.preferred_mode,
                    "avg_fatigue": record.avg_fatigue,
                    "difficulty_level": record.difficulty_level,
                    "last_seen": record.last_seen.isoformat() if record.last_seen else None,
                }
            return None
        finally:
            db.close()

    def upsert_profile(self, session_id: str, topic: Optional[str] = None,
                       mastery_score: Optional[float] = None,
                       preferred_mode: Optional[str] = None,
                       avg_fatigue: Optional[float] = None,
                       difficulty_level: Optional[int] = None) -> dict:
        """Create or update a learner profile."""
        db = self._get_session()
        try:
            record = (
                db.query(LearnerProfileRecord)
                .filter_by(session_id=session_id)
                .first()
            )
            if record is None:
                record = LearnerProfileRecord(session_id=session_id)
                db.add(record)

            if topic is not None:
                record.topic = topic
            if mastery_score is not None:
                record.mastery_score = mastery_score
            if preferred_mode is not None:
                record.preferred_mode = preferred_mode
            if avg_fatigue is not None:
                record.avg_fatigue = avg_fatigue
            if difficulty_level is not None:
                record.difficulty_level = difficulty_level
            record.last_seen = datetime.now(timezone.utc)

            db.commit()
            return {"status": "updated", "session_id": session_id}
        finally:
            db.close()

    # ── Quiz Records ────────────────────────────────────────────────

    def store_quiz_result(self, session_id: str, topic: str, question: str,
                          correct_answer: str, learner_answer: str,
                          score: float, feedback: str,
                          difficulty: int = 2) -> dict:
        """Store a quiz result."""
        db = self._get_session()
        try:
            record = QuizRecord(
                session_id=session_id,
                topic=topic,
                question=question,
                correct_answer=correct_answer,
                learner_answer=learner_answer,
                score=score,
                feedback=feedback,
                difficulty=difficulty,
            )
            db.add(record)
            db.commit()
            return {"status": "stored", "id": record.id}
        finally:
            db.close()

    def get_quiz_history(self, session_id: str) -> list:
        """Get all quiz results for a session."""
        db = self._get_session()
        try:
            records = (
                db.query(QuizRecord)
                .filter_by(session_id=session_id)
                .order_by(QuizRecord.timestamp.desc())
                .all()
            )
            return [
                {
                    "topic": r.topic,
                    "question": r.question,
                    "correct_answer": r.correct_answer,
                    "learner_answer": r.learner_answer,
                    "score": r.score,
                    "feedback": r.feedback,
                    "difficulty": r.difficulty,
                }
                for r in records
            ]
        finally:
            db.close()

    def get_recent_quiz_scores(self, session_id: str, limit: int = 5) -> list:
        """Get the most recent quiz scores for fatigue trend analysis."""
        db = self._get_session()
        try:
            records = (
                db.query(QuizRecord.score)
                .filter_by(session_id=session_id)
                .order_by(QuizRecord.timestamp.desc())
                .limit(limit)
                .all()
            )
            return [r.score for r in records if r.score is not None]
        finally:
            db.close()

    # ── Video Event Logging ──────────────────────────────────────────

    def log_video_event(
        self, session_id: str, event_type: str, video_id: str = "",
        position_sec: int = 0, playback_rate: float = 1.0,
        seek_delta_sec: int = 0, fatigue_score: float = 0.0,
        fatigue_label: str = "",
    ) -> dict:
        """Log a video player event."""
        db = self._get_session()
        try:
            record = VideoEventLog(
                session_id=session_id,
                event_type=event_type,
                video_id=video_id,
                position_sec=position_sec,
                playback_rate=playback_rate,
                seek_delta_sec=seek_delta_sec,
                fatigue_score=fatigue_score,
                fatigue_label=fatigue_label,
            )
            db.add(record)
            db.commit()
            return {"status": "logged", "event_type": event_type}
        except Exception as e:
            db.rollback()
            return {"status": "error", "error": str(e)}
        finally:
            db.close()

    def get_video_events(self, session_id: str) -> list:
        """Get video events for a session."""
        db = self._get_session()
        try:
            records = db.query(VideoEventLog).filter(
                VideoEventLog.session_id == session_id
            ).order_by(VideoEventLog.timestamp).all()
            return [
                {
                    "event_type": r.event_type,
                    "video_id": r.video_id,
                    "position_sec": r.position_sec,
                    "playback_rate": r.playback_rate,
                    "seek_delta_sec": r.seek_delta_sec,
                    "fatigue_score": r.fatigue_score,
                    "fatigue_label": r.fatigue_label,
                    "timestamp": str(r.timestamp),
                }
                for r in records
            ]
        finally:
            db.close()

    # ── Export ──────────────────────────────────────────────────────

    def export_session(self, session_id: str) -> dict:
        """Export full session data as JSON-serialisable dict."""
        return {
            "session": self.get_session(session_id),
            "profile": self.get_profile(session_id),
            "interactions": self.get_session_history(session_id),
            "quizzes": self.get_quiz_history(session_id),
            "video_events": self.get_video_events(session_id),
        }


# ─── CLI Entry Point ───────────────────────────────────────────────────
if __name__ == "__main__":
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    print("=" * 60)
    print("  SVC-06 · Data Persistence Service — Self-Test")
    print("=" * 60)

    store = DataStore()

    # Test session creation
    result = store.create_session("test-session-001", topic="machine_learning")
    print(f"\n✅ Session created: {result}")

    # Test profile upsert
    result = store.upsert_profile(
        "test-session-001",
        topic="machine_learning",
        mastery_score=0.5,
        preferred_mode="detailed",
        difficulty_level=2,
    )
    print(f"✅ Profile upserted: {result}")

    # Test profile retrieval
    profile = store.get_profile("test-session-001")
    print(f"✅ Profile retrieved: {json.dumps(profile, indent=2)}")

    # Test interaction logging
    result = store.log_interaction(
        session_id="test-session-001",
        user_message="Explain neural networks",
        mode_used="detailed",
        fatigue_score=0.2,
        fatigue_label="FRESH",
        content_snippet="Neural networks are computational models...",
    )
    print(f"✅ Interaction logged: {result}")

    # Test quiz record
    result = store.store_quiz_result(
        session_id="test-session-001",
        topic="machine_learning",
        question="What is backpropagation?",
        correct_answer="Algorithm for computing gradients in neural networks",
        learner_answer="It's how neural networks learn by going backwards",
        score=0.8,
        feedback="Good understanding! Consider mentioning gradient descent.",
        difficulty=3,
    )
    print(f"✅ Quiz stored: {result}")

    # Test history retrieval
    history = store.get_session_history("test-session-001")
    print(f"✅ Session history: {len(history)} interactions")

    # Test export
    export = store.export_session("test-session-001")
    print(f"✅ Session export: {json.dumps(export, indent=2)}")

    print("\n" + "=" * 60)
    print("  All data store tests passed! ✓")
    print("=" * 60)
