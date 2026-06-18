import logging
import os
from typing import Any, Dict

from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import SecretStr

from automa_ai.agents import GenericAgentType, GenericLLM

logger = logging.getLogger(__name__)

OPENAI_COMPATIBLE_API_KEY_ENV_VARS = ("OPENAI_API_KEY", "API_KEY", "ACCESS_TOKEN")


def resolve_chat_model(
    backend: GenericLLM | BaseChatModel,
    model_name: str,
    agent_type: GenericAgentType | str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    api_version: str | None = None,
    model_max_retries: int | None = None,
    model_kwargs: Dict[str, Any] | None = None,
    default_headers: Dict[str, str] | None = None,
    extra_body: Dict[str, Any] | None = None,
):
    # Backward compatibility for older calls shaped as:
    # resolve_chat_model(backend, model_name, base_url)
    if isinstance(agent_type, str) and base_url is None:
        base_url = agent_type
        agent_type = None

    if isinstance(backend, BaseChatModel):
        return backend

    model_kwargs = model_kwargs or {}
    default_headers = default_headers or {}

    if backend == GenericLLM.OLLAMA:
        ChatOllama = _load_ollama_chat_model()
        return ChatOllama(model=model_name, base_url=base_url, temperature=0)
    if backend == GenericLLM.BEDROCK:
        ChatBedrockConverse = _load_bedrock_chat_model()
        aws_access_key_id = os.getenv("AWS_ACCESS_KEY_ID")
        aws_secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY")
        aws_region = os.getenv("AWS_REGION")
        if aws_access_key_id is None or aws_secret_access_key is None:
            logger.warning(
                "AWS_ACCESS_KEY_ID, AWS_REGION, AWS_SECRET_ACCESS_KEY are not set"
            )
            return ChatBedrockConverse(
                model=model_name, region_name=aws_region, temperature=0
            )
        return ChatBedrockConverse(
            model=model_name,
            region_name=aws_region,
            aws_access_key_id=SecretStr(aws_access_key_id),
            aws_secret_access_key=SecretStr(aws_secret_access_key),
        )
    if backend == GenericLLM.OPENAI:
        return _resolve_openai_chat_model(
            model_name=model_name,
            agent_type=agent_type,
            base_url=base_url,
            api_key=api_key,
            api_version=api_version,
            default_headers=default_headers,
        )
    if backend == GenericLLM.OPENAI_COMPATIBLE:
        return _resolve_openai_compatible_chat_model(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            model_kwargs=model_kwargs,
            default_headers=default_headers,
            extra_body=extra_body,
        )
    if backend == GenericLLM.CLAUDE:
        ChatAnthropic = _load_anthropic_chat_model()
        assert api_key, "You must provide an API key to access Anthropic Claude model"
        return ChatAnthropic(
            model_name=model_name,
            base_url=base_url,
            api_key=SecretStr(api_key),
            timeout=None,
        )
    if backend == GenericLLM.GEMINI:
        ChatGoogleGenerativeAI = _load_gemini_chat_model()
        assert os.getenv(
            "GOOGLE_API_KEY"
        ), "You must add GOOGLE_API_KEY in the system environment."
        streaming = agent_type is GenericAgentType.LANGGRAPHCHAT
        if model_max_retries is None:
            max_retries = 2
        else:
            try:
                max_retries = max(0, int(model_max_retries))
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"model_max_retries must be convertible to an integer, got: {model_max_retries!r}"
                ) from exc
        return ChatGoogleGenerativeAI(
            model=model_name,
            temperature=0,
            timeout=None,
            max_retries=max_retries,
            max_tokens=None,
            streaming=streaming,
        )
    if backend == GenericLLM.LITELLAMA:
        LiteLlm = _load_litellm_model()
        return LiteLlm(model=model_name)

    raise ValueError(f"Unsupported model backend: {backend}")


