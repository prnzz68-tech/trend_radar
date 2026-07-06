from pathlib import Path
from string import Template

from src.llm.client import get_client
from src.schemas.post import PostForScoring
from src.schemas.score import PostScore
from src.settings import settings

_PROMPTS_DIR = Path("config/prompts")
_MAX_CONTENT_CHARS = 4000

_profile_cache: str | None = None
_template_cache: Template | None = None
_system_cache: str | None = None
_user_template_cache: Template | None = None


def _load_prompts() -> tuple[str, Template]:
    """Возвращает (system_prompt, user_template). Парсит score_post.md по маркерам."""
    global _profile_cache, _system_cache, _user_template_cache

    if _system_cache is not None and _user_template_cache is not None and _profile_cache is not None:
        return _system_cache, _user_template_cache

    _profile_cache = (_PROMPTS_DIR / "user_profile.md").read_text(encoding="utf-8")
    raw = (_PROMPTS_DIR / "score_post.md").read_text(encoding="utf-8")

    # Маркеры <!-- SYSTEM --> и <!-- USER -->
    sys_marker = "<!-- SYSTEM -->"
    usr_marker = "<!-- USER -->"
    if sys_marker not in raw or usr_marker not in raw:
        raise RuntimeError("score_post.md: missing SYSTEM/USER markers")

    after_sys = raw.split(sys_marker, 1)[1]
    system_part, user_part = after_sys.split(usr_marker, 1)
    _system_cache = system_part.strip()
    _user_template_cache = Template(user_part.strip())
    return _system_cache, _user_template_cache


async def score_post(post: PostForScoring) -> tuple[PostScore, int]:
    system, user_tpl = _load_prompts()
    profile = _profile_cache or ""

    content = post.content[:_MAX_CONTENT_CHARS]
    user = user_tpl.safe_substitute(
        profile=profile,
        source_name=post.source_name,
        title=post.title,
        author=post.author or "—",
        engagement=post.engagement if post.engagement is not None else "—",  # Этап 1
        content=content,
    )

    client = get_client()
    score, tokens = await client.complete_json(
        system=system,
        user=user,
        model=settings.OPENAI_MODEL_SCORE,
        response_schema=PostScore,
    )
    return score, tokens