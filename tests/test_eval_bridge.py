import pytest
import nanotrace
from nanotrace.eval.bridge import TraceDataset
from nanotrace.eval.heuristics import LocalHeuristicEvaluator
from nanotrace.schema.otel import GenAIAttributes


def test_eval_bridge_to_deepeval_and_ragas():
    tracer = nanotrace.init(storage_path=":memory:")

    with tracer.span("RAG_Workflow") as root:
        root.set_attribute(GenAIAttributes.PROMPT, {"args": ["What is OpenTelemetry?"]})

        with tracer.span("vector_retriever") as ret:
            ret.set_attribute(GenAIAttributes.OPERATION_NAME, "retrieval")
            ret.set_attribute(GenAIAttributes.COMPLETION, "OpenTelemetry is a vendor-neutral observability standard.")

        root.set_attribute(GenAIAttributes.COMPLETION, "OpenTelemetry provides vendor-neutral tracing.")

    tracer.flush()
    records = tracer.sink.query("SELECT * FROM spans")
    dataset = TraceDataset(records)

    # DeepEval test case conversion
    deepeval_cases = dataset.to_deepeval()
    assert len(deepeval_cases) == 1
    case = deepeval_cases[0]
    assert "What is OpenTelemetry?" in case.input
    assert "vendor-neutral tracing" in case.actual_output
    assert case.retrieval_context is not None
    assert len(case.retrieval_context) == 1

    # Ragas sample conversion
    ragas_ds = dataset.to_ragas()
    assert len(ragas_ds.samples) == 1
    sample = ragas_ds.samples[0]
    assert "What is OpenTelemetry?" in sample.user_input
    assert "vendor-neutral tracing" in sample.response

    # Local heuristic evaluators
    eval_results = dataset.run_heuristics()
    assert len(eval_results) == 3
    assert all(r.passed for r in eval_results)

    tracer.shutdown()
