# FFI Compliance Checker

A learning project: a tool that checks **ISO 26262 Freedom From Interference (FFI)**
on AUTOSAR ARXML and Vector MICROSAR generated code (TASKING compiler), combining
**deterministic checks** with **GenAI** (LLMs, RAG, MCP, agents).

> Proof of concept. All example data in this repo is **synthetic**. Never commit
> real customer ARXML or code (the `customer_data/` folder is git-ignored).

## Design principle

The verdict "is this FFI violation real?" is always made by **deterministic code**
(parser + rules), never by the LLM. The LLM explains, investigates, cites sources and
drafts reports on top of those findings. That keeps results repeatable and auditable,
and the tool still works if a customer does not allow any LLM.

```
ARXML + generated C + map file
        │
        ▼
 [1] Parser ──► [2] Graph model ──► [4] Rule engine ──► Findings + evidence
                                          │
                     [6] RAG (standards,  ▼
                     safety reqs) ──► [5/8] LLM agents ──► Explanations, report draft
                                          ▲
                                [7] MCP tools (query the model)
```

## Roadmap: one concept per milestone

| # | Milestone | You learn | Status |
|---|-----------|-----------|--------|
| 1 | Parse a synthetic ECU (ARXML) into Pydantic models | XML, AUTOSAR paths and ECUC, Pydantic, pytest | ✅ |
| 2 | Load the model into **Neo4j** and query it with Cypher | Graph databases, Cypher | ✅ |
| 3 | Parse generated C (MemMap sections) and the linker map | Static code extraction | ✅ |
| 4 | Memory-FFI rule engine with findings and evidence | Rules as code, traceability | ⬜ |
| 5 | Explain findings with a local LLM (**Ollama** + **Pydantic AI**) | Prompting, structured output | ⬜ |
| 6 | **RAG** over AUTOSAR specs and safety notes (**LlamaIndex** + **Chroma**) | Embeddings, chunking, retrieval | ⬜ |
| 7 | Expose the model as an **MCP server** | Tools for LLMs | ⬜ |
| 8 | Agent pipeline with human review (**LangGraph**) | Agents, state, checkpoints | ⬜ |
| 9 | Evaluation set, Docker, swappable model config | Portability to customer LLMs | ⬜ |

Scope: memory FFI first, Safe OS **SC3**, ASIL up to **D**, QM and ASIL partitions on
the same core supported. Timing (SC4) and communication FFI come later.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

python -m ffi_checker examples/demo_ecu/DemoEcu.arxml
pytest
```

Expected output (shortened):

```
Core1 (id 1)
  OS-Application OsApp_AsilC_Core1  [non-trusted, ASIL C]
    Task Task_AsilC_5ms
      Runnable SpeedMon_Run5ms  (SWC SpeedMonitor, ASIL C)
      Runnable Hmi_Run20ms  (SWC HmiGateway, ASIL QM)

Observations:
  [MIXED-ASIL-PARTITION] OsApp_AsilC_Core1 contains SWCs with ASIL QM, C. ...
