"""Loading and parsing utilities for project drafting directives."""

import logging
from pathlib import Path


logger = logging.getLogger(__name__)


def load_directives(path: Path) -> str:
    """
    Read a directives Markdown file.

    Returns an empty string when the file does not exist so draft generation
    can continue without project-specific directives.
    """

    if not path.exists():
        logger.warning("Directives file not found: %s", path)
        return ""

    content = path.read_text(encoding="utf-8")
    logger.info("Directives loaded from %s", path)
    return content


def extract_section_directive(
    directives: str,
    section_name: str,
) -> str:
    """
    Extract the directive block associated with a proposal section.

    Falls back to the global directives when no matching section exists.
    """

    if not directives:
        return ""

    section_lines: list[str] = []
    inside_section = False
    search_term = section_name.lower()

    for line in directives.splitlines():
        stripped = line.strip().lower()

        if not inside_section:
            if stripped.startswith("#") and search_term in stripped:
                inside_section = True
                section_lines.append(line)
            continue

        if stripped.startswith("#"):
            break

        section_lines.append(line)

    if section_lines:
        logger.debug(
            "Section directive found for: '%s'",
            section_name,
        )
        return "\n".join(section_lines)

    logger.debug(
        "No specific directive for '%s'; using global directives",
        section_name,
    )
    return extract_global_directives(directives)


def extract_global_directives(directives: str) -> str:
    """
    Extract directives that apply to every generated section.

    The current directives format expects:
    - 1. Tone and Style
    - 4. Global Restrictions
    - 5. Call Notes
    """

    global_sections = (
        "1. tone and style",
        "4. global restrictions",
        "5. call notes",
    )

    result: list[str] = []
    inside_section = False
    current_level: int | None = None

    for line in directives.splitlines():
        stripped = line.strip().lower()

        if stripped.startswith("#"):
            if any(section in stripped for section in global_sections):
                inside_section = True
                current_level = len(line) - len(line.lstrip("#"))
                result.append(line)
                continue

            if inside_section:
                new_level = len(line) - len(line.lstrip("#"))

                if current_level is not None and new_level <= current_level:
                    inside_section = False
                    current_level = None
                    continue

        if inside_section:
            result.append(line)

    return "\n".join(result)


def extract_call_context(directives: str) -> str:
    """
    Extract section 2 of the directives file as call-level context.
    """

    result: list[str] = []
    inside_section = False

    for line in directives.splitlines():
        stripped = line.strip()

        if stripped.startswith("# 2."):
            inside_section = True
            continue

        if (
            inside_section
            and stripped.startswith("# ")
            and not stripped.startswith("# 2.")
        ):
            break

        if inside_section:
            result.append(line)

    return "\n".join(result)