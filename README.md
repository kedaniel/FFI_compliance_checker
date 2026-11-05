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
| 5 | Explain findings with a local LLM (**Ollama** + **Pydantic AI**) | Prompting, structured output, guardrails | ✅ |
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

## Milestone 4 walkthrough: the rule engine

Until now the tool printed *observations*. Milestone 4 produces **findings**: a rule ID, a
severity, a detail text, and **evidence** that points to the exact map line and spec entry.
No LLM is involved. The same input always gives the same result, which is what an assessor needs.

It works on two inputs (and no ARXML):

| Input | File | Meaning |
|-------|------|---------|
| Linker map | `examples/tc39x/synthetic_tc39x.map` | where everything **is** (TASKING-style tables: sections, symbols, cross references, group ranges) |
| Partition spec | `examples/tc39x/partition_spec.json` | where everything **should be**: partitions, their groups and modules, module ASIL, shared groups, MPU granularity, guard pad size |

Both are synthetic. A real project's spec comes from its safety concept and OS/MPU
configuration. Later we can derive more of it from ARXML.

### Run it (no database)

```
python -m ffi_checker.rules --map examples/tc39x/synthetic_tc39x.map --spec examples/tc39x/partition_spec.json --expected examples/tc39x/expected_findings.json --out report.json
```

Expected end of the output:

```
5 error(s), 2 warning(s) on TC39x (synthetic demo ECU)
Comparison with expected_findings.json: matched 7, missing 0, unexpected 0, severity mismatches 0
```

### The five rules

| Rule | Checks | Severity |
|------|--------|----------|
| R1 placement | every object sits in a group owned by a partition that **lists its module** and has **at least its ASIL**; shared groups only accept the ASIL classes they allow | error |
| R2 alignment | every `_lc_gb_` / `_lc_ge_` MPU region boundary is a multiple of the MPU granularity (8 bytes) | error |
| R3 guard pad | between ASIL data and QM data of each core there is a gap of at least `min_bytes` (16) | error |
| R4 xref | a QM module references data defined by an ASIL module. The map cannot tell a read from a write | warning |
| R5 wildcard | no ASIL-rated object in the catch-all `WILDCARD_DATA` group (it means a MemMap section is missing) | error |

OS and BSW modules have no ASIL level of their own: they only have to be listed in the
partition they live in.

### How we know the engine is right: a test oracle

The synthetic map was built with **7 known problems and 3 known non-problems**
(`examples/tc39x/expected_findings.json`). `tests/test_rules.py` requires the engine to find
exactly those: nothing missing and nothing extra. Extra findings are as bad as missing ones,
because a checker that cries wolf is ignored.

Non-problems that must stay quiet: a cross-core reference between two ASIL D modules, a shared BSW
buffer, and BSW data in the wildcard group.

### Evidence report

`--out report.json` writes an audit record: tool version, UTC time, `"llm_used": false`, the
SHA-256 of the map and the spec, and every finding with its evidence. Change one byte of an
input and the hash changes, so a finding can always be tied to the exact files it came from.

### Files

| File | What it does |
|------|--------------|
| `src/ffi_checker/linkmap/tasking_parser.py` | Reads the boxed tables of the map by recognising their header rows. Every row keeps its line number. |
| `src/ffi_checker/spec.py` | The spec as Pydantic models. |
| `src/ffi_checker/rules/memory.py` | The five rules as plain functions `(map, spec) -> findings`. |
| `src/ffi_checker/rules/compare.py` | Compares findings with an expected list. |
| `src/ffi_checker/rules/__main__.py` | The command line and the evidence report. |

### Known simplifications

- The parser was written against a **synthetic** map. A real TASKING map may have other columns,
  wrapped lines or extra tables. Warnings show what it could not read, and the header sets at the
  top of `tasking_parser.py` are the place to adapt.
- The spec is written by hand. Connecting it to the ARXML model of milestones 1 to 3
  (partitions and runnables from ARXML, variables from C code) is a later step.
- R4 only looks at QM modules reading ASIL data. Lower-ASIL to higher-ASIL (for example B to D)
  is a small extension.
- Only data is checked. Code placement (`.text`) and timing are out of scope for now.

### Exercises (milestone 4)

1. Open the map and fix the alignment problem by changing `_lc_ge_ASIL_D_DATA_tc1` from `0x6000556c`
   to `0x60005570`. Which finding disappears, and why is the pad in front of it still fine?
2. Move `SteerMon_Calib` from `WILDCARD_DATA` to `ASIL_D_DATA_tc2` in the Locate Result table.
   Which rule now complains, and why is that a different problem?
3. Add a rule R6 of your own in `memory.py` (for example: every partition's groups must be
   contiguous) and add a seeded problem and an expected finding for it.
4. Open `report.json` and find the evidence for R3. Could an assessor check it using only the
   map file and the spec?

## Milestone 5 walkthrough: an LLM explains the findings

The rule engine says *what* is wrong. Milestone 5 adds an LLM that says it in plain language
and suggests a next step. The LLM **explains, it never decides**:

