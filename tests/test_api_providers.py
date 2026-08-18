from __future__ import annotations

from app.api.providers import API_PROVIDER_PRESETS, provider_by_id, provider_for_base_url
from app.models.schemas import AppSettings


def test_provider_presets_are_unique_and_schema_valid():
    assert len(API_PROVIDER_PRESETS) >= 6
    assert len({item.id for item in API_PROVIDER_PRESETS}) == len(API_PROVIDER_PRESETS)
    assert len({item.base_url for item in API_PROVIDER_PRESETS}) == len(API_PROVIDER_PRESETS)
    for preset in API_PROVIDER_PRESETS:
        settings = AppSettings(api_base_url=preset.base_url, api_model=preset.default_model)
        assert settings.api_base_url == preset.base_url.rstrip("/")
        assert preset.models and all(model.strip() for model in preset.models)
        assert preset.docs_url.startswith("https://")
        assert provider_by_id(preset.id) is preset
        assert provider_for_base_url(preset.base_url + "/") is preset


def test_unknown_provider_and_custom_url_do_not_false_match():
    assert provider_by_id("unknown") is None
    assert provider_for_base_url("http://localhost:11434/v1") is None
