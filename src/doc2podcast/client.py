"""Calls to an OpenAI-compatible chat endpoint, with the JSON mode probed once."""

import importlib
import logging
from typing import List, Optional

from .config import Settings
from .errors import ModelError

logger = logging.getLogger(__name__)

# Reaching the server is quick, writing a part of the script is not.
CONNECT_SECONDS = 15.0

# Probed once per process instead of again on every call.
_json_mode_supported = True


def _timeout(seconds: float):
    """A timeout object when the HTTP library is there, the plain number otherwise.

    Recent openai releases bring ``httpx2`` instead of ``httpx``, so both names are
    tried and the values stay the same either way.
    """
    for name in ("httpx", "httpx2"):
        try:
            module = importlib.import_module(name)
        except ImportError:
            continue
        try:
            return module.Timeout(seconds, connect=CONNECT_SECONDS)
        except (AttributeError, TypeError):
            return seconds
    return seconds


def make_client(settings: Settings):
    from openai import OpenAI

    return OpenAI(
        base_url=settings.base_url,
        api_key=settings.api_key,
        timeout=_timeout(settings.timeout),
        max_retries=settings.max_retries,
    )


def make_speech_client(settings: Settings):
    """The speech side runs on its own server unless it names none.

    It brings no retries of its own: voicing has one ladder, in ``voicing.py``, and a
    second one underneath would multiply the wait against a dead provider.
    """
    from openai import OpenAI

    return OpenAI(
        base_url=settings.tts_base_url,
        api_key=settings.tts_api_key,
        timeout=_timeout(settings.timeout),
        max_retries=0,
    )


def _rejects_json_mode(exc: Exception) -> bool:
    """True when the provider explicitly rejected response_format."""
    if getattr(exc, "status_code", None) != 400:
        return False
    text = str(exc).lower()
    return "response_format" in text or "json" in text


def _create(client, settings: Settings, messages: List[dict], *, json_mode: bool):
    kwargs = {"temperature": settings.temperature}
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    return client.chat.completions.create(model=settings.model, messages=messages, **kwargs)


def call_json(client, settings: Settings, messages: List[dict]) -> str:
    """One run, in JSON mode where the provider can do it."""
    global _json_mode_supported

    response = None
    if _json_mode_supported:
        try:
            response = _create(client, settings, messages, json_mode=True)
        except Exception as exc:
            if not _rejects_json_mode(exc):
                raise ModelError("Request to %s failed: %s" % (settings.base_url, exc))
            logger.warning(
                "The provider refused the JSON mode, this process asks without it from now on: %s",
                exc,
            )
            _json_mode_supported = False
    if response is None:
        try:
            response = _create(client, settings, messages, json_mode=False)
        except Exception as exc:
            raise ModelError("Request to %s failed: %s" % (settings.base_url, exc))
    return _content(response)


def _content(response) -> str:
    try:
        content = response.choices[0].message.content
    except (AttributeError, IndexError, TypeError):
        raise ModelError("The server response has an unexpected format.")
    return content or ""


def ask(client, settings: Settings) -> "Ask":
    """A small caller the steps hand around, so they do not carry both objects."""
    return Ask(client, settings)


class Ask:
    """One chat model, ready to be asked for JSON."""

    def __init__(self, client, settings: Settings):
        self.client = client
        self.settings = settings

    def __call__(self, messages: List[dict]) -> Optional[str]:
        return call_json(self.client, self.settings, messages)
