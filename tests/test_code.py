"""Milestone 3 tests: C parser, map parser, and linking code to the ARXML model."""

from pathlib import Path

import pytest

from ffi_checker import parse_arxml
from ffi_checker.code import parse_c_sources, parse_map
from ffi_checker.code.link import link_code

ROOT = Path(__file__).parent.parent / "examples" / "demo_ecu"
ARXML, SRC, MAP = ROOT / "DemoEcu.arxml", ROOT / "src", ROOT / "DemoEcu.map"


def parse_snippet(tmp_path, text, name="X.c"):
    f = tmp_path / name
    f.write_text(text)
    return parse_c_sources([f])


def accesses(model, func):
    f = next(f for f in model.functions.values() if f.name == func)
    return {(a.variable.split("::")[1], a.kind) for a in f.accesses}


# ------------------------------------------------------------------ C parser


def test_variable_in_memmap_section(tmp_path):
    m = parse_snippet(tmp_path, """
#define ABC_START_SEC_VAR_ZERO_INIT_8BIT
#include "ABC_MemMap.h"
VAR(uint8, ABC_VAR) Abc_Flag = 0u;
#define ABC_STOP_SEC_VAR_ZERO_INIT_8BIT
#include "ABC_MemMap.h"
""")
    v = m.variables["X.c::Abc_Flag"]
    assert (v.type, v.section) == ("uint8", "ABC_VAR_ZERO_INIT_8BIT")


def test_variable_outside_section_has_no_section(tmp_path):
    m = parse_snippet(tmp_path, "uint8 Lonely = 1u;\n")
    assert m.variables["X.c::Lonely"].section is None


def test_extern_prototypes_and_typedefs_are_not_definitions(tmp_path):
    m = parse_snippet(tmp_path, """
extern uint8 Other;
void Helper(void);
typedef struct { uint8 a; } MyType;
static uint16 Counter;
""")
    assert set(m.variables) == {"X.c::Counter"}


def test_arrays_and_initializer_lists(tmp_path):
    m = parse_snippet(tmp_path, """
VAR(uint8, X_VAR) Table[4] = { 1, 2, 3, 4 };
uint8 Other;
""")
    assert set(m.variables) == {"X.c::Table", "X.c::Other"}


def test_code_section_is_not_a_variable_section(tmp_path):
    m = parse_snippet(tmp_path, """
#define ABC_START_SEC_CODE
#include "ABC_MemMap.h"
uint8 Oops = 0u;
#define ABC_STOP_SEC_CODE
#include "ABC_MemMap.h"
""")
    assert m.variables["X.c::Oops"].section is None


@pytest.mark.parametrize("stmt,expected", [
    ("V = 1u;", {"write"}),
    ("V += 2u;", {"write"}),
    ("V++;", {"write"}),
    ("--V;", {"write"}),
    ("x = V;", {"read"}),
    ("if (V == 3u) { }", {"read"}),
    ("if (V <= 3u && V >= 1u) { }", {"read"}),
    ("p = &V;", {"address-of"}),
    ("x = a & V;", {"read"}),
    ("V = V + 1u;", {"read", "write"}),
    ("W = 5u;", set()),  # a different variable with a similar name
])
def test_access_classification(tmp_path, stmt, expected):
    m = parse_snippet(tmp_path, f"uint8 V;\nuint8 W;\nvoid F(void)\n{{\n  {stmt}\n}}\n")
    got = {k for name, k in accesses(m, "F") if name == "V"}
    assert got == expected


def test_comments_are_ignored(tmp_path):
    m = parse_snippet(tmp_path, """
uint8 V;
/* V = 1u; */
void F(void) {
  // V = 2u;
  x = 3u;
}
""")
    assert accesses(m, "F") == set()


def test_nested_braces_in_function(tmp_path):
    m = parse_snippet(tmp_path, """
uint8 V;
void F(void) { if (1) { while (0) { V = 1u; } } }
void G(void) { }
""")
    assert accesses(m, "F") == {("V", "write")}
    assert accesses(m, "G") == set()


