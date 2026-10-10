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
WORD = re.compile(r"\w+")
CLASS_WORD = re.compile(r"[\w-]+")


def _words(needle: str, inner: bool = False) -> list[str]:
    """The runs of word characters in `needle` that every match of it holds as whole words.

    Each pattern in rank() has a word boundary on both sides of the needle, so a run bounded
    by a non-word character or by the needle's ends is a word of the file too. A plain substring
    search has no boundaries at its ends, so only the `inner` runs count there."""
    runs = [(m.start(), m.end(), m.group()) for m in WORD.finditer(needle)]
    if inner:
        return [word for start, end, word in runs if start > 0 and end < len(needle)]
    return [word for _, _, word in runs]


class SourceIndex:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._files: list[tuple[Path, str]] | None = None
        # Built on the first rank(): an audit ranks every issue against the same files.
        self._words: dict[str, set[int]] | None = None
        self._tokens: dict[str, set[int]] = {}
        self._stems: dict[str, set[int]] = {}
        self._matches: dict[tuple[str, str], set[int]] = {}
        self._relative: dict[str, str] = {}

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

    def _index(self) -> None:
        """Words and class-like tokens → positions of the files that contain them, built once."""
        if self._words is not None:
            return
        self._words, self._tokens = {}, {}
        for position, (path, content) in enumerate(self.files()):
            self._stems.setdefault(path.stem, set()).add(position)
            for word in set(WORD.findall(content)):
                self._words.setdefault(word, set()).add(position)
            for token in set(CLASS_WORD.findall(content)):
                self._tokens.setdefault(token, set()).add(position)

    def _matching(self, kind: str, needle: str) -> set[int]:
        """Positions of the files a hint matches, worked out once per hint for the whole audit."""
        key = (kind, needle)
        if key in self._matches:
            return self._matches[key]
        self._index()
        if kind == "class" and CLASS_WORD.fullmatch(needle):
            # Bounded by anything but a word character or a hyphen, the class is a whole token.
            found = set(self._tokens.get(needle, ()))
        else:
            words = _words(needle, inner=kind == "text")
            candidates = set(range(len(self.files())))
            for word in words:
                candidates &= self._words.get(word, set())
            pattern = {
                "defines": rf"\b(?:function|const|class)\s+{re.escape(needle)}\b",
                "id": rf"""(?:id\s*=\s*["']{re.escape(needle)}["']|#{re.escape(needle)}\b)""",
                "class": rf"(?<![\w-]){re.escape(needle)}(?![\w-])",
            }.get(kind)
            files = self.files()
            found = {n for n in candidates
                     if (needle in files[n][1] if pattern is None else re.search(pattern, files[n][1]))}
        self._matches[key] = found
        return found

    def relative(self, path: str) -> str:
        if path not in self._relative:
            try:
                self._relative[path] = str(Path(path).resolve().relative_to(self.root.resolve()).as_posix())
            except (ValueError, OSError):
                self._relative[path] = path
        return self._relative[path]

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

        # Each hint is looked up in the index; the files it points to are scored in file order.
        self._index()
        stems = {c: self._stems.get(c, set()) for c in components}
        defines = {c: self._matching("defines", c) for c in components}
        id_files = self._matching("id", element_id) if element_id else set()
        class_files = {cls: self._matching("class", cls) for cls in classes + context}
        text_files = self._matching("text", text) if text else set()
        files = self.files()
        look_at = id_files | text_files
        for found in [*stems.values(), *defines.values(), *class_files.values()]:
            look_at |= found

        for number in sorted(look_at):
            path = files[number][0]
            # The component that renders the element counts fully; the ones around it (the page,
            # the layout) contain everything on the page and only count half.
            for position, component in enumerate(components):
                if number in stems[component]:
                    bump(path, 6 if position == 0 else 3, f"component {component}")
                elif number in defines[component]:
                    bump(path, 4 if position == 0 else 2, f"defines {component}")
            if number in id_files:
                bump(path, 4, f"id {element_id}")
            for cls in classes + context:
                if number in class_files[cls]:
                    bump(path, 5 if sized and SIZED_CLASS.search(cls) else 1, f"class {cls}")
            if number in text_files:
                bump(path, 3, "visible text")

        ranked = sorted(scores.values(), key=lambda e: (-e["score"], e["file"]))
        return [e for e in ranked if e["score"] >= 2][:limit]
