"""Tests for milestone 1. Run with:  pytest

Tests are your safety net: when you change the parser later, they tell you
immediately if something that used to work is now broken.
"""

from pathlib import Path

from ffi_checker import Asil, parse_arxml

DEMO = Path(__file__).parent.parent / "examples" / "demo_ecu" / "DemoEcu.arxml"
OS = "/DemoEcu/EcucConfig/Os"
SWC = "/DemoEcu/SwComponentTypes"


def test_counts():
    m = parse_arxml([DEMO])
    assert len(m.cores) == 2
    assert len(m.swcs) == 4
    assert len(m.runnables) == 4
    assert len(m.tasks) == 3
    assert len(m.os_applications) == 3
    assert m.warnings == []


def test_asil_is_read_from_sdg():
    m = parse_arxml([DEMO])
    assert m.swcs[f"{SWC}/BrakeCtrl"].asil == Asil.C
    assert m.swcs[f"{SWC}/HmiGateway"].asil == Asil.QM


def test_full_chain_runnable_to_core():
    m = parse_arxml([DEMO])
    run = m.runnables[f"{SWC}/BrakeCtrl/BrakeCtrl_IB/BrakeCtrl_Run10ms"]
    task = m.tasks[run.task]
    app = m.os_applications[task.os_application]
    core = m.cores[app.core]
    assert (task.name, app.name, core.core_id) == ("Task_AsilC_10ms", "OsApp_AsilC_Core0", 0)
    assert app.trusted is True


def test_seeded_mixed_asil_partition_is_visible():
    m = parse_arxml([DEMO])
    assert m.asil_levels_in_os_app(f"{OS}/OsApp_AsilC_Core1") == [Asil.QM, Asil.C]
    assert m.os_app_asil(f"{OS}/OsApp_AsilC_Core1") == Asil.C


def test_asil_ordering():
    assert Asil.QM.rank < Asil.A.rank < Asil.D.rank


def test_broken_reference_gives_warning(tmp_path):
    broken = tmp_path / "broken.arxml"
    broken.write_text(
        DEMO.read_text().replace(f"{OS}/Task_QM_100ms</VALUE-REF>", f"{OS}/Task_Typo</VALUE-REF>", 1)
    )
    m = parse_arxml([broken])
    assert any("Task_Typo" in w for w in m.warnings)


def test_model_split_across_files(tmp_path):
    """Real projects spread ARXML over many files; references must still resolve."""
    text = DEMO.read_text()
    start = text.index("<!-- ===================== ECU configuration")
    end = text.index("</AR-PACKAGES>\n    </AR-PACKAGE>")
    head, ecuc, tail = text[:start], text[start:end], text[end:]
    (tmp_path / "swc.arxml").write_text(head + tail)
    (tmp_path / "ecuc.arxml").write_text(
        text[: text.index("<AR-PACKAGES>", text.index("<SHORT-NAME>DemoEcu")) + len("<AR-PACKAGES>")]
        + ecuc
        + tail
    )
    m = parse_arxml([tmp_path / "swc.arxml", tmp_path / "ecuc.arxml"])
    assert len(m.runnables) == 4 and all(r.task for r in m.runnables.values())
    assert m.warnings == []
