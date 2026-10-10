"""文件存储抽象。

MVP 用 LocalStorage（本地磁盘）；二期接 OSS 时实现同接口的
OssStorage 并在 get_storage() 处切换，业务代码零改动。
"""

import uuid
from pathlib import Path

from .config import get_settings


class StorageBackend:
    def save(self, data: bytes, ext: str) -> str:
        """保存文件，返回存储侧路径标识（本地为文件名）。"""
        raise NotImplementedError

    def url_for(self, path: str) -> str:
        """返回可访问的 URL（本地为静态路由相对路径）。"""
        raise NotImplementedError


class LocalStorage(StorageBackend):
    def __init__(self, base_dir: str):
        self.base = Path(base_dir)
        self.base.mkdir(parents=True, exist_ok=True)

    def save(self, data: bytes, ext: str) -> str:
        # 服务端生成文件名，不信任用户上传的原始文件名
        name = f"{uuid.uuid4().hex}{ext}"
        (self.base / name).write_bytes(data)
        return name

    def url_for(self, path: str) -> str:
        return f"/uploads/{path}"


def get_storage() -> LocalStorage:
    return LocalStorage(get_settings().upload_dir)
