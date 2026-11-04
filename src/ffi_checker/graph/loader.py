"""Write a Graph into Neo4j.

Cypher concepts used here (Cypher = Neo4j's query language):
    MERGE   "find this node/relationship, or create it if missing". Running the
            load twice therefore does not create duplicates (it is idempotent).
    UNWIND  turns a list parameter into rows, so we send ONE query per label
            with all nodes as a list instead of one query per node (much faster).
    $rows   a query parameter. Never paste values into the query text yourself:
            parameters are safer and let Neo4j reuse the query plan.
    CONSTRAINT ... IS UNIQUE   makes `path` a unique key per label and creates an
            index on it, so MERGE/MATCH by path stays fast on big ECUs.
"""

from __future__ import annotations

import os

from .schema import NODE_LABELS, REL_TYPES, Graph

DEFAULT_URI = "bolt://localhost:7687"
DEFAULT_USER = "neo4j"
DEFAULT_PASSWORD = "ffi-checker-dev"  # matches docker-compose.yml, local development only


def load_settings() -> None:
    """Read a `.env` file (searched from the current folder upwards) into environment variables.

    Values already set in the environment win over the file, so you can still
    override a single setting from the command line.
    """
    try:
        from dotenv import find_dotenv, load_dotenv
    except ImportError:  # python-dotenv not installed: rely on real env vars only
        return
    load_dotenv(find_dotenv(usecwd=True), override=False)


def use_system_certificates() -> None:
    """Make Python trust the operating system's certificate store.

    Many company networks inspect HTTPS traffic and re-sign it with a company
    certificate. Windows already trusts that certificate, but Python ships its own
    list and does not, which gives "self-signed certificate in certificate chain".
    `truststore` makes Python use the OS list instead. Harmless on networks
    without inspection. Set FFI_SYSTEM_CERTS=0 to turn it off.
    """
    if os.environ.get("FFI_SYSTEM_CERTS", "1") == "0":
        return
    try:
        import truststore
    except ImportError:
        return
    truststore.inject_into_ssl()


def connect():
    """Open a Neo4j driver using NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD (env vars or `.env`)."""
    from neo4j import GraphDatabase  # imported here so the rest of the tool works without it

    load_settings()
    use_system_certificates()
    uri = os.environ.get("NEO4J_URI", DEFAULT_URI)
    auth = (
        os.environ.get("NEO4J_USER", DEFAULT_USER),
        os.environ.get("NEO4J_PASSWORD", DEFAULT_PASSWORD),
    )
    driver = GraphDatabase.driver(uri, auth=auth)
    driver.verify_connectivity()
    return driver


def load_graph(session, graph: Graph, reset: bool = False) -> None:
    """Write all nodes and relationships. `session` is a neo4j Session."""
    if reset:
        session.run("MATCH (n) DETACH DELETE n")

    for label in NODE_LABELS:
        session.run(
            f"CREATE CONSTRAINT {label.lower()}_path IF NOT EXISTS "
            f"FOR (n:{label}) REQUIRE n.path IS UNIQUE"
        )

    for label in NODE_LABELS:
        rows = [{"path": n.path, "props": n.props} for n in graph.nodes_with_label(label)]
        if rows:
            session.run(
                f"UNWIND $rows AS row "
                f"MERGE (n:{label} {{path: row.path}}) "
                f"SET n += row.props",
                rows=rows,
            )

    for rel_type, (src_label, dst_label) in REL_TYPES.items():
        rows = [{"src": r.src, "dst": r.dst} for r in graph.rels_of_type(rel_type)]
        if rows:
            session.run(
                f"UNWIND $rows AS row "
                f"MATCH (a:{src_label} {{path: row.src}}) "
                f"MATCH (b:{dst_label} {{path: row.dst}}) "
                f"MERGE (a)-[:{rel_type}]->(b)",
                rows=rows,
            )
