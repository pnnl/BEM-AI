from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined


BASE_DIR = Path(__file__).resolve().parents[1]
SKILLS_DIR = BASE_DIR / "skills"
SPEC_DIR = SKILLS_DIR / "specs" / "hvac"
TEMPLATE_PATH = SKILLS_DIR / "templates" / "hvac_child_skill.md.j2"


@dataclass(frozen=True)
class GeneratedSkill:
    name: str
    output_path: Path
    content: str


def _load_spec(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "name" not in data:
        raise ValueError(f"Invalid HVAC child skill spec: {path}")
    return data


def _load_specs(spec_dir: Path) -> list[dict[str, Any]]:
    if not spec_dir.is_dir():
        raise ValueError(f"HVAC child skill spec directory does not exist: {spec_dir}")

    specs: list[dict[str, Any]] = []
    for path in sorted(spec_dir.glob("*.yaml")):
        spec = _load_spec(path)
        spec["_spec_path"] = str(path)
        specs.append(spec)

    if not specs:
        raise ValueError(f"No HVAC child skill specs found in: {spec_dir}")

    return specs


def _build_environment(template_path: Path) -> Environment:
    return Environment(
        loader=FileSystemLoader(str(template_path.parent)),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        trim_blocks=False,
        lstrip_blocks=False,
    )


def _normalize_extra_sections(raw_sections: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    sections: list[dict[str, str]] = []
    for section in raw_sections or []:
        fmt = str(section.get("format", "markdown"))
        body = section.get("body", "")
        if fmt == "json":
            body = json.dumps(body, indent=2, ensure_ascii=True)
        elif not isinstance(body, str):
            raise ValueError(f"Markdown extra section body must be string, got {type(body)!r}")
        sections.append(
            {
                "title": str(section["title"]),
                "format": fmt,
                "body": body,
            }
        )
    return sections


def render_generated_skills(
    spec_dir: Path = SPEC_DIR,
    template_path: Path = TEMPLATE_PATH,
    output_dir: Path = SKILLS_DIR,
) -> list[GeneratedSkill]:
    specs = _load_specs(spec_dir)
    env = _build_environment(template_path)
    template = env.get_template(template_path.name)

    generated: list[GeneratedSkill] = []
    for raw_skill in specs:
        skill = dict(raw_skill)
        skill.setdefault("version", "0.1.0")
        skill.setdefault("output_format", "markdown_with_json_state_patch")
        skill.setdefault("sdk_methods_intro", "")
        skill.setdefault("conditional_required_state", [])
        skill.setdefault("extra_sections", [])
        skill["state_patch_json"] = json.dumps(skill["state_patch"], indent=2, ensure_ascii=True)
        skill["extra_sections"] = _normalize_extra_sections(skill.get("extra_sections"))
        content = template.render(skill=skill)
        generated.append(
            GeneratedSkill(
                name=skill["name"],
                output_path=output_dir / f"{skill['name']}.md",
                content=content,
            )
        )
    return generated


def load_managed_skill_names(spec_dir: Path = SPEC_DIR) -> set[str]:
    return {str(item["name"]) for item in _load_specs(spec_dir)}


def write_generated_skills(generated: list[GeneratedSkill], *, check: bool) -> int:
    mismatches: list[str] = []
    for skill in generated:
        if check:
            existing = skill.output_path.read_text(encoding="utf-8") if skill.output_path.exists() else None
            if existing != skill.content:
                mismatches.append(str(skill.output_path))
            continue
        skill.output_path.write_text(skill.content, encoding="utf-8")

    if mismatches:
        mismatch_text = "\n".join(mismatches)
        raise SystemExit(
            "Generated HVAC child skills are out of sync:\n"
            f"{mismatch_text}\n"
            "Run generate_hvac_child_skills.py without --check to update them."
        )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate OpenStudio AI HVAC child skill markdown files from a YAML spec."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if generated content does not match committed child skills.",
    )
    parser.add_argument(
        "--spec-dir",
        type=Path,
        default=SPEC_DIR,
        help="Directory containing one YAML file per HVAC child skill spec.",
    )
    parser.add_argument(
        "--template",
        type=Path,
        default=TEMPLATE_PATH,
        help="Path to the Jinja child-skill template.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=SKILLS_DIR,
        help="Directory where generated child skills are written.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    generated = render_generated_skills(
        spec_dir=args.spec_dir.resolve(),
        template_path=args.template.resolve(),
        output_dir=args.output_dir.resolve(),
    )
    return write_generated_skills(generated, check=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