```

Add `--json` to see the full parsed model.

## Milestone 1 walkthrough

| File | What it does |
|------|--------------|
| `examples/demo_ecu/DemoEcu.arxml` | Synthetic ECU: 4 SWCs, 2 cores, 3 OS-Applications, one **seeded FFI issue** (a QM runnable inside an ASIL C partition). Read the comment at the top first. |
| `src/ffi_checker/model.py` | Pydantic classes: `Core`, `SwComponent`, `Runnable`, `Task`, `OsApplication`, `EcuModel`. |
| `src/ffi_checker/arxml_parser.py` | Indexes every element by its AUTOSAR path, then resolves references: runnable → event → Rte mapping → task → OS-Application → core. |
| `src/ffi_checker/cli.py` | Prints the mapping per core and simple observations. |
| `tests/test_parser.py` | Checks the chain, the seeded issue, broken references and multi-file input. |

The chain the parser rebuilds is the backbone of every later FFI check:

```
SwComponent (ASIL) ─► Runnable ─► (Rte event-to-task mapping) ─► OsTask ─► OsApplication (trusted?) ─► Core
```

### Simplifications (to fix in later milestones)

- **ASIL** is read from an SDG on the SWC type (`<SDG GID="FFI_CHECKER"><SD GID="ASIL">C</SD>`).
  Standard AUTOSAR classic has no ASIL attribute, so check where your project keeps it.
- Runnables are mapped per **SWC type**. Real projects map per **SWC instance**
  (prototype in a composition), via `RteSwComponentInstance`.
- Only `OsTask` is considered; ISRs and BSW schedulables are not yet.
- `EcucPartition` (the newer way to link SWCs to partitions) is not yet read.

### Exercises (milestone 1)

1. Add a fifth SWC `Steering` (ASIL D) on Core1 in its own OS-Application. What does the
   `MIXED-CRITICALITY-CORE` observation say now?
2. Move `Hmi_Run20ms` into a new QM task and QM OS-Application to "fix" the seeded issue,
   then update the test.
3. Read ISRs (`OsIsr` containers, referenced by `OsAppIsrRef`) into the model.
4. Run the parser on a real (company) ARXML **locally**. Which warnings appear?
   They show which simplifications matter for you.

## Milestone 2 walkthrough: graph database

The same model, now stored in **Neo4j** so FFI questions become graph queries.

```
(SwComponent {asil, asil_rank})-[:HAS_RUNNABLE]->(Runnable)-[:MAPPED_TO]->(Task)
(OsApplication {trusted})-[:OWNS_TASK]->(Task)
(OsApplication)-[:RUNS_ON]->(Core {core_id})
```

### 1. Get a Neo4j database (pick one)

| Option | When | How |
|--------|------|-----|
| **Aura Free** (cloud, nothing to install) | Learning with the **synthetic** demo data only | console.neo4j.io → Create instance → Free. Save the credentials file it offers (the password is shown only once). |
| **Local Neo4j** (Docker / Rancher Desktop, or Neo4j Desktop) | Anything with real project data | `docker compose up -d` (wait ~20 s), or create a local database in Neo4j Desktop. |

### 2. Tell the tool how to connect

Copy [`.env.example`](.env.example) to `.env` and fill in your URI and password:

```powershell
Copy-Item .env.example .env     # macOS/Linux: cp .env.example .env
notepad .env
```

`.env` is git-ignored, so your password stays on your machine. Real environment
variables (`NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`) override the file if set.

**Company network error `self-signed certificate in certificate chain`?** Your network
re-signs HTTPS traffic. The tool already uses the operating system's certificate store
(via `truststore`) to handle this; run `pip install -e ".[dev,graph]"` again to get it. If
it still fails, as a last resort for the *synthetic* demo only, change `neo4j+s://` to
`neo4j+ssc://` in `.env` (encrypted, but the certificate is not verified).

### 3. Run it

```bash
pip install -e ".[dev,graph]"

python -m ffi_checker.graph load examples/demo_ecu/DemoEcu.arxml --reset
python -m ffi_checker.graph list         # named queries
python -m ffi_checker.graph query-all

$env:RUN_NEO4J_TESTS="1"; pytest         # also run the Neo4j integration tests
                                         # (they WIPE the database first)
```

Then run `MATCH (n) RETURN n` to *see* your ECU as a graph: in Aura via **Query** on
your instance, locally at **http://localhost:7474**. Click a node to see its properties.

Without a database, the unit tests still run (`pytest`); the Neo4j tests are skipped.

| File | What it does |
|------|--------------|
| `src/ffi_checker/graph/schema.py` | `EcuModel` → nodes and relationships. Pure Python, no database. |
| `src/ffi_checker/graph/loader.py` | Writes the graph with `MERGE` + `UNWIND` (idempotent, batched) and unique constraints on `path`. |
| `src/ffi_checker/graph/queries.py` | Named Cypher queries, each with a description. Read these first. |
| `src/ffi_checker/graph/__main__.py` | `load`, `list`, `query`, `query-all` commands. |
| `docker-compose.yml` | Local Neo4j Community (free). |
| `.env.example` | Connection settings template. Copy to `.env`. |
| `tests/test_graph.py` | Unit tests with a fake session, plus integration tests against a real Neo4j. |

Expected result for the seeded issue:

```
lower_asil_in_partition: Runnables whose SWC has a LOWER ASIL than the partition they run in. ...
  os_app=OsApp_AsilC_Core1, partition_asil=C, runnable=Hmi_Run20ms, swc=HmiGateway, asil=QM
```

### Cypher cheat sheet

| Cypher | Meaning |
|--------|---------|
| `MATCH (a:OsApplication)-[:RUNS_ON]->(c:Core)` | find this pattern |
| `WHERE a.trusted = true` | filter |
| `WITH a, collect(s.asil) AS asils` | group (like SQL `GROUP BY`) and pass on |
| `RETURN a.name, c.name` | output columns |
| `MERGE (n:Core {path: $p})` | find or create |
| `OPTIONAL MATCH` | like a LEFT JOIN: keep rows even without a match |

### Exercises (milestone 2)

1. In the Neo4j Browser, write a query that returns every runnable on `Core0` with its ASIL.
2. Write a query for "QM partitions on the same core as a trusted partition". Why could that
   matter for FFI? Add it to `QUERIES` with a test.
3. Load the ECU twice without `--reset` and check node counts. Why are there no duplicates?
4. Think ahead: in milestone 3 we add `(:Variable)` nodes with `[:WRITES]` relationships from
   runnables. Sketch the query "variables of an ASIL C SWC written by a QM runnable".

## Milestone 3 walkthrough: generated C code and the linker map

