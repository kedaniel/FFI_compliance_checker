"""Memory-FFI rules R1 to R5. Pure functions: (map, spec) -> findings. No LLM, no network.

R1 placement   every object must sit in a group owned by a partition that lists its module
               and whose ASIL is at least the module's ASIL (shared groups: ASIL must be allowed)
R2 alignment   every MPU region boundary (_lc_gb_/_lc_ge_ symbol) must be a multiple of the
               MPU granularity
R3 guard pad   between ASIL data and QM data of a core there must be a gap of min_bytes
R4 xref        a QM module referencing ASIL data is a potential interference. The map cannot
               tell a read from a write, so this is a warning
R5 wildcard    no ASIL-rated object in the WILDCARD group (a catch-all for sections that have
               no MemMap, so ASIL data there means a MemMap section is missing)

Each rule returns findings with evidence: the map line(s) and spec entries it was based on.
"""

from __future__ import annotations

from ..linkmap import CrossRef, MapModel, MapSection
from ..spec import ASIL_RANK, PLATFORM_CLASSES, Partition, Spec, asil_rated
from .model import Evidence, Finding


def _hex(value: int) -> str:
    return f"0x{value:08x}"


def _rule_text(spec: Spec, rule: str) -> str:
    return spec.rules.get(rule, "")


def _partition_ev(p: Partition) -> Evidence:
    return Evidence(
        source=f"spec: partitions[{p.name}]",
        text=f"core {p.core}, ASIL {p.asil}, {'trusted' if p.trusted else 'non-trusted'}, "
             f"modules {p.modules}, groups {p.groups}",
    )


def _section_ev(m: MapModel, s: MapSection) -> Evidence:
    return Evidence(
        source=m.ref(s.line),
        text=f"section {s.name} (size {s.size:#x}) placed at {_hex(s.address)} in group {s.group}",
    )


def _module_fits(partition: Partition, module: str, module_asil: str) -> bool:
    """Is `module` allowed in `partition`? It must be listed there, and for ASIL modules the
    partition must have at least the module's ASIL. OS and BSW code takes the integrity of
    the partition it is listed in."""
    if module not in partition.modules:
        return False
    if module_asil in PLATFORM_CLASSES:
        return True
    return (
        module_asil in ASIL_RANK
        and partition.asil in ASIL_RANK
        and ASIL_RANK[partition.asil] >= ASIL_RANK[module_asil]
    )


def _objects(m: MapModel):
    """Data objects: sections with a group and a Module/Symbol name. Skips code (no group),
    stacks and guard pads (names without a module)."""
    return [s for s in m.sections if s.group and s.module and s.kind != "text"]


# ------------------------------------------------------------------------------ R1


def check_placement(m: MapModel, spec: Spec) -> list[Finding]:
    rule, out = "R1_placement", []
    for s in _objects(m):
        shared = spec.shared_group(s.group)
        if shared and shared.is_wildcard:
            continue  # R5 owns the wildcard group
        module_asil = spec.module_asil.get(s.module)
        base = dict(rule=rule, symbol=s.symbol, module=s.module, group=s.group,
                    rule_text=_rule_text(spec, rule))
        if module_asil is None:
            out.append(Finding(severity="warning", detail=f"module {s.module} is not in the spec "
                               "(module_asil), cannot check its placement",
                               evidence=[_section_ev(m, s)], **base))
            continue

        if shared:
            if module_asil not in shared.allowed_asil:
                out.append(Finding(
                    severity="error",
                    detail=f"{module_asil} object located in shared group {s.group}, "
                           f"which allows only {shared.allowed_asil}",
                    evidence=[_section_ev(m, s), Evidence(
                        source=f"spec: shared_groups[{shared.group}]",
                        text=f"allowed_asil {shared.allowed_asil}")], **base))
            continue

        owner = spec.partition_of_group(s.group)
        if owner is None:
            out.append(Finding(severity="warning", detail=f"group {s.group} belongs to no partition "
                               "and is not a shared group", evidence=[_section_ev(m, s)], **base))
            continue
        if _module_fits(owner, s.module, module_asil):
            continue

        home = spec.partition_of_module(s.module)
        if module_asil in ASIL_RANK and owner.asil in ASIL_RANK and \
                ASIL_RANK[module_asil] > ASIL_RANK[owner.asil]:
            why = (f"ASIL-{module_asil} object located in {owner.asil} partition {owner.name}"
                   + ("" if owner.trusted else " (non-trusted, writable by QM code)"))
        elif module_asil in ASIL_RANK and owner.asil in ASIL_RANK and \
                ASIL_RANK[module_asil] < ASIL_RANK[owner.asil]:
            why = f"{module_asil} object located inside ASIL-{owner.asil} partition {owner.name}"
        else:
            why = f"module {s.module} ({module_asil}) is not assigned to partition {owner.name}"
        ev = [_section_ev(m, s), _partition_ev(owner)]
        if home:
            ev.append(Evidence(source=f"spec: partitions[{home.name}]",
                               text=f"module {s.module} belongs to this partition (groups {home.groups})"))
        out.append(Finding(severity="error", detail=why, evidence=ev, **base))
    return out


# ------------------------------------------------------------------------------ R2


