"""OpenAI-compatible Chat Completions adapter; zero third-party dependencies."""
from __future__ import annotations
import json
import os
import urllib.error
import urllib.request


class ProviderError(Exception):
    pass


def read_env(path):
    """Convenience parser for .env; does not print or log secrets."""
    values = {}
    if not os.path.isfile(path):
        return values
    for raw in open(path, encoding="utf-8"):
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        values[k.strip()] = v.strip().strip('"').strip("'")
    return values


class ChatProvider:
    def __init__(self, base_url, api_key, model, timeout=75):
        if not api_key:
            raise ProviderError("未设置模型 API Key。可以先点击『离线演示』。")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def complete(self, messages, tools):
        url = self.base_url
        if not url.endswith("/chat/completions"):
            url += "/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "temperature": 0.2,
        }
        if "api.deepseek.com" in self.base_url:
            payload["thinking"] = {"type": "disabled"}
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, method="POST",
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + self.api_key})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                parsed = json.loads(resp.read(3_000_000).decode("utf-8"))
            msg = parsed["choices"][0]["message"]
            return {"content": msg.get("content") or "", "tool_calls": msg.get("tool_calls") or []}
        except urllib.error.HTTPError as e:
            # Server error bodies can occasionally echo sensitive request data: never display them.
            raise ProviderError(f"模型服务 HTTP {e.code}，请检查地址、Key、模型名与工具调用支持。") from None
        except (urllib.error.URLError, TimeoutError) as e:
            raise ProviderError(f"无法访问模型服务：{type(e).__name__}") from None
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            raise ProviderError(f"模型服务返回格式不兼容：{type(e).__name__}") from None
