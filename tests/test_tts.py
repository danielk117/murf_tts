"""Tests for setup and the Murf TTS entity."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from unittest.mock import MagicMock

import httpx
import pytest
from homeassistant.components import tts
from homeassistant.components.tts import ATTR_VOICE, TTSAudioRequest
from homeassistant.components.tts.helper import get_engine_instance
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from murf.errors import BadRequestError, ForbiddenError, PaymentRequiredError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.murf_tts.const import ATTR_PITCH, ATTR_RATE, ATTR_STYLE

from .conftest import AUDIO, FakeTextToSpeech

ENTITY_ID = "tts.matthias"


def _entity(hass: HomeAssistant) -> tts.TextToSpeechEntity:
    engine = get_engine_instance(hass, ENTITY_ID)
    assert isinstance(engine, tts.TextToSpeechEntity)
    return engine


async def _message(text: str) -> AsyncGenerator[str]:
    for word in text.split(" "):
        yield word + " "


async def test_setup_creates_entity(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """The voice subentry becomes an entity with the voice's languages."""
    assert setup_integration.state is ConfigEntryState.LOADED
    assert hass.states.get(ENTITY_ID) is not None
    entity = _entity(hass)
    assert entity.default_language == "de-DE"
    # en-UK from Murf is exposed as the valid tag en-GB
    assert entity.supported_languages == ["de-DE", "en-GB"]


async def test_setup_invalid_key_starts_reauth(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_murf: MagicMock,
    murf_tts_api: FakeTextToSpeech,
) -> None:
    """A rejected key puts the entry into reauth."""
    murf_tts_api.get_voices.side_effect = ForbiddenError(body={"error_message": "nope"})
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert any(flow["context"]["source"] == "reauth" for flow in flows)


async def test_setup_network_error_retries(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_murf: MagicMock,
    murf_tts_api: FakeTextToSpeech,
) -> None:
    """Network errors lead to a retry."""
    murf_tts_api.get_voices.side_effect = httpx.ConnectTimeout("timeout")
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_get_tts_audio_uses_subentry_settings(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    murf_tts_api: FakeTextToSpeech,
) -> None:
    """Non-streamed audio is complete and uses the configured settings."""
    extension, data = await _entity(hass).async_get_tts_audio("Hallo Welt", "de-DE", {})
    assert extension == "mp3"
    assert data == b"".join(AUDIO)
    assert murf_tts_api.stream_calls[-1] == {
        "text": "Hallo Welt",
        "voice_id": "de-DE-matthias",
        "model": "FALCON",
        "format": "MP3",
        "channel_type": "MONO",
        "locale": "de-DE",
        "style": "Conversational",
        "rate": 5,
        "pitch": -3,
    }


async def test_stream_tts_audio(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    murf_tts_api: FakeTextToSpeech,
) -> None:
    """Streaming joins the message and yields Murf's chunks."""
    response = await _entity(hass).async_stream_tts_audio(
        TTSAudioRequest(
            language="de-DE", options={}, message_gen=_message("Guten Morgen")
        )
    )
    assert response.extension == "mp3"
    assert [chunk async for chunk in response.data_gen] == AUDIO
    assert murf_tts_api.stream_calls[-1]["text"] == "Guten Morgen "


async def test_other_language_maps_locale_and_drops_style(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    murf_tts_api: FakeTextToSpeech,
) -> None:
    """en-GB maps back to Murf's en-UK; the German style is not reused."""
    await _entity(hass).async_get_tts_audio("Hello", "en-GB", {})
    call = murf_tts_api.stream_calls[-1]
    assert call["locale"] == "en-UK"
    assert "style" not in call


async def test_options_override(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    murf_tts_api: FakeTextToSpeech,
) -> None:
    """Per-call options win over the subentry."""
    await _entity(hass).async_get_tts_audio(
        "Hallo",
        "de-DE",
        {ATTR_VOICE: "de-DE-lia", ATTR_STYLE: "Calm", ATTR_RATE: "20", ATTR_PITCH: 10},
    )
    call = murf_tts_api.stream_calls[-1]
    assert call["voice_id"] == "de-DE-lia"
    assert call["style"] == "Calm"
    assert call["rate"] == 20
    assert call["pitch"] == 10


