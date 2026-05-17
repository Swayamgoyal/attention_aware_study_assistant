"""
SVC-09 · YouTube Recommender Agent
Port: 8007 | Topic → Top 3 relevant YouTube videos

Search strategy (priority):
  1. YouTube Data API v3 (if valid key set)
  2. YouTube web search scrape (no key needed, always works)

Applies quality filtering (duration, view count) and caches results per session.
"""

import os
import re
import json
import math
from dataclasses import dataclass, field, asdict
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv()


@dataclass
class VideoResult:
    """A recommended YouTube video."""
    video_id: str
    title: str
    channel: str
    duration_sec: int
    thumbnail_url: str
    youtube_url: str
    view_count: int = 0
    relevance_score: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


class YouTubeRecommender:
    """
    Recommends YouTube videos for a given study topic.

    Uses YouTube Data API v3 for search + video details.
    Falls back to YouTube web scrape if API key is invalid or missing.
    """

    def __init__(self):
        self.api_key = os.getenv("YOUTUBE_API_KEY", "").strip()
        self.cache: dict[str, list[dict]] = defaultdict(list)
        self._api_available = bool(self.api_key)
        self._api_validated = False  # Track if API key actually works

    def recommend(
        self,
        topic: str,
        difficulty_level: int = 2,
        session_id: str = "",
        max_results: int = 3,
        max_duration_min: int = 20,
    ) -> list[dict]:
        """
        Search YouTube for educational videos matching the topic.

        Args:
            topic: Learning topic (e.g. "neural networks backpropagation")
            difficulty_level: 1-5 (adjusts search query)
            session_id: Session ID for caching
            max_results: Number of videos to return (default 3)
            max_duration_min: Maximum video duration in minutes

        Returns:
            List of VideoResult dicts
        """
        query = self._build_query(topic, difficulty_level)
        results = []

        # Try YouTube Data API first (if key exists and hasn't failed before)
        if self._api_available and not self._api_validated:
            results = self._search_youtube_api(query, max_results * 2, max_duration_min)

        # Fallback: YouTube web scrape (always works, no key needed)
        if not results:
            results = self._search_youtube_scrape(query, max_results * 2)

        # Filter and rank
        results = self._filter_and_rank(results, max_duration_min)[:max_results]

        # Cache
        result_dicts = [r.to_dict() for r in results]
        if session_id:
            self.cache[session_id] = result_dicts

        return result_dicts

    def get_cached(self, session_id: str) -> list[dict]:
        """Get cached recommendations for a session."""
        return self.cache.get(session_id, [])

    def _build_query(self, topic: str, difficulty: int) -> str:
        """Build an optimized search query based on topic and difficulty."""
        if difficulty <= 2:
            return f"{topic} tutorial for beginners explained simply"
        elif difficulty <= 3:
            return f"{topic} tutorial intermediate explanation"
        else:
            return f"{topic} advanced concepts deep dive"

    def _search_youtube_api(self, query: str, max_results: int, max_duration_min: int) -> list[VideoResult]:
        """Search using YouTube Data API v3."""
        try:
            import httpx

            search_url = "https://www.googleapis.com/youtube/v3/search"
            params = {
                "part": "snippet",
                "q": query,
                "type": "video",
                "videoDuration": "medium" if max_duration_min <= 20 else "long",
                "order": "relevance",
                "maxResults": max_results,
                "key": self.api_key,
                "relevanceLanguage": "en",
                "videoEmbeddable": "true",
            }

            resp = httpx.get(search_url, params=params, timeout=15)
            if resp.status_code != 200:
                print(f"[YouTube API] Search failed: {resp.status_code}")
                self._api_validated = True  # Mark as failed so we skip next time
                return []

            search_data = resp.json()
            video_ids = [item["id"]["videoId"] for item in search_data.get("items", [])]

            if not video_ids:
                return []

            # Get video details
            details_url = "https://www.googleapis.com/youtube/v3/videos"
            details_params = {
                "part": "contentDetails,statistics,snippet",
                "id": ",".join(video_ids),
                "key": self.api_key,
            }

            resp2 = httpx.get(details_url, params=details_params, timeout=15)
            if resp2.status_code != 200:
                return []

            details_data = resp2.json()
            results = []

            for item in details_data.get("items", []):
                vid = item["id"]
                snippet = item.get("snippet", {})
                content = item.get("contentDetails", {})
                stats = item.get("statistics", {})

                duration_sec = self._parse_duration(content.get("duration", "PT0S"))
                view_count = int(stats.get("viewCount", 0))
                thumbnail = (
                    snippet.get("thumbnails", {}).get("high", {}).get("url")
                    or snippet.get("thumbnails", {}).get("default", {}).get("url", "")
                )

                results.append(VideoResult(
                    video_id=vid,
                    title=snippet.get("title", ""),
                    channel=snippet.get("channelTitle", ""),
                    duration_sec=duration_sec,
                    thumbnail_url=thumbnail,
                    youtube_url=f"https://www.youtube.com/watch?v={vid}",
                    view_count=view_count,
                ))

            return results

        except Exception as e:
            print(f"[YouTube API] Error: {e}")
            return []

    def _search_youtube_scrape(self, query: str, max_results: int) -> list[VideoResult]:
        """
        Fallback: Scrape YouTube search results page.
        No API key needed — extracts video data from the search page's
        initial data JSON embedded in the HTML.
        """
        try:
            import httpx

            search_url = "https://www.youtube.com/results"
            params = {"search_query": query}
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                              "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9",
            }

            resp = httpx.get(search_url, params=params, headers=headers, timeout=15, follow_redirects=True)
            if resp.status_code != 200:
                print(f"[YouTube Scrape] Failed: {resp.status_code}")
                return []

            html = resp.text

            # Extract ytInitialData JSON from the page
            match = re.search(r"var ytInitialData\s*=\s*({.*?});\s*</script>", html)
            if not match:
                # Try alternate pattern
                match = re.search(r"ytInitialData\s*=\s*'({.*?})';", html)
            if not match:
                print("[YouTube Scrape] Could not find ytInitialData")
                return self._search_youtube_regex(html, max_results)

            try:
                data = json.loads(match.group(1))
            except json.JSONDecodeError:
                print("[YouTube Scrape] JSON parse failed")
                return self._search_youtube_regex(html, max_results)

            # Navigate the nested JSON to find video renderers
            results = []
            try:
                contents = (
                    data["contents"]["twoColumnSearchResultsRenderer"]
                    ["primaryContents"]["sectionListRenderer"]["contents"]
                )

                for section in contents:
                    items = section.get("itemSectionRenderer", {}).get("contents", [])
                    for item in items:
                        renderer = item.get("videoRenderer")
                        if not renderer:
                            continue

                        vid = renderer.get("videoId", "")
                        title = ""
                        title_runs = renderer.get("title", {}).get("runs", [])
                        if title_runs:
                            title = title_runs[0].get("text", "")

                        channel = ""
                        channel_runs = renderer.get("ownerText", {}).get("runs", [])
                        if channel_runs:
                            channel = channel_runs[0].get("text", "")

                        # Parse duration like "12:34" or "1:02:34"
                        duration_text = renderer.get("lengthText", {}).get("simpleText", "0:00")
                        duration_sec = self._parse_duration_text(duration_text)

                        # View count
                        view_text = renderer.get("viewCountText", {}).get("simpleText", "0 views")
                        view_count = self._parse_view_count(view_text)

                        if vid and title:
                            results.append(VideoResult(
                                video_id=vid,
                                title=title,
                                channel=channel,
                                duration_sec=duration_sec,
                                thumbnail_url=f"https://img.youtube.com/vi/{vid}/hqdefault.jpg",
                                youtube_url=f"https://www.youtube.com/watch?v={vid}",
                                view_count=view_count,
                            ))

                        if len(results) >= max_results:
                            break
                    if len(results) >= max_results:
                        break

            except (KeyError, TypeError, IndexError) as e:
                print(f"[YouTube Scrape] Parse error: {e}")
                if not results:
                    return self._search_youtube_regex(html, max_results)

            print(f"[YouTube Scrape] Found {len(results)} videos")
            return results

        except Exception as e:
            print(f"[YouTube Scrape] Error: {e}")
            return []

    def _search_youtube_regex(self, html: str, max_results: int) -> list[VideoResult]:
        """
        Last-resort fallback: extract video IDs from YouTube HTML via regex.
        Less data (no duration/views) but always works.
        """
        results = []
        seen = set()

        # Find videoId patterns in the HTML
        video_ids = re.findall(r'"videoId"\s*:\s*"([a-zA-Z0-9_-]{11})"', html)
        titles = re.findall(r'"title"\s*:\s*\{\s*"runs"\s*:\s*\[\s*\{\s*"text"\s*:\s*"([^"]+)"', html)

        for i, vid in enumerate(video_ids):
            if vid in seen:
                continue
            seen.add(vid)

            title = titles[i] if i < len(titles) else f"Video {vid}"

            results.append(VideoResult(
                video_id=vid,
                title=title,
                channel="",
                duration_sec=600,  # Assume 10 min
                thumbnail_url=f"https://img.youtube.com/vi/{vid}/hqdefault.jpg",
                youtube_url=f"https://www.youtube.com/watch?v={vid}",
                view_count=0,
            ))

            if len(results) >= max_results:
                break

        print(f"[YouTube Regex] Found {len(results)} videos")
        return results

    def _filter_and_rank(self, results: list[VideoResult], max_duration_min: int) -> list[VideoResult]:
        """Filter by duration and rank by relevance + view count."""
        max_sec = max_duration_min * 60
        filtered = [r for r in results if 0 < r.duration_sec <= max_sec]

        if not filtered:
            filtered = results  # Don't filter if nothing passes

        for i, r in enumerate(filtered):
            position_score = 1.0 - (i / max(len(filtered), 1))
            view_score = min(1.0, math.log10(max(r.view_count, 1)) / 7) if r.view_count > 0 else 0.3
            r.relevance_score = round(0.5 * position_score + 0.5 * view_score, 3)

        filtered.sort(key=lambda r: r.relevance_score, reverse=True)
        return filtered

    @staticmethod
    def _parse_duration(iso_duration: str) -> int:
        """Parse ISO 8601 duration (PT1H2M30S) to seconds."""
        pattern = r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?"
        match = re.match(pattern, iso_duration)
        if not match:
            return 0
        h = int(match.group(1) or 0)
        m = int(match.group(2) or 0)
        s = int(match.group(3) or 0)
        return h * 3600 + m * 60 + s

    @staticmethod
    def _parse_duration_text(text: str) -> int:
        """Parse human duration like '12:34' or '1:02:34' to seconds."""
        parts = text.strip().split(":")
        try:
            if len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            elif len(parts) == 2:
                return int(parts[0]) * 60 + int(parts[1])
            else:
                return 0
        except ValueError:
            return 0

    @staticmethod
    def _parse_view_count(text: str) -> int:
        """Parse view count like '1,234,567 views' to int."""
        nums = re.sub(r"[^\d]", "", text)
        return int(nums) if nums else 0

    def get_info(self) -> dict:
        return {
            "service": "youtube_recommender",
            "api_key_set": self._api_available,
            "method": "youtube_data_api_v3" if (self._api_available and not self._api_validated) else "web_scrape",
        }


# ─── CLI Test ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    rec = YouTubeRecommender()
    print(f"YouTube Recommender — {rec.get_info()}\n")

    topic = input("Enter a study topic (e.g. 'recursion in python'): ").strip() or "recursion python"
    print(f"\nSearching for: {topic}...")

    results = rec.recommend(topic, difficulty_level=2, session_id="cli-test")
    print(f"\nFound {len(results)} videos:\n")
    for i, v in enumerate(results, 1):
        mins = v["duration_sec"] // 60
        print(f"  {i}. {v['title']}")
        print(f"     Channel: {v['channel']} | {mins}min | {v['view_count']:,} views")
        print(f"     URL: {v['youtube_url']}")
        print(f"     Relevance: {v['relevance_score']}")
        print()