Milestone 1 told us which **partition** each runnable runs in. Milestone 3 adds the other
half of memory FFI: **which data does each function touch, and where does that data live?**

```
Runnable ──reads/writes──► Variable ──declared in──► MemMap section ──placed by linker in──► RAM region
(from ARXML)               (from C)                  (from C macros)                         (from map file)
```

### Run it (no database needed)

```
python -m ffi_checker examples/demo_ecu/DemoEcu.arxml --code examples/demo_ecu/src --map examples/demo_ecu/DemoEcu.map
```

New output after the milestone 1 part:

```
Variables:
  BrakeCtrl_BrakeRequest owner=BrakeCtrl  ASIL=C  memmap=BRAKECTRL_VAR_ZERO_INIT_8BIT  region=RAM_ASIL_C_CORE0
  Diag_UnmappedFlag      owner=Diagnostics ASIL=QM memmap=NONE (default section)       region=-
  ...
Code observations:
  [LOWER-ASIL-WRITE] Diag_Run100ms (SWC Diagnostics, ASIL QM) writes BrakeCtrl_BrakeRequest (owner BrakeCtrl, ASIL C)
  [UNPLACED-VARIABLE] Diag_UnmappedFlag: defined outside any MemMap section, ...
```

With the graph (Aura or local Neo4j), load code and map too, then run the new queries
(on Windows `cmd`, keep the command on one line):

```
python -m ffi_checker.graph load examples/demo_ecu/DemoEcu.arxml --reset --code examples/demo_ecu/src --map examples/demo_ecu/DemoEcu.map
python -m ffi_checker.graph query cross_partition_writes
python -m ffi_checker.graph query-all
```

### What the demo contains (all synthetic)

| File | Role |
|------|------|
| `examples/demo_ecu/src/*.c` | One file per SWC in generated style: `VAR(...)` variables wrapped in `START_SEC` / `STOP_SEC` MemMap macros, and one runnable function each. |
| `examples/demo_ecu/DemoEcu.map` | Simplified linker map: RAM regions and where each section was placed. **Not** the real TASKING format (see below). |
| `src/ffi_checker/code/c_parser.py` | Finds variables, their MemMap section, functions, and classifies every access as read, write or address-of. |
| `src/ffi_checker/code/map_parser.py` | Reads regions and sections. The only file to replace when a real TASKING map is supported. |
| `src/ffi_checker/code/link.py` | Joins code to ARXML: a function named like a runnable's `SYMBOL` belongs to that runnable and its SWC. A variable's owner is the SWC implemented in the same `.c` file. |

Seeded issues (try to spot them in the C files first):

| Issue | Where |
|-------|-------|
| QM runnable writes ASIL C data in **another partition** | `Diag_Run100ms` writes `BrakeCtrl_BrakeRequest` |
| QM runnable writes ASIL C data **inside its own ASIL C partition** | `Hmi_Run20ms` takes the address of and writes `SpeedMon_Speed` |
| Variable outside any MemMap section (lands in a default section) | `Diag_UnmappedFlag` |
| QM and ASIL C data share one RAM region | `Hmi_Display` and `SpeedMon_Speed` in `RAM_ASIL_C_CORE1` |

New graph queries: `variables`, `lower_asil_writers`, `cross_partition_writes`,
`unplaced_variables`, `mixed_asil_regions`.

### Known simplifications (to fix in later milestones)

- **The map format is invented.** I don't have a real TASKING map file, and I don't want to
  guess its layout. When you have a **sanitised** real one (names changed, only the memory
  and section tables), the real parser goes into `map_parser.py`.
- **Linker section matching is by name**: `.bss.<PREFIX>_<SECTION>` must end with the MemMap
  section name. In real MICROSAR the link is made by `#pragma section` lines in the
  `*_MemMap.h` files. Reading those is the proper way.
- **Only direct accesses** inside the runnable function are seen. Calls to helper functions,
  accesses through pointers, and RTE API calls (`Rte_Write_...`) are not followed yet.
  Address-of is reported so that you at least know the data can be reached.
- Regex parsing: fine for regular generated code, not for arbitrary C. tree-sitter or
  libclang would replace `c_parser.py` later.
- **Whether a write is allowed** depends on the MPU configuration (which partition may
  write which region). That arrives with the rule engine in milestone 4. Today a
  cross-partition write is an *observation*, not a verdict.

### Exercises (milestone 3)

1. In `HmiGateway.c`, remove the `SpeedMon_Speed = 0u;` line. What does `Hmi_Run20ms` show now? Why
   is the address-of still reported?
2. Add a second variable to `BrakeCtrl.c` inside the same MemMap section. Does the map need a new line?
3. Move `Diag_UnmappedFlag` into a MemMap section but forget to add the section to the `.map` file.
   Which observation fires, and what does its text say?
4. Run `cross_partition_writes` in the Neo4j browser with `RETURN *` instead of the column list
   and look at the picture.
