"""
SVC-10 · Transcription Summary Agent
Port: 8008 | Video transcript → LLM-powered learner-friendly summary

Strategy:
  1. Try YouTube auto-captions via youtube_transcript_api
  2. Try web-scraping captions from YouTube page HTML
  3. If no transcript available, ask LLM to summarise based on video title/topic

When Video Fatigue Monitor signals high fatigue, this service:
  1. Gets transcript for the video (captions or fallback)
  2. Sends transcript to Ollama LLM with a structured prompt
  3. Returns readable summary replacing remaining video content
"""

import os
import re
import sys
import json
import hashlib
import requests
from pathlib import Path
from dataclasses import dataclass, asdict
from dotenv import load_dotenv

load_dotenv()

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


@dataclass
class SummaryResult:
    """Structured summary output."""
    summary_markdown: str
    key_concepts: list
    estimated_read_sec: int
    video_section_covered: str
    prerequisite_gaps: list
    video_id: str
    transcript_source: str = "none"
    cached: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


class TranscriptionSummaryAgent:
    """
    Generates learner-friendly summaries from video transcripts.

    Pipeline:
    1. Get transcript (YouTube captions → web scrape → topic-only fallback)
    2. Summarise via LLM (Ollama llama3.1:8b)
    """

    def __init__(self):
        from services.llm_provider import get_llm
        self.llm = get_llm()
        # In-memory cache
        self._cache: dict[str, SummaryResult] = {}

    def summarise(
        self,
        video_id: str,
        from_position_sec: int = 0,
        to_position_sec: int = 0,
        topic: str = "",
        session_id: str = "",
        mastery_level: int = 2,
        fatigue_label: str = "CRITICAL",
    ) -> dict:
        """Generate a summary for a video segment."""
        # Check cache
        cache_key = f"{video_id}_{from_position_sec}_{to_position_sec}"
        if cache_key in self._cache:
            result = self._cache[cache_key]
            result.cached = True
            return result.to_dict()

        # Step 1: Get transcript (try multiple methods)
        transcript_text, source = self._get_transcript(video_id, from_position_sec, to_position_sec)

        # Step 2: Generate summary via LLM
        result = self._generate_summary(
            transcript_text, source, video_id,
            from_position_sec, to_position_sec,
            topic, mastery_level, fatigue_label,
        )

        # Cache result
        self._cache[cache_key] = result
        return result.to_dict()

    def _get_transcript(self, video_id: str, from_sec: int, to_sec: int) -> tuple[str, str]:
        """Get transcript. Returns (text, source_method)."""
        # Try 1: YouTube transcript API
        text = self._try_captions_api(video_id, from_sec, to_sec)
        if text and len(text) > 50:
            print(f"[SVC-10] Got transcript via API ({len(text)} chars)")
            return text, "youtube_captions"

        # Try 2: Web scrape captions from YouTube page
        text = self._try_web_scrape(video_id)
        if text and len(text) > 50:
            print(f"[SVC-10] Got transcript via web scrape ({len(text)} chars)")
            return text, "web_scrape"

        # Try 3: Check cached transcript files
        text = self._try_cached_file(video_id, from_sec, to_sec)
        if text and len(text) > 50:
            print(f"[SVC-10] Got transcript from cached file ({len(text)} chars)")
            return text, "cached_file"

        # No transcript available — LLM will work from topic only
        print(f"[SVC-10] No transcript found for {video_id}, using topic-only summary")
        return "", "topic_only"

    def _try_captions_api(self, video_id: str, from_sec: int, to_sec: int) -> str:
        """Try YouTube auto-captions via youtube_transcript_api."""
        try:
            from youtube_transcript_api import YouTubeTranscriptApi
            ytt = YouTubeTranscriptApi()

            # Try English first
            try:
                result = ytt.fetch(video_id=video_id, languages=["en"])
            except Exception:
                try:
                    transcript_list = ytt.list(video_id=video_id)
                    available = None
                    for t in transcript_list:
                        available = t
                        break
                    if available is None:
                        return ""
                    result = ytt.fetch(video_id=video_id, languages=[available.language_code])
                except Exception:
                    return ""

            # Filter to time range
            segments = []
            for snippet in result.snippets:
                seg_start = snippet.start
                if to_sec > 0 and seg_start > to_sec:
                    break
                if seg_start >= from_sec or from_sec == 0:
                    segments.append(snippet.text.strip())
            return " ".join(segments)

        except ImportError:
            return ""
        except Exception as e:
            print(f"[SVC-10] Caption API failed: {e}")
            return ""

    def _try_web_scrape(self, video_id: str) -> str:
        """Scrape captions from YouTube video page HTML."""
        try:
            url = f"https://www.youtube.com/watch?v={video_id}"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept-Language": "en-US,en;q=0.9",
            }
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code != 200:
                return ""

            html = resp.text

            # Extract captions from playerCaptionsTracklistRenderer
            caption_match = re.search(r'"captionTracks":\s*(\[.*?\])', html)
            if caption_match:
                try:
                    tracks = json.loads(caption_match.group(1))
                    # Get the first caption track URL
                    if tracks:
                        caption_url = tracks[0].get("baseUrl", "")
                        if caption_url:
                            cap_resp = requests.get(caption_url, timeout=10)
                            if cap_resp.status_code == 200:
                                # Parse XML captions
                                texts = re.findall(r'<text[^>]*>(.*?)</text>', cap_resp.text)
                                # Clean HTML entities
                                import html as html_mod
                                texts = [html_mod.unescape(t) for t in texts]
                                return " ".join(texts)
                except Exception:
                    pass

            # Fallback: extract from page description/meta
            desc_match = re.search(r'"shortDescription":"(.*?)"', html)
            if desc_match:
                desc = desc_match.group(1).replace("\\n", " ").replace('\\"', '"')
                if len(desc) > 100:
                    return desc

            return ""
        except Exception as e:
            print(f"[SVC-10] Web scrape failed: {e}")
            return ""

    def _try_cached_file(self, video_id: str, from_sec: int, to_sec: int) -> str:
        """Check for existing transcript files from the pipeline."""
        try:
            data_dir = PROJECT_ROOT / "transcriber" / "data" / video_id
            transcript_file = data_dir / f"{video_id}_transcript.json"
            if not transcript_file.exists():
                return ""

            with open(transcript_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            segments = data.get("segments", [])
            texts = []
            for seg in segments:
                start = seg.get("start", 0)
                if to_sec > 0 and start > to_sec:
                    break
                if start >= from_sec:
                    texts.append(seg.get("text", "").strip())
            return " ".join(texts) if texts else data.get("full_text", "")
        except Exception:
            return ""

    def _generate_summary(
        self, transcript_text: str, source: str, video_id: str,
        from_sec: int, to_sec: int, topic: str,
        mastery_level: int, fatigue_label: str,
    ) -> SummaryResult:
        """Generate summary using Ollama LLM."""
        # Truncate transcript if too long
        max_chars = 3000
        if len(transcript_text) > max_chars:
            transcript_text = transcript_text[:max_chars] + "..."

        # Build prompt based on what we have
        if transcript_text:
            prompt = f"""Summarize this video transcript for a fatigued student.

Topic: {topic or 'Educational Video'}
Video section: {self._format_time(from_sec)} to {self._format_time(to_sec) if to_sec > 0 else 'end'}
Student fatigue: {fatigue_label}

TRANSCRIPT:
{transcript_text}

Write a clear, structured summary with:
1. A brief overview (2-3 sentences)
2. 3-5 key points using bullet points
3. One key takeaway sentence

Use simple language. Be concise but thorough. Format in clean Markdown."""
        else:
            # No transcript — generate based on topic only
            prompt = f"""A student was watching a YouTube video about "{topic or 'an educational topic'}" but became fatigued (fatigue level: {fatigue_label}).

Since the transcript is not available, please provide:
1. A helpful overview of the topic "{topic}" (2-3 sentences)
2. 3-5 key concepts typically covered in a video about this topic
3. Key takeaway and suggested next steps

Write in clean Markdown. Be helpful and educational."""

        # Call LLM
        try:
            summary_text = self.llm.generate(
                system_prompt="You are a helpful learning assistant. Write clear, structured summaries in Markdown format. Keep it concise and easy to scan.",
                user_message=prompt,
                max_tokens=600,
            )

            if not summary_text or len(summary_text) < 20:
                summary_text = self._fallback_extractive(transcript_text, topic)

        except Exception as e:
            print(f"[SVC-10] LLM generation failed: {e}")
            summary_text = self._fallback_extractive(transcript_text, topic)

        # Extract concepts
        concepts = self._extract_concepts(summary_text)
        word_count = len(summary_text.split())

        return SummaryResult(
            summary_markdown=summary_text,
            key_concepts=concepts,
            estimated_read_sec=max(30, word_count // 4),
            video_section_covered=self._format_time_range(from_sec, to_sec),
            prerequisite_gaps=[],
            video_id=video_id,
            transcript_source=source,
        )

    def _fallback_extractive(self, transcript_text: str, topic: str) -> str:
        """Simple extractive summary when LLM fails."""
        if transcript_text and len(transcript_text) > 100:
            words = transcript_text.split()
            excerpt = " ".join(words[:150])
            return f"## Summary\n\n{excerpt}..."
        return f"## Summary\n\n*Summary for \"{topic}\" could not be generated. Please review the video content directly.*"

    def _extract_concepts(self, summary: str) -> list:
        """Extract key concepts from summary text."""
        bold_terms = re.findall(r"\*\*([^*]+)\*\*", summary)
        seen = set()
        concepts = []
        for term in bold_terms:
            t = term.strip().lower()
            if t not in seen and 2 < len(t) < 50:
                seen.add(t)
                concepts.append(term.strip())
            if len(concepts) >= 8:
                break
        return concepts

    def get_cached(self, video_id: str) -> dict | None:
        """Get any cached summary for a video."""
        for key, result in self._cache.items():
            if video_id in key:
                return result.to_dict()
        return None

    @staticmethod
    def _format_time(seconds: int) -> str:
        m, s = divmod(seconds, 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"

    @staticmethod
    def _format_time_range(from_sec: int, to_sec: int) -> str:
        fmt = TranscriptionSummaryAgent._format_time
        if to_sec > 0:
            return f"{fmt(from_sec)} – {fmt(to_sec)}"
        return f"{fmt(from_sec)} – end"


# ─── CLI Test ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    agent = TranscriptionSummaryAgent()
    print(f"LLM: {agent.llm.get_info()}\n")

    video_id = input("YouTube video ID (e.g. dQw4w9WgXcQ): ").strip() or "dQw4w9WgXcQ"
    result = agent.summarise(
        video_id=video_id,
        from_position_sec=0,
        to_position_sec=300,
        topic="general",
        mastery_level=2,
    )
    print(f"\n{result['summary_markdown']}")
    print(f"\nSource: {result['transcript_source']}")
    print(f"Concepts: {result['key_concepts']}")
    print(f"Read time: {result['estimated_read_sec']}s")
