"""Unit tests for the coverage engine in app/engine/mapper.py.

Uses SimpleNamespace to avoid DB access — these are pure logic tests.
"""

import types
from datetime import datetime, timedelta


from app.engine.mapper import compute_coverage, compute_recommendations


# ---------------------------------------------------------------------------
# Helpers to build lightweight mock objects
# ---------------------------------------------------------------------------


def _ctrl(control_id, required_tags, title="Test Control"):
    return types.SimpleNamespace(
        control_id=control_id,
        title=title,
        description="",
        required_tags=required_tags,
        optional_tags=[],
        evidence=[],
        sub_controls=[],
    )


def _tool(name, tags, tool_id=1, category=""):
    caps = [types.SimpleNamespace(tag=t) for t in tags]
    return types.SimpleNamespace(id=tool_id, name=name, category=category, capabilities=caps)


def _note(**kwargs):
    defaults = {
        "is_applicable": True,
        "exclusion_reason": "",
        "override_status": None,
        "override_expires": None,
        "override_justification": "",
        "notes": "",
        "evidence_url": "",
        "review_status": "not_reviewed",
        "review_notes": "",
        "assignee": "",
        "due_date": None,
    }
    defaults.update(kwargs)
    return types.SimpleNamespace(**defaults)


def _own(**kwargs):
    defaults = {"owner": "", "team": "", "evidence_owner": ""}
    defaults.update(kwargs)
    return types.SimpleNamespace(**defaults)


def _finding(status="open"):
    return types.SimpleNamespace(status=status)


# ---------------------------------------------------------------------------
# Basic coverage logic
# ---------------------------------------------------------------------------


def test_no_controls_empty_score():
    result = compute_coverage([], [], {}, {}, {})
    assert result["score"] == 0.0
    assert result["total_controls"] == 0
    assert result["controls"] == []


def test_single_control_no_required_tags_is_covered():
    """A control with no required tags is always covered."""
    ctrls = [_ctrl("C-1", [])]
    result = compute_coverage(ctrls, [], {}, {}, {})
    assert result["covered"] == 1
    assert result["score"] == 100.0
    assert result["controls"][0]["status"] == "covered"


def test_single_control_required_tag_no_tools():
    ctrls = [_ctrl("C-1", ["tag-a"])]
    result = compute_coverage(ctrls, [], {}, {}, {})
    assert result["not_covered"] == 1
    assert result["score"] == 0.0


def test_single_control_required_tag_matched():
    ctrls = [_ctrl("C-1", ["tag-a"])]
    tools = [_tool("ToolA", ["tag-a"])]
    result = compute_coverage(ctrls, tools, {}, {}, {})
    assert result["covered"] == 1
    assert result["score"] == 100.0


def test_partial_coverage():
    """Control requires 2 tags; only 1 is provided → partial."""
    ctrls = [_ctrl("C-1", ["tag-a", "tag-b"])]
    tools = [_tool("ToolA", ["tag-a"])]
    result = compute_coverage(ctrls, tools, {}, {}, {})
    assert result["partial"] == 1
    assert result["score"] == 50.0


def test_score_formula():
    """Score = (covered + 0.5*partial) / applicable * 100."""
    ctrls = [
        _ctrl("C-1", []),               # covered (no required tags)
        _ctrl("C-2", ["tag-a", "tag-b"]),  # partial (tag-a provided, tag-b missing)
        _ctrl("C-3", ["tag-b"]),        # not_covered (tag-b not provided at all)
    ]
    tools = [_tool("T", ["tag-a"])]
    result = compute_coverage(ctrls, tools, {}, {}, {})
    assert result["covered"] == 1
    assert result["partial"] == 1
    assert result["not_covered"] == 1
    expected = round((1 + 0.5 * 1) / 3 * 100, 1)
    assert result["score"] == expected


# ---------------------------------------------------------------------------
# Not-applicable controls
# ---------------------------------------------------------------------------


def test_not_applicable_excluded_from_score():
    ctrls = [_ctrl("C-1", ["tag-a"]), _ctrl("C-2", [])]
    notes = {"C-1": _note(is_applicable=False, exclusion_reason="Out of scope")}
    result = compute_coverage(ctrls, [], notes, {}, {})
    assert result["not_applicable"] == 1
    assert result["covered"] == 1  # C-2 has no required tags → covered
    assert result["score"] == 100.0


