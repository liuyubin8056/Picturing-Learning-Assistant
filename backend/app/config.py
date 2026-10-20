"""应用配置：固定从 backend/.env 读取（路径相对本文件，不依赖启动目录）。"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[1]  # backend/


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    # DeepSeek 多模态大模型（API Key 在 backend/.env 的 DEEPSEEK_API_KEY 填入）
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "Deepseek-V4.1-Flash"
    deepseek_timeout: float = 60.0
    # 推理型模型的思考 token 也计入 max_tokens，偏小会导致正文为空
    # 推理型模型的思考 token 与正文共享该上限：设得太小会导致正文为空
    # （实测高数题思考可达 12000+ token），故给足 32000
    deepseek_max_tokens: int = 32000

    # 数据库（开发默认 SQLite，可切 MySQL）
    database_url: str = "sqlite:///./dev.db"

    # 本地图片存储目录
    upload_dir: str = "./uploads"

    @property
    def llm_configured(self) -> bool:
        return bool(self.deepseek_api_key.strip())

    @property
    def upload_path(self) -> Path:
        """上传目录绝对路径（相对 backend/，避免启动目录影响）。"""
        p = Path(self.upload_dir)
        return p if p.is_absolute() else (BASE_DIR / p).resolve()

    @property
    def db_url(self) -> str:
        """SQLite 相对路径转绝对，避免在错误目录生成空库。"""
        if self.database_url.startswith("sqlite:///./"):
            return "sqlite:///" + str((BASE_DIR / self.database_url[10:]).resolve()).replace("\\", "/")
        return self.database_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
