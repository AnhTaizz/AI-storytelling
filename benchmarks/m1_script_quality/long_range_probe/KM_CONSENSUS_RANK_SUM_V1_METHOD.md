# KM_CONSENSUS_RANK_SUM_V1 Methodology

## Research Question
This is TASK M1-30CH-O. M1-30CH-M demonstrated that cross-encoder reranking (`bge-reranker-v2-m3`) over the frozen `DENSE_E5_LARGE_V1` (K) Top-30 pool improved Hit@10 (0.8000 → 0.9333), Recall@10 (0.5778 → 0.6444), and MRR (0.4209 → 0.5143), but Full Evidence Success@10 remained unchanged at 0.2667 (4 / 15 probes).

M1-30CH-N diagnosed the 8 candidate-complete failure probes and found:
- Every failing probe misses exactly one required evidence unit;
- 5 of 8 missing units sit at M ranks 11–15;
- 5 of 8 missing units moved downward relative to K;
- In those failure probes, 4 required units moved from K Top-10 to M outside Top-10, while 3 moved from K outside Top-10 into M Top-10.

This indicates that K (bi-encoder semantic embedding) and M (cross-encoder pair scoring) provide partially complementary ordering signals.

**Research Question: Can a deterministic, gold-blind consensus of K and M ranks preserve M's gains while reducing evidence losses caused by replacing K ordering entirely?**

This is a **selection / rank-fusion experiment**.
It is NOT:
- new retrieval;
- new reranking;
- query rewriting;
- graph memory;
- LLM inference;
- embedding inference;
- evidence-aware selection using gold labels.

This document is frozen **before** running the consensus evaluation. A negative result is valid and will not be rescued.

---

## Critical Anti-Leakage Contract
The selection algorithm MUST NOT read:
- `required_evidence_chunk_ids`
- `expected_answer`
- probe category
- gold labels
- M1-30CH-N failure labels
- probe success/failure status

before producing the consensus ranking.

Gold evidence may only be read AFTER the consensus ordering is frozen for evaluation.
The selector itself must operate strictly as a pure function on:
- candidate chunk ID
- K rank (1-based position in K Top-30)
- M rank (1-based position in M reranked Top-30)

within the frozen candidate pool.

---

## Inputs and Source Integrity
Only existing LOCAL artifacts are used. No model inference is executed. E5-large and BGE are not run again.
- Frozen probes: `.local/story_integration/otonari_30ch/LONG_RANGE_PROBE_V1/probes.yaml`
- Frozen chunks: `.local/story_integration/otonari_30ch/PARAGRAPH_PACK_V1/chunks.jsonl`
- Benchmark freeze specification: `benchmarks/m1_script_quality/long_range_probe/LONG_RANGE_PROBE_V1_FREEZE.yaml`
- K detailed ranking: `.local/story_integration/otonari_30ch/DENSE_E5_LARGE_V1/cutoff_filtered_per_probe.jsonl`
- M reranked per probe: `.local/story_integration/otonari_30ch/BGE_RERANKER_V2_M3_TOP30_V1/reranked_per_probe.jsonl`
- K public result: `benchmarks/m1_script_quality/long_range_probe/DENSE_E5_LARGE_V1_RESULT.yaml`
- M public result: `benchmarks/m1_script_quality/long_range_probe/BGE_RERANKER_V2_M3_TOP30_V1_RESULT.yaml`
- N public result: `benchmarks/m1_script_quality/long_range_probe/M_FAILURE_MODE_DIAGNOSTIC_V1_RESULT.yaml`

Integrity gates require:
- Benchmark freeze status is `FROZEN`, 15 probes, 35 required units;
- Source SHA-256 matches for probes, chunks, K ranking, and M reranked ranking;
- Exact reproduction of K and M primary metrics;
- Verification that for every probe, the K first 30 candidates and M reranked candidates form identical sets of length 30 with no duplicates.

---

## Frozen Candidate Contract
For every probe:
- Candidate set: exactly K CUTOFF_FILTERED Top-30 (depth = 30).
- M contains exactly the same set.
- No candidate may be added, removed, regenerated, re-embedded, or rescored. Only ordering within this pool changes.

---

## Consensus Rule: Rank Sum
For each candidate $c$ in the frozen Top-30:
- $k\_rank(c)$: 1-based index of $c$ in K Top-30 ($1 \le k\_rank(c) \le 30$)
- $m\_rank(c)$: 1-based index of $c$ in M reranked Top-30 ($1 \le m\_rank(c) \le 30$)

Define:
$$\text{rank\_sum}(c) = k\_rank(c) + m\_rank(c)$$

Primary ordering:
$$\text{rank\_sum ASC}$$

This is an equal-weight, parameter-free rank consensus.
- No learned weights.
- No alpha or lambda tuning.
- No per-probe calibration.
- No alternative weights or formulas (such as Borda count variants, reciprocal rank fusion, or weighted linear combinations) are evaluated in this task.

### Why Rank Sum
Rank sum is chosen because:
1. It is deterministic;
2. It is parameter-free;
3. It is symmetric between K and M;
4. It uses zero gold labels;
5. It directly tests whether equal-weight consensus between two established ordering signals can reduce destructive swaps without introducing tuning degrees of freedom.

