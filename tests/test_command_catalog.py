from src.plugins.command_catalog import is_fixed_command_text, match_fixed_command, render_help_text


def test_match_fixed_command_exact_and_prefix() -> None:
    assert match_fixed_command("报名学习") is None
    assert match_fixed_command(" 提交任务 12 hello ") == "提交任务"
    assert match_fixed_command("答题 3 1:A 2:B") == "答题"
    assert match_fixed_command("添加新词 resilient backlog") == "添加新词"
    assert match_fixed_command("今天天气不错") is None


def test_is_fixed_command_text() -> None:
    assert is_fixed_command_text("帮助")
    assert is_fixed_command_text("本周总结")
    assert not is_fixed_command_text("@机器人 今天天气不错")


def test_render_help_text_mentions_fixed_commands_and_at_usage() -> None:
    text = render_help_text()
    assert "报名学习" not in text
    assert "帮助" in text
    assert "添加新词" in text
    assert "@机器人 只用于翻译" in text