def _resolve_openai_chat_model(
    *,
    model_name: str,
    agent_type: GenericAgentType | str | None,
    base_url: str | None,
    api_key: str | None,
    api_version: str | None,
    default_headers: Dict[str, str],
):
    ChatOpenAI, AzureChatOpenAI = _load_openai_chat_models()
    resolved_api_key = (
        api_key.strip()
        if api_key and api_key.strip()
        else _extract_bearer_token(default_headers)
        or _first_populated_env("OPENAI_API_KEY")
    )
    assert resolved_api_key, (
        "You must provide an API key (api_key), an Authorization bearer token, "
        "or OPENAI_API_KEY in the environment to access OpenAI GPT models"
    )

    if base_url and "azure.com" in base_url.lower():
        if not api_version:
            raise ValueError(
                "AzureChatOpenAI requires azure_api_version and azure_deployment"
            )
        streaming = agent_type is GenericAgentType.LANGGRAPHCHAT
        return AzureChatOpenAI(
            azure_endpoint=base_url,
            api_key=SecretStr(resolved_api_key),
            api_version=api_version,
            azure_deployment=model_name,
            streaming=streaming,
        )

    return ChatOpenAI(
        model=model_name,
        base_url=base_url,
        api_key=SecretStr(resolved_api_key),
        temperature=0,
        streaming=True,
    )


def _resolve_openai_compatible_chat_model(
    *,
    model_name: str,
    base_url: str | None,
    api_key: str | None,
    model_kwargs: Dict[str, Any],
    default_headers: Dict[str, str],
    extra_body: Dict[str, Any] | None,
):
    ChatOpenAI, _ = _load_openai_chat_models()
    resolved_api_key = (
        api_key.strip()
        if api_key and api_key.strip()
        else _extract_bearer_token(default_headers)
        or _first_populated_env(*OPENAI_COMPATIBLE_API_KEY_ENV_VARS)
    )
    assert resolved_api_key, (
        "You must provide an API key to access OpenAI-compatible models. "
        "Checked explicit api_key, Authorization bearer token, plus env vars: "
        f"{', '.join(OPENAI_COMPATIBLE_API_KEY_ENV_VARS)}"
    )
    if not base_url or not base_url.strip():
        raise ValueError("OPENAI_COMPATIBLE models require a non-empty base_url.")

    return ChatOpenAI(
        model=model_name,
        base_url=base_url,
        api_key=SecretStr(resolved_api_key),
        temperature=0,
        streaming=True,
        model_kwargs=model_kwargs,
        default_headers=default_headers or None,
        extra_body=extra_body,
    )


def _first_populated_env(*keys: str) -> str | None:
    for key in keys:
        value = os.getenv(key)
        if value and value.strip():
            return value.strip()
    return None


def _extract_bearer_token(default_headers: Dict[str, str] | None) -> str | None:
    if not default_headers:
        return None
    authorization = default_headers.get("Authorization") or default_headers.get(
        "authorization"
    )
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


def _load_openai_chat_models():
    try:
        from langchain_openai import AzureChatOpenAI, ChatOpenAI
    except ImportError as exc:
        raise ImportError(
            "OpenAI and OpenAI-compatible models require 'langchain-openai'. "
            "Install langchain-openai to use GenericLLM.OPENAI or "
            "GenericLLM.OPENAI_COMPATIBLE."
        ) from exc
    return ChatOpenAI, AzureChatOpenAI


def _load_ollama_chat_model():
    try:
        from langchain_ollama import ChatOllama
    except ImportError as exc:
        raise ImportError(
            "Ollama models require 'langchain-ollama'. Install langchain-ollama "
            "to use GenericLLM.OLLAMA."
        ) from exc
    return ChatOllama


def _load_bedrock_chat_model():
    try:
        from langchain_aws import ChatBedrockConverse
    except ImportError as exc:
        raise ImportError(
            "Bedrock models require 'langchain-aws'. Install langchain-aws "
            "to use GenericLLM.BEDROCK."
        ) from exc
    return ChatBedrockConverse


def _load_anthropic_chat_model():
    try:
        from langchain_anthropic import ChatAnthropic
    except ImportError as exc:
        raise ImportError(
            "Anthropic models require 'langchain-anthropic'. Install "
            "langchain-anthropic to use GenericLLM.CLAUDE."
        ) from exc
    return ChatAnthropic


def _load_gemini_chat_model():
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
    except ImportError as exc:
        raise ImportError(
            "Gemini models require 'langchain-google-genai'. Install "
            "langchain-google-genai to use GenericLLM.GEMINI."
        ) from exc
    return ChatGoogleGenerativeAI


def _load_litellm_model():
    try:
        from google.adk.models.lite_llm import LiteLlm
    except ImportError as exc:
        raise ImportError(
            "LiteLLM support requires the Google ADK LiteLlm integration."
        ) from exc
    return LiteLlm
