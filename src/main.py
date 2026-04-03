from __future__ import annotations

import logging
from pathlib import Path

import nonebot
from fastapi.staticfiles import StaticFiles
from nonebot import get_driver, load_plugin
from nonebot.drivers.fastapi import Driver as FastAPIDriver
from starlette.middleware.sessions import SessionMiddleware

from src.admin.routes import router as admin_router
from src.infrastructure.settings.container import build_container
from src.infrastructure.settings.loader import load_settings
from src.plugins.scheduler import register_jobs


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
    onebot_access_token=settings.runtime.access_token,
)
driver = get_driver()
if not isinstance(driver, FastAPIDriver):
    raise RuntimeError("FastAPI driver is required.")

app = driver.server_app
app.add_middleware(SessionMiddleware, secret_key=settings.runtime.secret_key)
app.include_router(admin_router)
app.mount("/admin/static", StaticFiles(directory=str(settings.static_dir)), name="admin-static")

load_plugin("src.plugins.at_message")
load_plugin("src.plugins.commands")


@app.on_event("startup")
async def on_startup() -> None:
    await build_container(settings)
    register_jobs()


def run() -> None:
    nonebot.run(app="src.main:app")


if __name__ == "__main__":
    run()