def test_same_name_in_two_files_prefers_own_file(tmp_path):
    (tmp_path / "a.c").write_text("static uint8 V;\nvoid A(void) { V = 1u; }\n")
    (tmp_path / "b.c").write_text("static uint8 V;\nvoid B(void) { V = 2u; }\n")
    m = parse_c_sources([tmp_path])
    assert {a.variable for f in m.functions.values() if f.name == "A" for a in f.accesses} == {"a.c::V"}
    assert {a.variable for f in m.functions.values() if f.name == "B" for a in f.accesses} == {"b.c::V"}


def test_ambiguous_extern_gives_warning(tmp_path):
    (tmp_path / "a.c").write_text("uint8 V;\n")
    (tmp_path / "b.c").write_text("uint8 V;\n")
    (tmp_path / "c.c").write_text("extern uint8 V;\nvoid C(void) { V = 1u; }\n")
    m = parse_c_sources([tmp_path])
    assert any("several files" in w for w in m.warnings)


# ------------------------------------------------------------------ map parser


def test_map_parser_reads_regions_and_sections():
    m = parse_map(MAP)
    assert set(m.regions) == {"RAM_ASIL_C_CORE0", "RAM_QM_CORE0", "RAM_ASIL_C_CORE1"}
    assert m.link_sections[".bss.DIAG_VAR_ZERO_INIT_32BIT"].region == "RAM_QM_CORE0"  # from address
    assert m.link_sections[".bss.BRAKECTRL_VAR_ZERO_INIT_8BIT"].region == "RAM_ASIL_C_CORE0"  # explicit
    assert m.warnings == []


def test_map_parser_reports_bad_lines(tmp_path):
    f = tmp_path / "bad.map"
    f.write_text("MEMORY R origin=zzz length=0x10\nNONSENSE\nSECTION .a address=0x1 size=0x1\n")
    m = parse_map(f)
    assert len(m.warnings) == 2 and ".a" in m.link_sections


# ------------------------------------------------------------------ demo ECU end to end


@pytest.fixture(scope="module")
def demo():
    ecu = parse_arxml([ARXML])
    code = parse_map(MAP, parse_c_sources([SRC]))
    return ecu, code, link_code(ecu, code)


def test_demo_variables_and_regions(demo):
    _, code, _ = demo
    placed = {v.name: (code.link_section_of(v).region if code.link_section_of(v) else None)
              for v in code.variables.values()}
    assert placed == {
        "BrakeCtrl_BrakeRequest": "RAM_ASIL_C_CORE0",
        "Diag_Counter": "RAM_QM_CORE0",
        "Diag_UnmappedFlag": None,
        "Hmi_Display": "RAM_ASIL_C_CORE1",
        "SpeedMon_Speed": "RAM_ASIL_C_CORE1",
    }
    assert code.warnings == []


def test_demo_owners(demo):
    ecu, code, links = demo
    owner = {code.variables[v].name: ecu.swcs[s].name for v, s in links.owners.items()}
    assert owner == {
        "BrakeCtrl_BrakeRequest": "BrakeCtrl", "Diag_Counter": "Diagnostics",
        "Diag_UnmappedFlag": "Diagnostics", "Hmi_Display": "HmiGateway",
        "SpeedMon_Speed": "SpeedMonitor",
    }


def test_demo_seeded_cross_asil_writes(demo):
    ecu, code, links = demo
    writes = {(ecu.runnables[r].name, code.variables[v].name, k)
              for r, v, k in links.accesses if k != "read"}
    assert ("Diag_Run100ms", "BrakeCtrl_BrakeRequest", "write") in writes
    assert ("Hmi_Run20ms", "SpeedMon_Speed", "write") in writes
    assert ("Hmi_Run20ms", "SpeedMon_Speed", "address-of") in writes
