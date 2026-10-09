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
