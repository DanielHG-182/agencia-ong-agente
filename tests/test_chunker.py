import pytest

import scripts.chunker as chunker


def test_parse_sections_detects_heading_structure():
    markdown = """
# Project

Intro text.

## Objectives

Objective text.

### Specific Objective

Specific objective content.
"""

    sections = chunker.parse_sections(markdown)

    assert len(sections) == 3

    assert sections[0]["level"] == 1
    assert sections[0]["title"] == "Project"

    assert sections[1]["level"] == 2
    assert sections[1]["title"] == "Objectives"

    assert sections[2]["level"] == 3
    assert sections[2]["title"] == "Specific Objective"


def test_chunk_document_creates_single_chunk_for_short_section():
    markdown = """
## Objectives

This is a short section describing the project objectives.
"""

    chunks = chunker.chunk_document(markdown, "proposal.md")

    assert len(chunks) == 1

    result = chunks[0]

    assert result.section_title == "Objectives"
    assert result.section_level == 2
    assert result.part == 1
    assert result.total_parts == 1
    assert result.is_continuation is False
    assert result.parent_id is None
    assert result.source_file == "proposal.md"


def test_chunk_document_skips_empty_container_and_propagates_parent():
    markdown = """
## Work Packages

### WP1

Content for work package one.
"""

    chunks = chunker.chunk_document(markdown, "proposal.md")

    assert len(chunks) == 1

    result = chunks[0]

    assert result.section_title == "WP1"
    assert result.parent_section == "Work Packages"
    assert result.parent_section_level == 2


def test_split_by_paragraphs_splits_long_content(monkeypatch):
    monkeypatch.setattr(chunker, "estimate_tokens", lambda text: len(text.split()))

    content = (
        "one two three four\n\n"
        "five six seven eight\n\n"
        "nine ten eleven twelve"
    )

    parts = chunker.split_by_paragraphs(
        content,
        max_tokens=5,
        overlap_tokens=0,
    )

    assert len(parts) == 3
    assert parts[0] == "one two three four"
    assert parts[1] == "five six seven eight"
    assert parts[2] == "nine ten eleven twelve"


def test_split_by_paragraphs_adds_overlap(monkeypatch):
    monkeypatch.setattr(chunker, "estimate_tokens", lambda text: len(text.split()))

    content = (
        "one two\n\n"
        "three four\n\n"
        "five six"
    )

    parts = chunker.split_by_paragraphs(
        content,
        max_tokens=4,
        overlap_tokens=2,
    )

    assert len(parts) == 2
    assert parts[0] == "one two\n\nthree four"
    assert parts[1] == "three four\n\nfive six"


def test_chunk_document_splits_oversized_section(monkeypatch):
    monkeypatch.setattr(chunker, "MAX_TOKENS", 5)
    monkeypatch.setattr(chunker, "OVERLAP_TOKENS", 0)
    monkeypatch.setattr(chunker, "estimate_tokens", lambda text: len(text.split()))

    markdown = """
## Objectives

one two three four

five six seven eight

nine ten eleven twelve
"""

    chunks = chunker.chunk_document(markdown, "proposal.md")

    assert len(chunks) == 3

    assert [chunk.part for chunk in chunks] == [1, 2, 3]
    assert all(chunk.total_parts == 3 for chunk in chunks)

    assert chunks[0].is_continuation is False
    assert chunks[1].is_continuation is True
    assert chunks[2].is_continuation is True

    assert all(chunk.parent_id is not None for chunk in chunks)
    assert len({chunk.parent_id for chunk in chunks}) == 1


def test_table_is_kept_in_single_chunk_even_when_oversized(monkeypatch):
    monkeypatch.setattr(chunker, "MAX_TOKENS", 5)
    monkeypatch.setattr(chunker, "estimate_tokens", lambda text: len(text.split()))

    markdown = """
## Budget

<!-- TABLE:
one two three four five six seven eight nine ten
END TABLE -->
"""

    chunks = chunker.chunk_document(markdown, "proposal.md")

    assert len(chunks) == 1

    result = chunks[0]

    assert result.has_table is True
    assert result.oversized_by_table is True
    assert result.total_parts == 1


def test_chunk_navigation_links_are_wired(monkeypatch):
    monkeypatch.setattr(chunker, "MAX_TOKENS", 5)
    monkeypatch.setattr(chunker, "OVERLAP_TOKENS", 0)
    monkeypatch.setattr(chunker, "estimate_tokens", lambda text: len(text.split()))

    markdown = """
## Objectives

one two three four

five six seven eight

nine ten eleven twelve
"""

    chunks = chunker.chunk_document(markdown, "proposal.md")

    assert chunks[0].prev_chunk_id is None
    assert chunks[0].next_chunk_id == chunks[1].chunk_id

    assert chunks[1].prev_chunk_id == chunks[0].chunk_id
    assert chunks[1].next_chunk_id == chunks[2].chunk_id

    assert chunks[2].prev_chunk_id == chunks[1].chunk_id
    assert chunks[2].next_chunk_id is None