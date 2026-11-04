"""Milestone 4 tests: the TASKING map parser and the memory-FFI rules.

The synthetic example in examples/tc39x was built with 7 known problems and 3 known
non-problems. The first test is the important one: the engine must find exactly those.
"""

import json
import re
from pathlib import Path

import pytest

from ffi_checker.linkmap import parse_tasking_map
from ffi_checker.rules import compare, run_rules
from ffi_checker.rules.__main__ import build_report, main
from ffi_checker.spec import load_spec

EX = Path(__file__).parent.parent / "examples" / "tc39x"
MAP, SPEC, EXPECTED = EX / "synthetic_tc39x.map", EX / "partition_spec.json", EX / "expected_findings.json"


@pytest.fixture(scope="module")
def m():
    return parse_tasking_map(MAP)


@pytest.fixture(scope="module")
def spec():
    return load_spec(SPEC)


def findings_for(map_text, spec, tmp_path):
    f = tmp_path / "x.map"
    f.write_text(map_text)
    return run_rules(parse_tasking_map(f), spec)


# ----------------------------------------------------------------- the oracle


def test_engine_finds_exactly_the_expected_findings(m, spec):
    result = compare(run_rules(m, spec), EXPECTED)
    assert result.ok, result
    assert result.matched == ["F01", "F02", "F03", "F04", "F05", "F06", "F07"]


def test_expected_non_findings_are_not_reported(m, spec):
    reported = {f.symbol for f in run_rules(m, spec)} | {f.referenced_by for f in run_rules(m, spec)}
    assert "SpeedEst_Out" not in reported  # I01 cross-core, same ASIL
    assert "Com_IpduBuffer" not in reported  # I02 allowed shared BSW buffer
    assert "Dem_EventStatus" not in reported  # I03 BSW data in the wildcard group
    assert "TorqueArb" not in {f.referenced_by for f in run_rules(m, spec)}


def test_severities(m, spec):
    sev = {f.rule: set() for f in run_rules(m, spec)}
    for f in run_rules(m, spec):
        sev[f.rule].add(f.severity)
    assert sev["R4_xref"] == {"warning"}
    assert all(sev[r] == {"error"} for r in ("R1_placement", "R2_alignment", "R3_guard_pad", "R5_wildcard"))


def test_every_finding_has_evidence_with_a_source(m, spec):
    for f in run_rules(m, spec):
        assert f.evidence and all(e.source and e.text for e in f.evidence), f.fingerprint
        assert f.rule_text, f.fingerprint  # the rule as written in the spec travels with the finding


def test_map_evidence_points_at_the_right_line(m, spec):
    lines = MAP.read_text().splitlines()
    f = next(f for f in run_rules(m, spec) if f.symbol == "DiagLogger_RingBuf")
    line_no = int(f.evidence[0].source.rsplit(":", 1)[1])
    assert "DiagLogger_RingBuf" in lines[line_no - 1] and "ASIL_D_DATA_tc0" in lines[line_no - 1]


# ----------------------------------------------------------------- parser


def test_parser_reads_all_tables(m):
    assert (len(m.sections), len(m.symbols), len(m.xrefs), len(m.group_ranges)) == (58, 101, 10, 27)
    assert m.warnings == []


def test_parser_values(m):
    s = next(s for s in m.sections if s.symbol == "DiagLogger_RingBuf")
    assert (s.group, s.size, s.address, s.module, s.kind) == ("ASIL_D_DATA_tc0", 0x200, 0x70005618, "DiagLogger", "bss")
    assert m.symbols["_lc_ge_ASIL_D_DATA_tc1"].address == 0x6000556C
    assert m.group_ranges["Mpu_ReservedCorePad_tc2"].size == 0
    x = next(x for x in m.xrefs if x.symbol == "SafetyMon_State")
    assert (x.defined_in, x.referenced_in) == ("SafetyMon.o", ["SafetyMon.o", "InfoGw.o"])


def test_special_sections_have_no_module(m):
    special = [s for s in m.sections if s.name.startswith(("ustack", "istack", "csa")) or "ReservedCorePad" in s.name]
    assert special and all(s.module is None for s in special)


def test_parser_warns_on_a_bad_row(tmp_path):
    f = tmp_path / "bad.map"
    f.write_text(MAP.read_text().replace("0x00000200 | 0x70005618", "0xZZZ | 0x70005618", 1))
    assert any("cannot read" in w for w in parse_tasking_map(f).warnings)


