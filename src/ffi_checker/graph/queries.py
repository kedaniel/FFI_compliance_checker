"""Named Cypher queries about the ECU graph.

How to read a Cypher MATCH pattern:
    (a:OsApplication)-[:OWNS_TASK]->(t:Task)
    "find a node `a` labelled OsApplication that has an OWNS_TASK relationship
     to a node `t` labelled Task". Arrows give the direction.

Tip: paste any of these into the Neo4j Browser (http://localhost:7474) to see the
result as a picture. Change RETURN ... to RETURN * to see the matched subgraph.

These are still *observations*. Milestone 4 turns them into rules with IDs,
severity and evidence.
"""

from __future__ import annotations

# Maps the numeric rank stored on SwComponent back to the ASIL text.
_ASIL_NAMES = "['QM','A','B','C','D']"

# The chain from SWC to core, used by most queries.
_CHAIN = (
    "(c:Core)<-[:RUNS_ON]-(a:OsApplication)-[:OWNS_TASK]->(t:Task)"
    "<-[:MAPPED_TO]-(r:Runnable)<-[:HAS_RUNNABLE]-(s:SwComponent)"
)

QUERIES: dict[str, dict[str, str]] = {
    "mapping": {
        "description": "Every runnable with its SWC, ASIL, task, OS-Application and core.",
        "cypher": f"""
MATCH {_CHAIN}
RETURN c.name AS core, a.name AS os_app, a.trusted AS trusted,
       t.name AS task, r.name AS runnable, s.name AS swc, s.asil AS asil
ORDER BY core, os_app, task, runnable
""",
    },
    "mixed_asil_partitions": {
        "description": "OS-Applications that contain SWCs of different ASIL levels.",
        "cypher": """
MATCH (a:OsApplication)-[:OWNS_TASK]->(:Task)<-[:MAPPED_TO]-(:Runnable)<-[:HAS_RUNNABLE]-(s:SwComponent)
WITH a, collect(DISTINCT s.asil) AS asils
WHERE size(asils) > 1
RETURN a.name AS os_app, asils
ORDER BY os_app
""",
    },
    "lower_asil_in_partition": {
        "description": (
            "Runnables whose SWC has a LOWER ASIL than the partition they run in. "
            "Without FFI inside a partition, that code must be raised to the partition's ASIL."
        ),
        "cypher": f"""
MATCH (a:OsApplication)-[:OWNS_TASK]->(:Task)<-[:MAPPED_TO]-(r:Runnable)<-[:HAS_RUNNABLE]-(s:SwComponent)
WITH a, max(s.asil_rank) AS partition_rank,
     collect({{runnable: r.name, swc: s.name, asil: s.asil, rank: s.asil_rank}}) AS members
UNWIND members AS m
WITH a, partition_rank, m
WHERE m.rank < partition_rank
RETURN a.name AS os_app, {_ASIL_NAMES}[partition_rank] AS partition_asil,
       m.runnable AS runnable, m.swc AS swc, m.asil AS asil
ORDER BY os_app, runnable
""",
    },
    "mixed_criticality_cores": {
        "description": "Cores that run partitions of different ASIL levels (needs MPU + timing protection).",
        "cypher": f"""
MATCH {_CHAIN}
WITH c, a, max(s.asil_rank) AS app_rank
WITH c, collect(DISTINCT app_rank) AS ranks, collect(a.name) AS os_apps
WHERE size(ranks) > 1
RETURN c.name AS core, [x IN ranks | {_ASIL_NAMES}[x]] AS asil_levels, os_apps
ORDER BY core
""",
    },
    "trusted_partitions": {
        "description": "Trusted OS-Applications: they bypass memory protection.",
        "cypher": """
MATCH (a:OsApplication {trusted: true})
OPTIONAL MATCH (a)-[:RUNS_ON]->(c:Core)
RETURN a.name AS os_app, c.name AS core
ORDER BY os_app
""",
    },
    "unmapped_runnables": {
        "description": "Runnables not mapped to any task (they never run, or the mapping is missing).",
        "cypher": """
MATCH (s:SwComponent)-[:HAS_RUNNABLE]->(r:Runnable)
WHERE NOT EXISTS { (r)-[:MAPPED_TO]->(:Task) }
RETURN s.name AS swc, r.name AS runnable
ORDER BY swc, runnable
""",
    },
}


def run_query(session, name: str) -> list[dict]:
    """Run a named query and return rows as plain dicts."""
    if name not in QUERIES:
        raise KeyError(f"Unknown query '{name}'. Known: {', '.join(QUERIES)}")
    return session.run(QUERIES[name]["cypher"]).data()