def check_alignment(m: MapModel, spec: Spec) -> list[Finding]:
    rule, g, out = "R2_alignment", spec.mpu.granularity_bytes, []
    for sym in m.symbols.values():
        if not sym.name.startswith(("_lc_gb_", "_lc_ge_")):
            continue
        if sym.address % g != 0:
            edge = "start" if sym.name.startswith("_lc_gb_") else "end"
            out.append(Finding(
                rule=rule, severity="error", symbol=sym.name, address=_hex(sym.address),
                group=sym.name[len("_lc_gb_"):],
                detail=f"MPU region {edge} not {g}-byte aligned (address {_hex(sym.address)}, "
                       f"remainder {sym.address % g})",
                rule_text=_rule_text(spec, rule),
                evidence=[Evidence(source=m.ref(sym.line), text=f"{sym.name} = {_hex(sym.address)}"),
                          Evidence(source="spec: mpu.granularity_bytes", text=str(g))]))
    return out


# ------------------------------------------------------------------------------ R3


def check_guard_pad(m: MapModel, spec: Spec) -> list[Finding]:
    rule, pad, out = "R3_guard_pad", spec.guard_pad, []
    for core in spec.cores():
        a_name, b_name = (t.replace("{n}", str(core)) for t in pad.between)
        pad_name = pad.group.replace("{n}", str(core))
        a, b = m.group_ranges.get(a_name), m.group_ranges.get(b_name)
        base = dict(rule=rule, group=pad_name, rule_text=_rule_text(spec, rule))
        if a is None or b is None:
            missing = a_name if a is None else b_name
            out.append(Finding(severity="warning", detail=f"group {missing} not found in the map, "
                               f"cannot check the guard pad on core {core}", **base))
            continue
        gap = b.start - a.end if a.start < b.start else a.start - b.end
        if gap >= pad.min_bytes:
            continue
        pad_range = m.group_ranges.get(pad_name)
        pad_size = pad_range.size if pad_range else 0
        ev = [Evidence(source=m.ref(a.line), text=f"{a_name}: {_hex(a.start)} - {_hex(a.end)} (end exclusive)"),
              Evidence(source=m.ref(b.line), text=f"{b_name}: {_hex(b.start)} - {_hex(b.end)}")]
        if pad_range:
            ev.append(Evidence(source=m.ref(pad_range.line),
                               text=f"{pad_name}: size {pad_range.size:#x}"))
        ev.append(Evidence(source="spec: guard_pad.min_bytes", text=str(pad.min_bytes)))
        out.append(Finding(
            severity="error", evidence=ev, **base,
            detail=f"guard pad size {pad_size} between {a_name} and {b_name} "
                   f"(gap {gap} bytes, required {pad.min_bytes})"))
    return out


# ------------------------------------------------------------------------------ R4


def check_xref(m: MapModel, spec: Spec) -> list[Finding]:
    rule, out = "R4_xref", []
    for x in m.xrefs:
        owner = CrossRef.module_of(x.defined_in)
        owner_asil = spec.module_asil.get(owner)
        if not asil_rated(owner_asil):
            continue
        home = spec.partition_of_module(owner)
        core = f" (core {home.core})" if home else ""
        for ref in x.referenced_in:
            user = CrossRef.module_of(ref)
            if user == owner or spec.module_asil.get(user) != "QM":
                continue
            out.append(Finding(
                rule=rule, severity="warning", symbol=x.symbol, module=owner, referenced_by=user,
                detail=f"QM module references ASIL-{owner_asil} data{core}: the map cannot tell "
                       "a read from a write, so check the code",
                rule_text=_rule_text(spec, rule),
                evidence=[Evidence(source=m.ref(x.line),
                                   text=f"{x.symbol} defined in {x.defined_in}, referenced in "
                                        f"{', '.join(x.referenced_in)}"),
                          Evidence(source="spec: module_asil",
                                   text=f"{owner} = {owner_asil}, {user} = QM")]))
    return out


# ------------------------------------------------------------------------------ R5


def check_wildcard(m: MapModel, spec: Spec) -> list[Finding]:
    rule, out = "R5_wildcard", []
    wildcards = {s.group for s in spec.shared_groups if s.is_wildcard}
    for s in _objects(m):
        if s.group not in wildcards:
            continue
        module_asil = spec.module_asil.get(s.module)
        if asil_rated(module_asil):
            sg = spec.shared_group(s.group)
            out.append(Finding(
                rule=rule, severity="error", symbol=s.symbol, module=s.module, group=s.group,
                detail=f"ASIL-{module_asil} object fell into shared wildcard group (missing MemMap?)",
                rule_text=_rule_text(spec, rule),
                evidence=[_section_ev(m, s),
                          Evidence(source=f"spec: shared_groups[{s.group}]",
                                   text=f"allowed_asil {sg.allowed_asil}; {sg.note or ''}".strip())]))
    return out


ALL_RULES = [check_placement, check_alignment, check_guard_pad, check_xref, check_wildcard]


def run_rules(m: MapModel, spec: Spec) -> list[Finding]:
    findings = [f for rule in ALL_RULES for f in rule(m, spec)]
    return sorted(findings, key=lambda f: (f.rule, f.fingerprint))
