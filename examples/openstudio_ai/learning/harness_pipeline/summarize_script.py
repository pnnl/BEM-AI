from __future__ import annotations


def summarize_script(script_text: str) -> dict[str, str | int]:
    return {
        "summary": "Candidate reusable OpenStudio script captured from runtime use.",
        "line_count": len(script_text.splitlines()),
        "script_excerpt": script_text[:1200],
    }

