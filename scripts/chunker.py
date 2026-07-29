"""
chunker.py
Splits processed Markdown files into semantic chunks with metadata.

Strategy:
  - Primary split: by Markdown headings (H1 > H2 > H3)
  - Secondary split: by paragraphs if chunk exceeds MAX_TOKENS
  - Tables are never split (oversized_by_table flag)
  - Empty H2 containers propagate as parent metadata to H3 children
"""

import re
import os
import json
import hashlib
import logging
from pathlib import Path
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────

MAX_TOKENS   = int(os.getenv("CHUNK_MAX_TOKENS", 1024))
OVERLAP_TOKENS = int(os.getenv("CHUNK_OVERLAP_TOKENS", 150))


# ─────────────────────────────────────────────────────────
# DATA STRUCTURES
# ─────────────────────────────────────────────────────────

@dataclass
class Chunk:
    # Identity
    chunk_id:           str
    parent_id:          str | None      # None if not split
    part:               int             # 1 if not split
    total_parts:        int             # 1 if not split
    is_continuation:    bool            # True from part 2 onwards

    # Origin
    source_file:        str
    section_title:      str
    section_level:      int
    parent_section:     str | None      # H2 title if this chunk is H3
    parent_section_level: int | None

    # Content
    content:            str
    token_count:        int
    has_table:          bool
    oversized_by_table: bool            # True if over limit but kept whole for table

    # Navigation
    prev_chunk_id:      str | None = field(default=None)
    next_chunk_id:      str | None = field(default=None)


# ─────────────────────────────────────────────────────────
# TOKEN ESTIMATION
# ─────────────────────────────────────────────────────────

def estimate_tokens(text: str) -> int:
    """
    Approximates token count without loading a tokenizer.
    Rule of thumb: 1 token ≈ 4 characters in English/Spanish.
    Good enough for chunking decisions.
    """
    return len(text) // 4


# ─────────────────────────────────────────────────────────
# MARKDOWN PARSING
# ─────────────────────────────────────────────────────────

# Matches heading lines: # Title, ## Title, ### Title
HEADING_RE = re.compile(r'^(#{1,4})\s+(.+)', re.MULTILINE)
TABLE_RE   = re.compile(r'<!--\s*TABLE:.*?END TABLE\s*-->', re.DOTALL)


def has_table(text: str) -> bool:
    return bool(TABLE_RE.search(text))


def parse_sections(markdown: str) -> list[dict]:
    """
    Splits a Markdown string into sections based on headings.
    Each section contains:
        level: int, title: str, content: str, has_direct_content: bool
    """
    sections = []
    matches  = list(HEADING_RE.finditer(markdown))

    for i, match in enumerate(matches):
        level = len(match.group(1))
        title = match.group(2).strip()

        # Content is everything between this heading and the next
        start = match.end()
        end   = matches[i + 1].start() if i + 1 < len(matches) else len(markdown)
        content = markdown[start:end].strip()

        # Detect if this section has direct text (not just sub-headings)
        # Remove sub-headings and check if anything remains
        content_without_subheadings = HEADING_RE.sub("", content).strip()
        has_direct_content = bool(content_without_subheadings)

        sections.append({
            "level":               level,
            "title":               title,
            "content":             content,
            "has_direct_content":  has_direct_content,
        })

    return sections


# ─────────────────────────────────────────────────────────
# SECONDARY SPLIT (paragraph-based)
# ─────────────────────────────────────────────────────────

def split_by_paragraphs(content: str, max_tokens: int, overlap_tokens: int) -> list[str]:
    """
    Splits a large text block into smaller parts by paragraphs.
    Adds overlap between consecutive parts to preserve continuity.
    Tables are never cut — if a paragraph contains a table, it is
    kept whole even if it exceeds max_tokens.
    """
    paragraphs = [p.strip() for p in re.split(r'\n{2,}', content) if p.strip()]
    parts      = []
    current    = []
    current_tokens = 0

    for para in paragraphs:
        para_tokens  = estimate_tokens(para)
        para_has_tbl = has_table(para)

        # If adding this paragraph exceeds the limit
        if current_tokens + para_tokens > max_tokens and current:
            parts.append("\n\n".join(current))

            # Overlap: keep last N tokens worth of paragraphs
            overlap_text   = []
            overlap_so_far = 0
            for prev_para in reversed(current):
                prev_tokens = estimate_tokens(prev_para)
                if overlap_so_far + prev_tokens <= overlap_tokens:
                    overlap_text.insert(0, prev_para)
                    overlap_so_far += prev_tokens
                else:
                    break

            current        = overlap_text
            current_tokens = overlap_so_far

        current.append(para)
        current_tokens += para_tokens

        # If a single paragraph with a table is already oversized,
        # flush it immediately as its own part
        if para_has_tbl and current_tokens > max_tokens:
            parts.append("\n\n".join(current))
            current        = []
            current_tokens = 0

    if current:
        parts.append("\n\n".join(current))

    return parts


