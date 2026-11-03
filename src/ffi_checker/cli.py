"""Command line entry point.

Usage:
    python -m ffi_checker examples/demo_ecu/DemoEcu.arxml [more.arxml ...]

Milestone 1 only *shows* the partition mapping and a few observations. The real
rule engine with findings and evidence comes in milestone 4.
"""

from __future__ import annotations

import argparse
import sys

from .arxml_parser import parse_arxml
from .model import EcuModel


def print_mapping(model: EcuModel) -> None:
    for core in sorted(model.cores.values(), key=lambda c: c.core_id):
        print(f"{core.name} (id {core.core_id})")
        for app in model.os_apps_on_core(core.path):
            asil = model.os_app_asil(app.path)
            trust = "trusted" if app.trusted else "non-trusted"
            print(f"  OS-Application {app.name}  [{trust}, ASIL {asil.value if asil else '?'}]")
            for t in app.tasks:
                task = model.tasks.get(t)
                if task is None:
                    continue
                print(f"    Task {task.name}")
                for r in task.runnables:
                    run = model.runnables[r]
                    swc = model.swcs[run.swc]
                    level = swc.asil.value if swc.asil else "?"
                    print(f"      Runnable {run.name}  (SWC {swc.name}, ASIL {level})")


def print_observations(model: EcuModel) -> None:
    """Simple FFI-relevant observations. Not formal findings yet."""
    print("\nObservations:")
    found = False
    for app in model.os_applications.values():
        levels = model.asil_levels_in_os_app(app.path)
        if len(levels) > 1:
            found = True
            print(
                f"  [MIXED-ASIL-PARTITION] {app.name} contains SWCs with ASIL "
                f"{', '.join(a.value for a in levels)}. Code inside one partition is not "
                f"protected from other code in it, so all of it must meet ASIL {levels[-1].value}."
            )
        if app.trusted and model.os_app_asil(app.path) is not None:
            found = True
            print(
                f"  [TRUSTED-PARTITION] {app.name} is trusted: it is not restricted by the MPU. "
                f"Make sure its content is developed to the highest ASIL on the ECU."
            )
    for core in model.cores.values():
        app_levels = {model.os_app_asil(a.path) for a in model.os_apps_on_core(core.path)}
        app_levels.discard(None)
        if len(app_levels) > 1:
            found = True
            print(
                f"  [MIXED-CRITICALITY-CORE] {core.name} runs partitions with ASIL "
                f"{', '.join(sorted(a.value for a in app_levels))}. Allowed, but needs memory "
                f"and timing protection (checked in later milestones)."
            )
    if not found:
        print("  none")

    if model.warnings:
        print("\nParser warnings:")
        for w in model.warnings:
            print(f"  - {w}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="FFI compliance checker (milestone 1)")
    parser.add_argument("arxml", nargs="+", help="ARXML file(s) of one ECU")
    parser.add_argument("--json", action="store_true", help="dump the parsed model as JSON")
    args = parser.parse_args(argv)

    model = parse_arxml(args.arxml)
    if args.json:
        print(model.model_dump_json(indent=2))
    else:
        print_mapping(model)
        print_observations(model)
    return 0


if __name__ == "__main__":
    sys.exit(main())