It is not claimed to be an optimal fusion method.

---

## Tie Break (frozen)
For candidates with identical $\text{rank\_sum}$:
1. Lower $\max(k\_rank, m\_rank)$ (prefers balanced candidates over extreme rank outliers)
2. Lower $\min(k\_rank, m\_rank)$
3. $\text{chunk\_id ASC}$ (lexicographical string tie-break)

This tie-break rule is strictly symmetric between K and M: swapping the identity of K and M yields the exact same candidate ordering. Neither ranker is favored.

---

## Evaluated Ranking
- Ranks 1–30: Consensus ordering of the 30 candidates.
- Ranks >30: Unchanged K tail after removing the 30 candidates.
All Top-10 metrics depend solely on the frozen 30 candidates and the consensus ordering.

---

## Control and Comparisons
- **Primary Control**: M (`BGE_RERANKER_V2_M3_TOP30_V1`). The primary evaluation comparison is Consensus minus M.
- **Historical Context**: K (`DENSE_E5_LARGE_V1`). K is reported as secondary context only.

---

## Metrics
Evaluated across CUTOFF_FILTERED at depths K = 1, 3, 5, 10:
- Hit@K
- Required Evidence Recall@K
- Full Evidence Success@K
- Spoiler Violation@K (must remain 0.0)
- MRR

Primary metrics:
- Full Evidence Success@10
- Recall@10
- Hit@10
- MRR

---

## Diagnostic Populations (evaluated after consensus ordering is frozen)

### 1. N Failure Population
N identified 8 `CANDIDATE_COMPLETE_FAILURE` probes under M.
This population is reconstructed mechanically from gold annotations.
The analysis reports aggregate-only metrics for this population:
- Probes that become full-success under consensus
- Probes that remain failures
- Probes where M was full-fail (0 required in Top-10) and consensus improves required count in Top-10
- Probes worsened

For N's 8 missing required units (which were ranked >10 by M):
- M rank distribution across buckets (`11-15`, `16-20`, `21-30`)
- Consensus rank distribution across buckets (`<=10`, `11-15`, `16-20`, `21-30`, `>30`)
- Counts of units that entered Top-10, stayed outside Top-10, moved upward, and moved downward.

### 2. Global Required-Evidence Transitions
For all 35 required units, classify M Top-10 → Consensus Top-10:
- `STAY_TOP10`
- `M_TOP10_LOST_BY_CONSENSUS`
- `CONSENSUS_TOP10_GAIN_FROM_M`
- `STAY_OUTSIDE_TOP10`

At the probe level:
- M hit probes vs Consensus hit probes (hit gained, hit lost)
- M full-success probes vs Consensus full-success probes (full-success gained, full-success lost)

### 3. Candidate Ceiling
- `candidate_complete_probes` (reproduced mechanically, not hard-coded)
- `consensus_full_success_probes`
- `ceiling_utilization = consensus_full_success_probes / candidate_complete_probes`

---

## Frozen Verdict Rule
All deltas are computed as Consensus minus M on CUTOFF_FILTERED at Top-10:

- **SUPPORTED**:
  - $\Delta\text{Full Evidence Success@10} > 0$
  - $\text{AND } \Delta\text{Recall@10} \ge 0$
  - $\text{AND } \Delta\text{Hit@10} \ge 0$
  - $\text{AND } \text{full\_success\_gained} > \text{full\_success\_lost}$

- **PARTIALLY_SUPPORTED**:
  - SUPPORTED is false, but at least one of the following holds:
    - $\Delta\text{Full Evidence Success@10} > 0$
    - $\Delta\text{Recall@10} > 0$
    - $\Delta\text{Hit@10} > 0$
  - AND all critical gates pass.

- **NOT_SUPPORTED**:
  - $\Delta\text{Full Evidence Success@10} \le 0$
  - $\text{AND } \Delta\text{Recall@10} \le 0$
  - $\text{AND } \Delta\text{Hit@10} \le 0$

- **NOT_EVALUABLE**:
  - Any critical gate fails (input integrity, candidate-set equality, anti-leakage contract, determinism, privacy).

This rule is preregistered and will not be modified after results are observed.

---

## Determinism and Privacy
- The experiment runs twice in full. Rankings, metrics, transition tables, diagnostic summaries, and artifact hashes must match byte-for-byte.
- Private details (probe IDs, chunk IDs, story text, questions, individual ranks) are restricted to `.local/story_integration/otonari_30ch/KM_CONSENSUS_RANK_SUM_V1/`.
- The public result file `KM_CONSENSUS_RANK_SUM_V1_RESULT.yaml` contains aggregate data only and is scanned for sensitive leaks prior to publication.

---

## Non-Goals
This task does not:
- tune fusion weights or test multiple combinations;
- compare alternative rank fusion methods (e.g., RRF, Borda variants, CombMNZ);
- re-embed or re-score passages with neural models;
- retrieve from outside the frozen Top-30 candidate pool;
- generate or optimize queries;
- perform graph memory traversal or LLM-based reasoning.
