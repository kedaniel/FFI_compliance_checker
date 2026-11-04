"""A small parser for AUTOSAR-style generated C code. No compiler needed.

What it finds
-------------
* Variable definitions at file level, and the MemMap section they are inside:

      #define BRAKECTRL_START_SEC_VAR_ZERO_INIT_8BIT
      #include "BrakeCtrl_MemMap.h"
      VAR(uint8, BRAKECTRL_VAR) BrakeCtrl_BrakeRequest = 0u;
      #define BRAKECTRL_STOP_SEC_VAR_ZERO_INIT_8BIT
      #include "BrakeCtrl_MemMap.h"

* Function definitions, and for each one which known variables it reads / writes.

Why not a real C parser (libclang, tree-sitter)?
    A regex-and-brace-counting parser is easy to read and good enough to learn the
    ideas on generated code, which is very regular. Its limits are listed in the
    README ("Known simplifications"). Replacing it with tree-sitter later only
    changes this file.
"""

from __future__ import annotations

import re
from pathlib import Path

from .model import Access, AccessKind, CodeModel, Function, Variable

START_SEC = re.compile(r"^\s*#\s*define\s+(\w+?)_START_SEC_(\w+)")
STOP_SEC = re.compile(r"^\s*#\s*define\s+(\w+?)_STOP_SEC_(\w+)")
VAR_MACRO = re.compile(r"^(?:VAR|CONST)\s*\(\s*([^,()]+?)\s*,[^)]*\)\s*(\w+)\s*(?:\[[^\]]*\])?$")
PLAIN_DEF = re.compile(r"^([\w\s\*]+?)[\s\*]+(\w+)\s*(?:\[[^\]]*\])?$")
FUNC_HEADER = re.compile(r"(\w+)\s*\([^()]*\)\s*$")
STORAGE_WORDS = {"static", "volatile", "const", "register"}
SKIP_START = ("extern", "typedef", "return", "else", "if", "for", "while", "do", "switch")

WRITE_AFTER = r"\s*(?:\[[^\]]*\])?\s*(?:=(?!=)|[-+*/%&|^]=|<<=|>>=|\+\+|--)"
WRITE_BEFORE = r"(?:\+\+|--)\s*$"
ADDR_BEFORE = r"&\s*$"


def strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def _parse_definition(statement: str) -> tuple[str, str] | None:
    """Return (type, name) if `statement` (text before ';' and '=') defines a variable."""
    stmt = " ".join(statement.split())
    if not stmt or stmt.startswith(SKIP_START):
        return None
    words = stmt.split(" ")
    while words and words[0] in STORAGE_WORDS:
        words.pop(0)
    stmt = " ".join(words)
    m = VAR_MACRO.match(stmt)
    if m:
        return m.group(1).strip(), m.group(2)
    if "(" in stmt:  # a prototype or macro call, not a variable
        return None
    m = PLAIN_DEF.match(stmt)
    if m:
        return m.group(1).strip(), m.group(2)
    return None


def _scan_file(path: Path, rel: str, model: CodeModel) -> list[tuple[str, str]]:
    """Find variable definitions and function bodies. Returns [(function name, body)]."""
    text = strip_comments(path.read_text(encoding="utf-8", errors="replace"))
    sections: list[str] = []
    functions: list[tuple[str, str]] = []
    depth, buf, header, body = 0, "", "", []

    def finish_statement(stmt: str) -> None:
        stmt = stmt.split("=", 1)[0]
        parsed = _parse_definition(stmt)
        if parsed is None:
            return
        vtype, name = parsed
        var = Variable(
            name=name, path=f"{rel}::{name}", file=rel, type=vtype,
            section=sections[-1] if sections and re.match(r"^\w+?_(VAR|CONST)", sections[-1]) else None,
        )
        model.variables[var.path] = var

    for line in text.splitlines():
        m = START_SEC.match(line)
        if m and depth == 0:
            sections.append(f"{m.group(1)}_{m.group(2)}")
            continue
        m = STOP_SEC.match(line)
        if m and depth == 0:
            if sections:
                sections.pop()
            continue
        if line.lstrip().startswith("#"):
            continue
        for ch in line + "\n":
            if ch == "{":
                if depth == 0:
                    header, body = buf.strip(), []
                    buf = ""
                else:
                    body.append(ch)
                depth += 1
            elif ch == "}" and depth > 0:
                depth -= 1
                if depth == 0:
                    if header.endswith("="):  # initializer list: `VAR(..) a[2] = { 1, 2 };`
                        buf = header
                    else:
                        fm = FUNC_HEADER.search(header)
                        if fm and not header.startswith(SKIP_START):
                            functions.append((fm.group(1), "".join(body)))
                        buf = ""
                else:
                    body.append(ch)
            elif depth > 0:
                body.append(ch)
            elif ch == ";":
                finish_statement(buf)
                buf = ""
            else:
                buf += ch
    return functions


def _classify(body: str, name: str) -> set[AccessKind]:
    kinds: set[AccessKind] = set()
    for m in re.finditer(rf"\b{re.escape(name)}\b", body):
        before, after = body[: m.start()], body[m.end():]
        if (
            re.search(ADDR_BEFORE, before)
            and not re.search(r"[\w)\]]\s*&\s*$", before)  # `a & V`: bitwise AND
            and not re.search(r"&&\s*$", before)  # `a && V`: logical AND
        ):
            kinds.add("address-of")
        elif re.match(WRITE_AFTER, after) or re.search(WRITE_BEFORE, before):
            kinds.add("write")
        else:
            kinds.add("read")
    return kinds


def parse_c_sources(paths: list[str | Path]) -> CodeModel:
    """Parse .c/.h files (or whole folders) into a CodeModel (without map information)."""
    files: list[Path] = []
    for p in map(Path, paths):
        files += sorted(f for f in p.rglob("*") if f.suffix in {".c", ".h"}) if p.is_dir() else [p]

    model = CodeModel()
    bodies: list[tuple[str, str, str]] = []  # (file, function, body)
    for f in files:
        for fname, body in _scan_file(f, f.name, model):
            bodies.append((f.name, fname, body))

    by_name: dict[str, list[Variable]] = {}
    for v in model.variables.values():
        by_name.setdefault(v.name, []).append(v)

    for file, fname, body in bodies:
        func = Function(name=fname, file=file)
        for name, candidates in by_name.items():
            if not re.search(rf"\b{re.escape(name)}\b", body):
                continue
            own = [v for v in candidates if v.file == file]
            if own:
                target = own[0]
            elif len(candidates) == 1:
                target = candidates[0]
            else:
                model.warnings.append(f"{fname}: '{name}' is defined in several files, skipped")
                continue
            func.accesses += [Access(variable=target.path, kind=k)
                              for k in sorted(_classify(body, name))]
        model.functions[f"{file}::{fname}"] = func
    return model
