"""The in-memory model of an ECU, built with Pydantic.

Why Pydantic?
    Pydantic classes look like normal Python classes with type hints, but they
    *validate* their data: if you try to create a Core with core_id="abc" you get
    a clear error instead of a silent bug. Later (milestone 5) the same classes
    are used to force the LLM to answer in a fixed, checkable structure.

How the objects connect (the "FFI chain" for memory):

    SwComponent --has--> Runnable --mapped to--> Task --owned by--> OsApplication --runs on--> Core

Every object is identified by its AUTOSAR *path*, e.g.
"/DemoEcu/EcucConfig/Os/Task_AsilC_5ms". Short names are not unique in AUTOSAR,
paths are. Objects point to each other by path (a string), the same way ARXML
references work.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class Asil(str, Enum):
    """ISO 26262 integrity levels, from lowest (QM) to highest (D)."""

    QM = "QM"
    A = "A"
    B = "B"
    C = "C"
    D = "D"

    @property
    def rank(self) -> int:
        """Numeric order so we can compare levels: QM=0 ... D=4."""
        return ["QM", "A", "B", "C", "D"].index(self.value)


def highest_asil(levels: list[Asil]) -> Asil | None:
    """Return the highest ASIL in a list, or None if the list is empty."""
    return max(levels, key=lambda a: a.rank) if levels else None


class Core(BaseModel):
    name: str
    path: str
    core_id: int


class Runnable(BaseModel):
    name: str
    path: str
    swc: str  # path of the SwComponent that owns this runnable
    symbol: str | None = None  # name of the C function that implements it
    task: str | None = None  # path of the Task it is mapped to (None = unmapped)


class SwComponent(BaseModel):
    name: str
    path: str
    asil: Asil | None = None  # None = ASIL not specified in the ARXML
    runnables: list[str] = Field(default_factory=list)  # runnable paths


class Task(BaseModel):
    name: str
    path: str
    os_application: str | None = None  # path of the owning OsApplication
    runnables: list[str] = Field(default_factory=list)


class OsApplication(BaseModel):
    """An OS-Application = a memory-protection partition in AUTOSAR OS (SC3/SC4)."""

    name: str
    path: str
    trusted: bool = False  # trusted apps run in supervisor mode, NOT memory-protected
    core: str | None = None  # path of the Core
    tasks: list[str] = Field(default_factory=list)


class EcuModel(BaseModel):
    """Everything we know about one ECU. Dicts are keyed by AUTOSAR path."""

    cores: dict[str, Core] = Field(default_factory=dict)
    swcs: dict[str, SwComponent] = Field(default_factory=dict)
    runnables: dict[str, Runnable] = Field(default_factory=dict)
    tasks: dict[str, Task] = Field(default_factory=dict)
    os_applications: dict[str, OsApplication] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)  # problems found while parsing

    # ---- Convenience queries (in milestone 2 these become graph queries) ----

    def runnables_of_os_app(self, os_app_path: str) -> list[Runnable]:
        app = self.os_applications[os_app_path]
        return [
            self.runnables[r]
            for t in app.tasks
            if t in self.tasks
            for r in self.tasks[t].runnables
        ]

    def asil_levels_in_os_app(self, os_app_path: str) -> list[Asil]:
        """All ASIL levels of the SWCs whose runnables run in this OS-Application."""
        levels = []
        for r in self.runnables_of_os_app(os_app_path):
            asil = self.swcs[r.swc].asil
            if asil is not None and asil not in levels:
                levels.append(asil)
        return sorted(levels, key=lambda a: a.rank)

    def os_app_asil(self, os_app_path: str) -> Asil | None:
        """A partition must be developed to the highest ASIL of anything inside it."""
        return highest_asil(self.asil_levels_in_os_app(os_app_path))

    def os_apps_on_core(self, core_path: str) -> list[OsApplication]:
        return [a for a in self.os_applications.values() if a.core == core_path]
