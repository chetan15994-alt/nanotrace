"""Seed Realistic Multi-Domain RAG Datasets & Vector Embedding Benchmarks.

Populates DuckDB rag_queries table with heterogeneous domains:
1. FinTech & SEC Regulatory Compliance (SOX, 10-K, EBITDA, GAAP) -> High Grounding (0.85 - 0.96)
2. BioMed & Clinical Guidelines (Pharmacovigilance, Off-Label) -> In-domain vs 🚨 Semantic Voids
3. Cloud DevOps & Kubernetes SRE Runbooks -> 1536d vector embeddings
4. Adversarial Out-of-Distribution & Edge Cases -> Extreme Voids, Boundary Precision (0.549 vs 0.551), Multilingual
"""

import argparse
import hashlib
import json
import os
import random
import sys
from typing import Any, Dict, List

import duckdb

from nanotrace.rag.models import RetrievedChunk
from nanotrace.rag.radar import RAGRadarEngine


def generate_embedding(seed_text: str, dim: int = 1536) -> List[float]:
    """Generate deterministic pseudo-embedding vector normalized to unit sphere."""
    seed = int(hashlib.md5(seed_text.encode("utf-8")).hexdigest()[:8], 16)
    rng = random.Random(seed)
    raw = [rng.gauss(0.0, 1.0) for _ in range(dim)]
    norm = sum(x * x for x in raw) ** 0.5
    if norm > 0:
        return [round(x / norm, 6) for x in raw]
    return [0.0] * dim


