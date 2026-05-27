from __future__ import annotations

from src.infrastructure.settings.models import StaticConfig


def test_prompts_settings_support_dialogue_guardian_fields() -> None:
    config = StaticConfig.model_validate(
        {
            "prompts": {
                "dialogue_story_opener_prompt": "Story with {lesson_title}",
                "dialogue_idle_followup_prompt": "Follow up on {latest_message}",
            }
        }
    )

    assert config.prompts.dialogue_story_opener_prompt == "Story with {lesson_title}"
    assert config.prompts.dialogue_idle_followup_prompt == "Follow up on {latest_message}"


def test_prompts_settings_dialogue_guardian_defaults_not_empty() -> None:
    config = StaticConfig()
    assert "Theme title: {lesson_title}" in config.prompts.dialogue_story_opener_prompt
    assert "Latest message: {latest_message}" in config.prompts.dialogue_idle_followup_prompt
