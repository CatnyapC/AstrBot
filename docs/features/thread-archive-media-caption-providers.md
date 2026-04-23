# Thread Archive Media Caption Providers

## Summary

`astrbot_plugin_thread_archive` uses provider selectors for image and video captioning, while record captioning uses a dedicated local audio service.

## Config Keys

- `image_caption_provider_id`
- `video_caption_provider_id`
- `sticker_caption_provider_id`
- `record_caption_service_url`
- `record_caption_service_timeout`

## Selection Order

### Image

1. `sticker_caption_provider_id` for stickers
2. `image_caption_provider_id`
3. runtime `default_image_caption_provider_id`
4. `image_caption_fallback_provider_ids`

### Video

1. `video_caption_provider_id`
2. `image_caption_provider_id`
3. runtime `default_image_caption_provider_id`
4. `image_caption_fallback_provider_ids`

### Record

1. `record_caption_service_url`
2. local audio service response

## Why

Archive-side media resolving keeps image and video on the provider path, while record uses a local native-audio service better suited for `Gemma 4 E4B`.
