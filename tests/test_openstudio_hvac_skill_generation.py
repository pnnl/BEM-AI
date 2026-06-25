from __future__ import annotations

from examples.openstudio_ai.scripts.generate_hvac_child_skills import (
    SPEC_DIR,
    load_managed_skill_names,
    render_generated_skills,
)


def test_openstudio_hvac_child_skill_generator_is_in_sync() -> None:
    generated = render_generated_skills()

    for skill in generated:
        assert skill.output_path.exists(), f"Missing generated skill: {skill.output_path}"
        assert skill.output_path.read_text(encoding="utf-8") == skill.content


def test_openstudio_hvac_child_skill_spec_matches_generated_file_names() -> None:
    expected_names = load_managed_skill_names()
    generated_names = {skill.name for skill in render_generated_skills()}

    assert expected_names == generated_names


def test_openstudio_hvac_child_skill_specs_exist_per_managed_skill() -> None:
    expected_names = load_managed_skill_names()
    spec_names = {path.stem for path in SPEC_DIR.glob("*.yaml")}

    assert expected_names == spec_names
