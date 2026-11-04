"""Milestone 2 tests.

Unit tests (always run): check the graph we build, and that the loader sends
the expected Cypher, using a fake session instead of a real database.

Integration tests (marked `neo4j`): run against the Neo4j configured in `.env`
(or NEO4J_* env vars). They WIPE that database, so they only run when you ask:

    PowerShell:   $env:RUN_NEO4J_TESTS="1"; pytest -m neo4j
    macOS/Linux:  RUN_NEO4J_TESTS=1 pytest -m neo4j
"""

import os
from pathlib import Path

import pytest

from ffi_checker import parse_arxml
from ffi_checker.graph import QUERIES, run_query, to_graph
from ffi_checker.code import parse_c_sources, parse_map
from ffi_checker.graph.loader import load_graph
from ffi_checker.graph.schema import NODE_LABELS

DEMO = Path(__file__).parent.parent / "examples" / "demo_ecu" / "DemoEcu.arxml"


@pytest.fixture
def graph():
    return to_graph(parse_arxml([DEMO]))


# ----------------------------------------------------------------- unit tests


def test_node_counts(graph):
    counts = {label: len(graph.nodes_with_label(label)) for label in
              ["Core", "OsApplication", "Task", "Runnable", "SwComponent"]}
    assert counts == {"Core": 2, "OsApplication": 3, "Task": 3, "Runnable": 4, "SwComponent": 4}


def test_relationship_counts(graph):
    assert len(graph.rels_of_type("HAS_RUNNABLE")) == 4
    assert len(graph.rels_of_type("MAPPED_TO")) == 4
    assert len(graph.rels_of_type("OWNS_TASK")) == 3
    assert len(graph.rels_of_type("RUNS_ON")) == 3


def test_every_relationship_points_to_existing_nodes(graph):
    paths = {n.path for n in graph.nodes}
    for r in graph.rels:
        assert r.src in paths and r.dst in paths, r


def test_asil_rank_stored_for_comparisons(graph):
    swc = {n.props["name"]: n.props for n in graph.nodes_with_label("SwComponent")}
    assert swc["BrakeCtrl"]["asil"] == "C" and swc["BrakeCtrl"]["asil_rank"] == 3
    assert swc["HmiGateway"]["asil_rank"] == 0


class FakeSession:
    """Records queries instead of sending them to Neo4j."""

    def __init__(self):
        self.calls = []

    def run(self, query, **params):
        self.calls.append((query, params))


def test_loader_uses_merge_and_batches(graph):
    s = FakeSession()
    load_graph(s, graph, reset=True)
    queries = [q for q, _ in s.calls]
    assert queries[0] == "MATCH (n) DETACH DELETE n"
    assert sum("CREATE CONSTRAINT" in q for q in queries) == len(NODE_LABELS)
    node_loads = [(q, p) for q, p in s.calls if "MERGE (n:" in q]
    assert len(node_loads) == 5  # one batched query per label, not one per node
    assert all("UNWIND $rows" in q for q, _ in node_loads)
    rel_loads = [q for q in queries if "MERGE (a)-[r:" in q]
    assert len(rel_loads) == 4


def test_graph_with_code_adds_variables_and_memory(graph):
    root = DEMO.parent
    code = parse_map(root / "DemoEcu.map", parse_c_sources([root / "src"]))
    g = to_graph(parse_arxml([DEMO]), code)
    assert len(g.nodes_with_label("Variable")) == 5
    assert len(g.nodes_with_label("MemoryRegion")) == 3
    assert len(g.rels_of_type("OWNS_VARIABLE")) == 5
    assert len(g.rels_of_type("IN_SECTION")) == 4  # Diag_UnmappedFlag has none
    assert len(g.rels_of_type("PLACED_IN")) == 5
    # Hmi_Run20ms both takes the address of and writes SpeedMon_Speed: "write" wins.
    assert {r.props["kind"] for r in g.rels_of_type("WRITES")} == {"write"}
    assert len(g.rels_of_type("WRITES")) == 7 and len(g.rels_of_type("READS")) == 3
    paths = {n.path for n in g.nodes}
    assert all(r.src in paths and r.dst in paths for r in g.rels)


def test_every_query_has_description_and_cypher():
    for name, q in QUERIES.items():
        assert q["description"] and "RETURN" in q["cypher"], name


# ----------------------------------------------------------- integration tests

needs_neo4j = pytest.mark.skipif(
    os.environ.get("RUN_NEO4J_TESTS") != "1", reason="set RUN_NEO4J_TESTS=1 to run (wipes the database)"
)


@pytest.fixture
def neo4j_session(graph):
    from ffi_checker.graph.loader import connect

    driver = connect()
    with driver.session() as session:
        load_graph(session, graph, reset=True)  # NOTE: wipes the database
        yield session
    driver.close()


