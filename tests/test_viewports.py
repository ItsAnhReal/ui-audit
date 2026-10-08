from ui_audit import viewports


def test_sweep_widths_includes_both_ends():
    assert viewports.sweep_widths(320, 500, 80) == [320, 400, 480, 500]
    assert viewports.sweep_widths(320, 480, 80) == [320, 400, 480]


def test_breakpoint_neighbors_are_clamped_to_range():
    assert viewports.breakpoint_neighbors([390, 768], 320, 1920) == [389, 390, 391, 767, 768, 769]
    assert viewports.breakpoint_neighbors([320, 1920], 320, 1920) == [320, 321, 1919, 1920]


def _step_probe(edge: int):
    calls = []

    def probe(width: int):
        calls.append(width)
        return frozenset({"overflow"}) if width >= edge else frozenset()

    return probe, calls


def test_find_boundary_is_pixel_exact():
    probe, calls = _step_probe(947)
    last_low, first_high, used = viewports.find_boundary(probe, 880, 960, frozenset(), frozenset({"overflow"}))
    assert (last_low, first_high) == (946, 947)
    assert used == len(calls) <= 7  # log2(80) rounded up


def test_sweep_refines_every_change_within_budget():
    def probe(width: int):
        return frozenset({"a"}) if 800 <= width <= 946 else frozenset()

    result = viewports.sweep(probe, viewports.sweep_widths(320, 1920, 80))
    assert sorted(result.anomalies) == [799, 800, 946, 947]

    limited = viewports.sweep(probe, viewports.sweep_widths(320, 1920, 80), max_refinements=1)
    assert sorted(limited.anomalies) == [799, 800]

    unrefined = viewports.sweep(probe, viewports.sweep_widths(320, 1920, 80), refine=False)
    assert unrefined.anomalies == []


def test_select_captures_priority_and_cap():
    plans = viewports.select_captures(
        standard=[390, 768, 1366, 1920], breakpoint_widths=[389, 390, 391, 767, 768, 769],
        anomalies=[799, 800, 946, 947], with_issues={800, 946}, cap=8, min_width=320, max_width=1920)
    widths = [p.width for p in plans]
    assert widths == sorted(widths)
    assert len(widths) == 8
    # Standard presets first, then anomalies with issues, then breakpoint neighbours.
    assert {390, 768, 1366, 1920, 800, 946} <= set(widths)
    assert {389, 391} <= set(widths)
    by_width = {p.width: p.reasons for p in plans}
    assert by_width[390] == ["standard", "breakpoint"]
    assert by_width[800] == ["anomaly"]


def test_select_captures_without_cap_keeps_everything():
    plans = viewports.select_captures([390], [767, 768], [500], set(), cap=0, min_width=320, max_width=1920)
    assert [p.width for p in plans] == [390, 500, 767, 768]


def test_height_for_presets_and_ranges():
    assert viewports.height_for(390) == 844
    assert viewports.height_for(1366) == 768
    assert viewports.height_for(500) == 844
    assert viewports.height_for(900) == 1024
    assert viewports.height_for(1500) == 900
