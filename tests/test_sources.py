import re

from ui_audit import sources
from ui_audit.sources import SourceIndex


def test_rank_prefers_runtime_files_then_component_and_id(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src/PricingCard.tsx").write_text('export function PricingCard() { return <div id="plans" className="plans p-4">Team plan</div> }')
    (tmp_path / "src/styles.css").write_text(".plans { display: grid }")
    (tmp_path / "src/Other.tsx").write_text("export const Other = () => null")
    index = SourceIndex(tmp_path)
    hints = {"components": ["PricingCard"], "files": [], "id": "plans", "classes": ["plans", "p-4"], "text": "Team plan"}
    ranked = index.rank(hints)
    assert ranked[0]["file"] == "src/PricingCard.tsx"
    assert "src/styles.css" not in [r["file"] for r in ranked]  # one utility-free class match is too weak
    assert all(r["file"] != "src/Other.tsx" for r in ranked)

    runtime = index.rank({"files": [{"file": str(tmp_path / "src/Other.tsx"), "line": 1}]})
    assert runtime[0] == {"file": "src/Other.tsx", "score": 10, "reasons": ["runtime source"], "line": 1}


def test_rank_without_hints_is_empty(tmp_path):
    assert SourceIndex(tmp_path).rank({}) == []


def test_rank_prefers_the_file_that_sets_a_size_for_size_checks(tmp_path):
    # Shaped like VibeSpace: the grid's classes live in a constants file, ProfileTile.tsx renders
    # the grid with them, and the page renders ProfileTileGrid.
    (tmp_path / "src/pages").mkdir(parents=True)
    (tmp_path / "src/tile-grid.ts").write_text(
        "export const GRID = 'grid grid-cols-[repeat(2,9.75rem)] md:grid-cols-[repeat(4,9.75rem)] auto-rows-[9.75rem] justify-center';")
    (tmp_path / "src/ProfileTile.tsx").write_text("export function ProfileTileGrid() { return <div className={GRID} /> }")
    (tmp_path / "src/pages/Profile.tsx").write_text("export default function Profile() { return <ProfileTileGrid /> }")
    index = SourceIndex(tmp_path)
    hints = {"files": [{"file": str(tmp_path / "src/ProfileTile.tsx"), "line": 1},
                       {"file": str(tmp_path / "src/pages/Profile.tsx"), "line": 1}],
             "components": ["ProfileTileGrid", "Profile"],
             "classes": ["grid", "grid-cols-[repeat(2,9.75rem)]", "md:grid-cols-[repeat(4,9.75rem)]",
                         "auto-rows-[9.75rem]", "justify-center"]}
    ranked = [r["file"] for r in index.rank(hints, check="horizontal-overflow")]
    assert ranked == ["src/tile-grid.ts", "src/ProfileTile.tsx", "src/pages/Profile.tsx"]
    # For a check that is not about size, the classes are no stronger than any others.
    assert index.rank(hints, check="unnamed-control")[0]["file"] == "src/ProfileTile.tsx"


def test_rank_puts_the_app_file_before_a_shared_primitive(tmp_path):
    (tmp_path / "src/components/ui").mkdir(parents=True)
    (tmp_path / "src/components/ui/sheet.tsx").write_text("const SheetContent = () => null")
    (tmp_path / "src/TopBar.tsx").write_text("export default function TopBar() {}")
    index = SourceIndex(tmp_path)
    hints = {"files": [{"file": str(tmp_path / "src/components/ui/sheet.tsx"), "line": 60},
                       {"file": str(tmp_path / "src/TopBar.tsx"), "line": 81}]}
    assert [r["file"] for r in index.rank(hints)] == ["src/TopBar.tsx", "src/components/ui/sheet.tsx"]


def _scan(root, hints, check):
    """rank() as it was before the index: every pattern against every file."""
    index = SourceIndex(root)
    scores = {}
    components = [c for c in hints.get("components") or [] if len(c) > 2]
    classes = [c for c in hints.get("classes") or [] if not sources.UTILITY_CLASS.match(c)]
    context = [c for c in hints.get("contextClasses") or [] if not sources.UTILITY_CLASS.match(c) and c not in classes]
    element_id, text = hints.get("id"), (hints.get("text") or "").strip()
    text = text[:40] if len(text) >= 6 else ""
    for path, content in index.files():
        found = scores.setdefault(index.relative(str(path)), [])
        for position, component in enumerate(components):
            if path.stem == component:
                found.append((6 if position == 0 else 3, f"component {component}"))
            elif re.search(rf"\b(?:function|const|class)\s+{re.escape(component)}\b", content):
                found.append((4 if position == 0 else 2, f"defines {component}"))
        if element_id and re.search(rf"""(?:id\s*=\s*["']{re.escape(element_id)}["']|#{re.escape(element_id)}\b)""", content):
            found.append((4, f"id {element_id}"))
        for cls in classes + context:
            if re.search(rf"(?<![\w-]){re.escape(cls)}(?![\w-])", content):
                sized = check in sources.SIZE_CHECKS and sources.SIZED_CLASS.search(cls)
                found.append((5 if sized else 1, f"class {cls}"))
        if text and text in content:
            found.append((3, "visible text"))
    ranked = sorted(((f, sum(p for p, _ in r), [w for _, w in r]) for f, r in scores.items() if r),
                    key=lambda e: (-e[1], e[0]))
    return [e for e in ranked if e[1] >= 2]


def test_the_index_finds_what_scanning_every_file_finds(tmp_path):
    (tmp_path / "src").mkdir()
    files = {
        "Card.tsx": "export class Card-ish {}",  # a stem match with no definition in it
        "Grid.tsx": "const Grid = () => <div className='w-[324px] grid-cols-[repeat(2,9.75rem)] nav-item' />",
        "page.html": '<main id="main-content"><p>Welcome back to the dashboard</p></main>',
        "styles.css": "#main-content { width: 100% } .nav-item-wide { } .nav-item { } .x.nav-item:hover {}",
        "Header.vue": "<script>const Headerish = 1; function Header() {}</script> Hello, welcome back",
    }
    for name, content in files.items():
        (tmp_path / "src" / name).write_text(content)
    hints = [
        {"components": ["Card", "Header"], "classes": ["w-[324px]", "nav-item"], "id": "main-content",
         "text": "elcome back to the dashboa"},
        {"components": ["Grid"], "classes": ["grid-cols-[repeat(2,9.75rem)]"], "contextClasses": ["nav-item"]},
        {"id": "main-content", "text": "Welcome back"},
        {"classes": ["--", "nav-item-wide"], "text": "x y z w"},
    ]
    index = SourceIndex(tmp_path)
    for hint in hints:
        for check in ("horizontal-overflow", "small-target"):
            ranked = [(e["file"], e["score"], e["reasons"]) for e in index.rank(hint, limit=10, check=check)]
            assert ranked == _scan(tmp_path, hint, check)
    assert len(index.rank(hints[0], limit=10)) >= 3  # the cases above do match something
