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
