"""The Murf AI text-to-speech integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from .api import MurfApi, MurfAuthError, MurfError
from .const import CONF_MODEL, CONF_REGION, DEFAULT_MODEL, DEFAULT_REGION, DOMAIN

PLATFORMS: list[Platform] = [Platform.TTS]

type MurfConfigEntry = ConfigEntry[MurfApi]


async def async_setup_entry(hass: HomeAssistant, entry: MurfConfigEntry) -> bool:
    """Set up Murf AI from a config entry."""
    api = MurfApi(
        hass,
        entry.data[CONF_API_KEY],
        entry.data.get(CONF_REGION, DEFAULT_REGION),
    )

    # Loading the voice catalogue validates the key and lets the entities
    # report languages and voices without a network call.
    models = {
        subentry.data.get(CONF_MODEL, DEFAULT_MODEL)
        for subentry in entry.subentries.values()
    } or {DEFAULT_MODEL}
    try:
        for model in sorted(models):
            await api.async_get_voices(model)
    except MurfAuthError as err:
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN, translation_key="invalid_auth"
        ) from err
    except MurfError as err:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="cannot_connect",
            translation_placeholders={"error": str(err)},
        ) from err

    entry.runtime_data = api
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: MurfConfigEntry) -> None:
    """Reload when voices (subentries) are added, changed or removed."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: MurfConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
