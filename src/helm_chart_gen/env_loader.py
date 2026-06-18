from __future__ import annotations

import os
from pathlib import Path


def load_project_env() -> None:
    """Load .env early enough for CrewAI/LiteLLM provider selection."""
    env_path = _find_env_file()
    if env_path:
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)

    _normalize_crewai_storage()
    _normalize_azure_openai_env()


def _find_env_file() -> Path | None:
    candidates = [Path.cwd(), *Path.cwd().parents]
    module_root = Path(__file__).resolve().parents[3]
    candidates.append(module_root)

    for directory in candidates:
        env_path = directory / ".env"
        if env_path.exists():
            return env_path
    return None


def _normalize_crewai_storage() -> None:
    storage_dir = os.getenv("CREWAI_STORAGE_DIR")
    if not storage_dir:
        os.environ["CREWAI_STORAGE_DIR"] = str((Path.cwd() / ".crewai_storage").resolve())
        return

    storage_path = Path(storage_dir)
    if not storage_path.is_absolute():
        os.environ["CREWAI_STORAGE_DIR"] = str((Path.cwd() / storage_path).resolve())


def _normalize_azure_openai_env() -> None:
    # Support both Azure OpenAI naming styles.
    if os.getenv("AZURE_OPENAI_API_KEY") and not os.getenv("AZURE_API_KEY"):
        os.environ["AZURE_API_KEY"] = os.environ["AZURE_OPENAI_API_KEY"]
    if os.getenv("AZURE_OPENAI_ENDPOINT") and not os.getenv("AZURE_API_BASE"):
        os.environ["AZURE_API_BASE"] = os.environ["AZURE_OPENAI_ENDPOINT"]
    if os.getenv("AZURE_OPENAI_API_VERSION") and not os.getenv("AZURE_API_VERSION"):
        os.environ["AZURE_API_VERSION"] = os.environ["AZURE_OPENAI_API_VERSION"]

    model = os.getenv("MODEL", "").strip()
    if os.getenv("AZURE_API_KEY") and model and "/" not in model:
        os.environ["MODEL"] = f"azure/{model}"