@pytest.mark.neo4j
@needs_neo4j
def test_neo4j_mapping(neo4j_session):
    assert len(run_query(neo4j_session, "mapping")) == 4


@pytest.mark.neo4j
@needs_neo4j
def test_neo4j_load_twice_creates_no_duplicates(neo4j_session, graph):
    load_graph(neo4j_session, graph)
    count = neo4j_session.run("MATCH (n) RETURN count(n) AS n").single()["n"]
    assert count == len(graph.nodes)


@pytest.mark.neo4j
@needs_neo4j
def test_neo4j_seeded_issue_found(neo4j_session):
    rows = run_query(neo4j_session, "lower_asil_in_partition")
    assert rows == [{"os_app": "OsApp_AsilC_Core1", "partition_asil": "C",
                     "runnable": "Hmi_Run20ms", "swc": "HmiGateway", "asil": "QM"}]
    mixed = run_query(neo4j_session, "mixed_asil_partitions")
    assert [r["os_app"] for r in mixed] == ["OsApp_AsilC_Core1"]
    assert sorted(mixed[0]["asils"]) == ["C", "QM"]


@pytest.mark.neo4j
@needs_neo4j
def test_neo4j_other_queries(neo4j_session):
    assert [r["core"] for r in run_query(neo4j_session, "mixed_criticality_cores")] == ["Core0"]
    assert [r["os_app"] for r in run_query(neo4j_session, "trusted_partitions")] == ["OsApp_AsilC_Core0"]
    assert run_query(neo4j_session, "unmapped_runnables") == []


def test_settings_are_read_from_env_file(tmp_path, monkeypatch):
    from ffi_checker.graph.loader import load_settings

    (tmp_path / ".env").write_text("NEO4J_URI=neo4j+s://example.databases.neo4j.io\nNEO4J_PASSWORD=from-file\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("NEO4J_URI", raising=False)
    monkeypatch.setenv("NEO4J_PASSWORD", "from-env")  # real env var must win over the file
    load_settings()
    assert os.environ["NEO4J_URI"] == "neo4j+s://example.databases.neo4j.io"
    assert os.environ["NEO4J_PASSWORD"] == "from-env"


def test_system_certificates_can_be_enabled_and_disabled(monkeypatch):
    import ssl

    from ffi_checker.graph.loader import use_system_certificates

    monkeypatch.setenv("FFI_SYSTEM_CERTS", "0")
    use_system_certificates()  # must do nothing, and not raise
    monkeypatch.setenv("FFI_SYSTEM_CERTS", "1")
    original = ssl.SSLContext
    try:
        use_system_certificates()
        ssl.create_default_context()  # still works with the OS certificate store
    finally:
        ssl.SSLContext = original


@pytest.fixture
def neo4j_code_session():
    from ffi_checker.graph.loader import connect

    root = DEMO.parent
    code = parse_map(root / "DemoEcu.map", parse_c_sources([root / "src"]))
    driver = connect()
    with driver.session() as session:
        load_graph(session, to_graph(parse_arxml([DEMO]), code), reset=True)  # wipes the database
        yield session
    driver.close()


@pytest.mark.neo4j
@needs_neo4j
def test_neo4j_code_queries(neo4j_code_session):
    s = neo4j_code_session
    variables = {r["variable"]: r for r in run_query(s, "variables")}
    assert variables["BrakeCtrl_BrakeRequest"]["region"] == "RAM_ASIL_C_CORE0"
    assert variables["Diag_UnmappedFlag"]["region"] is None

    lower = {(r["runnable"], r["variable"]) for r in run_query(s, "lower_asil_writers")}
    assert lower == {("Diag_Run100ms", "BrakeCtrl_BrakeRequest"), ("Hmi_Run20ms", "SpeedMon_Speed")}

    # Only Diag -> BrakeCtrl crosses partitions. Hmi -> SpeedMon is inside OsApp_AsilC_Core1,
    # and SpeedMon_Run5ms writing its own variable does not count.
    cross = run_query(s, "cross_partition_writes")
    assert [(r["runnable"], r["variable"], r["owner_os_app"]) for r in cross] == [
        ("Diag_Run100ms", "BrakeCtrl_BrakeRequest", "OsApp_AsilC_Core0")
    ]

    assert [r["variable"] for r in run_query(s, "unplaced_variables")] == ["Diag_UnmappedFlag"]

    mixed = run_query(s, "mixed_asil_regions")
    assert [r["region"] for r in mixed] == ["RAM_ASIL_C_CORE1"]
    assert sorted(mixed[0]["asil_levels"]) == ["C", "QM"]
