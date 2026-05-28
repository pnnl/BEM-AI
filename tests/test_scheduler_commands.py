from __future__ import annotations

from automa_ai.scheduler import (
    CancelCommand,
    LoopCommand,
    TasksCommand,
    load_default_loop_prompt,
    parse_scheduler_command,
)


def test_parse_scheduler_command_supports_loop_variants() -> None:
    assert parse_scheduler_command("/loop") == LoopCommand(
        interval=None,
        prompt=None,
    )
    assert parse_scheduler_command(
        '/loop --interval 5m --prompt "check the job queue"'
    ) == LoopCommand(
        interval="5m",
        prompt="check the job queue",
    )
    assert parse_scheduler_command(
        "/loop -i every 10 minutes -p check the job queue"
    ) == LoopCommand(
        interval="every 10 minutes",
        prompt="check the job queue",
    )
    assert parse_scheduler_command("/loop keep working") == LoopCommand(
        interval=None,
        prompt="keep working",
    )


def test_parse_scheduler_command_treats_unflagged_text_as_prompt_only() -> None:
    assert parse_scheduler_command("/loop 5m check the job queue") == LoopCommand(
        interval=None,
        prompt="5m check the job queue",
    )


def test_parse_scheduler_command_rejects_invalid_loop_options() -> None:
    try:
        parse_scheduler_command("/loop --interval soon --prompt check")
    except ValueError as exc:
        assert str(exc) == "invalid /loop interval: soon"
    else:
        raise AssertionError("expected ValueError")

    try:
        parse_scheduler_command("/loop --interval 5m check")
    except ValueError as exc:
        assert str(exc) == "invalid /loop interval: 5m check"
    else:
        raise AssertionError("expected ValueError")


def test_parse_scheduler_command_supports_tasks_and_cancel() -> None:
    assert parse_scheduler_command("/tasks") == TasksCommand()
    assert parse_scheduler_command("/cancel abc123") == CancelCommand(task_id="abc123")
    assert parse_scheduler_command("hello") is None


def test_parse_scheduler_command_rejects_cancel_without_task_id() -> None:
    try:
        parse_scheduler_command("/cancel")
    except ValueError as exc:
        assert str(exc) == "/cancel requires a task id"
    else:
        raise AssertionError("expected ValueError")


def test_load_default_loop_prompt_prefers_project_scope(tmp_path) -> None:
    project_prompt = tmp_path / "project" / ".automa" / "loop.md"
    home_prompt = tmp_path / "home" / ".automa" / "loop.md"
    project_prompt.parent.mkdir(parents=True)
    home_prompt.parent.mkdir(parents=True)
    project_prompt.write_text("project prompt", encoding="utf-8")
    home_prompt.write_text("home prompt", encoding="utf-8")

    assert (
        load_default_loop_prompt(
            project_root=project_prompt.parents[1],
            home_dir=home_prompt.parents[1],
        )
        == "project prompt"
    )
