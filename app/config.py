import os
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
# .env 路径可用环境变量重定向（测试隔离用）
ENV_PATH = Path(os.environ.get("ENV_PATH") or (BASE_DIR / ".env"))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ENV_PATH), env_file_encoding="utf-8", extra="ignore"
    )

    bailian_api_key: str = ""
    bailian_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    database_url: str = f"sqlite:///{BASE_DIR / 'data' / 'token.db'}"
    config_dir: Path = BASE_DIR / "config"
    env_path: Path = ENV_PATH
    default_total_tokens: int = 1_000_000
    default_valid_days: int = 90
    free_quota_low_percent: float = 0.2
    sync_hour: int = 3

    @property
    def chat_url(self) -> str:
        return self.bailian_base_url.rstrip("/") + "/chat/completions"

    @property
    def models_url(self) -> str:
        return self.bailian_base_url.rstrip("/") + "/models"

    @property
    def api_base(self) -> str:
        """ListModels / models-limits 挂在域名根上的 /api/v1。"""
        url = self.bailian_base_url.rstrip("/")
        suffix = "/compatible-mode/v1"
        if url.endswith(suffix):
            return url[: -len(suffix)]
        return url

    @property
    def list_models_url(self) -> str:
        return self.api_base + "/api/v1/models"

    @property
    def list_limits_url(self) -> str:
        return self.api_base + "/api/v1/models/limits"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def load_yaml(name: str) -> dict:
    path = get_settings().config_dir / name
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
