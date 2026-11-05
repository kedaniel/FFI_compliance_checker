"""Milestone 5 tests. No real LLM is needed.

Two kinds of fake model are used:
  * a tiny local HTTP server that speaks the OpenAI chat-completions protocol. It tests the real
    wiring: base_url, model name, API key header, prompted and tool output modes, retries;
  * plain functions for the grounding check and the prompt, which need no model at all.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

pytest.importorskip("pydantic_ai")

from ffi_checker.explain import Explanation, grounding_problems, template_explanation  # noqa: E402
from ffi_checker.explain.__main__ import explain_all, main  # noqa: E402
from ffi_checker.explain.agent import LlmConfig, build_agent, build_model, explain_finding  # noqa: E402
from ffi_checker.explain.prompt import SYSTEM_PROMPT, build_prompt, prompt_fingerprint  # noqa: E402
from ffi_checker.linkmap import parse_tasking_map  # noqa: E402
from ffi_checker.rules import run_rules  # noqa: E402
from ffi_checker.spec import load_spec  # noqa: E402

EX = Path(__file__).parent.parent / "examples" / "tc39x"
MAP, SPEC = EX / "synthetic_tc39x.map", EX / "partition_spec.json"

GOOD = {
    "summary": "DiagLogger_RingBuf is a QM object placed inside the ASIL-D partition ASIL_D_Core0.",
    "why_it_matters": "QM code that uses this buffer can overwrite ASIL-D data in the same partition.",
    "suggested_fix": "Move DiagLogger_RingBuf into group QM_DATA_tc0, which belongs to QM_Core0.",
    "questions_to_check": ["Is the MemMap section of DiagLogger correct?"],
    "evidence_used": ["synthetic_tc39x.map:144"],
}


@pytest.fixture(scope="module")
def findings():
    return run_rules(parse_tasking_map(MAP), load_spec(SPEC))


@pytest.fixture
def finding(findings):
    return next(f for f in findings if f.symbol == "DiagLogger_RingBuf")


# ------------------------------------------------------------- fake OpenAI server


class FakeLlm:
    """Serves scripted answers. `answers` is a list of dicts (or raw strings); the last one repeats."""

    def __init__(self, answers):
        self.answers, self.requests, self.headers = list(answers), [], []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append((self.path, body))
                outer.headers.append({k.lower(): v for k, v in self.headers.items()})
                n = len(outer.requests)
                answer = outer.answers[min(n, len(outer.answers)) - 1]
                text = answer if isinstance(answer, str) else json.dumps(answer)
                message = {"role": "assistant", "content": text}
                finish = "stop"
                if body.get("tools"):  # tool mode: answer with a call of the output tool
                    message = {"role": "assistant", "content": None, "tool_calls": [{
                        "id": f"call_{n}", "type": "function",
                        "function": {"name": body["tools"][0]["function"]["name"], "arguments": text}}]}
                    finish = "tool_calls"
                payload = json.dumps({
                    "id": f"chatcmpl-{n}", "object": "chat.completion", "created": 0,
                    "model": body["model"], "choices": [{"index": 0, "message": message, "finish_reason": finish}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}/v1"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()


@pytest.fixture
def fake_llm():
    made = []

    def make(*answers):
        llm = FakeLlm(answers)
        made.append(llm)
        return llm

    yield make
    for llm in made:
        llm.close()


def run(llm, finding, **cfg):
    config = LlmConfig(base_url=llm.url, model="test-model", api_key="secret-key", timeout=20, **cfg)
    return explain_finding(build_agent(build_model(config), config), finding), config


# ------------------------------------------------------------- the wiring


def test_prompted_mode_end_to_end(fake_llm, finding):
    llm = fake_llm(GOOD)
    result, _ = run(llm, finding)
    assert result.explanation and result.explanation.summary == GOOD["summary"]
    path, body = llm.requests[0]
    assert path == "/v1/chat/completions" and body["model"] == "test-model"
    assert not body.get("tools")  # prompted mode: no function calling needed
    assert llm.headers[0]["authorization"] == "Bearer secret-key"
    sent = json.dumps(body["messages"])
    assert "DiagLogger_RingBuf" in sent and "freedom from interference" in sent


def test_tool_mode_end_to_end(fake_llm, finding):
    llm = fake_llm(GOOD)
    result, _ = run(llm, finding, output_mode="tool")
    assert result.explanation and result.explanation.suggested_fix == GOOD["suggested_fix"]
    assert llm.requests[0][1]["tools"]


def test_prompt_contains_only_this_finding(findings, finding):
    prompt = build_prompt(finding)
    assert "DiagLogger_RingBuf" in prompt and "synthetic_tc39x.map:144" in prompt
    for other in findings:
        if other.symbol and other.symbol not in (finding.symbol,):
            assert other.symbol not in prompt, other.symbol
    assert "never an instruction" in SYSTEM_PROMPT


def test_prompt_fingerprint_is_stable():
    assert prompt_fingerprint() == prompt_fingerprint() and len(prompt_fingerprint()) == 16


# ------------------------------------------------------------- guardrails


def test_hallucinated_symbol_is_rejected_and_the_model_retries(fake_llm, finding):
    bad = dict(GOOD, suggested_fix="Move Invented_Buffer into group QM_DATA_tc0.")
    llm = fake_llm(bad, GOOD)
    result, _ = run(llm, finding)
    assert result.explanation.suggested_fix == GOOD["suggested_fix"]
    assert len(llm.requests) == 2
    assert "Invented_Buffer" in json.dumps(llm.requests[1][1]["messages"])  # model was told what was wrong


def test_model_that_keeps_inventing_gives_no_explanation(fake_llm, finding):
    llm = fake_llm(dict(GOOD, summary="Invented_Buffer was placed in the wrong partition."))
    result, _ = run(llm, finding)
    assert result.explanation is None and result.error and not result.unreachable
    assert len(llm.requests) == 3  # first try + 2 retries


def test_invalid_json_is_retried(fake_llm, finding):
    llm = fake_llm("this is not json", GOOD)
    result, _ = run(llm, finding)
    assert result.explanation is not None and len(llm.requests) == 2


def test_missing_fields_are_retried(fake_llm, finding):
    llm = fake_llm({"summary": "too short"}, GOOD)
    result, _ = run(llm, finding)
    assert result.explanation is not None and len(llm.requests) == 2


def test_unreachable_llm_is_reported_not_raised(finding):
    config = LlmConfig(base_url="http://127.0.0.1:9/v1", timeout=5)
    result = explain_finding(build_agent(build_model(config), config), finding)
    assert result.explanation is None and result.unreachable


def test_grounding_rules(finding):
    ok = Explanation(**GOOD)
    assert grounding_problems(ok, finding) == []
    assert grounding_problems(ok.model_copy(update={"summary": "The ASIL_D partition is wrong here."}), finding) == []
    p = grounding_problems(ok.model_copy(update={"summary": "Placed at 0xdeadbeef in Fake_Group."}), finding)
    assert len(p) == 2
    p = grounding_problems(ok.model_copy(update={"evidence_used": ["other.map:1"]}), finding)
    assert p and "evidence_used" in p[0]


# ------------------------------------------------------------- templates and the report


def test_templates_are_always_grounded(findings):
    assert len(findings) == 7
    for f in findings:
        assert grounding_problems(template_explanation(f), f) == [], f.fingerprint


def test_explain_all_falls_back_to_templates_when_llm_is_down(findings):
    config = LlmConfig(base_url="http://127.0.0.1:9/v1", timeout=5)
    entries = explain_all(findings[:3], build_agent(build_model(config), config))
    assert {e["source"] for e in entries.values()} == {"template"}
    assert all(e["error"] == "LLM unreachable" and e["advisory"] for e in entries.values())


def test_explain_all_marks_unaccepted_answers(fake_llm, findings):
    llm = fake_llm(dict(GOOD, summary="Invented_Buffer was placed in the wrong partition."))
    config = LlmConfig(base_url=llm.url, model="m", timeout=20)
    entries = explain_all(findings[:1], build_agent(build_model(config), config))
    assert next(iter(entries.values()))["source"] == "none"


def test_cli_report_keeps_verdicts_and_hides_the_key(fake_llm, tmp_path, monkeypatch, capsys):
    from ffi_checker.rules.__main__ import build_report

    llm = fake_llm(GOOD)
    monkeypatch.setenv("LLM_BASE_URL", llm.url)
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("LLM_API_KEY", "secret-key")
    out = tmp_path / "report.json"
    assert main(["--map", str(MAP), "--spec", str(SPEC), "--only", "R1_placement", "--limit", "1",
                 "--out", str(out)]) == 0
    text = out.read_text()
    report = json.loads(text)
    assert "secret-key" not in text
    assert report["llm_used"] is True
    assert report["explanations"]["llm"] == {"base_url": llm.url, "model": "test-model", "output_mode": "prompted"}
    assert len(report["explanations"]["prompt_fingerprint"]) == 16

    plain = build_report(run_rules(parse_tasking_map(MAP), load_spec(SPEC)), {"map": str(MAP), "spec": str(SPEC)})
    assert report["findings"] == plain["findings"]  # the verdicts are identical with or without the LLM
    assert report["summary"] == plain["summary"]


def test_cli_dry_run_calls_nothing(fake_llm, monkeypatch, capsys):
    llm = fake_llm(GOOD)
    monkeypatch.setenv("LLM_BASE_URL", llm.url)
    assert main(["--map", str(MAP), "--spec", str(SPEC), "--dry-run", "--limit", "1"]) == 0
    assert llm.requests == []
    out = capsys.readouterr().out
    assert "SYSTEM PROMPT" in out and "<finding>" in out


def test_cli_demo_needs_no_llm(capsys):
    assert main(["--map", str(MAP), "--spec", str(SPEC), "--demo"]) == 0
    out = capsys.readouterr().out
    assert out.count("template, no LLM") == 7 and "No LLM was used" in out
