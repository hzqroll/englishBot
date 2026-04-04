from __future__ import annotations

import logging
from pathlib import Path

import nonebot
from fastapi.staticfiles import StaticFiles
from nonebot import get_driver, load_plugin
from nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter
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
    onebot_access_token=settings.runtime.access_token,
)
driver = get_driver()
if not isinstance(driver, FastAPIDriver):
    raise RuntimeError("FastAPI driver is required.")
driver.register_adapter(OneBotV11Adapter)

app = driver.server_app
app.state.settings = settings
app.add_middleware(SessionMiddleware, secret_key=settings.runtime.secret_key)
app.include_router(admin_router)
app.mount("/admin/static", StaticFiles(directory=str(settings.static_dir)), name="admin-static")

load_plugin("src.plugins.at_message")
load_plugin("src.plugins.commands")


@app.on_event("startup")
async def on_startup() -> None:
    from src.plugins.scheduler import register_jobs

    await ensure_container(settings)
    register_jobs()


def run() -> None:
    driver.run(host=settings.runtime.host, port=settings.runtime.port)


if __name__ == "__main__":
    run()
