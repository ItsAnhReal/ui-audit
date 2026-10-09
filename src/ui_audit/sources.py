"""Best-effort mapping from a DOM element back to source files.

Two kinds of evidence, in decreasing order of trust:

1. Runtime hints from development builds: React `_debugSource`, Vue
   `__file`, Svelte `__svelte_meta`, plus component names.
2. A ranked text search of the project for the element's id, classes,
   component names and visible text.

Both are hints for the coding agent to inspect, never conclusions.
"""

from __future__ import annotations

import re
from pathlib import Path

from .routes import SKIP_DIRS

SOURCE_EXTS = {".tsx", ".jsx", ".ts", ".js", ".mjs", ".vue", ".svelte", ".astro", ".html",
               ".css", ".scss", ".sass", ".less", ".mdx"}
MAX_FILES = 5000
MAX_BYTES = 500_000
# Utility classes say little about which file to edit.
# A class with a size written into it (Tailwind's `grid-cols-[repeat(2,9.75rem)]`, `w-[324px]`)
# is close to unique: the file that contains it is where that size was set.
SIZED_CLASS = re.compile(r"\[[^\]]*\d(?:\.\d+)?(?:px|rem|em|ch|vw|vh|%|fr)")
# Checks about how wide or tall something is, where the file that sets the size matters most.
SIZE_CHECKS = {"horizontal-overflow", "offscreen-content", "offscreen-control", "clipped-content", "text-spill"}
# Shared primitives (shadcn's components/ui, a ui/ folder) are rarely where a page's defect is
# fixed; the file that uses them with these props is.
PRIMITIVE_DIR = re.compile(r"(?:^|/)ui/[^/]+$")
UTILITY_CLASS = re.compile(r"^(?:-?[a-z]{1,3}-\d|flex$|grid$|block$|hidden$|relative$|absolute$|w-|h-|p[xytrbl]?-|m[xytrbl]?-|text-|bg-|gap-)")


class SourceIndex:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._files: list[tuple[Path, str]] | None = None

    def files(self) -> list[tuple[Path, str]]:
        if self._files is None:
            self._files = []
            stack = [self.root]
            while stack and len(self._files) < MAX_FILES:
                directory = stack.pop()
                try:
                    entries = sorted(directory.iterdir())
                except OSError:
                    continue
                for entry in entries:
                    if entry.is_dir():
                        if entry.name not in SKIP_DIRS and not entry.name.startswith("."):
                            stack.append(entry)
                    elif entry.suffix in SOURCE_EXTS:
                        try:
                            if entry.stat().st_size <= MAX_BYTES:
                                self._files.append((entry, entry.read_text(errors="ignore")))
                        except OSError:
                            continue
        return self._files

    def relative(self, path: str) -> str:
        try:
            return str(Path(path).resolve().relative_to(self.root.resolve()))
        except (ValueError, OSError):
            return path

    def rank(self, hints: dict, limit: int = 3, check: str = "") -> list[dict]:
        if not hints:
            return []
        scores: dict[str, dict] = {}

        def bump(path: Path | str, points: int, why: str, line: int | None = None) -> None:
            key = self.relative(str(path))
            entry = scores.setdefault(key, {"file": key, "score": 0, "reasons": [], "line": None})
            entry["score"] += points
            if why not in entry["reasons"]:
                entry["reasons"].append(why)
            if line and not entry["line"]:
                entry["line"] = line

        # The element's own JSX comes first, the components around it after; nearer is likelier.
        for position, hint in enumerate(hints.get("files") or []):
            points = max(10 - position, 7) - (4 if PRIMITIVE_DIR.search(self.relative(hint["file"])) else 0)
            bump(hint["file"], points, "runtime source", hint.get("line"))
        sized = check in SIZE_CHECKS

        components = [c for c in hints.get("components") or [] if len(c) > 2]
        classes = [c for c in hints.get("classes") or [] if not UTILITY_CLASS.match(c)]
        context = [c for c in hints.get("contextClasses") or [] if not UTILITY_CLASS.match(c) and c not in classes]
        element_id = hints.get("id")
        text = (hints.get("text") or "").strip()
        text = text[:40] if len(text) >= 6 else ""

        for path, content in self.files():
            # The component that renders the element counts fully; the ones around it (the page,
            # the layout) contain everything on the page and only count half.
            for position, component in enumerate(components):
                if path.stem == component:
                    bump(path, 6 if position == 0 else 3, f"component {component}")
                elif re.search(rf"\b(?:function|const|class)\s+{re.escape(component)}\b", content):
                    bump(path, 4 if position == 0 else 2, f"defines {component}")
            if element_id and re.search(rf"""(?:id\s*=\s*["']{re.escape(element_id)}["']|#{re.escape(element_id)}\b)""", content):
                bump(path, 4, f"id {element_id}")
            for cls in classes + context:
                if re.search(rf"(?<![\w-]){re.escape(cls)}(?![\w-])", content):
                    bump(path, 5 if sized and SIZED_CLASS.search(cls) else 1, f"class {cls}")
            if text and text in content:
                bump(path, 3, "visible text")

        ranked = sorted(scores.values(), key=lambda e: (-e["score"], e["file"]))
        return [e for e in ranked if e["score"] >= 2][:limit]
