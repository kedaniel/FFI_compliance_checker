"""Run the rules, then let an LLM explain each finding.

    python -m ffi_checker.explain --map M --spec S --demo        no LLM, template explanations
    python -m ffi_checker.explain --map M --spec S --dry-run     show the prompts, call nothing
    python -m ffi_checker.explain --map M --spec S               use the LLM from .env / LLM_* variables
    ... --only R1_placement --limit 2 --out report.json

Findings and severities always come from the rule engine. The explanation is advisory text
added next to them. If the LLM is not reachable, templates are used and the report says so.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..linkmap import parse_tasking_map
from ..rules import run_rules
from ..rules.__main__ import build_report
from ..rules.model import Finding
from ..spec import load_spec
from .grounding import grounding_problems
from .prompt import PROMPT_VERSION, build_prompt, prompt_fingerprint
from .schema import Explanation
from .template import template_explanation


def explain_all(findings: list[Finding], agent=None) -> dict[str, dict]:
    """Return {finding fingerprint: entry}. With agent=None every explanation is a template.

    entry = {"source": "llm" | "template", "explanation": {...} | None, "error": str | None, ...}
    """
    from .agent import explain_finding  # imported here: the LLM libraries are optional

    entries: dict[str, dict] = {}
    llm_down = agent is None
    note = None if agent is None else "LLM unreachable"
    for f in findings:
        if not llm_down:
            result = explain_finding(agent, f)
            if result.explanation is not None:
                entries[f.fingerprint] = {"source": "llm", "advisory": True,
                                          "explanation": result.explanation.model_dump(), "error": None}
                continue
            if result.unreachable:
                llm_down = True
            else:  # the model answered but we could not accept the answer
                entries[f.fingerprint] = {"source": "none", "advisory": True, "explanation": None,
                                          "error": result.error}
                continue
        t = template_explanation(f)
        entries[f.fingerprint] = {"source": "template", "advisory": True,
                                  "explanation": t.model_dump(), "error": note,
                                  "grounding_issues": grounding_problems(t, f)}
    return entries


def print_explanation(entry: dict) -> None:
    x = entry["explanation"]
    if x is None:
        print(f"  (no explanation: {entry['error']})")
        return
    label = {"llm": "LLM", "template": "template, no LLM"}.get(entry["source"], entry["source"])
    print(f"  Explanation ({label}, advisory):")
    print(f"    Summary:        {x['summary']}")
    print(f"    Why it matters: {x['why_it_matters']}")
    print(f"    Suggested fix:  {x['suggested_fix']}")
    for q in x["questions_to_check"]:
        print(f"    Check:          {q}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m ffi_checker.explain", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--map", required=True)
    p.add_argument("--spec", required=True)
    p.add_argument("--only", help="only findings of this rule, e.g. R1_placement")
    p.add_argument("--limit", type=int, help="explain at most this many findings")
    p.add_argument("--out", help="write the evidence report (JSON) here")
    p.add_argument("--demo", action="store_true", help="template explanations, no LLM")
    p.add_argument("--dry-run", action="store_true", help="print the prompts, call nothing")
    p.add_argument("--base-url", help="override LLM_BASE_URL")
    p.add_argument("--model", help="override LLM_MODEL")
    args = p.parse_args(argv)

    findings = run_rules(parse_tasking_map(args.map), load_spec(args.spec))
    shown = [f for f in findings if not args.only or f.rule == args.only][: args.limit]

    if args.dry_run:
        from .prompt import SYSTEM_PROMPT
        print("=== SYSTEM PROMPT ===\n" + SYSTEM_PROMPT)
        for f in shown:
            print(f"=== USER PROMPT for {f.fingerprint} ===\n{build_prompt(f)}\n")
        return 0

    cfg, agent = None, None
    if not args.demo:
        from .agent import LlmConfig, build_agent, build_model
        cfg = LlmConfig.from_env()
        cfg = cfg.model_copy(update={k: v for k, v in
                                     (("base_url", args.base_url), ("model", args.model)) if v})
        agent = build_agent(build_model(cfg), cfg)
        print(f"Using LLM {cfg.model} at {cfg.base_url} (mode {cfg.output_mode})\n")

    entries = explain_all(shown, agent)
    for f in shown:
        print(f"[{f.severity.upper()}] {f.rule}  {f.fingerprint}\n  {f.detail}")
        print_explanation(entries[f.fingerprint])
        print()

    sources = {e["source"] for e in entries.values()}
    if agent is not None and "template" in sources:
        print(f"NOTE: the LLM at {cfg.base_url} could not be reached, so template explanations were "
              "used. Start it (for Ollama: `ollama serve`) and check LLM_BASE_URL / LLM_MODEL.")
    if args.demo:
        print("NOTE: --demo shows template explanations. No LLM was used.")

    if args.out:
        report = build_report(findings, {"map": args.map, "spec": args.spec})
        report["llm_used"] = "llm" in sources
        report["explanations"] = {
            "advisory": "Explanations are generated text. Findings and severities come from the rules.",
            "llm": cfg.public() if cfg else None,
            "prompt_version": PROMPT_VERSION,
            "prompt_fingerprint": prompt_fingerprint(),
            "entries": entries,
        }
        Path(args.out).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Evidence report written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
