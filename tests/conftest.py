"""Fixtures for the Murf AI TTS tests."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Generator
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.murf_tts.config_flow import _key_fingerprint
from custom_components.murf_tts.const import (
    CONF_AUDIO_FORMAT,
    CONF_LOCALE,
    CONF_MODEL,
    CONF_PITCH,
    CONF_RATE,
    CONF_REGION,
    CONF_STYLE,
    CONF_VOICE_ID,
    DOMAIN,
    SUBENTRY_TYPE_TTS,
)

API_KEY = "test-api-key"
AUDIO = [b"ID3-first", b"-second", b"-third"]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Allow loading custom_components in every test."""


def _locale(detail: str, styles: list[str]) -> SimpleNamespace:
    return SimpleNamespace(detail=detail, available_styles=styles)


def make_voice(
    voice_id: str, name: str, gender: str, locales: dict[str, SimpleNamespace]
) -> SimpleNamespace:
    """Build an object shaped like murf.types.ApiVoice."""
    return SimpleNamespace(
        voice_id=voice_id,
        display_name=name,
        gender=gender,
        description=None,
        locale=next(iter(locales)),
        display_language=None,
        available_styles=None,
        supported_locales=locales,
    )


VOICES = [
    make_voice(
        "de-DE-matthias",
        "Matthias",
        "Male",
        {
            "de-DE": _locale("German (Germany)", ["Conversational", "Promo"]),
            "en-UK": _locale("English (UK)", ["Conversational"]),
        },
    ),
    make_voice(
        "de-DE-lia",
        "Lia",
        "Female",
        {"de-DE": _locale("German (Germany)", ["Conversational", "Calm"])},
    ),
    make_voice(
        "en-US-natalie",
        "Natalie",
        "Female",
        {"en-US": _locale("English (US & Canada)", ["Promo", "Narration"])},
    ),
]


class FakeTextToSpeech:
    """Stand-in for AsyncMurf.text_to_speech."""

    def __init__(self) -> None:
        self.get_voices = AsyncMock(return_value=VOICES)
        self.stream_calls: list[dict[str, Any]] = []
        self.stream_error: Exception | None = None

    def stream(self, **kwargs: Any) -> AsyncGenerator[bytes]:
        self.stream_calls.append(kwargs)
        error = self.stream_error

        async def _gen() -> AsyncGenerator[bytes]:
            if error is not None:
                raise error
            for chunk in AUDIO:
                yield chunk

        return _gen()


@pytest.fixture
def murf_tts_api() -> FakeTextToSpeech:
    """Shared fake text_to_speech API for all AsyncMurf instances."""
    return FakeTextToSpeech()


@pytest.fixture
def mock_murf(murf_tts_api: FakeTextToSpeech) -> Generator[MagicMock]:
    """Replace the SDK client."""
    with patch("custom_components.murf_tts.api.AsyncMurf") as client_cls:
        client_cls.return_value.text_to_speech = murf_tts_api
        yield client_cls


@pytest.fixture
def config_entry(hass: HomeAssistant) -> MockConfigEntry:
    """A config entry with one German voice."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Murf AI",
        unique_id=_key_fingerprint(API_KEY),
        data={CONF_API_KEY: API_KEY, CONF_REGION: "eu-central"},
        subentries_data=[
            ConfigSubentryData(
                subentry_type=SUBENTRY_TYPE_TTS,
                title="Matthias",
                unique_id=None,
                data={
                    CONF_MODEL: "falcon",
                    CONF_LOCALE: "de-DE",
                    CONF_VOICE_ID: "de-DE-matthias",
                    CONF_STYLE: "Conversational",
                    CONF_RATE: 5,
                    CONF_PITCH: -3,
                    CONF_AUDIO_FORMAT: "mp3",
                },
            )
        ],
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
async def setup_integration(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_murf: MagicMock
) -> MockConfigEntry:
    """Set up the integration with the fake SDK."""
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry
