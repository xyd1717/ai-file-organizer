from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class APIProviderPreset:
    id: str
    name: str
    base_url: str
    models: tuple[str, ...]
    docs_url: str
    note: str

    @property
    def default_model(self) -> str:
        return self.models[0]


CUSTOM_PROVIDER_ID = "custom"

# These are OpenAI-compatible Chat Completions endpoints documented by each
# provider. Model fields remain editable because availability depends on the
# user's account, region, and provider-side updates.
API_PROVIDER_PRESETS: tuple[APIProviderPreset, ...] = (
    APIProviderPreset(
        id="openai",
        name="OpenAI",
        base_url="https://api.openai.com/v1",
        models=("gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol"),
        docs_url="https://developers.openai.com/api/docs/models",
        note="适合通用文件分类；账号可用模型以连接测试结果为准。",
    ),
    APIProviderPreset(
        id="deepseek",
        name="DeepSeek",
        base_url="https://api.deepseek.com",
        models=("deepseek-v4-flash", "deepseek-v4-pro"),
        docs_url="https://api-docs.deepseek.com/zh-cn/guides/reasoning_model",
        note="Flash 更适合低成本批量分类，Pro 更适合复杂内容判断。",
    ),
    APIProviderPreset(
        id="kimi_cn",
        name="Kimi（月之暗面，中国区）",
        base_url="https://api.moonshot.cn/v1",
        models=("kimi-k2.6", "kimi-k2.5"),
        docs_url="https://platform.kimi.com/docs/api/overview",
        note="此预设使用中国区开放平台；中国区与国际区 API Key 不互通。",
    ),
    APIProviderPreset(
        id="qwen_cn",
        name="阿里云百炼（千问，中国区）",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        models=("qwen3.7-plus", "qwen-plus"),
        docs_url="https://help.aliyun.com/zh/model-studio/base-url",
        note="使用北京地域 OpenAI 兼容端点；API Key 必须与地域和计费方案匹配。",
    ),
    APIProviderPreset(
        id="siliconflow_cn",
        name="硅基流动（中国区）",
        base_url="https://api.siliconflow.cn/v1",
        models=(
            "deepseek-ai/DeepSeek-V3.2",
            "Qwen/Qwen3.6-27B",
            "Pro/moonshotai/Kimi-K2.6",
        ),
        docs_url="https://api-docs.siliconflow.cn/docs/userguide/capabilities/text-generation",
        note="聚合多家模型；请选择与你账号权限对应的模型 ID。",
    ),
    APIProviderPreset(
        id="zhipu",
        name="智谱 GLM",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        models=("glm-5.2", "glm-5.1"),
        docs_url="https://docs.bigmodel.cn/cn/guide/develop/http/introduction",
        note="使用智谱开放平台的 OpenAI 兼容 Chat Completions 接口。",
    ),
)

_BY_ID = {preset.id: preset for preset in API_PROVIDER_PRESETS}


def provider_by_id(provider_id: str) -> APIProviderPreset | None:
    return _BY_ID.get(provider_id)


def provider_for_base_url(base_url: str) -> APIProviderPreset | None:
    normalized = base_url.strip().rstrip("/").casefold()
    return next(
        (preset for preset in API_PROVIDER_PRESETS if preset.base_url.rstrip("/").casefold() == normalized),
        None,
    )


__all__ = [
    "APIProviderPreset",
    "API_PROVIDER_PRESETS",
    "CUSTOM_PROVIDER_ID",
    "provider_by_id",
    "provider_for_base_url",
]
