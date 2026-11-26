"""LLM providers for `pipeline.py summarize`. Each module has KEY_ENV, MODEL and complete(prompt, key, model)."""
import os

from providers import claude, deepseek, gemini, grok, openai
from providers.base import ProviderError  # noqa: F401

PROVIDERS = {'openai': openai, 'gemini': gemini, 'claude': claude, 'deepseek': deepseek, 'grok': grok}


def model_for(name):
    return os.environ.get(name.upper() + '_MODEL') or PROVIDERS[name].MODEL
