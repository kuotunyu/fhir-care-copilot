"""公開 Markdown 的相對連結與章節 anchor 必須能解析。"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from urllib.parse import unquote

REPO_ROOT = Path(__file__).resolve().parent.parent
MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
HEADING = re.compile(r"^[ ]{0,3}#{1,6}\s+(.+)$")
FENCE = re.compile(r"^[ ]{0,3}(`{3,}|~{3,})(.*)$")


def _tracked_files() -> set[Path]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return {(REPO_ROOT / line).resolve() for line in result.stdout.splitlines() if line}


def _tracked_markdown_files(tracked_files: set[Path]) -> list[Path]:
    return sorted(path for path in tracked_files if path.suffix.casefold() == ".md")


def _github_slug(heading: str) -> str:
    heading = re.sub(r"\s+#+\s*$", "", heading)
    text = re.sub(r"<[^>]+>", "", heading.casefold())
    text = re.sub(r"[`*_~]", "", text)
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    return re.sub(r"\s+", "-", text).strip("-")


def _markdown_heading_slugs(markdown: str) -> set[str]:
    slugs: set[str] = set()
    fence_character: str | None = None
    fence_length = 0

    for line in markdown.splitlines():
        fence = FENCE.match(line)
        if fence_character is None and fence:
            marker = fence.group(1)
            fence_character = marker[0]
            fence_length = len(marker)
            continue
        if fence_character is not None:
            if fence:
                marker = fence.group(1)
                if (
                    marker[0] == fence_character
                    and len(marker) >= fence_length
                    and not fence.group(2).strip()
                ):
                    fence_character = None
                    fence_length = 0
            continue

        heading = HEADING.match(line)
        if heading:
            slugs.add(_github_slug(heading.group(1)))

    return slugs


def _is_tracked_target(target: Path, tracked_files: set[Path]) -> bool:
    resolved = target.resolve()
    if resolved.is_file():
        return resolved in tracked_files
    if resolved.is_dir():
        return any(resolved in path.parents for path in tracked_files)
    return False


def _relative_link_issues(source: Path, tracked_files: set[Path]) -> list[str]:
    issues: list[str] = []
    text = source.read_text(encoding="utf-8")

    for match in MARKDOWN_LINK.finditer(text):
        raw_target = match.group(1).strip()
        if raw_target.startswith(("http://", "https://", "mailto:", "data:")):
            continue
        if raw_target.startswith("<") and raw_target.endswith(">"):
            raw_target = raw_target[1:-1]

        relative, separator, fragment = raw_target.partition("#")
        relative = unquote(relative)
        fragment = unquote(fragment).casefold()
        target = source if not relative else (source.parent / relative).resolve()
        display_source = source.relative_to(REPO_ROOT).as_posix()

        try:
            target.relative_to(REPO_ROOT.resolve())
        except ValueError:
            issues.append(f"{display_source} -> {raw_target}: outside repository")
            continue

        if not target.exists():
            issues.append(f"{display_source} -> {raw_target}: missing file")
            continue
        if not _is_tracked_target(target, tracked_files):
            issues.append(f"{display_source} -> {raw_target}: target is not tracked")
            continue

        if separator and fragment and target.suffix.casefold() == ".md":
            headings = _markdown_heading_slugs(target.read_text(encoding="utf-8"))
            if fragment not in headings:
                issues.append(f"{display_source} -> {raw_target}: missing anchor")

    return issues


def test_tracked_relative_markdown_links_resolve() -> None:
    """重新命名文件或標題卻未更新入口連結時,公開導覽必須失敗。"""
    tracked_files = _tracked_files()
    issues = [
        issue
        for source in _tracked_markdown_files(tracked_files)
        if source.exists()
        for issue in _relative_link_issues(source, tracked_files)
    ]

    assert not issues, "Broken relative Markdown links:\n" + "\n".join(issues)


def test_fenced_code_headings_are_not_github_anchors() -> None:
    markdown = "# Visible\n\n```markdown\n# Hidden\n```\n"

    assert _markdown_heading_slugs(markdown) == {"visible"}


def test_existing_but_untracked_file_is_not_a_public_target(tmp_path: Path) -> None:
    target = tmp_path / "ignored.md"
    target.write_text("internal\n", encoding="utf-8")

    assert not _is_tracked_target(target, tracked_files=set())
