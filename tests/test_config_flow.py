"""Tests for the Murf AI config flow."""

from __future__ import annotations

from unittest.mock import MagicMock

import httpx
import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_API_KEY, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from murf.errors import ForbiddenError
from pytest_homeassistant_custom_component.common import MockConfigEntry

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

from .conftest import API_KEY, FakeTextToSpeech


async def test_user_flow_creates_entry(
    hass: HomeAssistant, mock_murf: MagicMock
) -> None:
    """A valid key creates the account entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: f"  {API_KEY} ", CONF_REGION: "eu-central"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Murf AI"
    assert result["data"] == {CONF_API_KEY: API_KEY, CONF_REGION: "eu-central"}


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (
            ForbiddenError(body={"error_message": "Invalid 'api-key' header passed"}),
            "invalid_auth",
        ),
        (httpx.ConnectError("boom"), "cannot_connect"),
    ],
)
async def test_user_flow_errors_and_recovery(
    hass: HomeAssistant,
    mock_murf: MagicMock,
    murf_tts_api: FakeTextToSpeech,
    error: Exception,
    expected: str,
) -> None:
    """Errors are shown and the flow recovers."""
    murf_tts_api.get_voices.side_effect = error
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: API_KEY, CONF_REGION: "global"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected}

    murf_tts_api.get_voices.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: API_KEY, CONF_REGION: "global"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_duplicate_key(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """The same key cannot be added twice."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: API_KEY, CONF_REGION: "global"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_flow(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Reauth stores the new key."""
    entry = setup_integration
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "new-key"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_API_KEY] == "new-key"
    assert entry.data[CONF_REGION] == "eu-central"


async def test_reconfigure_flow(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Region can be changed."""
    entry = setup_integration
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: API_KEY, CONF_REGION: "uk"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_REGION] == "uk"


async def test_add_voice_subentry(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Walk through language -> voice -> settings."""
    hass.config.language = "de"
    hass.config.country = "DE"
    entry = setup_integration

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_TTS), context={"source": SOURCE_USER}
    )
    assert result["step_id"] == "language"
    schema = result["data_schema"].schema
    locale_key = next(k for k in schema if k == CONF_LOCALE)
    assert locale_key.default() == "de-DE"

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_LOCALE: "de-DE", CONF_MODEL: "FALCON"}
    )
    assert result["step_id"] == "voice"
    voice_options = result["data_schema"].schema[CONF_VOICE_ID].config["options"]
    assert {o["value"] for o in voice_options} == {"de-DE-lia", "de-DE-matthias"}

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_VOICE_ID: "de-DE-lia"}
    )
    assert result["step_id"] == "settings"

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Lia ruhig",
            CONF_STYLE: "Calm",
            CONF_RATE: -10.0,
            CONF_PITCH: 0,
            CONF_AUDIO_FORMAT: "MP3",
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Lia ruhig"
    assert result["data"] == {
        CONF_LOCALE: "de-DE",
        CONF_MODEL: "FALCON",
        CONF_VOICE_ID: "de-DE-lia",
        CONF_STYLE: "Calm",
        CONF_RATE: -10,
        CONF_PITCH: 0,
        CONF_AUDIO_FORMAT: "MP3",
    }
    await hass.async_block_till_done()
    assert hass.states.get("tts.lia_ruhig") is not None


async def test_language_without_voices_for_model(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    murf_tts_api: FakeTextToSpeech,
) -> None:
    """A language that the chosen model cannot speak shows an error."""

    async def voices(model: str | None = None, **_: object) -> list:
        from .conftest import VOICES

        return VOICES if model == "FALCON" else [VOICES[2]]

    murf_tts_api.get_voices.side_effect = voices
    entry = setup_integration
    entry.runtime_data._voices.clear()

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_TTS), context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_LOCALE: "de-DE", CONF_MODEL: "GEN2"}
    )
    assert result["step_id"] == "language"
    assert result["errors"] == {"base": "no_voices_for_language"}


async def test_reconfigure_voice_subentry(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """An existing voice keeps its values as defaults and can be changed."""
    entry = setup_integration
    subentry_id = next(iter(entry.subentries))

    result = await entry.start_subentry_reconfigure_flow(hass, subentry_id)
    assert result["step_id"] == "language"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_LOCALE: "de-DE", CONF_MODEL: "FALCON"}
    )
    voice_key = next(k for k in result["data_schema"].schema if k == CONF_VOICE_ID)
    assert voice_key.default() == "de-DE-matthias"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_VOICE_ID: "de-DE-matthias"}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Matthias",
            CONF_STYLE: "Promo",
            CONF_RATE: 0,
            CONF_PITCH: 0,
            CONF_AUDIO_FORMAT: "OGG",
        },
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    data = entry.subentries[subentry_id].data
    assert data[CONF_STYLE] == "Promo"
    assert data[CONF_AUDIO_FORMAT] == "OGG"
