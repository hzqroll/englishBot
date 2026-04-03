from __future__ import annotations

from pathlib import Path

import yaml

from src.infrastructure.settings.models import (
    AppRuntimeSettings,
    EffectiveSettings,
    StaticConfig,
)


def load_settings(project_root: Path | None = None) -> EffectiveSettings:
    project_root = project_root or Path(__file__).resolve().parents[3]
    runtime = AppRuntimeSettings()
    config_path = Path(runtime.config_path)
    if not config_path.is_absolute():
        config_path = project_root / config_path

    static_payload: dict = {}
    if config_path.exists():
        static_payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}

    static = StaticConfig.model_validate(static_payload)
    return EffectiveSettings(
        runtime=runtime,
        static=static,
        project_root=project_root,
        template_dir=project_root / "src" / "admin" / "templates",
        static_dir=project_root / "src" / "admin" / "static",
    )

