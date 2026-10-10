"""应用配置：从 backend/.env 读取（环境变量优先于 .env 文件）。"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # DeepSeek 多模态大模型（API Key 在 backend/.env 的 DEEPSEEK_API_KEY 填入）
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "Deepseek-V4.1-Flash"
    deepseek_timeout: float = 60.0
    # 推理型模型的思考 token 也计入 max_tokens，偏小会导致正文为空
    deepseek_max_tokens: int = 8192

    # 数据库（开发默认 SQLite，可切 MySQL）
    database_url: str = "sqlite:///./dev.db"

    # 本地图片存储目录
    upload_dir: str = "./uploads"

    @property
    def llm_configured(self) -> bool:
        return bool(self.deepseek_api_key.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
