"""Config flow for the Murf AI text-to-speech integration."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.config_entries import (
    SOURCE_USER,
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.const import CONF_API_KEY, CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import MurfApi, MurfAuthError, MurfError, MurfVoice, murf_locale_to_ha
from .const import (
    API_KEY_URL,
    AUDIO_FORMATS,
    CONF_AUDIO_FORMAT,
    CONF_LOCALE,
    CONF_MODEL,
    CONF_PITCH,
    CONF_RATE,
    CONF_REGION,
    CONF_STYLE,
    CONF_VOICE_ID,
    DEFAULT_AUDIO_FORMAT,
    DEFAULT_MODEL,
    DEFAULT_REGION,
    DOMAIN,
    LOGGER,
    MODELS,
    PITCH_MAX,
    PITCH_MIN,
    RATE_MAX,
    RATE_MIN,
    REGIONS,
    SUBENTRY_TYPE_TTS,
)

if TYPE_CHECKING:
    from . import MurfConfigEntry


def _key_fingerprint(api_key: str) -> str:
    """Stable, non-reversible id for an API key (used as unique id)."""
    return hashlib.sha256(api_key.strip().encode()).hexdigest()[:16]


def _account_schema(defaults: Mapping[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_API_KEY, default=defaults.get(CONF_API_KEY, vol.UNDEFINED)
            ): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
            vol.Required(
                CONF_REGION, default=defaults.get(CONF_REGION, DEFAULT_REGION)
            ): SelectSelector(
                SelectSelectorConfig(
                    options=REGIONS,
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key=CONF_REGION,
                )
            ),
        }
    )


async def _async_validate_key(hass: HomeAssistant, api_key: str) -> dict[str, str]:
    """Check the key against the voice catalogue. Return form errors."""
    api = MurfApi(hass, api_key.strip(), DEFAULT_REGION)
    try:
        await api.async_get_voices(DEFAULT_MODEL)
    except MurfAuthError:
        return {"base": "invalid_auth"}
    except MurfError as err:
        LOGGER.warning("Could not reach Murf: %s", err)
        return {"base": "cannot_connect"}
    except Exception:
        LOGGER.exception("Unexpected error validating the Murf API key")
        return {"base": "unknown"}
    return {}


class MurfConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the account level config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the API key and region."""
        errors: dict[str, str] = {}
        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            await self.async_set_unique_id(_key_fingerprint(api_key))
            self._abort_if_unique_id_configured()
            errors = await _async_validate_key(self.hass, api_key)
            if not errors:
                return self.async_create_entry(
                    title="Murf AI",
                    data={**user_input, CONF_API_KEY: api_key},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_account_schema(user_input or {}),
            errors=errors,
            description_placeholders={"api_key_url": API_KEY_URL},
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start reauthentication after Murf rejected the key."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a new API key."""
        errors: dict[str, str] = {}
        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            errors = await _async_validate_key(self.hass, api_key)
            if not errors:
                return self.async_update_reload_and_abort(
                    self._get_reauth_entry(),
                    unique_id=_key_fingerprint(api_key),
                    data_updates={CONF_API_KEY: api_key},
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_KEY): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    )
                }
            ),
            errors=errors,
            description_placeholders={"api_key_url": API_KEY_URL},
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the API key or the region."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            errors = await _async_validate_key(self.hass, api_key)
            if not errors:
                return self.async_update_reload_and_abort(
                    entry,
                    unique_id=_key_fingerprint(api_key),
                    data_updates={**user_input, CONF_API_KEY: api_key},
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_account_schema(user_input or entry.data),
            errors=errors,
            description_placeholders={"api_key_url": API_KEY_URL},
        )

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Each voice is a subentry and becomes one TTS entity."""
        return {SUBENTRY_TYPE_TTS: MurfVoiceSubentryFlow}


class MurfVoiceSubentryFlow(ConfigSubentryFlow):
    """Add or change a voice: language -> voice -> settings."""

    def __init__(self) -> None:
        """Initialize the flow."""
        super().__init__()
        self._data: dict[str, Any] = {}
        self._api: MurfApi | None = None

    # ---- entry points -------------------------------------------------

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Add a new voice."""
        self._data = {}
        return await self.async_step_language()

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Change an existing voice."""
        self._data = dict(self._get_reconfigure_subentry().data)
        return await self.async_step_language()

    # ---- helpers ------------------------------------------------------

    @property
    def _is_new(self) -> bool:
        return self.source == SOURCE_USER

    async def _async_voices(self, model: str) -> dict[str, MurfVoice]:
        assert self._api is not None
        return await self._api.async_get_voices(model)

    def _default_locale(self, locales: Mapping[str, str]) -> str | None:
        """Pick the locale matching the Home Assistant language, if any."""
        language = (self.hass.config.language or "en").replace("_", "-")
        country = self.hass.config.country
        candidates = [language]
        if "-" not in language and country:
            candidates.append(f"{language}-{country}")
        for candidate in candidates:
            for code in locales:
                if murf_locale_to_ha(code).lower() == candidate.lower():
                    return code
        primary = language.split("-")[0].lower()
        for code in locales:
            if code.split("-")[0].lower() == primary:
                return code
        return next(iter(locales), None)

    # ---- step 1: model and language -----------------------------------

    async def async_step_language(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Choose the model and the language."""
        entry: MurfConfigEntry = self._get_entry()
        if entry.state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="entry_not_loaded")
        self._api = entry.runtime_data

        # Locales of all models, so the list does not depend on the model
        # field of the same form. The voice step filters per model.
        locales: dict[str, str] = {}
        try:
            for model in MODELS:
                for voice in (await self._async_voices(model)).values():
                    for locale in voice.locales.values():
                        locales.setdefault(locale.code, locale.label)
        except MurfError as err:
            LOGGER.warning("Could not load Murf voices: %s", err)
            return self.async_abort(reason="cannot_connect")
        if not locales:
            return self.async_abort(reason="no_voices")

        errors: dict[str, str] = {}
        if user_input is not None:
            voices = await self._async_voices(user_input[CONF_MODEL])
            if any(user_input[CONF_LOCALE] in v.locales for v in voices.values()):
                self._data.update(user_input)
                return await self.async_step_voice()
            errors["base"] = "no_voices_for_language"

        options = sorted(
            (
                SelectOptionDict(value=code, label=f"{label} ({code})")
                for code, label in locales.items()
            ),
            key=lambda option: option["label"].casefold(),
        )
        defaults = user_input or self._data
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_LOCALE,
                    default=defaults.get(CONF_LOCALE)
                    or self._default_locale(locales)
                    or vol.UNDEFINED,
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=options, mode=SelectSelectorMode.DROPDOWN
                    )
                ),
                vol.Required(
                    CONF_MODEL, default=defaults.get(CONF_MODEL, DEFAULT_MODEL)
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=MODELS,
                        mode=SelectSelectorMode.LIST,
                        translation_key=CONF_MODEL,
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="language", data_schema=schema, errors=errors
        )

    # ---- step 2: voice ------------------------------------------------

    async def async_step_voice(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Choose a voice that speaks the selected language."""
        locale = self._data[CONF_LOCALE]
        voices = {
            voice_id: voice
            for voice_id, voice in (
                await self._async_voices(self._data[CONF_MODEL])
            ).items()
            if locale in voice.locales
        }

        if user_input is not None and user_input[CONF_VOICE_ID] in voices:
            self._data.update(user_input)
            return await self.async_step_settings()

        options = sorted(
            (
                SelectOptionDict(value=voice_id, label=voice.label)
                for voice_id, voice in voices.items()
            ),
            key=lambda option: option["label"].casefold(),
        )
        default = self._data.get(CONF_VOICE_ID)
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_VOICE_ID,
                    default=default if default in voices else options[0]["value"],
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=options, mode=SelectSelectorMode.DROPDOWN
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="voice",
            data_schema=schema,
            errors={"base": "invalid_voice"} if user_input is not None else {},
            description_placeholders={"language": locale},
        )

    # ---- step 3: style, speed, pitch, format, name ---------------------

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Fine tune the voice and name the entity."""
        voices = await self._async_voices(self._data[CONF_MODEL])
        voice = voices[self._data[CONF_VOICE_ID]]
        locale = voice.locales[self._data[CONF_LOCALE]]

        if user_input is not None:
            name = user_input.pop(CONF_NAME).strip() or voice.name
            user_input[CONF_RATE] = int(user_input[CONF_RATE])
            user_input[CONF_PITCH] = int(user_input[CONF_PITCH])
            self._data.update(user_input)
            if self._is_new:
                return self.async_create_entry(title=name, data=self._data)
            return self.async_update_and_abort(
                self._get_entry(),
                self._get_reconfigure_subentry(),
                title=name,
                data=self._data,
            )

        default_name = (
            self._get_reconfigure_subentry().title
            if not self._is_new
            else f"{voice.name} ({self._data[CONF_LOCALE]})"
        )
        fields: dict[Any, Any] = {
            vol.Required(CONF_NAME, default=default_name): str,
        }
        if locale.styles:
            current_style = self._data.get(CONF_STYLE)
            fields[
                vol.Required(
                    CONF_STYLE,
                    default=current_style
                    if current_style in locale.styles
                    else locale.styles[0],
                )
            ] = SelectSelector(
                SelectSelectorConfig(
                    options=list(locale.styles), mode=SelectSelectorMode.DROPDOWN
                )
            )
        else:
            self._data.pop(CONF_STYLE, None)
        fields[vol.Required(CONF_RATE, default=self._data.get(CONF_RATE, 0))] = (
            NumberSelector(
                NumberSelectorConfig(
                    min=RATE_MIN, max=RATE_MAX, step=1, mode=NumberSelectorMode.SLIDER
                )
            )
        )
        fields[vol.Required(CONF_PITCH, default=self._data.get(CONF_PITCH, 0))] = (
            NumberSelector(
                NumberSelectorConfig(
                    min=PITCH_MIN,
                    max=PITCH_MAX,
                    step=1,
                    mode=NumberSelectorMode.SLIDER,
                )
            )
        )
        fields[
            vol.Required(
                CONF_AUDIO_FORMAT,
                default=self._data.get(CONF_AUDIO_FORMAT, DEFAULT_AUDIO_FORMAT),
            )
        ] = SelectSelector(
            SelectSelectorConfig(
                options=list(AUDIO_FORMATS),
                mode=SelectSelectorMode.DROPDOWN,
                translation_key=CONF_AUDIO_FORMAT,
            )
        )
        return self.async_show_form(
            step_id="settings",
            data_schema=vol.Schema(fields),
            description_placeholders={
                "voice": voice.name,
                "language": locale.label,
            },
        )
