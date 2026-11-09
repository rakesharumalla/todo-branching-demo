from todo.naming import lakebase_branch_name, port_for_branch


def test_branch_name_sanitizes_and_prefixes():
    assert (
        lakebase_branch_name("rakesh.arumalla", "feature/priority")
        == "rakesh-arumalla-feature-priority"
    )


def test_branch_name_truncates_to_63():
    name = lakebase_branch_name("rakesh", "x" * 100)
    assert len(name) <= 63
    assert name.startswith("rakesh-")


def test_port_is_deterministic_and_in_range():
    p1 = port_for_branch("feature/priority")
    p2 = port_for_branch("feature/priority")
    assert p1 == p2
    assert 8502 <= p1 <= 8599


def test_production_maps_to_base_port():
    assert port_for_branch("main", base=8501) == 8501
    assert port_for_branch("production", base=8501) == 8501
