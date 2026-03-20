def format_research(result: dict, query: str) -> str:
    """Format the agent's research result as a Telegram message."""
    posts = result.get("posts", [])
    answer = result.get("answer", "")

    lines = [f"🧠 *Research: {_escape_md(query)}*\n"]

    if answer:
        lines.append(f"_{_escape_md(answer)}_\n")

    if not posts:
        lines.append("No high\\-quality posts found\\.")
        return "\n".join(lines)

    lines.append(f"📌 *Top {len(posts)} posts:*\n")

    for i, post in enumerate(posts, 1):
        username = _escape_md(post["username"])
        summary = _escape_md(post["summary"])
        likes = post["likes"]
        retweets = post["retweets"]
        replies = post.get("replies", 0)
        score = post.get("quality_score", 0)
        url = post["url"]
        is_thread = post.get("is_thread", False)
        relevance = post.get("relevance", "")

        thread_tag = " 🧵" if is_thread else ""
        score_bar = _score_bar(score)

        block = f"*{i}\\. @{username}*{_escape_md(thread_tag)}\n"
        block += f"{summary}\n"

        if relevance:
            block += f"💡 _{_escape_md(relevance)}_\n"

        block += (
            f"❤️ {likes}  🔁 {retweets}  💬 {replies}  "
            f"{score_bar}  [Open]({url})\n"
        )

        lines.append(block)

    return "\n".join(lines)


def _score_bar(score: float) -> str:
    """Visual quality score indicator."""
    if score >= 20:
        return "🔥🔥🔥"
    elif score >= 10:
        return "🔥🔥"
    elif score >= 5:
        return "🔥"
    else:
        return "⭐"


def _escape_md(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    special = r"_*[]()~`>#+-=|{}.!"
    escaped = ""
    for char in text:
        if char in special:
            escaped += f"\\{char}"
        else:
            escaped += char
    return escaped
