"""拍照答疑核心业务：幂等去重 → 存图 → 多模态答疑 → 落库。"""

import json
from datetime import datetime, timezone

from sqlmodel import Session, select

from ..llm.deepseek import DeepSeekClient, LLMCallError, LLMNotConfiguredError
from ..models import Question, User
from ..storage import StorageBackend

ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10MB


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class QuestionService:
    def __init__(self, session: Session, storage: StorageBackend, llm: DeepSeekClient):
        self.session = session
        self.storage = storage
        self.llm = llm

    def get_by_client_id(self, client_question_id: str) -> Question | None:
        return self.session.exec(
            select(Question).where(Question.client_question_id == client_question_id)
        ).first()

    def ensure_user(self, user_id: int) -> User:
        user = self.session.get(User, user_id)
        if user is None:
            user = User(id=user_id)
            self.session.add(user)
            self.session.commit()
            self.session.refresh(user)
        return user

    async def submit(
        self,
        user_id: int,
        client_question_id: str,
        image_bytes: bytes,
        ext: str,
    ) -> tuple[Question, bool]:
        """提交题目照片并答疑。

        返回 (question, replay)：
        - replay=True 表示幂等命中已 answered 的记录，直接返回旧结果；
        - 上次 failed 的记录凭同一 client_question_id 重试（复用已存图片）。
        """
        if ext.lower() not in ALLOWED_EXT:
            raise ValueError(f"不支持的图片格式 {ext}，仅支持 jpg/jpeg/png/webp/bmp")
        if not image_bytes:
            raise ValueError("图片内容为空")
        if len(image_bytes) > MAX_IMAGE_BYTES:
            raise ValueError("图片超过 10MB 上限")
        if not client_question_id or len(client_question_id) > 64:
            raise ValueError("client_question_id 必填且长度不超过 64")

        existing = self.get_by_client_id(client_question_id)
        if existing is not None and existing.status == "answered":
            return existing, True

        if existing is None:
            self.ensure_user(user_id)
            image_path = self.storage.save(image_bytes, ext)
            question = Question(
                user_id=user_id,
                client_question_id=client_question_id,
                image_path=image_path,
            )
            self.session.add(question)
            self.session.commit()
            self.session.refresh(question)
        else:
            # 失败重试：复用记录与首次上传的图片
            question = existing
            question.status = "pending"
            question.error_msg = None

        try:
            result = await self.llm.ask_with_image(image_bytes)
            if result.meta and isinstance(result.meta.get("difficulty"), (int, float)):
                # 模型偶尔给出 4/5，统一裁剪到约定的 1~3
                result.meta["difficulty"] = max(
                    1, min(3, int(round(result.meta["difficulty"])))
                )
            # 多题照片：逐题讲解单独落库，并从 meta 摘掉避免重复存储
            probs = (result.meta or {}).pop("problems", None) if result.meta else None

            question.answer = result.answer
            if isinstance(probs, list) and probs:
                question.problems_json = json.dumps(probs, ensure_ascii=False)
            question.meta_json = (
                json.dumps(result.meta, ensure_ascii=False) if result.meta else None
            )
            # 预生成的学生反馈候选选项（供前端渲染多选+自定义）
            if result.meta:
                opts = result.meta.get("feedback_options")
                if isinstance(opts, list) and opts:
                    question.feedback_options = json.dumps(opts, ensure_ascii=False)
            question.status = "answered"
            question.answered_at = _utcnow()
            self.session.add(question)
            self.session.commit()
            self.session.refresh(question)

            # 弱信号入账：拍照求助本身计入（错因中性，等用户反馈后再修正）
            if question.feedback_options:
                from . import profile_service as _ps

                _ps.record_ask(self.session, question.user_id, question)

            # token 计量（答疑是主要开销场景，必须落库才能度量与优化）
            from .token_service import record_usage

            u = result.usage or {}
            record_usage(
                self.session,
                user_id=question.user_id,
                scene="qa",
                model=self.llm.model,
                prompt_tokens=u.get("prompt_tokens", 0),
                completion_tokens=u.get("completion_tokens", 0),
                reasoning_tokens=u.get("reasoning_tokens", 0),
                cache_hit_tokens=u.get("cache_hit_tokens", 0),
                cache_miss_tokens=u.get("cache_miss_tokens", 0),
            )
            self.session.commit()
        except LLMNotConfiguredError:
            question.status = "failed"
            question.error_msg = "DEEPSEEK_API_KEY 未配置"
            self.session.add(question)
            self.session.commit()
            raise
        except LLMCallError as e:
            question.status = "failed"
            question.error_msg = str(e)[:500]
            self.session.add(question)
            self.session.commit()
            raise

        self.session.add(question)
        self.session.commit()
        self.session.refresh(question)
        return question, False

    def get(self, question_id: int) -> Question | None:
        return self.session.get(Question, question_id)

    def list_by_user(
        self, user_id: int, limit: int = 20, offset: int = 0
    ) -> list[Question]:
        stmt = (
            select(Question)
            .where(Question.user_id == user_id)
            .order_by(Question.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.exec(stmt))
