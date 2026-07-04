from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

APP_NAME = "My ClaudeCode NVIDIA NIM Proxy"
ENV_HEADER = """# Managed by My ClaudeCode Server /admin.
# Paste your NVIDIA NIM key here. Nothing else is required.
"""

# User asked for a clean env with only the NVIDIA NIM API value.
# The app still accepts NVIDIA_NIM_API_KEY for backwards compatibility, but new
# installs only create NVIDIA_NIM_API.
DEFAULT_ENV = """# NVIDIA NIM API Key
NVIDIA_NIM_API=
"""

DEFAULT_NVIDIA_NIM_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_NVIDIA_NIM_MODEL = "z-ai/glm-5.1"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = "2424"
DEFAULT_MAX_TOKENS = "4096"
DEFAULT_CLAUDE_BINARY = "claude"
PROVIDERS = ["NVIDIA_NIM"]


def app_home() -> Path:
    if os.environ.get("FREE_CLAUDE_CODE_HOME"):
        return Path(os.environ["FREE_CLAUDE_CODE_HOME"]).expanduser().resolve()
    return Path(__file__).resolve().parents[1]


def env_path() -> Path:
    return app_home() / ".env"


def parse_env_text(text: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        out[key] = value
    return out


def load_env() -> Dict[str, str]:
    values = dict(os.environ)
    p = env_path()
    if p.exists():
        values.update(parse_env_text(p.read_text(encoding="utf-8")))
    return values


def ensure_env() -> Path:
    p = env_path()
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(DEFAULT_ENV, encoding="utf-8")
        try:
            p.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
    return p


def _api_value(values: Dict[str, str]) -> str:
    return (values.get("NVIDIA_NIM_API") or values.get("NVIDIA_NIM_API_KEY") or "").strip()


def write_env_values(updates: Dict[str, str]) -> None:
    """Write a minimal user-facing .env.

    NVIDIA_NIM_API is the primary persisted value.
    NVIDIA_NIM_MODEL is also persisted if the user sets it via UI.
    """
    p = ensure_env()
    old = parse_env_text(p.read_text(encoding="utf-8"))
    old.update({k: v for k, v in updates.items() if k})
    api = _api_value(old)
    model = old.get("NVIDIA_NIM_MODEL", "")
    content = f"# NVIDIA NIM API Key\nNVIDIA_NIM_API={api}\n"
    if model:
        content += f"# NVIDIA NIM Model\nNVIDIA_NIM_MODEL={model}\n"
    p.write_text(content, encoding="utf-8")
    try:
        p.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


@dataclass
class ProviderConfig:
    name: str
    base_url: str
    api_key: str
    model: str
    needs_key: bool = True


def get_provider(values: Optional[Dict[str, str]] = None) -> ProviderConfig:
    values = values or load_env()
    return ProviderConfig(
        name="NVIDIA_NIM",
        base_url=values.get("NVIDIA_NIM_BASE_URL", DEFAULT_NVIDIA_NIM_BASE_URL).strip().rstrip("/"),
        api_key=_api_value(values),
        model=values.get("NVIDIA_NIM_MODEL", DEFAULT_NVIDIA_NIM_MODEL).strip(),
        needs_key=True,
    )


def local_base_url(values: Optional[Dict[str, str]] = None) -> str:
    values = values or load_env()
    host = values.get("HOST", DEFAULT_HOST)
    port = values.get("PORT", DEFAULT_PORT)
    return values.get("ANTHROPIC_BASE_URL") or f"http://{host}:{port}"
