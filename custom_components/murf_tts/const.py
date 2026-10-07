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

MODELS: Final = ["FALCON", "GEN2"]
DEFAULT_MODEL: Final = "FALCON"

# Murf format name -> file extension understood by Home Assistant
AUDIO_FORMATS: Final = {
    "MP3": "mp3",
    "OGG": "ogg",
    "WAV": "wav",
    "FLAC": "flac",
}
DEFAULT_AUDIO_FORMAT: Final = "MP3"

RATE_MIN: Final = -50
RATE_MAX: Final = 50
PITCH_MIN: Final = -50
PITCH_MAX: Final = 50
