"""Text-to-speech entities for Murf AI."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from homeassistant.components.tts import (
    ATTR_VOICE,
    TextToSpeechEntity,
    TTSAudioRequest,
    TTSAudioResponse,
    TtsAudioType,
    Voice,
)
from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MurfConfigEntry
from .api import (
    MurfAuthError,
    MurfConnectionError,
    MurfError,
    MurfQuotaError,
    MurfVoice,
    murf_locale_to_ha,
)
from .const import (
    ATTR_PITCH,
    ATTR_RATE,
    ATTR_STYLE,
    CONF_AUDIO_FORMAT,
    CONF_LOCALE,
    CONF_MODEL,
    CONF_PITCH,
    CONF_RATE,
    CONF_STYLE,
    CONF_VOICE_ID,
    DOMAIN,
    LOGGER,
    PITCH_MAX,
    PITCH_MIN,
    RATE_MAX,
    RATE_MIN,
    SUBENTRY_TYPE_TTS,
    normalize_audio_format,
    normalize_model,
)

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MurfConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create one TTS entity per configured voice."""
    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_TYPE_TTS:
            continue
        async_add_entities(
            [MurfTTSEntity(entry, subentry)],
            config_subentry_id=subentry.subentry_id,
        )


class MurfTTSEntity(TextToSpeechEntity):
    """A Murf voice as a Home Assistant TTS entity."""

    # The TTS manager requires entity.name to be set, so the entity carries
    # the voice name itself instead of inheriting it from the device.
    _attr_has_entity_name = False
    _attr_supported_options = [ATTR_VOICE, ATTR_STYLE, ATTR_RATE, ATTR_PITCH]

    def __init__(self, entry: MurfConfigEntry, subentry: ConfigSubentry) -> None:
        """Initialize the entity from the subentry settings."""
        self._entry = entry
        self._api = entry.runtime_data
        data = subentry.data
        self._model: str = normalize_model(data.get(CONF_MODEL))
        self._voice_id: str = data[CONF_VOICE_ID]
        self._locale: str = data[CONF_LOCALE]
        self._style: str | None = data.get(CONF_STYLE)
        self._rate: int = int(data.get(CONF_RATE, 0))
        self._pitch: int = int(data.get(CONF_PITCH, 0))
        self._format: str = normalize_audio_format(data.get(CONF_AUDIO_FORMAT))

        voice = self._voice(self._voice_id)
        if voice is None:
            LOGGER.warning(
                "Voice %s (%s) is no longer offered by Murf",
                self._voice_id,
                self._model,
            )

        self._attr_unique_id = subentry.subentry_id
        self._attr_name = subentry.title
        self._attr_default_language = murf_locale_to_ha(self._locale)
        self._attr_supported_languages = sorted(
            self._language_map(voice) or {self._attr_default_language: self._locale}
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, subentry.subentry_id)},
            name=subentry.title,
            manufacturer="Murf AI",
            model=f"{voice.name if voice else self._voice_id} · {self._model.capitalize()}",
            entry_type=DeviceEntryType.SERVICE,
        )

    # ---- voices and languages ----------------------------------------

    def _voice(self, voice_id: str) -> MurfVoice | None:
        return self._api.cached_voices(self._model).get(voice_id)

    @staticmethod
    def _language_map(voice: MurfVoice | None) -> dict[str, str]:
        """Home Assistant language tag -> Murf locale for a voice."""
        if voice is None:
            return {}
        return {murf_locale_to_ha(code): code for code in voice.locales}

    def _resolve_locale(self, language: str | None, voice_id: str) -> str | None:
        """Find the Murf locale for a requested language and voice."""
        language_map = self._language_map(self._voice(voice_id))
        if not language or language == self._attr_default_language:
            # Keep the configured locale if the (possibly overridden) voice has it.
            if not language_map or self._locale in language_map.values():
                return self._locale
            language = self._attr_default_language
        if language in language_map:
            return language_map[language]
        primary = language.split("-")[0].lower()
        for tag, code in language_map.items():
            if tag.split("-")[0].lower() == primary:
                return code
        if not language_map:
            # Voice not in the catalogue cache; let Murf decide.
            return None
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="unsupported_language",
            translation_placeholders={"language": language, "voice": voice_id},
        )

    @callback
    def async_get_supported_voices(self, language: str) -> list[Voice] | None:
        """Voices of the same model that can speak the language."""
        primary = language.split("-")[0].lower()
        voices = [
            Voice(voice.voice_id, voice.label)
            for voice in self._api.cached_voices(self._model).values()
            if any(
                murf_locale_to_ha(code) == language
                or code.split("-")[0].lower() == primary
                for code in voice.locales
            )
        ]
        return sorted(voices, key=lambda voice: voice.name.casefold()) or None

    # ---- synthesis ----------------------------------------------------

    @staticmethod
    def _int_option(
        options: dict[str, Any], key: str, low: int, high: int
    ) -> int | None:
        if (value := options.get(key)) is None:
            return None
        try:
            number = int(value)
        except (TypeError, ValueError) as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_number",
                translation_placeholders={
                    "option": key,
                    "min": str(low),
                    "max": str(high),
                },
            ) from err
        if not low <= number <= high:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_number",
                translation_placeholders={
                    "option": key,
                    "min": str(low),
                    "max": str(high),
                },
            )
        return number

    async def _async_open(
        self, message: str, language: str | None, options: dict[str, Any]
    ) -> AsyncGenerator[bytes]:
        """Validate options and start the Murf stream."""
        voice_id = options.get(ATTR_VOICE) or self._voice_id
        rate = self._int_option(options, ATTR_RATE, RATE_MIN, RATE_MAX)
        pitch = self._int_option(options, ATTR_PITCH, PITCH_MIN, PITCH_MAX)
        locale = self._resolve_locale(language, voice_id)
        style = options.get(ATTR_STYLE)
        if style is None and voice_id == self._voice_id and locale == self._locale:
            # Styles differ per voice and locale; only reuse the configured one
            # for the configured combination.
            style = self._style
        try:
            return await self._api.async_open_stream(
                text=message,
                voice_id=voice_id,
                model=self._model,
                audio_format=self._format,
                locale=locale,
                style=style,
                rate=self._rate if rate is None else rate,
                pitch=self._pitch if pitch is None else pitch,
            )
        except MurfError as err:
            raise self._to_ha_error(err) from err

    def _to_ha_error(self, err: MurfError) -> HomeAssistantError:
        if isinstance(err, MurfAuthError):
            self._entry.async_start_reauth(self.hass)
            return HomeAssistantError(
                translation_domain=DOMAIN, translation_key="invalid_auth"
            )
        if isinstance(err, MurfQuotaError):
            key = "quota_exceeded"
        elif isinstance(err, MurfConnectionError):
            key = "cannot_connect"
        else:
            key = "request_failed"
        return HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key=key,
            translation_placeholders={"error": str(err)},
        )

    async def _async_wrap(self, stream: AsyncGenerator[bytes]) -> AsyncGenerator[bytes]:
        """Translate errors raised while the audio is still streaming."""
        try:
            async for chunk in stream:
                yield chunk
        except MurfError as err:
            raise self._to_ha_error(err) from err

    async def async_stream_tts_audio(
        self, request: TTSAudioRequest
    ) -> TTSAudioResponse:
        """Stream audio back while Murf is still producing it."""
        message = "".join([chunk async for chunk in request.message_gen])
        stream = await self._async_open(message, request.language, request.options)
        return TTSAudioResponse(
            extension=self._format,
            data_gen=self._async_wrap(stream),
        )

    async def async_get_tts_audio(
        self, message: str, language: str, options: dict[str, Any]
    ) -> TtsAudioType:
        """Return the complete audio (used for cached, non-streamed playback)."""
        stream = await self._async_open(message, language, options)
        audio = b"".join([chunk async for chunk in self._async_wrap(stream)])
        return self._format, audio
