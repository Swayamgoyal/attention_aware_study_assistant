"""
Launch all microservices in a single process (development mode).

For production, run each service separately with uvicorn.
This script mounts all services under a single FastAPI app
with path-based routing for easy development.
"""

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from services.api import (
    create_orchestrator_app,
    create_attention_app,
    create_profiler_app,
    create_content_app,
    create_quiz_app,
    create_data_store_app,
    create_video_fatigue_app,
    create_youtube_app,
    create_summary_app,
)

# Main gateway app
app = FastAPI(title="Attention-Aware Study Assistant — API Gateway", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount all service apps (original 6 + 3 new video services)
app.mount("/attention", create_attention_app())
app.mount("/profiler", create_profiler_app())
app.mount("/content", create_content_app())
app.mount("/quiz", create_quiz_app())
app.mount("/data", create_data_store_app())
app.mount("/video-fatigue", create_video_fatigue_app())
app.mount("/youtube", create_youtube_app())
app.mount("/summary", create_summary_app())

# ─── Player Page (served with real HTTP origin for YouTube API) ────────
import os
_player_html_path = os.path.join(os.path.dirname(__file__), "frontend", "player.html")

@app.get("/player")
async def serve_player():
    """Serve the YouTube player HTML page with proper HTTP origin."""
    return FileResponse(_player_html_path, media_type="text/html")

# Orchestrator endpoints at root level
orch_app = create_orchestrator_app()
for route in orch_app.routes:
    app.routes.append(route)

# ─── Video Interact Endpoint ──────────────────────────────────────────
# This lives at the gateway level to coordinate the video ReAct loop
from pydantic import BaseModel
from services.video_fatigue_monitor import VideoFatigueMonitor
from services.transcription_summary import TranscriptionSummaryAgent
from services.data_store import DataStore

_video_monitor = VideoFatigueMonitor()
_summary_agent = None  # Lazy init to avoid LLM load at import
_data_store = DataStore()


def _get_summary_agent():
    global _summary_agent
    if _summary_agent is None:
        _summary_agent = TranscriptionSummaryAgent()
    return _summary_agent


class VideoInteractRequest(BaseModel):
    session_id: str
    event_type: str       # play, pause, seek, speed_change
    video_id: str = ""
    position_sec: int = 0
    playback_rate: float = 1.0
    seek_delta_sec: int = 0
    topic: str = ""


@app.post("/video-interact")
def video_interact(req: VideoInteractRequest):
    """
    Video ReAct Loop:
    1. OBSERVE  → SVC-08 Video Fatigue Monitor (process player event)
    2. REASON   → Check fatigue threshold
    3. ACT      → If CRITICAL → SVC-10 summary. Else → suggestion or none.
    4. REFLECT  → Log to SVC-06 Data Store
    """
    # 1. OBSERVE: Process the video event
    fatigue_state = _video_monitor.process_event(
        session_id=req.session_id,
        event_type=req.event_type,
        position_sec=req.position_sec,
        playback_rate=req.playback_rate,
        seek_delta_sec=req.seek_delta_sec,
    )

    result = {
        "session_id": req.session_id,
        "fatigue_state": fatigue_state.to_dict(),
        "action": fatigue_state.recommended_action,
    }

    # 2-3. REASON + ACT: If CRITICAL, generate summary
    if fatigue_state.trigger_summary and req.video_id:
        try:
            agent = _get_summary_agent()
            summary = agent.summarise(
                video_id=req.video_id,
                from_position_sec=req.position_sec,
                topic=req.topic,
                session_id=req.session_id,
                mastery_level=2,
                fatigue_label=fatigue_state.label,
            )
            result["summary"] = summary
            result["action"] = "show_summary"
        except Exception as e:
            result["summary_error"] = str(e)
    elif fatigue_state.label == "STRUGGLING":
        result["message"] = "Consider slowing down or taking a note. The content seems challenging."

    # 4. REFLECT: Log to data store
    _data_store.log_video_event(
        session_id=req.session_id,
        event_type=req.event_type,
        video_id=req.video_id,
        position_sec=req.position_sec,
        playback_rate=req.playback_rate,
        seek_delta_sec=req.seek_delta_sec,
        fatigue_score=fatigue_state.score,
        fatigue_label=fatigue_state.label,
    )

    return result


@app.get("/")
def root():
    return {
        "name": "Attention-Aware Study Assistant",
        "version": "2.0",
        "services": {
            "orchestrator": "/docs (root)",
            "attention_monitor": "/attention/docs",
            "learner_profiler": "/profiler/docs",
            "content_adapter": "/content/docs",
            "quiz_engine": "/quiz/docs",
            "data_store": "/data/docs",
            "video_fatigue_monitor": "/video-fatigue/docs",
            "youtube_recommender": "/youtube/docs",
            "transcription_summary": "/summary/docs",
        },
    }


if __name__ == "__main__":
    print("=" * 60)
    print("  Starting all 10 services on port 8000...")
    print("  API Docs: http://localhost:8000/docs")
    print("  Services: /attention, /profiler, /content, /quiz, /data")
    print("  Video:    /video-fatigue, /youtube, /summary")
    print("=" * 60)
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)
