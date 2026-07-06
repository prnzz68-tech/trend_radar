from src.llm.client import get_client


import json
from string import Template
from pathlib import Path

import structlog

from src.llm.client import get_client
from src.schemas.digest import DigestInput, DigestOutput
from src.settings import settings

logger = structlog.get_logger(__name__)

PROMPT_PATH = Path("config/prompts/build_digest.md")
CHUNK_THRESHOLD = 80


def _split_prompt(raw: str) -> tuple[str, str]:
    """Разделить промпт на system/user по маркерам '# System' и '# User'."""
    parts = raw.split("# User", 1)
    system = parts[0].replace("# System", "").strip()
    user = parts[1].strip() if len(parts) > 1 else ""
    return system, user


def _render(system_tpl: str, user_tpl: str, input_: DigestInput, posts_subset) -> tuple[str, str]:
    posts_json = json.dumps(
        [p.model_dump(mode="json") for p in posts_subset],
        ensure_ascii=False,
        indent=2,
    )
    mapping = {
        "profile": input_.profile,
        "period_start": input_.period_start.strftime("%Y-%m-%d"),
        "period_end": input_.period_end.strftime("%Y-%m-%d"),
        "posts_json": posts_json,
    }
    return (
        Template(system_tpl).safe_substitute(mapping),
        Template(user_tpl).safe_substitute(mapping),
    )


async def build_digest(input_: DigestInput) -> DigestOutput:
    raw = PROMPT_PATH.read_text(encoding="utf-8")
    system_tpl, user_tpl = _split_prompt(raw)

    client = get_client()
    model = settings.OPENAI_MODEL_DIGEST

    if len(input_.posts) <= CHUNK_THRESHOLD:
        system, user = _render(system_tpl, user_tpl, input_, input_.posts)
        text, tokens = await client.complete_text(system=system, user=user, model=model)
        logger.info("digest_built", posts=len(input_.posts), tokens=tokens)
        return DigestOutput(content_md=text.strip())

    # Нарезка по категориям при большом объёме (Этап 1: idea по opportunity)
    logger.info("digest_chunked", total=len(input_.posts))
    groups = {
        "pain": [p for p in input_.posts if p.category == "pain" or p.problem],
        "idea": [
            p for p in input_.posts
            if p.category in ("case", "idea") or p.opportunity
        ],
        "high_engagement": [
            p for p in input_.posts
            if (p.engagement is not None and p.engagement >= 50)
            or (p.rating is not None and p.rating >= 50)
            or p.relevance_score >= 9
        ],
        "trends": input_.posts,  # для трендов нужна полная выборка
    }

    parts: list[str] = []
    for name, subset in groups.items():
        if not subset:
            continue
        system, user = _render(system_tpl, user_tpl, input_, subset)
        text, _ = await client.complete_text(system=system, user=user, model=model)
        parts.append(text.strip())

    return DigestOutput(content_md="\n\n".join(parts))