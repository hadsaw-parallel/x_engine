import json
import logging
from datetime import datetime, timedelta

import anthropic

from config.settings import SUMMARY_LANGUAGE
from src.search import search_posts, unroll_thread, Post

logger = logging.getLogger(__name__)

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    """Return a cached Anthropic client, reading key from env at first use."""
    global _client
    if _client is None:
        import os
        api_key = os.getenv("CLAUDE_API_KEY", "")
        _client = anthropic.Anthropic(api_key=api_key)
    return _client


def _get_model() -> str:
    import os
    return os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

# Date range: last 30 days
_since_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")


async def research(question: str, status_callback=None) -> dict:
    """
    Full ReAct research pipeline:
    1. Analyze question → generate smart search queries
    2. Search X → collect posts → score quality
    3. Review: enough signal? If not, refine queries and search again (up to 3 rounds)
    4. Unroll top threads for full context
    5. Filter noise, rank, summarize — return research digest
    """

    all_posts: list[Post] = []
    seen_urls: set[str] = set()
    queries_used: list[str] = []

    # === ReAct Loop: up to 3 rounds ===
    for round_num in range(1, 4):
        if round_num == 1:
            queries = _generate_queries(question)
        else:
            # Ask Claude to refine based on what we've found so far
            queries = _refine_queries(question, queries_used, all_posts)
            if not queries:
                break

        if status_callback:
            await status_callback(
                f"🔍 Round {round_num}: Searching with {len(queries)} queries..."
            )

        queries_used.extend(queries)
        new_posts = await _run_searches(queries, seen_urls)
        all_posts.extend(new_posts)

        logger.info(
            f"Round {round_num}: {len(new_posts)} new posts, "
            f"{len(all_posts)} total"
        )

        # Check: do we have enough high-quality posts?
        quality_posts = [p for p in all_posts if p.quality_score > 5]
        if len(quality_posts) >= 8 or round_num == 3:
            break

        # If we have very few results, keep searching
        if len(all_posts) >= 50:
            break

    if not all_posts:
        return {"answer": "No posts found on X for this topic.", "posts": []}

    # === Sort by quality score ===
    all_posts.sort(key=lambda p: p.quality_score, reverse=True)

    # === Unroll threads for top posts ===
    if status_callback:
        await status_callback("📖 Unrolling top threads...")

    top_posts = all_posts[:15]
    for post in top_posts[:5]:  # unroll top 5 only (rate limit friendly)
        try:
            thread = await unroll_thread(post.url)
            if thread and len(thread) > len(post.text) * 1.5:
                post.is_thread = True
                post.thread_text = thread
        except Exception as e:
            logger.warning(f"Thread unroll failed for {post.url}: {e}")

    # === Final analysis ===
    if status_callback:
        await status_callback("🧠 Analyzing and writing digest...")

    result = _analyze_and_summarize(question, top_posts)
    return result


async def _run_searches(queries: list[str], seen_urls: set[str]) -> list[Post]:
    """Run multiple search queries, deduplicate results."""
    new_posts = []
    last_error = None

    for q in queries:
        try:
            posts = await search_posts(q, count=20)
            for p in posts:
                if p.url not in seen_urls:
                    seen_urls.add(p.url)
                    new_posts.append(p)
        except Exception as e:
            logger.warning(f"Search failed for '{q}': {e}")
            last_error = e

    # If ALL queries failed, raise so the user sees the actual error
    if not new_posts and last_error is not None:
        raise RuntimeError(f"All searches failed: {last_error}")

    return new_posts


def _generate_queries(question: str) -> list[str]:
    """Use Claude to break a question into smart X search queries."""

    response = _get_client().messages.create(
        model=_get_model(),
        max_tokens=1024,
        system=(
            "You are an expert X/Twitter search strategist.\n\n"
            "Given a research question, generate 3-5 targeted search queries "
            "to find HIGH-QUALITY posts on X — real builds, demos, tutorials, "
            "code, launches, research, and genuine insights.\n\n"
            "Rules:\n"
            "- Use X search operators: min_faves:5, filter:links, -filter:retweets\n"
            f"- Add 'since:{_since_date}' to limit to recent posts\n"
            "- Mix approaches: technical keywords, known people/companies, product names\n"
            "- Keep queries short (2-5 keywords + operators)\n"
            "- One query should be broad, others should be specific angles\n\n"
            "Return ONLY a JSON array of query strings."
        ),
        messages=[{"role": "user", "content": question}],
    )

    return _parse_json_array(response.content[0].text)