# ---------------------------------------------------------------------------
# Manual overrides
# ---------------------------------------------------------------------------


def test_override_covered_respected():
    ctrls = [_ctrl("C-1", ["tag-a"])]  # tag-a not provided by any tool
    notes = {"C-1": _note(override_status="covered", override_expires=None)}
    result = compute_coverage(ctrls, [], notes, {}, {})
    assert result["covered"] == 1
    assert result["controls"][0]["is_override"] is True


def test_expired_override_not_used():
    """An expired override must not affect status."""
    ctrls = [_ctrl("C-1", ["tag-a"])]
    past = datetime.utcnow() - timedelta(days=1)
    notes = {"C-1": _note(override_status="covered", override_expires=past)}
    result = compute_coverage(ctrls, [], notes, {}, {})
    # Override expired → falls back to tag-based logic → not_covered
    assert result["not_covered"] == 1
    assert result["controls"][0]["is_override"] is False


def test_future_override_respected():
    ctrls = [_ctrl("C-1", ["tag-a"])]
    future = datetime.utcnow() + timedelta(days=30)
    notes = {"C-1": _note(override_status="partial", override_expires=future)}
    result = compute_coverage(ctrls, [], notes, {}, {})
    assert result["partial"] == 1


# ---------------------------------------------------------------------------
# Null/None guard regression
# ---------------------------------------------------------------------------


def test_none_required_tags_does_not_crash():
    """Control with required_tags=None must not raise TypeError."""
    ctrl = _ctrl("C-1", None)  # simulates DB returning NULL
    ctrl.required_tags = None
    result = compute_coverage([ctrl], [], {}, {}, {})
    # No required tags → treated as covered
    assert result["covered"] == 1


# ---------------------------------------------------------------------------
# is_overdue flag
# ---------------------------------------------------------------------------


def test_overdue_flag_set_when_past_due_and_not_covered():
    past = datetime.utcnow() - timedelta(days=5)
    ctrls = [_ctrl("C-1", ["tag-a"])]
    notes = {"C-1": _note(due_date=past)}
    result = compute_coverage(ctrls, [], notes, {}, {})
    assert result["controls"][0]["is_overdue"] is True


def test_overdue_flag_not_set_when_covered():
    past = datetime.utcnow() - timedelta(days=5)
    ctrls = [_ctrl("C-1", [])]  # no required tags → covered
    notes = {"C-1": _note(due_date=past)}
    result = compute_coverage(ctrls, [], notes, {}, {})
    assert result["controls"][0]["is_overdue"] is False


# ---------------------------------------------------------------------------
# compute_recommendations
# ---------------------------------------------------------------------------


def test_recommendations_empty_when_all_covered():
    ctrls = [_ctrl("C-1", [])]
    all_tools = [_tool("ExtraT", ["tag-x"], tool_id=2)]
    recs = compute_recommendations(ctrls, [], all_tools)
    # All controls already covered (no required tags), nothing to recommend
    assert recs == []


def test_recommendations_ranks_by_controls_helped():
    ctrls = [
        _ctrl("C-1", ["tag-a"]),
        _ctrl("C-2", ["tag-a"]),
        _ctrl("C-3", ["tag-b"]),
    ]
    tool_a = _tool("ToolA", ["tag-a"], tool_id=10)
    tool_b = _tool("ToolB", ["tag-b"], tool_id=11)
    recs = compute_recommendations(ctrls, [], [tool_a, tool_b])
    assert len(recs) == 2
    # ToolA helps 2 controls, ToolB helps 1
    assert recs[0]["tool_name"] == "ToolA"
    assert recs[0]["controls_helped"] == 2


def test_recommendations_excludes_already_selected():
    ctrls = [_ctrl("C-1", ["tag-a"])]
    selected = [_tool("ToolA", ["tag-a"], tool_id=1)]
    all_tools = [_tool("ToolA", ["tag-a"], tool_id=1), _tool("ToolB", ["tag-b"], tool_id=2)]
    recs = compute_recommendations(ctrls, selected, all_tools)
    tool_names = [r["tool_name"] for r in recs]
    assert "ToolA" not in tool_names
