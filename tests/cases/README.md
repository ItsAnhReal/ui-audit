# Check cases

One small page per situation a check has to get right. The first line says what an audit of
that page must report: `clean`, or `check=count` pairs. `tests/test_cases.py` audits them all.

Most of these started as a false finding on a real app. When a check reports something that
is not a defect, add the smallest page that reproduces it here before changing the check.

`never-click-*.html` pages are also audited with state discovery on by `tests/test_state_safety.py`:
disclosure-looking controls with destructive names must never be clicked.