def _refine_queries(question: str, used_queries: list[str], found_posts: list[Post]) -> list[str]:
    """Ask Claude to generate new queries based on what we've found so far."""

    post_summary = ""
    for p in found_posts[:10]:
        post_summary += f"- @{p.username}: {p.text[:100]}... (score: {p.quality_score})\n"

    response = _get_client().messages.create(
        model=_get_model(),
        max_tokens=1024,
        system=(
            "You are refining a search on X/Twitter. The initial queries didn't find "
            "enough high-quality results.\n\n"
            "Given: the original question, queries already tried, and posts found so far, "
            "generate 2-3 NEW queries that:\n"
            "- Take a different angle (different keywords, people, related topics)\n"
            "- Are more specific or use different terminology\n"
            "- Target people who actually build things (use min_faves:10, filter:links)\n"
            f"- Use 'since:{_since_date}' for recency\n\n"
            "If the existing results are already good enough, return an empty array [].\n"
            "Return ONLY a JSON array."
        ),
        messages=[{
            "role": "user",
            "content": (
                f"Question: {question}\n\n"
                f"Queries tried: {json.dumps(used_queries)}\n\n"
                f"Posts found so far:\n{post_summary}"
            ),
        }],
    )

    return _parse_json_array(response.content[0].text)


def _analyze_and_summarize(question: str, posts: list[Post]) -> dict:
    """Filter noise, rank by relevance, create research digest."""

    posts_text = ""
    for i, post in enumerate(posts):
        content = post.thread_text if post.is_thread else post.text
        thread_label = " [THREAD]" if post.is_thread else ""

        posts_text += (
            f"[{i}] @{post.username}{thread_label}\n"
            f"{content}\n"
            f"Likes: {post.likes} | Retweets: {post.retweets} | "
            f"Replies: {post.replies} | Followers: {post.followers} | "
            f"Quality Score: {post.quality_score}\n"
            f"Date: {post.created_at} | URL: {post.url}\n\n"
        )

    response = _get_client().messages.create(
        model=_get_model(),
        max_tokens=4096,
        system=(
            "You are a senior tech research analyst. A user asked a question and we "
            "searched X/Twitter extensively. Your job:\n\n"
            "1. FILTER aggressively:\n"
            "   - KEEP: real builds, working demos, tutorials with code, launch "
            "announcements with substance, research findings, detailed technical "
            "insights, experience reports from practitioners\n"
            "   - REMOVE: hype, generic opinions, self-promotion without substance, "
            "engagement bait, reposts, 'just learned about X' without adding value\n\n"
            "2. RANK by: relevance to the question > depth of insight > quality score\n\n"
            "3. SUMMARIZE each kept post in 2-3 lines focusing on WHAT they built/found "
            "and WHY it matters\n\n"
            "4. SYNTHESIZE a 3-5 sentence overview answering the user's question based "
            "on the collective findings\n\n"
            f"Language: {SUMMARY_LANGUAGE}\n\n"
            "Return ONLY valid JSON:\n"
            "{\n"
            '  "answer": "3-5 sentence synthesis answering the question",\n'
            '  "posts": [\n'
            '    {"index": 0, "summary": "2-3 line summary", "relevance": "why this matters"}\n'
            "  ]\n"
            "}\n\n"
            "Select 5-10 BEST posts. Quality over quantity. "
            "If nothing is genuinely relevant, return empty posts with an honest answer."
        ),
        messages=[{
            "role": "user",
            "content": f"Question: {question}\n\nPosts:\n\n{posts_text}",
        }],
    )

    text = response.content[0].text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0]

    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Failed to parse analysis JSON")
        return {"answer": text[:500], "posts": []}

    # Enrich with original post data
    enriched = []
    for item in result.get("posts", []):
        idx = item.get("index", -1)
        if 0 <= idx < len(posts):
            post = posts[idx]
            enriched.append({
                "username": post.username,
                "text": post.text,
                "likes": post.likes,
                "retweets": post.retweets,
                "replies": post.replies,
                "url": post.url,
                "created_at": post.created_at,
                "quality_score": post.quality_score,
                "is_thread": post.is_thread,
                "summary": item.get("summary", ""),
                "relevance": item.get("relevance", ""),
            })

    return {"answer": result.get("answer", ""), "posts": enriched}


def _parse_json_array(text: str) -> list[str]:
    """Parse a JSON array of strings from Claude's response."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0]

    try:
        result = json.loads(text)
        if isinstance(result, list) and all(isinstance(q, str) for q in result):
            return result[:5]
    except json.JSONDecodeError:
        logger.warning(f"Failed to parse JSON array: {text[:100]}")

    return []
