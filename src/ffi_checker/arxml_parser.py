"""Read ARXML files and build an EcuModel.

Key AUTOSAR ideas used here
---------------------------
1. Identifiables and paths: any element with a <SHORT-NAME> child is an
   "identifiable". Its path is the chain of SHORT-NAMEs from the root, e.g.
   /DemoEcu/SwComponentTypes/BrakeCtrl. References (<...-REF>) contain such paths.

2. ECUC (ECU configuration): BSW modules (Os, Rte, EcuC, ...) are configured with
   generic <ECUC-CONTAINER-VALUE> elements. What a container *is* comes from its
   <DEFINITION-REF>, e.g. ".../Os/OsApplication". We only look at the LAST part
   of that path ("OsApplication"), so the parser works with MICROSAR
   ("/MICROSAR/Os/...") and with standard ("/AUTOSAR/EcucDefs/Os/...") definitions.

3. A real project splits its ARXML across many files. References can point from
   one file into another, so we first index ALL files, then resolve references.

We use only the Python standard library (xml.etree) to keep things simple.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from .model import Asil, Core, EcuModel, OsApplication, Runnable, SwComponent, Task

SWC_TAGS = {
    "APPLICATION-SW-COMPONENT-TYPE",
    "SENSOR-ACTUATOR-SW-COMPONENT-TYPE",
    "COMPLEX-DEVICE-DRIVER-SW-COMPONENT-TYPE",
    "SERVICE-SW-COMPONENT-TYPE",
    "ECU-ABSTRACTION-SW-COMPONENT-TYPE",
}


# --------------------------------------------------------------------------- helpers


def local(tag: str) -> str:
    """Drop the XML namespace: '{http://autosar.org/schema/r4.0}SHORT-NAME' -> 'SHORT-NAME'."""
    return tag.rsplit("}", 1)[-1]


def child(el: ET.Element, name: str) -> ET.Element | None:
    """First direct child with the given (namespace-free) tag name."""
    for c in el:
        if local(c.tag) == name:
            return c
    return None


def child_text(el: ET.Element, name: str) -> str | None:
    c = child(el, name)
    return c.text.strip() if c is not None and c.text else None


def descendants(el: ET.Element, name: str):
    """All elements below `el` (any depth) with the given tag name."""
    for d in el.iter():
        if local(d.tag) == name:
            yield d


def last_segment(path: str | None) -> str:
    return path.rsplit("/", 1)[-1] if path else ""


# --------------------------------------------------------------------------- indexing


def index_identifiables(root: ET.Element) -> dict[str, ET.Element]:
    """Walk the XML tree and return {autosar_path: element} for every identifiable."""
    index: dict[str, ET.Element] = {}

    def walk(el: ET.Element, parent_path: str) -> None:
        name = child_text(el, "SHORT-NAME")
        path = f"{parent_path}/{name}" if name else parent_path
        if name:
            index[path] = el
        for c in el:
            walk(c, path)

    walk(root, "")
    return index


# --------------------------------------------------------------------------- ECUC access


def ecuc_params(container: ET.Element) -> dict[str, str]:
    """{parameter name: value} for one ECUC container (direct parameters only)."""
    result = {}
    values = child(container, "PARAMETER-VALUES")
    if values is None:
        return result
    for p in values:
        name = last_segment(child_text(p, "DEFINITION-REF"))
        result[name] = child_text(p, "VALUE") or ""
    return result


def ecuc_refs(container: ET.Element) -> dict[str, list[str]]:
    """{reference name: [target paths]} for one ECUC container. A reference can repeat."""
    result: dict[str, list[str]] = {}
    values = child(container, "REFERENCE-VALUES")
    if values is None:
        return result
    for r in values:
        name = last_segment(child_text(r, "DEFINITION-REF"))
        target = child_text(r, "VALUE-REF")
        if target:
            result.setdefault(name, []).append(target)
    return result


def as_bool(text: str | None) -> bool:
    return (text or "").strip().lower() in {"true", "1"}


# --------------------------------------------------------------------------- main entry


def parse_arxml(files: list[str | Path]) -> EcuModel:
    """Parse one or more ARXML files into a single EcuModel."""
    index: dict[str, ET.Element] = {}
    for f in files:
        index.update(index_identifiables(ET.parse(f).getroot()))

    model = EcuModel()
    event_to_runnable: dict[str, str] = {}

    # Pass 1: create objects --------------------------------------------------
    for path, el in index.items():
        tag = local(el.tag)
        name = path.rsplit("/", 1)[-1]

        if tag in SWC_TAGS:
            model.swcs[path] = SwComponent(name=name, path=path, asil=_read_asil(el, path, model))

        elif tag == "RUNNABLE-ENTITY":
            swc_path = _owning_swc(path, index)
            model.runnables[path] = Runnable(
                name=name, path=path, swc=swc_path or "", symbol=child_text(el, "SYMBOL")
            )
            if swc_path is None:
                model.warnings.append(f"Runnable {path} is not inside a SW component")

        elif tag.endswith("-EVENT"):
            target = child_text(el, "START-ON-EVENT-REF")
            if target:
                event_to_runnable[path] = target

        elif tag == "ECUC-CONTAINER-VALUE":
            kind = last_segment(child_text(el, "DEFINITION-REF"))
            if kind == "EcucCoreDefinition":
                core_id = ecuc_params(el).get("EcucCoreId", "")
                if core_id.isdigit():
                    model.cores[path] = Core(name=name, path=path, core_id=int(core_id))
                else:
                    model.warnings.append(f"Core {path} has no valid EcucCoreId")
            elif kind == "OsTask":
                model.tasks[path] = Task(name=name, path=path)
            elif kind == "OsApplication":
                params, refs = ecuc_params(el), ecuc_refs(el)
                core = refs.get("OsApplicationCoreRef", [None])[0]
                model.os_applications[path] = OsApplication(
                    name=name,
                    path=path,
                    trusted=as_bool(params.get("OsTrusted")),
                    core=core,
                    tasks=refs.get("OsAppTaskRef", []),
                )

    for swc in model.swcs.values():
        swc.runnables = [r.path for r in model.runnables.values() if r.swc == swc.path]

    # Pass 2: resolve references (now that every object exists) -----------------
    for app in model.os_applications.values():
        if app.core and app.core not in model.cores:
            model.warnings.append(f"{app.name}: core reference {app.core} not found")
            app.core = None
        for t in app.tasks:
            if t in model.tasks:
                model.tasks[t].os_application = app.path
            else:
                model.warnings.append(f"{app.name}: task reference {t} not found")

    for path, el in index.items():
        if local(el.tag) != "ECUC-CONTAINER-VALUE":
            continue
        if last_segment(child_text(el, "DEFINITION-REF")) != "RteEventToTaskMapping":
            continue
        refs = ecuc_refs(el)
        event = refs.get("RteEventRef", [None])[0]
        task = refs.get("RteMappedToTaskRef", [None])[0]
        runnable = event_to_runnable.get(event or "")
        if runnable not in model.runnables:
            model.warnings.append(f"{path}: event {event} does not lead to a known runnable")
            continue
        if task not in model.tasks:
            model.warnings.append(f"{path}: task {task} not found")
            continue
        model.runnables[runnable].task = task
        if runnable not in model.tasks[task].runnables:
            model.tasks[task].runnables.append(runnable)

    for r in model.runnables.values():
        if r.task is None:
            model.warnings.append(f"Runnable {r.name} is not mapped to any task")
    for t in model.tasks.values():
        if t.os_application is None:
            model.warnings.append(f"Task {t.name} is not assigned to any OS-Application")

    return model


def _read_asil(swc_el: ET.Element, path: str, model: EcuModel) -> Asil | None:
    """Read ASIL from <SDG GID="FFI_CHECKER"><SD GID="ASIL">C</SD></SDG>."""
    for sdg in descendants(swc_el, "SDG"):
        if sdg.get("GID") != "FFI_CHECKER":
            continue
        for sd in sdg:
            if local(sd.tag) == "SD" and sd.get("GID") == "ASIL" and sd.text:
                value = sd.text.strip().upper().removeprefix("ASIL").strip() or "QM"
                try:
                    return Asil(value)
                except ValueError:
                    model.warnings.append(f"{path}: unknown ASIL value '{sd.text}'")
                    return None
    model.warnings.append(f"{path}: no ASIL specified")
    return None


def _owning_swc(runnable_path: str, index: dict[str, ET.Element]) -> str | None:
    """Walk up the path until we hit an element that is a SW component type."""
    parts = runnable_path.split("/")
    for i in range(len(parts) - 1, 0, -1):
        candidate = "/".join(parts[:i])
        el = index.get(candidate)
        if el is not None and local(el.tag) in SWC_TAGS:
            return candidate
    return None
