from __future__ import annotations

import asyncio
import logging

import nonebot
from fastapi.staticfiles import StaticFiles
from nonebot import get_driver
from nonebot.drivers.fastapi import Driver as FastAPIDriver
from starlette.middleware.sessions import SessionMiddleware

from src.admin.routes import router as admin_router
from src.infrastructure.settings.container import ensure_container
from src.infrastructure.settings.loader import load_settings


settings = load_settings()


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


configure_logging()
nonebot.init(
    driver="~fastapi",
    host=settings.runtime.host,
    port=settings.runtime.port,
)
driver = get_driver()
if not isinstance(driver, FastAPIDriver):
    raise RuntimeError("FastAPI driver is required.")

app = driver.server_app
app.state.settings = settings
app.add_middleware(SessionMiddleware, secret_key=settings.runtime.secret_key)
app.include_router(admin_router)
app.mount("/admin/static", StaticFiles(directory=str(settings.static_dir)), name="admin-static")


driver = get_driver()


@driver.on_startup
async def _on_startup() -> None:
    from src.plugins.scheduler import recover_missing_daily_lessons_for_today, register_jobs

    container = await ensure_container(settings)
    register_jobs()
    asyncio.create_task(recover_missing_daily_lessons_for_today())
    logging.getLogger(__name__).info("container initialized, feishu_app_id=%s", settings.runtime.feishu_app_id)

    if settings.runtime.feishu_app_id and settings.static.feishu.enabled:
        from src.infrastructure.channels.feishu_bot import FeishuBot

        feishu_bot = FeishuBot(
            app_id=settings.runtime.feishu_app_id,
            app_secret=settings.runtime.feishu_app_secret,
            enabled_chat_ids=settings.static.feishu.enabled_group_ids or None,
        )
        feishu_bot.start()


def run() -> None:
    driver.run(host=settings.runtime.host, port=settings.runtime.port)


if __name__ == "__main__":
    run()