async def test_invalid_rate_option(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Out of range numbers are rejected before calling Murf."""
    with pytest.raises(ServiceValidationError):
        await _entity(hass).async_get_tts_audio("Hallo", "de-DE", {ATTR_RATE: 99})


async def test_unsupported_language_for_voice(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """A voice override that cannot speak the language is rejected."""
    with pytest.raises(ServiceValidationError):
        await _entity(hass).async_get_tts_audio(
            "Hello", "en-GB", {ATTR_VOICE: "de-DE-lia"}
        )


async def test_supported_voices(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Voices for a language come from the cached catalogue."""
    voices = _entity(hass).async_get_supported_voices("de-DE")
    assert [voice.voice_id for voice in voices] == ["de-DE-lia", "de-DE-matthias"]
    assert _entity(hass).async_get_supported_voices("ja-JP") is None


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (
            PaymentRequiredError(body={"errorMessage": "No characters left"}),
            "No characters left",
        ),
        (BadRequestError(body={"errorMessage": "Invalid style"}), "Invalid style"),
        (httpx.ReadTimeout("slow"), "slow"),
    ],
)
async def test_synthesis_errors(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    murf_tts_api: FakeTextToSpeech,
    error: Exception,
    message: str,
) -> None:
    """SDK errors become translated Home Assistant errors."""
    murf_tts_api.stream_error = error
    with pytest.raises(HomeAssistantError) as exc_info:
        await _entity(hass).async_get_tts_audio("Hallo", "de-DE", {})
    assert exc_info.value.translation_placeholders["error"].endswith(message)


async def test_auth_error_during_synthesis_starts_reauth(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    murf_tts_api: FakeTextToSpeech,
) -> None:
    """A revoked key triggers reauth instead of failing silently."""
    murf_tts_api.stream_error = ForbiddenError(body={"error_message": "revoked"})
    with pytest.raises(HomeAssistantError) as exc_info:
        await _entity(hass).async_get_tts_audio("Hallo", "de-DE", {})
    assert exc_info.value.translation_key == "invalid_auth"
    await hass.async_block_till_done()
    flows = hass.config_entries.flow.async_progress()
    assert any(flow["context"]["source"] == "reauth" for flow in flows)


async def test_unload(hass: HomeAssistant, setup_integration: MockConfigEntry) -> None:
    """The entry unloads cleanly."""
    assert await hass.config_entries.async_unload(setup_integration.entry_id)
    assert setup_integration.state is ConfigEntryState.NOT_LOADED


async def test_end_to_end_through_tts_manager(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    murf_tts_api: FakeTextToSpeech,
) -> None:
    """Audio requested the way media players get it."""
    media_source_id = tts.generate_media_source_id(
        hass, "Willkommen zu Hause", ENTITY_ID, language="de-DE", cache=False
    )
    extension, data = await tts.async_get_media_source_audio(hass, media_source_id)
    assert extension == "mp3"
    assert data == b"".join(AUDIO)
    assert murf_tts_api.stream_calls[-1]["text"].strip() == "Willkommen zu Hause"


async def test_legacy_upper_case_subentry(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_murf: MagicMock,
    murf_tts_api: FakeTextToSpeech,
) -> None:
    """Subentries stored by 1.0.0 (FALCON/MP3) keep working."""
    subentry = next(iter(config_entry.subentries.values()))
    hass.config_entries.async_update_subentry(
        config_entry,
        subentry,
        data={**subentry.data, "model": "FALCON", "audio_format": "MP3"},
    )
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    extension, _ = await _entity(hass).async_get_tts_audio("Hallo", "de-DE", {})
    assert extension == "mp3"
    call = murf_tts_api.stream_calls[-1]
    assert (call["model"], call["format"]) == ("FALCON", "MP3")
    assert murf_tts_api.get_voices.await_args.kwargs == {"model": "FALCON"}