# ─────────────────────────────────────────────────────────
# CHUNK ID GENERATION
# ─────────────────────────────────────────────────────────

def make_chunk_id(source_file: str, title: str, part: int) -> str:
    """
    Generates a short deterministic ID from source + title + part.
    Example: "proyecto_2022_metodologia_1"
    """
    base = f"{source_file}_{title}_{part}"
    hash_suffix = hashlib.sha256(base.encode()).hexdigest()[:6]
    slug = re.sub(r'[^a-z0-9]+', '_', base.lower())[:40]
    return f"{slug}_{hash_suffix}"


# ─────────────────────────────────────────────────────────
# MAIN CHUNKER
# ─────────────────────────────────────────────────────────

def chunk_document(markdown: str, source_file: str) -> list[Chunk]:
    """
    Main entry point for chunking a single Markdown document.
    Returns a flat list of Chunk objects with full metadata.
    """
    sections = parse_sections(markdown)
    chunks: list[Chunk] = []

    # Track the current H1/H2 context to propagate as parent
    current_h1: str | None = None
    current_h2: str | None = None

    for section in sections:
        level   = section["level"]
        title   = section["title"]
        content = section["content"]

        # Update heading context
        if level == 1:
            current_h1 = title
            current_h2 = None
        elif level == 2:
            current_h2 = title

        # H1,H2,H3 etc... with no direct content → container only, skip chunk creation
        if not section["has_direct_content"]:
            logger.debug(f"H2 container (no direct content): '{title}' — propagating as parent")
            continue

        # Determine parent context for this chunk
        if level == 3:
            parent_section       = current_h2
            parent_section_level = 2 if current_h2 else None
        elif level == 2:
            parent_section       = current_h1
            parent_section_level = 1 if current_h1 else None
        else:
            parent_section       = None
            parent_section_level = None

        # Check if content fits in a single chunk
        token_count    = estimate_tokens(content)
        section_has_tbl = has_table(content)

        if token_count <= MAX_TOKENS or section_has_tbl:
            # Single chunk — no split needed
            # (tables kept whole even if oversized)
            chunk_id = make_chunk_id(source_file, title, 1)
            chunks.append(Chunk(
                chunk_id             = chunk_id,
                parent_id            = None,
                part                 = 1,
                total_parts          = 1,
                is_continuation      = False,
                source_file          = source_file,
                section_title        = title,
                section_level        = level,
                parent_section       = parent_section,
                parent_section_level = parent_section_level,
                content              = content,
                token_count          = token_count,
                has_table            = section_has_tbl,
                oversized_by_table   = section_has_tbl and token_count > MAX_TOKENS,
            ))

        else:
            # Secondary split by paragraphs
            parent_id = make_chunk_id(source_file, title, 0)  # 0 = parent reference
            parts     = split_by_paragraphs(content, MAX_TOKENS, OVERLAP_TOKENS)
            total     = len(parts)

            logger.debug(f"Section '{title}' split into {total} parts ({token_count} tokens)")

            for i, part_content in enumerate(parts):
                part_num = i + 1
                chunk_id = make_chunk_id(source_file, title, part_num)
                chunks.append(Chunk(
                    chunk_id             = chunk_id,
                    parent_id            = parent_id,
                    part                 = part_num,
                    total_parts          = total,
                    is_continuation      = i > 0,
                    source_file          = source_file,
                    section_title        = title,
                    section_level        = level,
                    parent_section       = parent_section,
                    parent_section_level = parent_section_level,
                    content              = part_content,
                    token_count          = estimate_tokens(part_content),
                    has_table            = has_table(part_content),
                    oversized_by_table   = False,
                ))

    # Wire prev/next navigation links
    for i, chunk in enumerate(chunks):
        chunk.prev_chunk_id = chunks[i - 1].chunk_id if i > 0 else None
        chunk.next_chunk_id = chunks[i + 1].chunk_id if i + 1 < len(chunks) else None

    logger.info(f"{source_file} → {len(chunks)} chunks generated")
    return chunks


# ─────────────────────────────────────────────────────────
# PUBLIC INTERFACE
# ─────────────────────────────────────────────────────────

def chunk_file(path: Path) -> list[Chunk]:
    """Entry point. Receives a .md path, returns list of Chunk objects."""
    markdown = path.read_text(encoding="utf-8")
    return chunk_document(markdown, source_file=path.name)


def chunks_to_json(chunks: list[Chunk], output_path: Path):
    """Saves chunks as JSON for inspection or debugging."""
    data = [asdict(c) for c in chunks]
    output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"Chunks saved to {output_path}")