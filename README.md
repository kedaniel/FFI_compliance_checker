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
| 1 | Parse a synthetic ECU (ARXML) into Pydantic models | XML, AUTOSAR paths and ECUC, Pydantic, pytest | ✅ this PR |
| 2 | Load the model into **Neo4j** and query it with Cypher | Graph databases | ⬜ |
| 3 | Parse generated C (MemMap sections) and the TASKING map file | Static code extraction | ⬜ |
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

### Exercises

1. Add a fifth SWC `Steering` (ASIL D) on Core1 in its own OS-Application. What does the
   `MIXED-CRITICALITY-CORE` observation say now?
2. Move `Hmi_Run20ms` into a new QM task and QM OS-Application to "fix" the seeded issue,
   then update the test.
3. Read ISRs (`OsIsr` containers, referenced by `OsAppIsrRef`) into the model.
4. Run the parser on a real (company) ARXML **locally**. Which warnings appear?
   They show which simplifications matter for you.
