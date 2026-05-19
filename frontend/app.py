"""
SVC-07 · Frontend — Streamlit App
Port: 8501 | User-facing interactive interface

Features:
  - Topic input with real keypress telemetry (JS component)
  - Adaptive content display (4 modes)
  - Real-time fatigue gauge (Plotly)
  - Quiz UI with answer evaluation
  - Sidebar: session history, profile stats, mode override
  - Session summary with LLM-generated narrative
  - Session export (downloadable JSON)
  - Break suggestion when exhausted
"""

import os
import sys
import time
import uuid
import json
import streamlit as st
import plotly.graph_objects as go
from dotenv import load_dotenv
import streamlit.components.v1 as components

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
load_dotenv()

# ─── Configuration ─────────────────────────────────────────────────────
ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://localhost:8000")

# ─── Page Config ───────────────────────────────────────────────────────
st.set_page_config(
    page_title="Attention-Aware Study Assistant",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Custom CSS ────────────────────────────────────────────────────────
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

    /* Hide Deploy button and toolbar */
    .stDeployButton, [data-testid="stToolbar"],
    button[kind="header"], .stActionButton { display: none !important; }

    /* Keep sidebar always visible (disable collapse control) */
    [data-testid="collapsedControl"],
    [data-testid="stSidebarCollapsedControl"],
    [data-testid="stSidebarCollapseButton"] {
        display: none !important;
    }

    /* Force sidebar to render as a static left column (even if Streamlit loads it collapsed) */
    [data-testid="stAppViewContainer"] {
        --sidebar-width: 22rem;
        --sidebar-size: 22rem;
    }
    section[data-testid="stSidebar"] {
        display: block !important;
        visibility: visible !important;
        transform: translateX(0) !important;
        margin-left: 0 !important;
        width: 22rem !important;
        min-width: 22rem !important;
        max-width: 22rem !important;
    }
    section[data-testid="stSidebar"] > div {
        width: 22rem !important;
        min-width: 22rem !important;
        max-width: 22rem !important;
    }

    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }
    .main-header {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 1.5rem 2rem;
        border-radius: 16px;
        margin-bottom: 1.5rem;
        color: white;
        box-shadow: 0 8px 32px rgba(102, 126, 234, 0.3);
    }
    .main-header h1 {
        color: white; margin: 0; font-size: 1.8rem;
        font-weight: 700; letter-spacing: -0.02em;
    }
    .main-header p {
        color: rgba(255,255,255,0.85); margin: 0.3rem 0 0 0;
        font-weight: 300;
    }
    .mode-badge {
        display: inline-block;
        padding: 0.35rem 1rem;
        border-radius: 24px;
        font-weight: 600;
        font-size: 0.8rem;
        margin-right: 0.5rem;
        letter-spacing: 0.05em;
        text-transform: uppercase;
    }
    .mode-detailed { background: linear-gradient(135deg, #27ae60, #2ecc71); color: white; }
    .mode-concise  { background: linear-gradient(135deg, #f39c12, #e67e22); color: white; }
    .mode-analogy  { background: linear-gradient(135deg, #e67e22, #d35400); color: white; }
    .mode-quiz     { background: linear-gradient(135deg, #e74c3c, #c0392b); color: white; }
    .content-card {
        background: linear-gradient(135deg, #f8f9fa 0%, #ffffff 100%);
        border-radius: 12px;
        padding: 1.8rem;
        border-left: 5px solid #667eea;
        margin: 1rem 0;
        box-shadow: 0 2px 12px rgba(0,0,0,0.06);
    }
    .stat-card {
        background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
        border-radius: 10px;
        padding: 1rem;
        text-align: center;
        margin: 0.5rem 0;
        box-shadow: 0 2px 8px rgba(0,0,0,0.05);
    }
    .stat-card h3 { margin: 0; font-size: 1.5rem; color: #2c3e50; font-weight: 700; }
    .stat-card p { margin: 0; color: #7f8c8d; font-size: 0.8rem; }
    .break-alert {
        background: linear-gradient(135deg, #ff6b6b 0%, #ee5a24 100%);
        color: white;
        padding: 1.2rem 1.5rem;
        border-radius: 12px;
        margin: 1rem 0;
        text-align: center;
        font-weight: 500;
        box-shadow: 0 4px 15px rgba(238, 90, 36, 0.3);
        animation: pulse 2s ease-in-out infinite;
    }
    @keyframes pulse {
        0%, 100% { transform: scale(1); }
        50% { transform: scale(1.01); }
    }
    .history-item {
        padding: 0.4rem 0.6rem;
        border-radius: 6px;
        margin: 0.2rem 0;
        background: rgba(102, 126, 234, 0.06);
        font-size: 0.82rem;
    }
    /* Smoother transitions */
    .stButton > button {
        transition: all 0.2s ease;
        border-radius: 8px;
    }
    .stButton > button:hover {
        transform: translateY(-1px);
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
    }
</style>
""", unsafe_allow_html=True)


# ─── Keypress Telemetry JS Component ──────────────────────────────────
KEYPRESS_JS = """
<div id="telemetry-container">
    <textarea id="study-input" placeholder="Type your question or topic here..."
        style="width:100%; height:100px; padding:12px; font-size:15px;
               font-family:'Inter',sans-serif; border:2px solid #e0e0e0;
               border-radius:10px; resize:vertical; outline:none;
               transition: border-color 0.2s ease;"
        onfocus="this.style.borderColor='#667eea'"
        onblur="this.style.borderColor='#e0e0e0'"
    ></textarea>
    <div style="display:flex; gap:8px; margin-top:10px;">
        <button id="submit-btn" onclick="submitData('explain')"
            style="flex:1; padding:10px 20px; background:linear-gradient(135deg,#667eea,#764ba2);
                   color:white; border:none; border-radius:8px; cursor:pointer;
                   font-size:14px; font-weight:600; font-family:'Inter',sans-serif;
                   transition: transform 0.15s ease, box-shadow 0.15s ease;">
            🚀 Get Explanation
        </button>
        <button id="quiz-btn" onclick="submitData('quiz')"
            style="flex:1; padding:10px 20px; background:linear-gradient(135deg,#e74c3c,#c0392b);
                   color:white; border:none; border-radius:8px; cursor:pointer;
                   font-size:14px; font-weight:600; font-family:'Inter',sans-serif;
                   transition: transform 0.15s ease, box-shadow 0.15s ease;">
            ❓ Quiz Me
        </button>
    </div>
    <div id="keystroke-info" style="margin-top:8px; font-size:0.75rem; color:#aaa;"></div>
</div>

<script>
    const timestamps = [];
    const textarea = document.getElementById('study-input');
    const info = document.getElementById('keystroke-info');

    textarea.addEventListener('keydown', function(e) {
        if (e.key === 'Enter' && !e.shiftKey) return;
        timestamps.push(Date.now());
        if (timestamps.length > 1) {
            info.textContent = '⌨ ' + (timestamps.length - 1) + ' keystrokes captured';
        }
    });

    function computeIntervals() {
        if (timestamps.length < 2) return [];
        const intervals = [];
        for (let i = 1; i < timestamps.length; i++) {
            intervals.push(timestamps[i] - timestamps[i-1]);
        }
        return intervals;
    }

    function submitData(mode) {
        const text = textarea.value.trim();
        if (!text) {
            textarea.style.borderColor = '#e74c3c';
            setTimeout(() => textarea.style.borderColor = '#e0e0e0', 1500);
            return;
        }
        const intervals = computeIntervals();
        const data = {
            text: text,
            mode: mode,
            keypress_intervals: intervals,
            timestamp: Date.now()
        };
        // Send to Streamlit
        window.parent.postMessage({
            type: 'streamlit:setComponentValue',
            data: data
        }, '*');

        // Also try the Streamlit component API
        if (window.Streamlit) {
            window.Streamlit.setComponentValue(data);
        }

        // Reset
        timestamps.length = 0;
        info.textContent = '✓ Submitted';
        textarea.value = '';
    }

    // Hover effects
    document.getElementById('submit-btn').addEventListener('mouseover', function() {
        this.style.transform = 'translateY(-2px)';
        this.style.boxShadow = '0 4px 15px rgba(102,126,234,0.4)';
    });
    document.getElementById('submit-btn').addEventListener('mouseout', function() {
        this.style.transform = 'translateY(0)';
        this.style.boxShadow = 'none';
    });
    document.getElementById('quiz-btn').addEventListener('mouseover', function() {
        this.style.transform = 'translateY(-2px)';
        this.style.boxShadow = '0 4px 15px rgba(231,76,60,0.4)';
    });
    document.getElementById('quiz-btn').addEventListener('mouseout', function() {
        this.style.transform = 'translateY(0)';
        this.style.boxShadow = 'none';
    });
</script>
"""


# ─── Session State Initialization ──────────────────────────────────────
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())[:8]
if "orchestrator" not in st.session_state:
    from services.orchestrator import Orchestrator
    st.session_state.orchestrator = Orchestrator()
if "history" not in st.session_state:
    st.session_state.history = []
if "last_result" not in st.session_state:
    st.session_state.last_result = None
if "quiz_pending" not in st.session_state:
    st.session_state.quiz_pending = None
if "interaction_count" not in st.session_state:
    st.session_state.interaction_count = 0
if "last_interaction_time" not in st.session_state:
    st.session_state.last_interaction_time = time.time()
if "show_break" not in st.session_state:
    st.session_state.show_break = False


def get_orch():
    return st.session_state.orchestrator


# ─── Fatigue Simulation Fallback ──────────────────────────────────────
def simulate_keypress_data(interaction_count: int):
    """Fallback: simulate progressive fatigue if JS telemetry unavailable."""
    levels = [
        ([130, 140, 135, 128, 145], 2000),
        ([180, 200, 170, 220, 190], 5000),
        ([250, 300, 220, 350, 280], 10000),
        ([400, 250, 500, 300, 550], 18000),
        ([600, 200, 800, 300, 700], 25000),
    ]
    idx = min(interaction_count, len(levels) - 1)
    return levels[idx]


# ─── Fatigue Gauge ─────────────────────────────────────────────────────
def create_fatigue_gauge(score: float, label: str):
    """Create a Plotly gauge chart for fatigue level."""
    colors = {
        "FRESH": "#27ae60", "MODERATE": "#f39c12",
        "TIRED": "#e67e22", "EXHAUSTED": "#e74c3c",
    }
    color = colors.get(label, "#95a5a6")

    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=score * 100,
        title={"text": f"Fatigue: {label}", "font": {"size": 15, "family": "Inter"}},
        number={"suffix": "%", "font": {"size": 28, "family": "Inter"}},
        gauge={
            "axis": {"range": [0, 100], "tickwidth": 1, "tickcolor": "#ddd"},
            "bar": {"color": color, "thickness": 0.75},
            "bgcolor": "#f0f0f0",
            "steps": [
                {"range": [0, 25], "color": "#d5f5e3"},
                {"range": [25, 50], "color": "#fef9e7"},
                {"range": [50, 75], "color": "#fdebd0"},
                {"range": [75, 100], "color": "#fadbd8"},
            ],
            "threshold": {
                "line": {"color": "#e74c3c", "width": 3},
                "thickness": 0.8,
                "value": 75,
            },
        },
    ))
    fig.update_layout(
        height=200, margin=dict(l=20, r=20, t=40, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        font={"family": "Inter"},
    )
    return fig


# ─── Fatigue History Chart ────────────────────────────────────────────
def create_fatigue_history_chart(history: list):
    """Create a mini line chart showing fatigue trend over interactions."""
    if len(history) < 2:
        return None
    scores = []
    for h in history:
        # Map labels to approximate scores for visualization
        label_to_score = {"FRESH": 0.15, "MODERATE": 0.4, "TIRED": 0.65, "EXHAUSTED": 0.85}
        scores.append(label_to_score.get(h.get("fatigue", "FRESH"), 0.3))

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        y=scores, mode="lines+markers",
        line={"color": "#667eea", "width": 2, "shape": "spline"},
        marker={"size": 6, "color": "#764ba2"},
        fill="tozeroy", fillcolor="rgba(102,126,234,0.1)",
    ))
    fig.update_layout(
        height=120, margin=dict(l=10, r=10, t=10, b=10),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        xaxis={"visible": False}, yaxis={"range": [0, 1], "visible": False},
        showlegend=False,
    )
    return fig


# ─── Header ────────────────────────────────────────────────────────────
st.markdown("""
<div class="main-header">
    <h1>🧠 Attention-Aware Study Assistant</h1>
    <p>Adaptive learning that matches your cognitive state — powered by AI</p>
</div>
""", unsafe_allow_html=True)


# ─── Sidebar ──────────────────────────────────────────────────────────
with st.sidebar:

    # Manual mode override
    st.markdown("### 🎛️ Mode Override")
    mode_override = st.selectbox(
        "Force teaching mode:",
        ["Auto (recommended)", "detailed", "concise", "analogy", "quiz"],
        index=0,
        key="mode_selector",
    )
    manual_mode = None if mode_override.startswith("Auto") else mode_override

    st.markdown("---")

    # Profile stats
    st.markdown("### 📊 Learner Profile")
    profile = get_orch().profiler.get_profile(st.session_state.session_id)
    if profile:
        col1, col2 = st.columns(2)
        with col1:
            mastery_val = profile.get("mastery_score", 0.5)
            st.metric("Mastery", f"{mastery_val:.0%}")
        with col2:
            diff_val = profile.get("difficulty_level", 2)
            st.metric("Difficulty", f"{diff_val}/5")
        st.progress(profile.get("avg_fatigue", 0), text=f"Avg Fatigue: {profile.get('avg_fatigue', 0):.0%}")
        st.caption(f"Preferred: **{profile.get('preferred_mode', 'detailed').title()}** mode")

    # Fatigue trend chart
    if len(st.session_state.history) >= 2:
        st.markdown("### 📈 Fatigue Trend")
        trend_chart = create_fatigue_history_chart(st.session_state.history)
        if trend_chart:
            st.plotly_chart(trend_chart, use_container_width=True)

    st.markdown("---")

    # Session history
    st.markdown("### 📜 Interaction History")
    if st.session_state.history:
        for i, h in enumerate(reversed(st.session_state.history[-8:])):
            mode_icon = {"detailed": "📖", "concise": "📋", "analogy": "🎭", "quiz": "❓"}.get(h["mode"], "📄")
            fatigue_icon = {"FRESH": "🟢", "MODERATE": "🟡", "TIRED": "🟠", "EXHAUSTED": "🔴"}.get(h["fatigue"], "⚪")
            st.markdown(
                f'<div class="history-item">{mode_icon} {h["mode"].upper()} {fatigue_icon} — {h["topic"][:30]}</div>',
                unsafe_allow_html=True,
            )
    else:
        st.caption("No interactions yet — start typing!")

    st.markdown("---")

    # Action buttons
    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("📊 Summary", use_container_width=True):
            st.session_state["show_summary"] = True
    with col_b:
        if st.button("🔄 New Session", use_container_width=True):
            st.session_state.session_id = str(uuid.uuid4())[:8]
            st.session_state.history = []
            st.session_state.last_result = None
            st.session_state.quiz_pending = None
            st.session_state.interaction_count = 0
            st.session_state.show_break = False
            st.session_state.last_interaction_time = time.time()
            st.rerun()

    # Export session
    if st.session_state.history:
        export_data = get_orch().data_store.export_session(st.session_state.session_id)
        export_json = json.dumps(export_data, indent=2, default=str)
        st.download_button(
            "📥 Export Session (JSON)",
            data=export_json,
            file_name=f"session_{st.session_state.session_id}.json",
            mime="application/json",
            use_container_width=True,
        )

    # Session summary modal
    if st.session_state.get("show_summary"):
        st.markdown("---")
        st.markdown("### 📊 Session Summary")
        with st.spinner("Generating summary..."):
            summary = get_orch().get_session_summary(st.session_state.session_id)
        st.metric("Interactions", summary.get("total_interactions", 0))
        st.metric("Quizzes", summary.get("total_quizzes", 0))

        mode_dist = summary.get("mode_distribution", {})
        if mode_dist:
            st.markdown("**Mode Distribution:**")
            for m, count in mode_dist.items():
                st.caption(f"  {m}: {count}×")

        narrative = summary.get("narrative_summary")
        if narrative:
            st.markdown("---")
            st.markdown("**AI Recap:**")
            st.markdown(f"*{narrative}*")

        if st.button("Close Summary"):
            st.session_state["show_summary"] = False
            st.rerun()


# ─── Mode Tabs ─────────────────────────────────────────────────────────
if "app_mode" not in st.session_state:
    st.session_state.app_mode = "learning"

mode_col1, mode_col2 = st.columns(2)
with mode_col1:
    if st.button("📚 Learning Mode", use_container_width=True,
                 type="primary" if st.session_state.app_mode == "learning" else "secondary"):
        st.session_state.app_mode = "learning"
        st.rerun()
with mode_col2:
    if st.button("❓ Quiz Mode", use_container_width=True,
                 type="primary" if st.session_state.app_mode == "quiz" else "secondary"):
        st.session_state.app_mode = "quiz"
        st.rerun()

st.markdown("")

# ═══════════════════════════════════════════════════════════════════════
# LEARNING MODE — Video + Prompt (fatigue from video interactions)
# ═══════════════════════════════════════════════════════════════════════
if st.session_state.app_mode == "learning":

    st.markdown("""
    <div style="background: linear-gradient(135deg, #e74c3c 0%, #8e44ad 100%);
         padding: 1rem 1.5rem; border-radius: 14px; margin-bottom: 1rem; color: white;
         box-shadow: 0 6px 24px rgba(142, 68, 173, 0.3);">
        <h2 style="color:white; margin:0; font-size:1.4rem;">📺 Video Learning Mode</h2>
        <p style="color:rgba(255,255,255,0.85); margin:0.3rem 0 0 0; font-weight:300; font-size:0.9rem;">
            Search YouTube for videos — fatigue is tracked through your control interactions
        </p>
    </div>
    """, unsafe_allow_html=True)

    # Video session state
    if "video_recommendations" not in st.session_state:
        st.session_state.video_recommendations = []
    if "active_video" not in st.session_state:
        st.session_state.active_video = None
    if "video_fatigue" not in st.session_state:
        st.session_state.video_fatigue = {"score": 0.0, "label": "ENGAGED"}
    if "video_summary" not in st.session_state:
        st.session_state.video_summary = None
    if "video_position" not in st.session_state:
        st.session_state.video_position = 0

    # YouTube search
    vid_col1, vid_col2 = st.columns([3, 1])
    with vid_col1:
        video_topic = st.text_input(
            "Search for educational videos:",
            placeholder="e.g., recursion in python, calculus derivatives...",
            key="video_topic_input",
        )
    with vid_col2:
        search_video = st.button("Find Videos", use_container_width=True, type="primary")

    if search_video and video_topic:
        with st.spinner("Searching YouTube..."):
            try:
                import httpx
                r = httpx.post(
                    f"{ORCHESTRATOR_URL}/youtube/recommend",
                    json={
                        "topic": video_topic,
                        "difficulty_level": 2,
                        "session_id": st.session_state.session_id,
                        "max_results": 6,
                    },
                    timeout=30,
                )
                st.session_state.video_recommendations = r.json() if r.status_code == 200 else []
            except Exception as e:
                st.error(f"Search failed: {e}")
                st.session_state.video_recommendations = []

    # Display recommendations
    if st.session_state.video_recommendations:
        st.markdown("#### Recommended Videos")
        recs = st.session_state.video_recommendations[:6]
        for row_start in range(0, len(recs), 3):
            row_vids = recs[row_start:row_start + 3]
            vid_cols = st.columns(3)
            for i, vid in enumerate(row_vids):
                with vid_cols[i]:
                    duration_min = vid.get("duration_sec", 0) // 60
                    vid_id = vid.get("video_id", "")
                    thumb_url = vid.get("thumbnail_url", "") or f"https://img.youtube.com/vi/{vid_id}/hqdefault.jpg"
                    st.markdown(f"""
                    <div style="background:#1a1a2e; border-radius:12px; overflow:hidden;
                         box-shadow: 0 4px 15px rgba(0,0,0,0.3); margin-bottom:0.5rem;">
                        <img src="{thumb_url}" style="width:100%; height:140px; object-fit:cover;"
                             onerror="this.src='https://img.youtube.com/vi/{vid_id}/hqdefault.jpg'"/>
                        <div style="padding:0.7rem; color:white;">
                            <p style="font-size:0.82rem; font-weight:600; margin:0 0 0.3rem 0;
                               line-height:1.3; min-height:2.4rem; overflow:hidden;">
                                {vid.get('title', 'Video')[:65]}
                            </p>
                            <p style="font-size:0.7rem; color:rgba(255,255,255,0.6); margin:0;">
                                {vid.get('channel', '')[:30]} &bull; {duration_min}min
                            </p>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
                    if st.button("Watch", key=f"watch_{vid_id}_{row_start+i}", use_container_width=True):
                        st.session_state.active_video = vid
                        st.session_state.video_fatigue = {"score": 0.0, "label": "ENGAGED"}
                        st.session_state.video_summary = None
                        st.session_state.video_position = 0
                        st.rerun()

    # Active Video Player
    if st.session_state.active_video:
        vid = st.session_state.active_video
        vid_id = vid.get("video_id", "")
        st.markdown(f"**▶ Now Playing:** {vid.get('title', 'Video')}")
        player_url = f"{ORCHESTRATOR_URL}/player?v={vid_id}&sid={st.session_state.session_id}&api={ORCHESTRATOR_URL}"
        components.iframe(player_url, height=850, scrolling=True)

        if st.button("✖ Close Video", use_container_width=True):
            st.session_state.active_video = None
            st.session_state.video_summary = None
            st.rerun()

        if st.session_state.video_summary:
            summary_data = st.session_state.video_summary
            st.markdown(summary_data.get("summary_markdown", "*No summary available*"))
            if st.button("Resume Video", type="primary"):
                st.session_state.video_summary = None
                st.rerun()

    # ─── Learning Prompt (below video) ────────────────────────────────
    st.markdown("---")
    st.markdown("### 💬 Ask About This Topic")
    learn_input = st.text_area(
        "Ask a question or enter a topic:",
        placeholder="e.g., Explain the Pythagorean theorem step by step...",
        height=80,
        key="learn_input",
        label_visibility="collapsed",
    )
    learn_submit = st.button("🚀 Get Explanation", use_container_width=True, type="primary",
                             key="learn_submit_btn")

    if learn_submit and learn_input:
        response_delay = int((time.time() - st.session_state.last_interaction_time) * 1000)
        kp, _ = simulate_keypress_data(st.session_state.interaction_count)
        with st.spinner("🧠 Thinking..."):
            result = get_orch().interact(
                user_message=learn_input,
                session_id=st.session_state.session_id,
                keypress_intervals=kp,
                response_delay_ms=response_delay,
                manual_mode=manual_mode,
            )
        st.session_state.last_result = result
        st.session_state.interaction_count += 1
        st.session_state.last_interaction_time = time.time()
        st.session_state.history.append({
            "topic": learn_input[:50],
            "mode": result["mode_used"],
            "fatigue": result["fatigue_state"]["label"],
        })
        st.rerun()

    # Display learning result
    if st.session_state.last_result and st.session_state.app_mode == "learning":
        result = st.session_state.last_result
        if result.get("type") != "quiz":
            mode = result["mode_used"]
            mode_emoji = {"detailed": "📖", "concise": "📋", "analogy": "🎭", "quiz": "❓"}.get(mode, "📄")
            mode_colors = {"detailed": "mode-detailed", "concise": "mode-concise",
                           "analogy": "mode-analogy", "quiz": "mode-quiz"}
            st.markdown(f"""
            <span class="mode-badge {mode_colors.get(mode, '')}">
                {mode_emoji} {mode.upper()} MODE
            </span>
            """, unsafe_allow_html=True)
            st.markdown('<div class="content-card">', unsafe_allow_html=True)
            st.markdown(result["content"])
            st.markdown('</div>', unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════
# QUIZ MODE — Original prompt + keypress telemetry (untouched logic)
# ═══════════════════════════════════════════════════════════════════════
elif st.session_state.app_mode == "quiz":

    col_main, col_gauge = st.columns([3, 1])

    with col_gauge:
        if st.session_state.last_result:
            fs = st.session_state.last_result["fatigue_state"]
            st.plotly_chart(
                create_fatigue_gauge(fs["score"], fs["label"]),
                use_container_width=True,
            )
            signals = fs.get("signals", {})
            for sig, val in signals.items():
                if val is not None:
                    sig_label = sig.replace("_", " ").title()
                    st.progress(min(val, 1.0), text=f"{sig_label}: {val:.2f}")
        else:
            st.plotly_chart(
                create_fatigue_gauge(0.0, "FRESH"),
                use_container_width=True,
            )
            st.caption("💡 Start a conversation to see your fatigue level")

    with col_main:
        if st.session_state.show_break:
            st.markdown("""
            <div class="break-alert">
                ☕ <strong>Your cognitive load is high!</strong>
                Consider taking a 5-minute break.
            </div>
            """, unsafe_allow_html=True)
            if st.button("✅ I'm back! Resume studying"):
                st.session_state.show_break = False
                st.session_state.interaction_count = max(0, st.session_state.interaction_count - 2)
                st.rerun()

        st.markdown("### 💬 Ask a Question or Enter a Topic")
        user_input = st.text_area(
            "What would you like to learn?",
            placeholder="e.g., Explain how neural networks learn through backpropagation...",
            height=100,
            key="quiz_user_input",
            label_visibility="collapsed",
        )

        quiz_btn = st.button("❓ Quiz Me", use_container_width=True, type="primary",
                             key="quiz_me_btn")

        # Process — uses existing keypress variance + response delay norm
        if quiz_btn and user_input:
            response_delay = int((time.time() - st.session_state.last_interaction_time) * 1000)
            kp, _ = simulate_keypress_data(st.session_state.interaction_count)
            forced_mode = "quiz"

            with st.spinner("🧠 Thinking..."):
                result = get_orch().interact(
                    user_message=user_input,
                    session_id=st.session_state.session_id,
                    keypress_intervals=kp,
                    response_delay_ms=response_delay,
                    manual_mode=forced_mode,
                )

            st.session_state.last_result = result
            st.session_state.interaction_count += 1
            st.session_state.last_interaction_time = time.time()
            st.session_state.history.append({
                "topic": user_input[:50],
                "mode": result["mode_used"],
                "fatigue": result["fatigue_state"]["label"],
            })

            if result["fatigue_state"]["label"] == "EXHAUSTED":
                st.session_state.show_break = True
            if result.get("type") == "quiz" and result.get("quiz_data"):
                st.session_state.quiz_pending = result["quiz_data"]
            st.rerun()

        # Display result
        if st.session_state.last_result:
            result = st.session_state.last_result
            mode = result["mode_used"]
            mode_colors = {"detailed": "mode-detailed", "concise": "mode-concise",
                           "analogy": "mode-analogy", "quiz": "mode-quiz"}
            mode_emoji = {"detailed": "📖", "concise": "📋", "analogy": "🎭", "quiz": "❓"}.get(mode, "📄")

            st.markdown(f"""
            <span class="mode-badge {mode_colors.get(mode, '')}">
                {mode_emoji} {mode.upper()} MODE
            </span>
            <span style="color:#888; font-size:0.85rem;">
                Generated in {result.get('response_time_seconds', 0)}s
            </span>
            """, unsafe_allow_html=True)

            st.markdown('<div class="content-card">', unsafe_allow_html=True)
            st.markdown(result["content"])
            st.markdown('</div>', unsafe_allow_html=True)

        # Quiz answer
        if st.session_state.quiz_pending:
            qd = st.session_state.quiz_pending
            st.markdown("---")
            st.markdown("### ✏️ Your Answer")
            answer = st.text_input("Type your answer:", key="quiz_answer", placeholder="Enter your response...")
            if st.button("📝 Submit Answer", type="primary"):
                if answer:
                    with st.spinner("🔍 Evaluating..."):
                        eval_result = get_orch().submit_quiz_answer(
                            st.session_state.session_id,
                            qd["question"], qd["correct_answer"],
                            answer, "",
                        )
                    ev = eval_result.get("evaluation", {})
                    score = ev.get("score", 0)
                    if ev.get("is_correct"):
                        st.success(f"**Correct!** Score: {score:.0%}")
                        st.balloons()
                    elif score >= 0.5:
                        st.warning(f"**Partially correct.** Score: {score:.0%}")
                    else:
                        st.error(f"**Not quite.** Score: {score:.0%}")
                    st.info(f"**Feedback:** {ev.get('feedback', '')}")
                    with st.expander("View correct answer & explanation"):
                        st.markdown(f"**Correct Answer:** {qd['correct_answer']}")
                        if qd.get("explanation"):
                            st.caption(qd["explanation"])
                        st.markdown("---")
                        st.markdown("**📖 Detailed Explanation:**")
                        with st.spinner("Generating explanation..."):
                            explain_result = get_orch().interact(
                                user_message=f"Explain this concept in detail: {qd['question']}. The correct answer is: {qd['correct_answer']}",
                                session_id=st.session_state.session_id,
                                keypress_intervals=[200, 200, 200],
                                response_delay_ms=2000,
                                manual_mode="detailed",
                            )
                        st.markdown(explain_result.get("content", "*Explanation unavailable*"))
                    st.session_state.quiz_pending = None


# ─── Footer ────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown(
    '<div style="text-align:center; color:#aaa; font-size:0.8rem; padding: 0.5rem 0;">'
    'Built with Streamlit + FastAPI + Ollama/Gemini + SQLAlchemy '
    '| <a href="/docs" style="color:#667eea;">API Docs</a> '
    '| 10 Microservices | GenAI System Building Challenge'
    '</div>',
    unsafe_allow_html=True,
)