def seed_rag_database(db_path: str = "./.traces/showcase.duckdb") -> Dict[str, Any]:
    print(f"🌱 Seeding multi-domain RAG dataset into: {db_path}")
    engine = RAGRadarEngine(db_path=db_path, void_threshold=0.55)

    datasets = [
        # ── Domain 1: FinTech & SEC Regulatory Compliance ─────────────────────
        {
            "query": "What are our EBITDA margin calculation formulas according to GAAP standards?",
            "dim": 1536,
            "chunks": [
                ("chk_fin_01", "EBITDA is calculated as Operating Income before Depreciation and Amortization under GAAP...", 0.94),
                ("chk_fin_02", "Reconciliation of Non-GAAP measures: EBITDA margin equals EBITDA divided by total GAAP revenue...", 0.91),
                ("chk_fin_03", "SEC Regulation G requires explicit numerical reconciliation for any non-GAAP metric EBITDA disclosed in 10-Q...", 0.88),
            ],
            "agent": "FinancialComplianceAgent",
        },
        {
            "query": "Under SOX Section 404, what internal controls are required for off-balance-sheet leases?",
            "dim": 1536,
            "chunks": [
                ("chk_fin_04", "Sarbanes-Oxley Act Section 404 mandates annual assessment of internal control over financial reporting for all lease commitments...", 0.92),
                ("chk_fin_05", "ASC 842 requires operating leases to be recognized on balance sheet as right-of-use (ROU) assets and lease liabilities...", 0.89),
                ("chk_fin_06", "Auditors must verify segregation of duties and automated controls in lease portfolio accounting software...", 0.85),
            ],
            "agent": "FinancialComplianceAgent",
        },
        {
            "query": "How does the liquidity coverage ratio (LCR) mandate high-quality liquid assets (HQLA)?",
            "dim": 1536,
            "chunks": [
                ("chk_fin_07", "The Liquidity Coverage Ratio requires banking institutions to maintain unencumbered Level 1 and Level 2 HQLA...", 0.95),
                ("chk_fin_08", "Level 1 HQLA includes central bank reserves and sovereign debt with 0% risk weight under Basel III standards...", 0.93),
                ("chk_fin_09", "Total net cash outflows are calculated over a stressed 30-day calendar period under standard liquidity simulations...", 0.90),
            ],
            "agent": "FinancialComplianceAgent",
        },
        {
            "query": "What is the revenue recognition criteria for multi-element software contracts under ASC 606?",
            "dim": 1536,
            "chunks": [
                ("chk_fin_10", "Step 2 of ASC 606 requires identifying separate performance obligations for software licenses, maintenance, and cloud hosting...", 0.93),
                ("chk_fin_11", "Transaction price must be allocated based on relative standalone selling prices (SSP) across each performance obligation...", 0.88),
                ("chk_fin_12", "Revenue for term licenses is recognized point-in-time upon delivery of cryptographic key, while SaaS is recognized over time...", 0.86),
            ],
            "agent": "FinancialComplianceAgent",
        },
        {
            "query": "What are the disclosure requirements for material cyber incidents on SEC Form 8-K?",
            "dim": 1536,
            "chunks": [
                ("chk_fin_13", "SEC Item 1.05 of Form 8-K requires disclosure of any cybersecurity incident determined to be material within four business days...", 0.96),
                ("chk_fin_14", "Materiality determination considers financial, operational, and reputational impact without unreasonable delay...", 0.94),
                ("chk_fin_15", "Item 106 of Regulation S-K requires annual disclosure of cybersecurity risk management, strategy, and board governance...", 0.89),
            ],
            "agent": "FinancialComplianceAgent",
        },

        # ── Domain 2: BioMed & Clinical Guidelines (In-Domain vs Off-Label Voids)
        {
            "query": "What is the recommended dosing adjustment of metformin in patients with eGFR between 30 and 44 mL/min?",
            "dim": 768,
            "chunks": [
                ("chk_med_01", "In patients with eGFR 30–44 mL/min/1.73m², maximum recommended metformin dose is 1000 mg daily, with renal monitoring every 3 months...", 0.91),
                ("chk_med_02", "Initiation of metformin is contraindicated in patients with eGFR < 45 mL/min due to elevated lactic acidosis risk...", 0.88),
                ("chk_med_03", "Assess eGFR annually in all metformin patients and at least bi-annually in those approaching renal threshold boundaries...", 0.84),
            ],
            "agent": "ClinicalDiagnosticsAgent",
        },
        {
            "query": "What are the primary adverse drug events associated with PCSK9 inhibitor monotherapy?",
            "dim": 768,
            "chunks": [
                ("chk_med_04", "Evolocumab and alirocumab exhibit injection site reactions (3.2%), nasopharyngitis, and rare neurocognitive complaints...", 0.89),
                ("chk_med_05", "FOURIER and ODYSSEY outcomes trials demonstrated excellent long-term hepatic and muscular safety profiles exceeding statin tolerance...", 0.86),
                ("chk_med_06", "Immune response monitoring indicates anti-drug antibody incidence remains below 1% with negligible impact on LDL lowering...", 0.83),
            ],
            "agent": "ClinicalDiagnosticsAgent",
        },
        {
            "query": "What is the first-line antibiotic treatment for acute uncomplicated bacterial cystitis in adults?",
            "dim": 768,
            "chunks": [
                ("chk_med_07", "First-line agents include nitrofurantoin monohydrate/macrocrystals (100 mg BID for 5 days) or TMP-SMX (160/800 mg BID for 3 days)...", 0.92),
                ("chk_med_08", "Fosfomycin trometamol (3g single oral dose) represents an alternative first-line option with minimal resistance selection...", 0.89),
                ("chk_med_09", "Fluoroquinolones should be reserved for complicated pyelonephritis due to FDA black box warnings regarding tendonopathy...", 0.85),
            ],
            "agent": "ClinicalDiagnosticsAgent",
        },
        # Off-label & Gaps (Semantic Voids < 0.55)
        {
            "query": "Can high-dose St. John's Wort be safely combined with tricyclic antidepressants for severe refractory depression?",
            "dim": 768,
            "chunks": [
                ("chk_med_gap_01", "General dietary supplements overview: Hypericum perforatum interacts with CYP3A4 substrates and P-glycoprotein...", 0.52),
                ("chk_med_gap_02", "Pharmacotherapy for depressive episodes mentions SSRI and SNRI first-line lines without specific herb-drug combinations...", 0.46),
            ],
            "agent": "ClinicalDiagnosticsAgent",
        },
        {
            "query": "What is the pediatric dosing protocol for unverified homeopathic belladonna extract in neonates?",
            "dim": 768,
            "chunks": [
                ("chk_med_gap_03", "FDA consumer advisory warns against homeopathic teething tablets containing variable concentrations of belladonna alkaloids...", 0.44),
                ("chk_med_gap_04", "Toxicology report on anticholinergic poisoning in infant case studies...", 0.38),
            ],
            "agent": "ClinicalDiagnosticsAgent",
        },
        {
            "query": "What is the clinical efficacy of colloidal silver ingestion for systemic viral prophylaxis?",
            "dim": 768,
            "chunks": [
                ("chk_med_gap_05", "NCCIH guidelines state silver has no known physiological function or proven clinical benefit when taken orally...", 0.40),
                ("chk_med_gap_06", "Case reports on argyria: irreversible blue-grey discoloration of dermal tissues following long-term silver salts ingestion...", 0.35),
            ],
            "agent": "ClinicalDiagnosticsAgent",
        },

        # ── Domain 3: Cloud DevOps & Kubernetes SRE Runbooks (1536d Embeddings) 
        {
            "query": "How to troubleshoot Kubernetes Pod CrashLoopBackOff caused by OOMKilled exit code 137?",
            "dim": 1536,
            "chunks": [
                ("chk_sre_01", "Exit code 137 indicates container process was terminated by Linux kernel OOM-killer (128 + 9 SIGKILL)...", 0.89),
                ("chk_sre_02", "Inspect pod lifecycle with kubectl describe pod and check lastState.terminated.reason for OOMKilled...", 0.84),
                ("chk_sre_03", "Increase resources.limits.memory in container spec or profile memory leaks using pprof / heap profilers...", 0.81),
            ],
            "agent": "DevOpsSREAgent",
        },
        {
            "query": "What is the recommended etcd raft election timeout and heartbeat interval across multi-region clusters?",
            "dim": 1536,
            "chunks": [
                ("chk_sre_04", "Standard etcd heartbeat interval is 100ms and election timeout is 1000ms for low-latency local networks...", 0.87),
                ("chk_sre_05", "For multi-region deployments with round-trip latency exceeding 50ms, set heartbeat to 250ms and election timeout to 2500ms...", 0.83),
                ("chk_sre_06", "Avoid excessive election timeouts that delay leader failover recovery or too aggressive values causing split-brain flappings...", 0.80),
            ],
            "agent": "DevOpsSREAgent",
        },
        {
            "query": "How to configure Envoy proxy circuit breaking max_connections and max_pending_requests in Istio?",
            "dim": 1536,
            "chunks": [
                ("chk_sre_07", "Define DestinationRule trafficPolicy.connectionPool.tcp.maxConnections to cap concurrent upstream TCP connections...", 0.90),
                ("chk_sre_08", "Configure http.maxPendingRequests to queue incoming requests before returning HTTP 503 Service Unavailable...", 0.86),
                ("chk_sre_09", "OutlierDetection block defines consecutive5xx errors, ejectionInterval, and baseEjectionTime for unhealthy endpoints...", 0.82),
            ],
            "agent": "DevOpsSREAgent",
        },
        {
            "query": "How to resolve Kafka consumer group rebalance storm caused by max.poll.interval.ms timeout?",
            "dim": 1536,
            "chunks": [
                ("chk_sre_10", "If message processing latency exceeds max.poll.interval.ms (default 300s), coordinator marks consumer dead and triggers rebalance...", 0.88),
                ("chk_sre_11", "Increase max.poll.interval.ms or reduce max.poll.records to ensure poll loop is invoked within configured heartbeat window...", 0.85),
                ("chk_sre_12", "Enable cooperative sticky assignor (org.apache.kafka.clients.consumer.CooperativeStickyAssignor) to avoid stop-the-world rebalances...", 0.79),
            ],
            "agent": "DevOpsSREAgent",
        },
        {
            "query": "What are the kernel sysctl parameters to optimize TCP SYN backlog for 100k concurrent connections?",
            "dim": 1536,
            "chunks": [
                ("chk_sre_13", "Set net.ipv4.tcp_max_syn_backlog = 65536 and net.core.somaxconn = 65536 to accommodate high burst SYN connection handshakes...", 0.85),
                ("chk_sre_14", "Tune net.ipv4.tcp_tw_reuse = 1 and expand ephemeral port range via net.ipv4.ip_local_port_range = 1024 65535...", 0.81),
                ("chk_sre_15", "Verify file descriptor limits in /etc/security/limits.conf with nofile set to 1048576 for application worker processes...", 0.76),
            ],
            "agent": "DevOpsSREAgent",
        },

        # ── Domain 4: Adversarial Out-of-Distribution, Hallucination Traps & Edge Cases
        {
            "query": "Detail the provisions and naval borders ratified in the 1842 Lunar Maritime Treaty of Copernicus.",
            "dim": 1536,
            "chunks": [
                ("chk_adv_gap_01", "Historical overview of 19th century British naval treaties in the Atlantic Ocean...", 0.28),
                ("chk_adv_gap_02", "Lunar reconnaissance orbiter topographical survey of the Copernicus crater...", 0.22),
            ],
            "agent": "AdversarialResearchAgent",
        },
        {
            "query": "Explain why Donald Knuth was awarded the 2024 Nobel Prize in Physics for developing quantum gravity.",
            "dim": 1536,
            "chunks": [
                ("chk_adv_gap_03", "The Art of Computer Programming Volume 4B combinatorial algorithms summary...", 0.31),
                ("chk_adv_gap_04", "List of Nobel Prize laureates in Physics from 1901 to 2024...", 0.24),
            ],
            "agent": "AdversarialResearchAgent",
        },
        {
            "query": "What is the optimal agricultural crop rotation schedule for cultivating Martian regolith potatoes?",
            "dim": 1536,
            "chunks": [
                ("chk_adv_gap_05", "NASA Technical Memorandum on perchlorate contamination in simulated Mars soil simulant JSC-1A...", 0.24),
                ("chk_adv_gap_06", "Iowa State agricultural extension guide for solanum tuberosum nitrogen rotation...", 0.18),
            ],
            "agent": "AdversarialResearchAgent",
        },
        {
            "query": "How to invoke the non-existent Azure Cognitive QuantumTeleportation API endpoint in Python?",
            "dim": 1536,
            "chunks": [
                ("chk_adv_gap_07", "Azure Quantum workspace SDK connection guide using qsharp and azure-identity...", 0.33),
                ("chk_adv_gap_08", "Azure Cognitive Services REST API authentication and subscription key headers...", 0.26),
            ],
            "agent": "AdversarialResearchAgent",
        },
        # Strict boundary cases: 0.549 (Void) vs 0.551 (Grounded)
        {
            "query": "Query at exact threshold lower boundary test: 0.549 similarity",
            "dim": 256,
            "chunks": [
                ("chk_bound_01", "Boundary chunk A with threshold score 0.550...", 0.550),
                ("chk_bound_02", "Boundary chunk B with threshold score 0.548...", 0.548),
            ],
            "agent": "BoundaryTesterAgent",
        },
        {
            "query": "Query at exact threshold upper boundary test: 0.551 similarity",
            "dim": 256,
            "chunks": [
                ("chk_bound_03", "Boundary chunk C with threshold score 0.552...", 0.552),
                ("chk_bound_04", "Boundary chunk D with threshold score 0.550...", 0.550),
            ],
            "agent": "BoundaryTesterAgent",
        },
        # Multilingual & Unicode Robustness
        {
            "query": "日本語の財務諸表における減価償却費の計算方法 (Depreciation calculation in Japanese financial statements)",
            "dim": 768,
            "chunks": [
                ("chk_multi_01", "法人税法に基づく固定資産の減価償却方法（定額法および定率法）の算定基準...", 0.82),
                ("chk_multi_02", "耐用年数省令に定める資産区分ごとの償却率一覧および残存簿価処理規則...", 0.79),
            ],
            "agent": "MultilingualAgent",
        },
        {
            "query": "كيفية حساب نسبة السيولة السريعة للشركات المالية (Quick ratio calculation for financial institutions)",
            "dim": 768,
            "chunks": [
                ("chk_multi_03", "نسبة السيولة السريعة (نسبة الاختبار الحمضي) = (الأصول المتداولة - المخزون) / الخصوم المتداولة...", 0.84),
                ("chk_multi_04", "المعايير المحاسبية الدولية وإدارة المخاطر في البنوك والمصارف المركزية...", 0.80),
            ],
            "agent": "MultilingualAgent",
        },
        {
            "query": "🚀 Multi-modal emoji query: What are the latency SLAs for streaming audio WebSocket endpoints? 🎧",
            "dim": 512,
            "chunks": [
                ("chk_multi_05", "Real-time bidirectional Gemini Live API latency profile guarantees first-chunk audio TTFB < 220ms...", 0.88),
                ("chk_multi_06", "WebSocket protocol framing, binary Opus chunk packets, and jitter buffer configuration...", 0.83),
            ],
            "agent": "LiveMediaAgent",
        },
    ]

    recorded_count = 0
    void_count = 0

    for item in datasets:
        q_text = item["query"]
        dim = item.get("dim", 768)
        emb = generate_embedding(q_text, dim=dim)
        chunks = [
            RetrievedChunk(chunk_id=cid, text=ctxt, similarity_score=sim)
            for cid, ctxt, sim in item["chunks"]
        ]
        rec = engine.record_query(
            query_text=q_text,
            retrieved_chunks=chunks,
            query_embedding=emb,
            trace_id=hashlib.md5(q_text.encode()).hexdigest()[:16],
        )
        recorded_count += 1
        if rec.is_semantic_void:
            void_count += 1

    # Also run scan_spans_for_rag to index any existing retrieval spans in DuckDB
    scanned_from_spans = engine.scan_spans_for_rag()
    print(f"✅ Seeding Complete!")
    print(f"   • Total Custom Seed Queries: {recorded_count}")
    print(f"   • Detected Semantic Voids: {void_count} ({void_count / recorded_count * 100:.1f}%)")
    print(f"   • Indexed from Spans Table: {scanned_from_spans}")

    summary = engine.get_radar_summary()
    print(f"   • Radar Engine Total Queries: {summary.total_queries}")
    print(f"   • Radar Engine Total Voids: {summary.semantic_void_count} ({summary.void_rate_pct:.1f}%)")
    print(f"   • Mean Similarity: {summary.mean_similarity:.4f}")
    return summary.to_dict()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed RAG datasets into DuckDB")
    parser.add_argument("--db", default="./.traces/showcase.duckdb", help="Path to DuckDB database")
    args = parser.parse_args()
    seed_rag_database(args.db)
