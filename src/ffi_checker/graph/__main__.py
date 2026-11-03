"""Graph command line.

    python -m ffi_checker.graph load examples/demo_ecu/DemoEcu.arxml --reset
    python -m ffi_checker.graph list
    python -m ffi_checker.graph query lower_asil_in_partition
    python -m ffi_checker.graph query-all

Needs a running Neo4j (see docker-compose.yml) and `pip install -e ".[graph]"`.
"""

from __future__ import annotations

import argparse
import sys

from ..arxml_parser import parse_arxml
from .loader import connect, load_graph
from .queries import QUERIES, run_query
from .schema import to_graph


def print_rows(rows: list[dict]) -> None:
    if not rows:
        print("  (no results)")
        return
    for row in rows:
        print("  " + ", ".join(f"{k}={v}" for k, v in row.items()))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m ffi_checker.graph")
    sub = p.add_subparsers(dest="cmd", required=True)
    load = sub.add_parser("load", help="parse ARXML and load it into Neo4j")
    load.add_argument("arxml", nargs="+")
    load.add_argument("--reset", action="store_true", help="delete everything in the database first")
    sub.add_parser("list", help="list the named queries")
    q = sub.add_parser("query", help="run one named query")
    q.add_argument("name", choices=list(QUERIES))
    sub.add_parser("query-all", help="run every named query")
    args = p.parse_args(argv)

    if args.cmd == "list":
        for name, q in QUERIES.items():
            print(f"{name:26} {q['description']}")
        return 0

    driver = connect()
    try:
        with driver.session() as session:
            if args.cmd == "load":
                model = parse_arxml(args.arxml)
                graph = to_graph(model)
                load_graph(session, graph, reset=args.reset)
                print(f"Loaded {len(graph.nodes)} nodes and {len(graph.rels)} relationships.")
                for w in model.warnings:
                    print(f"  warning: {w}")
                print("Open http://localhost:7474 and try:  MATCH (n) RETURN n")
            elif args.cmd == "query":
                print(f"{args.name}: {QUERIES[args.name]['description']}")
                print_rows(run_query(session, args.name))
            elif args.cmd == "query-all":
                for name, q in QUERIES.items():
                    print(f"\n{name}: {q['description']}")
                    print_rows(run_query(session, name))
    finally:
        driver.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
