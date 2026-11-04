"""04_rag_trace_to_ragas.py

Demonstrates RAG pipeline tracing and converting traces into Ragas EvaluationDatasets.
"""

import nanotrace
from nanotrace.eval.bridge import load_traces

nanotrace.init(storage_path="./.traces/nanotrace.duckdb")


@nanotrace.trace_agent(name="RAG_System")
def run_rag_pipeline(query: str):
    # Traced vector retrieval step
    with nanotrace.span("dense_retriever") as ret_span:
        ret_span.set_attribute("gen_ai.operation.name", "retrieval")
        context_doc = "DuckDB supports vectorized analytical execution directly in Python processes."
        ret_span.set_attribute("gen_ai.completion", context_doc)

    # Traced answer generation
    with nanotrace.span("llm_generation") as gen_span:
        gen_span.set_attribute("gen_ai.operation.name", "chat")
        gen_span.set_attribute("gen_ai.request.model", "gpt-4o-mini")
        answer = f"Based on the documents, {context_doc.lower()}"
        gen_span.set_attribute("gen_ai.completion", answer)

    return answer


if __name__ == "__main__":
    print("\n⚡️ Running RAG pipeline...")
    ans = run_rag_pipeline("Why is DuckDB fast?")
    print(f"Generated Answer: {ans}\n")

    nanotrace.flush()

    print("Converting to Ragas EvaluationDataset...")
    dataset = load_traces(db_path="./.traces/nanotrace.duckdb", limit=5)
    ragas_ds = dataset.to_ragas()

    for idx, sample in enumerate(ragas_ds.samples, 1):
        print(f"\n[Ragas Sample #{idx}]")
        print(f"  • User Input:          {sample.user_input}")
        print(f"  • Response:            {sample.response}")
        print(f"  • Retrieved Contexts:  {sample.retrieved_contexts}")