```
map + spec ──► rule engine ──► FINDINGS (severity, evidence)   <- deterministic, unchanged
                                   │
                                   ▼   one finding at a time
                          prompt ──► LLM ──► Explanation (validated JSON)
                                              │
                                  grounding check: every name and address must come from the finding
                                              │  no  ──► model is told what was wrong and tries again
                                              ▼  yes
                                    explanation added to the report (marked "advisory")
```

### Try it without any LLM first

```
pip install -e ".[dev,graph,llm]"
python -m ffi_checker.explain --map examples/tc39x/synthetic_tc39x.map --spec examples/tc39x/partition_spec.json --demo
python -m ffi_checker.explain --map examples/tc39x/synthetic_tc39x.map --spec examples/tc39x/partition_spec.json --dry-run --limit 1
```

`--demo` prints explanations built from templates (no model). `--dry-run` prints the exact
prompts an LLM would receive, so you can read what it is told. On Windows `cmd` keep each command on one line.

### Then with a real local model (Ollama)

1. Install **Ollama** from ollama.com/download (Windows installer, installs for your user).
2. In a terminal: `ollama pull qwen2.5:7b` (about 5 GB). If your laptop is short on memory or
   slow, use `ollama pull qwen2.5:3b` and set `LLM_MODEL=qwen2.5:3b` in `.env`.
3. Run the same command **without** `--demo`:
   ```
   python -m ffi_checker.explain --map examples/tc39x/synthetic_tc39x.map --spec examples/tc39x/partition_spec.json --limit 2 --out report.json
   ```
   Without a GPU each explanation takes some seconds up to a minute.

If the LLM cannot be reached, the tool says so and uses templates, so it always produces a result.

### Pointing it at a customer's LLM

Nothing in the code is tied to Ollama. The tool talks to any **OpenAI-compatible** endpoint
(vLLM, LM Studio, Azure OpenAI, an internal gateway). Change only the settings in `.env`:

| Setting | Meaning |
|---------|---------|
| `LLM_BASE_URL` | e.g. `http://localhost:11434/v1` (Ollama), `https://llm.customer.internal/v1` |
| `LLM_MODEL` | the model name that server knows |
| `LLM_API_KEY` | key, if the server needs one |
| `LLM_OUTPUT_MODE` | `prompted` (default, works with any chat model) or `tool` (function calling) |

Company TLS inspection is handled the same way as for Neo4j (the OS certificate store is used).

### The guardrails (the important part of this milestone)

| Risk | Protection | Where |
|------|-----------|-------|
| LLM changes or disputes a verdict | `Explanation` has no severity or verdict field. The report keeps the rule engine's findings untouched, and a test checks they are identical with and without the LLM. | `schema.py`, `test_cli_report_keeps_verdicts_and_hides_the_key` |
| LLM invents a symbol, address or file | Grounding check: every identifier-like word and hex number must appear in the finding. If not, the answer is rejected and the model must retry. After 2 retries the finding is reported without an explanation. | `grounding.py`, `agent.py` |
| Malformed answer | Pydantic validates the JSON (required fields, length limits) and the model retries on errors. | `schema.py` |
| Prompt injection through a symbol name | The system prompt says everything inside `<finding>` is data, and the model only gets one finding, not the files. | `prompt.py` |
| Customer data leaves the network | Nothing is sent unless you configure an endpoint. `--dry-run` shows the exact text. API keys never go into the report. | `__main__.py` |
| LLM down or slow | Falls back to templates and says so. | `__main__.py` |

The report (`--out`) records which model and server were used, the prompt version and a hash
of the prompt text, next to the SHA-256 of the input files. Explanations are labelled `advisory`.

### Files

| File | What it does |
|------|--------------|
| `src/ffi_checker/explain/schema.py` | The answer format (`Explanation`). |
| `src/ffi_checker/explain/prompt.py` | System prompt, per-rule background text and the prompt builder. |
| `src/ffi_checker/explain/grounding.py` | The check that an answer only uses facts from the finding. |
| `src/ffi_checker/explain/agent.py` | Settings, the Pydantic AI agent with output validator and retries, and `explain_finding`. |
| `src/ffi_checker/explain/template.py` | Explanations without an LLM. |
| `src/ffi_checker/explain/__main__.py` | The command line and report. |
| `tests/test_explain.py` | Tests with a fake OpenAI-compatible server: no real model needed. |

### Known simplifications

- **Tested without a real model.** The tests use a fake server that speaks the OpenAI protocol,
  so the wiring, retries and guardrails are verified, but the quality of the wording from a
  real 3B or 7B model is not. Judge that on your laptop and tell me what you see.
- The background text per rule is written by us. In milestone 6 it is replaced by retrieval
  over the standard and your safety requirements (RAG).
- The grounding check catches invented names and numbers, not wrong reasoning. That is why the
  text is marked advisory and the engineer still decides.
- Explanations are generated one finding at a time and sequentially. Parallel requests and caching
  come when needed.

### Exercises (milestone 5)

1. Run `--dry-run` and read the prompt. What does the model know about the finding? What does it not know?
2. Run with the LLM and compare its text with the `--demo` template for the same finding. Which is
   more useful? Where is it vaguer or wrong?
3. In `prompt.py` change the system prompt (for example "answer in German"). Does the answer change?
   Which line of `report.json` shows that the prompt version changed?
4. Make the grounding check stricter or looser in `grounding.py` and see which tests fail.