def test_parser_warns_when_no_section_table(tmp_path):
    f = tmp_path / "empty.map"
    f.write_text("nothing useful here\n")
    assert any("no 'Locate Result'" in w for w in parse_tasking_map(f).warnings)


# ----------------------------------------------------------------- rules, one change at a time


def test_fixing_the_alignment_removes_only_r2(spec, tmp_path):
    text = MAP.read_text().replace("| _lc_ge_ASIL_D_DATA_tc1         | 0x6000556c |", "| _lc_ge_ASIL_D_DATA_tc1         | 0x60005570 |")
    rules = {f.rule for f in findings_for(text, spec, tmp_path)}
    assert "R2_alignment" not in rules and len(rules) == 4


def test_guard_pad_rule_uses_the_gap_not_only_the_pad_size(spec, tmp_path):
    # tc1's pad group is 0x10 big but also fine as a gap; make the QM group start right after ASIL_D
    text = MAP.read_text().replace("| QM_DATA_tc1             | ordered contiguous | 0x60005580 |",
                                   "| QM_DATA_tc1             | ordered contiguous | 0x60005570 |")
    f = [x for x in findings_for(text, spec, tmp_path) if x.rule == "R3_guard_pad"]
    assert {x.group for x in f} == {"Mpu_ReservedCorePad_tc1", "Mpu_ReservedCorePad_tc2"}


def test_qm_module_in_its_own_partition_is_fine(m, spec):
    assert not [f for f in run_rules(m, spec) if f.symbol in {"BodyCtl_Lamps", "Telemetry_Frame", "InfoGw_RxBuf"}]


def test_unknown_module_gives_a_warning_not_silence(spec, tmp_path):
    text = MAP.read_text().replace(".bss.BodyCtl.BodyCtl_Lamps", ".bss.Mystery.BodyCtl_Lamps")
    f = [x for x in findings_for(text, spec, tmp_path) if x.symbol == "BodyCtl_Lamps"]
    assert f and f[0].severity == "warning" and "not in the spec" in f[0].detail


def test_missing_group_gives_a_warning(spec, tmp_path):
    text = "\n".join(l for l in MAP.read_text().splitlines() if "| QM_DATA_tc0 " not in l or "ordered" not in l)
    f = [x for x in findings_for(text, spec, tmp_path) if x.rule == "R3_guard_pad" and x.group.endswith("tc0")]
    assert f and f[0].severity == "warning"


def test_asil_object_in_a_wrong_but_higher_partition_is_still_an_error(spec, tmp_path):
    # SpeedEst (ASIL D, core 1) moved into core 0's ASIL D group: ASIL fits, but it is not listed there
    text = MAP.read_text().replace(
        "| mpe:dspr1  | ASIL_D_DATA_tc1         | .bss.SpeedEst.SpeedEst_Out (122)",
        "| mpe:dspr1  | ASIL_D_DATA_tc0         | .bss.SpeedEst.SpeedEst_Out (122)")
    f = [x for x in findings_for(text, spec, tmp_path) if x.symbol == "SpeedEst_Out" and x.rule == "R1_placement"]
    assert f and "not assigned to partition" in f[0].detail


# ----------------------------------------------------------------- report and CLI


def test_report_has_hashes_and_no_llm(m, spec):
    rep = build_report(run_rules(m, spec), {"map": str(MAP), "spec": str(SPEC)})
    assert rep["llm_used"] is False and rep["summary"] == {"errors": 5, "warnings": 2}
    assert re.fullmatch(r"[0-9a-f]{64}", rep["inputs"]["map"]["sha256"])
    assert {f["id"] for f in rep["findings"]} >= {"R3_guard_pad:Mpu_ReservedCorePad_tc2"}


def test_cli_matches_expected_and_writes_report(tmp_path, capsys):
    out = tmp_path / "report.json"
    code = main(["--map", str(MAP), "--spec", str(SPEC), "--expected", str(EXPECTED), "--out", str(out)])
    assert code == 0
    assert "matched 7, missing 0, unexpected 0" in capsys.readouterr().out
    assert json.loads(out.read_text())["summary"]["errors"] == 5


def test_cli_exit_codes(tmp_path):
    assert main(["--map", str(MAP), "--spec", str(SPEC), "--strict"]) == 1
    wrong = tmp_path / "expected.json"
    wrong.write_text(json.dumps({"expected_findings": [{"id": "X", "rule": "R2_alignment", "severity": "error", "symbol": "nope"}]}))
    assert main(["--map", str(MAP), "--spec", str(SPEC), "--expected", str(wrong)]) == 2
