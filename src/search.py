import os
import asyncio
import logging
from dataclasses import dataclass, field
from twikit import Client

from config.settings import COOKIES_FILE, MAX_RESULTS

logger = logging.getLogger(__name__)


def _patch_client_transaction() -> None:
    """
    Twikit 2.x parses X's homepage to generate request transaction IDs.
    This parsing can break when X changes their page structure.
    Patch both methods to fail silently so API calls can still proceed.
    """
    try:
        from twikit.x_client_transaction.transaction import ClientTransaction

        original_init = ClientTransaction.init
        original_generate = ClientTransaction.generate_transaction_id

        async def _safe_init(self, *args, **kwargs):
            try:
                await original_init(self, *args, **kwargs)
            except Exception:
                self._inited = True

        def _safe_generate(self, *args, **kwargs):
            try:
                return original_generate(self, *args, **kwargs)
            except Exception:
                return ""

        ClientTransaction.init = _safe_init
        ClientTransaction.generate_transaction_id = _safe_generate
    except Exception:
        pass


_patch_client_transaction()


@dataclass
class Post:
    username: str
    text: str
    likes: int
    retweets: int
    replies: int
    url: str
    created_at: str
    followers: int = 0
    is_thread: bool = False
    thread_text: str = ""
    quality_score: float = 0.0


_client: Client | None = None
_login_lock = asyncio.Lock()


async def _get_client() -> Client:
    """Get an authenticated Twikit client using browser cookies."""
    global _client

    async with _login_lock:
        if _client is not None:
            return _client

        if not os.path.exists(COOKIES_FILE):
            raise FileNotFoundError(
                f"Cookie file '{COOKIES_FILE}' not found.\n"
                "Run: python setup_cookies.py"
            )

        client = Client("en-US")
        client.load_cookies(COOKIES_FILE)
        _client = client
        return _client


def reset_client():
    """Reset the client so cookies are reloaded on next use."""
    global _client
    _client = None


async def search_posts(query: str, count: int = MAX_RESULTS) -> list[Post]:
    """Search X/Twitter for recent posts matching the query."""
    client = await _get_client()

    try:
        results = await client.search_tweet(query, product="Latest", count=count)
    except Exception as e:
        if "unauthorized" in str(e).lower() or "401" in str(e):
            reset_client()
            raise RuntimeError(
                "Cookies expired. Please re-run: python setup_cookies.py"
            ) from e
        raise

    posts = []
    for tweet in results:
        if not tweet.user:
            continue

        followers = tweet.user.followers_count or 0
        likes = tweet.favorite_count or 0
        retweets = tweet.retweet_count or 0
        replies = tweet.reply_count or 0

        post = Post(
            username=tweet.user.screen_name,
            text=tweet.text or "",
            likes=likes,
            retweets=retweets,
            replies=replies,
            url=f"https://x.com/{tweet.user.screen_name}/status/{tweet.id}",
            created_at=tweet.created_at or "",
            followers=followers,
            quality_score=_calc_quality(likes, retweets, replies, followers),
        )
        posts.append(post)

    return posts


async def unroll_thread(tweet_url: str) -> str:
    """Fetch a full thread by walking the reply chain."""
    client = await _get_client()

    # Extract tweet ID from URL
    tweet_id = tweet_url.rstrip("/").split("/")[-1]

    try:
        tweet = await client.get_tweet_by_id(tweet_id)
    except Exception as e:
        logger.warning(f"Failed to fetch tweet {tweet_id}: {e}")
        return ""

    if not tweet or not tweet.user:
        return ""

    author = tweet.user.screen_name
    thread_parts = [tweet.text or ""]

    # Walk up the reply chain to find the thread start
    current = tweet
    parent_texts = []
    for _ in range(20):  # max 20 tweets in a thread
        parent_id = getattr(current, "in_reply_to_tweet_id", None)
        if not parent_id:
            break
        try:
            parent = await client.get_tweet_by_id(parent_id)
            if parent and parent.user and parent.user.screen_name == author:
                parent_texts.append(parent.text or "")
                current = parent
            else:
                break
        except Exception:
            break

    # Reverse parents (oldest first) + current tweet
    parent_texts.reverse()
    full_thread = parent_texts + thread_parts

    return "\n\n".join(full_thread)


def _calc_quality(likes: int, retweets: int, replies: int, followers: int) -> float:
    """
    Calculate a quality score based on normalized engagement.
    A tweet with 50 likes from 500 followers > 50 likes from 500K followers.
    """
    raw_engagement = likes + (retweets * 2) + (replies * 3)

    # Normalized engagement: how much punch per follower
    if followers > 0:
        normalized = (raw_engagement / followers) * 1000
    else:
        normalized = float(raw_engagement)

    # Bonus for having links (can't detect here, but high engagement tweets
    # with substance tend to have higher reply ratios)
    reply_ratio = replies / max(likes, 1)
    discussion_bonus = min(reply_ratio * 2, 3.0)  # cap at 3x

    return round(normalized + discussion_bonus, 2)
