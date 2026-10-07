"""Constants for the Murf AI TTS integration."""

from __future__ import annotations

import logging
from typing import Final

DOMAIN: Final = "murf_tts"
LOGGER = logging.getLogger(__package__)

SUBENTRY_TYPE_TTS: Final = "tts"

API_KEY_URL: Final = "https://murf.ai/api/dashboard"

# Config entry data
CONF_REGION: Final = "region"

# Subentry data
CONF_MODEL: Final = "model"
CONF_LOCALE: Final = "locale"
CONF_VOICE_ID: Final = "voice_id"
CONF_STYLE: Final = "style"
CONF_RATE: Final = "rate"
CONF_PITCH: Final = "pitch"
CONF_AUDIO_FORMAT: Final = "audio_format"

# Per-call TTS options (in addition to tts.ATTR_VOICE)
ATTR_STYLE: Final = "style"
ATTR_RATE: Final = "rate"
ATTR_PITCH: Final = "pitch"

# Regions offered by Murf for speech synthesis. The voice catalogue is only
# served from api.murf.ai, so the region only applies to synthesis requests.
REGIONS: Final = [
    "global",
    "eu-central",
    "uk",
    "us-east",
    "us-west",
    "ca",
    "sa-east",
    "in",
    "jp",
    "kr",
    "au",
    "me",
]
DEFAULT_REGION: Final = "global"

# Stored and shown in lower case, because Home Assistant only allows
# [a-z0-9-_] as selector option keys. The API layer sends them upper case.
MODELS: Final = ["falcon", "gen2"]
DEFAULT_MODEL: Final = "falcon"

# The format value doubles as the file extension for Home Assistant.
AUDIO_FORMATS: Final = ["mp3", "ogg", "wav", "flac"]
DEFAULT_AUDIO_FORMAT: Final = "mp3"


def normalize_model(value: str | None) -> str:
    """Return the stored model in its canonical form (tolerates old upper case)."""
    model = (value or DEFAULT_MODEL).lower()
    return model if model in MODELS else DEFAULT_MODEL


def normalize_audio_format(value: str | None) -> str:
    """Return the stored audio format in its canonical form."""
    audio_format = (value or DEFAULT_AUDIO_FORMAT).lower()
    return audio_format if audio_format in AUDIO_FORMATS else DEFAULT_AUDIO_FORMAT


RATE_MIN: Final = -50
RATE_MAX: Final = 50
PITCH_MIN: Final = -50
PITCH_MAX: Final = 50
