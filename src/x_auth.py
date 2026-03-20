"""
X/Twitter login handler.

Runs twikit's async login() in a background thread so we can intercept
the email-verification (ACID) challenge and relay it through Telegram
without blocking the bot's event loop.
"""
import asyncio
import builtins
import logging
import threading
from typing import Optional

from twikit import Client
from twikit.errors import AccountLocked, AccountSuspended, TwitterException

logger = logging.getLogger(__name__)

COOKIES_FILE = "cookies.json"


def _patch_client_transaction() -> None:
    """
    Twikit 2.x parses X's homepage to generate request transaction IDs.
    This parsing breaks on Android/Termux because X changed their page structure.
    Patch both methods to fail silently so login can still proceed.
    """
    try:
        from twikit.x_client_transaction.transaction import ClientTransaction

        original_init = ClientTransaction.init
        original_generate = ClientTransaction.generate_transaction_id

        async def _safe_init(self, *args, **kwargs):
            try:
                await original_init(self, *args, **kwargs)
            except Exception:
                self._inited = True  # mark done even if scraping failed

        def _safe_generate(self, *args, **kwargs):
            try:
                return original_generate(self, *args, **kwargs)
            except Exception:
                return ""  # empty header — X still processes the request

        ClientTransaction.init = _safe_init
        ClientTransaction.generate_transaction_id = _safe_generate
    except Exception:
        pass  # if twikit structure changes, skip silently


_patch_client_transaction()


class LoginSession:
    """Shared state between the background login thread and the Telegram handler."""

    def __init__(self):
        self.client: Optional[Client] = None
        self.error: Optional[str] = None

        # Signals login thread → bot
        self.done       = threading.Event()   # login finished (success or error)
        self.needs_code = threading.Event()   # X asked for email verification code

        # Signal bot → login thread
        self.code_ready = threading.Event()   # bot has put the code in .code
        self.code: Optional[str] = None


# Only one login can run at a time (single-user bot)
_active_session: Optional[LoginSession] = None


def _intercepted_input(prompt: str = "") -> str:
    """Replacement for builtins.input during login — relays to Telegram."""
    if _active_session is None:
        return ""
    session = _active_session
    session.needs_code.set()          # tell the bot we need a code
    session.code_ready.wait(timeout=300)   # block this thread until bot provides it
    session.code_ready.clear()
    return session.code or ""


def _run_login(session: LoginSession, username: str, password: str) -> None:
    """Runs in a background thread with its own event loop."""
    original_input = builtins.input
    builtins.input = _intercepted_input
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        client = Client("en-US")
        loop.run_until_complete(
            client.login(
                auth_info_1=username,
                password=password,
                enable_ui_metrics=False,
            )
        )
        client.save_cookies(COOKIES_FILE)
        session.client = client

    except AccountSuspended:
        session.error = "Your X account is suspended."
    except AccountLocked:
        session.error = "Your X account is locked. Unlock it at x.com first."
    except TwitterException as e:
        session.error = f"X login failed: {e}"
    except Exception as e:
        logger.exception("Unexpected login error")
        session.error = str(e)
    finally:
        builtins.input = original_input
        session.needs_code.clear()
        session.done.set()


def start_login(username: str, password: str) -> LoginSession:
    """Start X login in a background thread. Returns a session to monitor."""
    global _active_session
    session = LoginSession()
    _active_session = session
    thread = threading.Thread(
        target=_run_login,
        args=(session, username, password),
        daemon=True,
    )
    thread.start()
    return session


def provide_code(session: LoginSession, code: str) -> None:
    """Give the email verification code to the waiting login thread."""
    session.code = code
    session.code_ready.set()


async def wait_for_login(session: LoginSession, timeout: float = 40.0) -> str:
    """
    Poll the session until login completes or needs a code.
    Returns: 'done' | 'needs_code' | 'timeout'
    """
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if session.done.is_set():
            return "done"
        if session.needs_code.is_set():
            return "needs_code"
        await asyncio.sleep(0.3)
    return "timeout"
