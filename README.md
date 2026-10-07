# Murf AI TTS for Home Assistant

Text-to-speech for Home Assistant using the official [Murf AI API](https://murf.ai/api) and the official `murf` Python SDK.

Each Murf voice you add becomes its own `tts.*` entity that can be used in `tts.speak`, automations, scripts and Assist voice pipelines.

## Features

- Official Murf API with your own API key (no scraping of the Murf website)
- Voice catalogue loaded from Murf: pick language, model and voice from dropdowns
- Several voices per account (each with its own style, speed, pitch and format)
- Falcon (low latency) and Gen2 (highest quality) models
- Streaming playback (Home Assistant 2025.7+): audio starts while Murf is still generating
- Multi-language voices: every language a voice speaks is offered to Home Assistant
- Per-call overrides for voice, style, speed and pitch
- Region selection for synthesis (e.g. EU Central)
- Reauthentication when the key is revoked, clear error messages, English and German UI

## Requirements

- Home Assistant 2025.7 or newer
- A Murf API key from the [Murf API dashboard](https://murf.ai/api/dashboard) (Free trail: No credit card required and $10 free, every month)

## Installation

### HACS

1. HACS → three-dot menu → *Custom repositories*
2. Add this repository's URL, category *Integration*
3. Install **Murf AI TTS** and restart Home Assistant

### Manual

Copy `custom_components/murf_tts` into `<config>/custom_components/` and restart Home Assistant.

## Setup

1. *Settings → Devices & services → Add integration → Murf AI TTS*
2. Enter the API key and choose the region
3. On the integration entry, choose **Add voice**:
   1. Language and model
   2. Voice (only voices that speak the language are listed)
   3. Name, style, speed, pitch, audio format

Voices can be changed later with **Change voice** on the voice entry. API key and region can be changed with *Reconfigure* on the integration entry.

## Usage

```yaml
action: tts.speak
target:
  entity_id: tts.matthias_de_de
data:
  media_player_entity_id: media_player.kitchen
  message: "Die Waschmaschine ist fertig."
```

Per-call overrides:

```yaml
action: tts.speak
target:
  entity_id: tts.matthias_de_de
data:
  media_player_entity_id: media_player.kitchen
  message: "Achtung, die Haustür ist offen!"
  options:
    style: Promo      # must be a style of the voice in that language
    rate: 10          # -50 .. 50
    pitch: -5         # -50 .. 50
    voice: de-DE-lia  # another voice of the same model
```

`language` can be set to any language the voice speaks (for example `en-GB` for a voice that also speaks English). Murf's `en-UK` locale is exposed as the standard tag `en-GB`.

## Notes

- **Region:** the voice catalogue is only served from `api.murf.ai`; the region setting applies to speech synthesis. Murf limits concurrent requests per region (see the Murf docs), which can matter if several speakers announce at the same time.
- **Caching:** Home Assistant caches generated audio by default (`cache: true`), so repeated messages do not use Murf characters again.
- **Privacy:** the text you send is processed by Murf. Do not send personal data you would not want to leave your network.

## License

MIT
