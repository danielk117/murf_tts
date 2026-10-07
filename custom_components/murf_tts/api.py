"""Thin wrapper around the Murf Python SDK.

Keeps SDK specifics (two endpoints, error classes, response models) out of
the Home Assistant facing code.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx
from homeassistant.core import HomeAssistant
from homeassistant.helpers.httpx_client import get_async_client
from murf import AsyncMurf
from murf.core.api_error import ApiError
from murf.region import MurfRegion

from .const import LOGGER, normalize_audio_format, normalize_model

# Murf uses a few locale codes that are not valid BCP 47 tags.
_MURF_TO_HA_LOCALE = {"en-UK": "en-GB"}


def murf_locale_to_ha(locale: str) -> str:
    """Convert a Murf locale code to the language tag Home Assistant uses."""
    return _MURF_TO_HA_LOCALE.get(locale, locale)


class MurfError(Exception):
    """Base error for the Murf integration."""


class MurfAuthError(MurfError):
    """The API key was rejected."""


class MurfQuotaError(MurfError):
    """The account has no characters left or the plan does not allow the call."""


class MurfConnectionError(MurfError):
    """Murf could not be reached or answered with a server error."""


class MurfRequestError(MurfError):
    """Murf rejected the request (bad voice, style, text, ...)."""


@dataclass(frozen=True, slots=True)
class MurfLocale:
    """A locale a voice can speak, with its styles."""

    code: str
    label: str
    styles: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MurfVoice:
    """A Murf voice as needed by the integration."""

    voice_id: str
    name: str
    gender: str | None
    description: str | None
    locales: dict[str, MurfLocale] = field(default_factory=dict)

    @property
    def label(self) -> str:
        """Human readable label for selectors."""
        parts = [self.name]
        if self.gender:
            parts.append(self.gender)
        label = " · ".join(parts)
        if self.description:
            label = f"{label} – {self.description}"
        return label


def _error_message(body: Any) -> str:
    """Extract the human readable message from a Murf error body."""
    if isinstance(body, dict):
        for key in ("errorMessage", "error_message", "message", "detail"):
            if body.get(key):
                return str(body[key])
    return str(body) if body else "unknown error"


def translate_error(err: Exception) -> MurfError:
    """Map SDK and transport exceptions to integration exceptions."""
    if isinstance(err, MurfError):
        return err
    if isinstance(err, ApiError):
        message = _error_message(err.body)
        status = err.status_code or 0
        if status in (401, 403):
            return MurfAuthError(message)
        if status == 402:
            return MurfQuotaError(message)
        if status == 429 or status >= 500:
            return MurfConnectionError(f"HTTP {status}: {message}")
        return MurfRequestError(message)
    if isinstance(err, httpx.HTTPError):
        return MurfConnectionError(str(err) or type(err).__name__)
    return MurfError(str(err))


def _parse_voice(raw: Any) -> MurfVoice | None:
    """Turn an SDK ApiVoice into a MurfVoice."""
    if not raw.voice_id:
        return None
    locales: dict[str, MurfLocale] = {}
    for code, details in (raw.supported_locales or {}).items():
        locales[code] = MurfLocale(
            code=code,
            label=(details.detail if details and details.detail else code),
            styles=tuple(details.available_styles or ()) if details else (),
        )
    # Older API responses only carry the primary locale.
    if not locales and raw.locale:
        locales[raw.locale] = MurfLocale(
            code=raw.locale,
            label=raw.display_language or raw.locale,
            styles=tuple(raw.available_styles or ()),
        )
    gender = raw.gender if isinstance(raw.gender, str) else None
    return MurfVoice(
        voice_id=raw.voice_id,
        name=raw.display_name or raw.voice_id,
        gender=gender,
        description=raw.description or None,
        locales=locales,
    )


class MurfApi:
    """Access to the Murf API for one account."""

    def __init__(self, hass: HomeAssistant, api_key: str, region: str) -> None:
        """Create the clients.

        The voice catalogue is only available on api.murf.ai, synthesis is
        sent to the configured region.
        """
        http_client = get_async_client(hass)
        self._catalog = AsyncMurf(api_key=api_key, httpx_client=http_client)
        self._speech = AsyncMurf(
            api_key=api_key,
            region=MurfRegion(region),
            httpx_client=http_client,
        )
        self._voices: dict[str, dict[str, MurfVoice]] = {}

    async def async_get_voices(
        self, model: str, *, refresh: bool = False
    ) -> dict[str, MurfVoice]:
        """Return the voices for a model, keyed by voice id (cached)."""
        model = normalize_model(model)
        if not refresh and model in self._voices:
            return self._voices[model]
        try:
            raw_voices = await self._catalog.text_to_speech.get_voices(
                model=model.upper()
            )
        except Exception as err:
            raise translate_error(err) from err
        voices: dict[str, MurfVoice] = {}
        for raw in raw_voices:
            if voice := _parse_voice(raw):
                voices[voice.voice_id] = voice
        LOGGER.debug("Loaded %d Murf voices for model %s", len(voices), model)
        self._voices[model] = voices
        return voices

    def cached_voices(self, model: str) -> dict[str, MurfVoice]:
        """Return the cached voices for a model without a network call."""
        return self._voices.get(normalize_model(model), {})

    async def async_open_stream(
        self,
        *,
        text: str,
        voice_id: str,
        model: str,
        audio_format: str,
        locale: str | None = None,
        style: str | None = None,
        rate: int | None = None,
        pitch: int | None = None,
    ) -> AsyncGenerator[bytes]:
        """Start synthesis and return the audio as an async generator.

        The first chunk is fetched before returning, so authentication and
        validation errors are raised here and not in the middle of playback.
        """
        # Only send what is set; the SDK would serialise None as JSON null.
        optional: dict[str, Any] = {
            "locale": locale,
            "style": style,
            "rate": rate,
            "pitch": pitch,
        }
        kwargs = {key: value for key, value in optional.items() if value is not None}

        stream: AsyncIterator[bytes] = self._speech.text_to_speech.stream(
            text=text,
            voice_id=voice_id,
            model=normalize_model(model).upper(),
            format=normalize_audio_format(audio_format).upper(),
            channel_type="MONO",
            **kwargs,
        )
        try:
            first_chunk = await anext(stream)
        except StopAsyncIteration as err:
            raise MurfRequestError("Murf returned no audio") from err
        except Exception as err:
            await _aclose(stream)
            raise translate_error(err) from err

        async def _audio() -> AsyncGenerator[bytes]:
            try:
                yield first_chunk
                async for chunk in stream:
                    yield chunk
            except (ApiError, httpx.HTTPError) as err:
                raise translate_error(err) from err
            finally:
                await _aclose(stream)

        return _audio()


async def _aclose(stream: AsyncIterator[bytes]) -> None:
    """Close an async generator if it supports it."""
    aclose = getattr(stream, "aclose", None)
    if aclose is not None:
        await aclose()
