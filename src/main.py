# src/main.py

import asyncio
import signal
from pathlib import Path

import structlog
import typer

from src.settings import settings
from src.pipeline.score import run_score
from src.pipeline.digest import run_digest
from src.utils.logging import setup_logging

setup_logging()
log = structlog.get_logger(__name__)

app = typer.Typer(help="Trend Radar CLI")


@app.command()
def run() -> None:
    """Production: бот + scheduler в одном event loop."""
    asyncio.run(_run_async())


async def _run_async() -> None:
    from src.bot.bot import build_bot
    from src.scheduler import build_scheduler

    scheduler = build_scheduler()
    bot, dp = build_bot()

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _request_stop() -> None:
        log.info("shutdown.signal_received")
        stop_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _request_stop)
        except NotImplementedError:
            pass

    scheduler.start()
    log.info("scheduler.started", jobs=[j.id for j in scheduler.get_jobs()])

    polling_task = asyncio.create_task(dp.start_polling(bot), name="bot_polling")
    stop_task = asyncio.create_task(stop_event.wait(), name="stop_waiter")

    try:
        await asyncio.wait(
            {polling_task, stop_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
    finally:
        log.info("shutdown.begin")

        # Каждый шаг в своём try — чтобы сбой одного не сорвал остальную очистку.
        try:
            scheduler.shutdown(wait=True)
        except Exception as e:
            log.warning("shutdown.scheduler_error", error=str(e))

        # stop_polling кидает RuntimeError, если polling не стартовал (падение на bot.me()).
        try:
            await dp.stop_polling()
        except RuntimeError:
            pass
        except Exception as e:
            log.warning("shutdown.stop_polling_error", error=str(e))

        if not polling_task.done():
            polling_task.cancel()
        await asyncio.gather(polling_task, stop_task, return_exceptions=True)

        # Критично: закрыть сессию, иначе Telegram держит getUpdates → Conflict.
        try:
            await bot.session.close()
        except Exception as e:
            log.warning("shutdown.session_close_error", error=str(e))

        log.info("shutdown.done")


@app.command()
def collect() -> None:
    """Сбор постов из всех активных источников."""
    from src.pipeline.collect import run_collect

    stats = asyncio.run(run_collect())
    typer.echo("Collect finished:")
    for name, count in stats.items():
        typer.echo(f"  {name}: +{count} new")


@app.command()
def score(limit: int = typer.Option(50, "--limit", help="Макс. постов за запуск")) -> None:
    """Оценить непросмотренные посты через LLM."""
    result = asyncio.run(run_score(limit=limit))
    typer.echo(result)


@app.command()
def digest(
    days: int = typer.Option(7, "--days", help="Период в днях"),
    min_relevance: int = typer.Option(6, "--min-relevance", help="Минимальный relevance_score"),
    manual: bool = typer.Option(False, "--manual", help="Пометить как manual-запуск"),
) -> None:
    """Собрать дайджест за период и сохранить в БД."""
    digest_id = asyncio.run(
        run_digest(
            days=days,
            min_relevance=min_relevance,
            exclude_delivered=True,
            is_manual=manual,
        )
    )
    if digest_id is None:
        typer.echo("Nothing to digest.")
    else:
        typer.echo(f"Digest created: id={digest_id}")


@app.command()
def bot() -> None:
    """Запустить только Telegram-бот (без scheduler)."""
    from src.bot.bot import run_bot
    asyncio.run(run_bot())


@app.command("tg_login")
def tg_login() -> None:
    """Разовая интерактивная авторизация Telethon для чтения каналов."""
    asyncio.run(_tg_login_async())


async def _tg_login_async() -> None:
    from telethon import TelegramClient
    from src.sources.telegram import TELETHON_SESSION_PATH

    if not settings.TG_API_ID or not settings.TG_API_HASH:
        raise typer.BadParameter("Set TG_API_ID and TG_API_HASH before tg_login.")

    Path(TELETHON_SESSION_PATH).parent.mkdir(parents=True, exist_ok=True)
    client = TelegramClient(
        TELETHON_SESSION_PATH,
        settings.TG_API_ID,
        settings.TG_API_HASH,
    )
    try:
        await client.start()
        me = await client.get_me()
        username = getattr(me, "username", None) or getattr(me, "id", "unknown")
        typer.echo(f"Telethon session is ready for {username}.")
    finally:
        await client.disconnect()


@app.command()
def deliver(digest_id: int = typer.Option(..., "--digest-id")) -> None:
    """Ручная доставка существующего дайджеста."""
    from src.pipeline.deliver import deliver_digest
    asyncio.run(deliver_digest(digest_id))


if __name__ == "__main__":
    app()
