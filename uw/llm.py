"""One call shape for every LLM provider the underwriting server offers.

A model reference is "provider:model", e.g. "anthropic:claude-opus-5-5" or "gemini:gemini-...".
Claude goes through the Anthropic SDK; every other provider speaks the OpenAI chat API and goes
through the OpenAI SDK with its own base URL. Keys come from environment variables only.
Install: pip install anthropic openai (only the SDKs of the providers you use).
"""

import copy
import json
import os
import re
import urllib.request

PROVIDERS = {
    "anthropic": dict(label="Claude", key="ANTHROPIC_API_KEY"),
    "openai": dict(label="OpenAI", key="OPENAI_API_KEY", base=None),
    "xai": dict(label="xAI Grok", key="XAI_API_KEY", base="https://api.x.ai/v1"),
    "gemini": dict(
        label="Google Gemini",
        key="GEMINI_API_KEY",
        base="https://generativelanguage.googleapis.com/v1beta/openai/",
    ),
    "openrouter": dict(
        label="OpenRouter",
        key="OPENROUTER_API_KEY",
        base="https://openrouter.ai/api/v1",
    ),
    "local": dict(
        label="Local",
        key=None,
        base=os.environ.get("UW_LOCAL_URL", "http://localhost:11434/v1"),
    ),
}
# Claude models that accept server-side refusal fallback ("default" form).
FALLBACK_MODELS = (
    "claude-opus-5-5",
    "claude-opus-5",
    "claude-fable-5-1",
    "claude-sonnet-5-5",
)
# JSON Schema keywords structured outputs reject. The engine enforces all of them again.
UNSUPPORTED = {"minLength", "maxLength", "pattern", "$schema", "$id", "title"}


class LLMError(Exception):
    pass


def _strip(schema):
    if isinstance(schema, dict):
        return {k: _strip(v) for k, v in schema.items() if k not in UNSUPPORTED}
    if isinstance(schema, list):
        return [_strip(v) for v in schema]
    return schema


def _split(ref):
    provider, sep, model = ref.partition(":")
    if not sep or provider not in PROVIDERS or not model:
        raise LLMError(
            f"unknown model {ref!r}; expected provider:model with provider in {', '.join(PROVIDERS)}"
        )
    return provider, model


def _key(provider):
    env = PROVIDERS[provider]["key"]
    if env is None:
        return "local"  # local servers ignore the key, but the SDK requires one
    if not os.environ.get(env):
        raise LLMError(f"{env} is not set")
    return os.environ[env]


def _openai(provider):
    import openai

    return openai.OpenAI(api_key=_key(provider), base_url=PROVIDERS[provider]["base"])


def _local_up():
    try:
        urllib.request.urlopen(
            PROVIDERS["local"]["base"].rstrip("/") + "/models", timeout=1
        ).close()
        return True
    except OSError:
        return False


def available():
    """Models of every provider whose key is set (local: whose server answers), plus per-provider errors."""
    models, errors = [], {}
    for p, cfg in PROVIDERS.items():
        if (cfg["key"] and not os.environ.get(cfg["key"])) or (
            p == "local" and not _local_up()
        ):
            continue
        try:
            if p == "anthropic":
                import anthropic

                ids = [m.id for m in anthropic.Anthropic(api_key=_key(p)).models.list()]
            else:
                ids = [m.id for m in _openai(p).models.list().data]
            models += [
                dict(id=f"{p}:{i}", provider=cfg["label"], model=i) for i in sorted(ids)
            ]
        except Exception as e:  # one provider failing must not hide the others
            errors[cfg["label"]] = str(e).splitlines()[0][:200]
    return models, errors


def complete(ref, system, messages, schema=None):
    """Text of one reply. messages: [{"role": "user"|"assistant", "content": str}]. schema: JSON output."""
    provider, model = _split(ref)
    try:
        if provider == "anthropic":
            return _claude(model, system, messages, schema)
        return _chat(provider, model, system, messages, schema)
    except LLMError:
        raise
    except ImportError as e:
        raise LLMError(f"{e.name} SDK not installed: pip install {e.name}")
    except (
        Exception
    ) as e:  # SDK errors differ per provider; the message is what the user needs
        raise LLMError(
            f"{PROVIDERS[provider]['label']}: {str(e).splitlines()[0][:300]}"
        )


def _claude(model, system, messages, schema):
    import anthropic

    client = anthropic.Anthropic(api_key=_key("anthropic"))
    kw = dict(
        model=model,
        max_tokens=16000,
        messages=messages,
        system=[
            {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
        ],
    )
    if schema:
        kw["output_config"] = {
            "format": {"type": "json_schema", "schema": schema}
        }
    if model in FALLBACK_MODELS:
        r = client.beta.messages.create(
            betas=["server-side-fallback-2026-07-01"],
            extra_body={"fallbacks": "default"},
            **kw,
        )
    else:
        r = client.messages.create(**kw)
    if r.stop_reason == "refusal":
        raise LLMError(
            f"Claude declined ({getattr(r.stop_details, 'category', None) or 'no category'})"
        )
    if r.stop_reason == "max_tokens":
        raise LLMError("Claude reply hit max_tokens before finishing")
    return "".join(b.text for b in r.content if b.type == "text")


def _chat(provider, model, system, messages, schema):
    import openai

    client = _openai(provider)
    kw = dict(model=model, messages=[{"role": "system", "content": system}] + messages)
    if schema:
        try:
            r = client.chat.completions.create(
                **kw,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "judgments",
                        "schema": schema,
                        "strict": False,
                    },
                },
            )
        except openai.BadRequestError:  # provider or model without JSON Schema output
            r = client.chat.completions.create(
                **kw, response_format={"type": "json_object"}
            )
    else:
        r = client.chat.completions.create(**kw)
    c = r.choices[0]
    if c.finish_reason == "length":
        raise LLMError(
            f"{PROVIDERS[provider]['label']} reply hit its length limit before finishing"
        )
    return c.message.content or ""


def judge(ref, questions_doc, prompt, schema):
    """Judgments for questions.json. The engine validates them; this only parses the JSON."""
    text = complete(
        ref,
        prompt,
        [{"role": "user", "content": json.dumps(questions_doc, indent=1)}],
        _strip(schema),
    )
    text = re.sub(
        r"^```(?:json)?\s*|\s*```$", "", text.strip()
    )  # json_object mode sometimes adds fences
    try:
        j = json.loads(text)
    except json.JSONDecodeError as e:
        raise LLMError(f"model returned invalid JSON ({e.msg} at char {e.pos})")
    if not isinstance(j, dict):
        raise LLMError("model returned JSON that is not an object")
    j = copy.copy(j)
    j["ledger_sha256"] = questions_doc[
        "ledger_sha256"
    ]  # this server pairs answers with their ledger
    return j
