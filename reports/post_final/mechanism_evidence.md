# Safety-mechanism evidence from the frozen Formal comparison

## Question

The existing Formal experiment compares the frozen V2 joint method with one frozen greedy baseline. This report asks what that comparison supports about joint conflict solving, edit-set uniqueness, and abstention. It does not introduce a tuned baseline, rerun inference, or claim a factorial ablation.

## Frozen results

| Measure | V2 Joint | Frozen Greedy | Difference |
|---|---:|---:|---:|
| Overall contract | 81/100 | 55/100 | +26 |
| Exact automatic repair | 66/95 | 50/95 | +16 |
| Connected multi contract | 10/10 | 7/10 | +3 |
| Ambiguity contract | 10/10 | 0/10 | +10 |
| Wrong modifications | 0 | 19 | -19 |
| Unsafe commits | 0 | 10 | -10 |
| Partial-as-full | 0 | not a separately isolated mechanism result | — |

Wrong modifications and unsafe commits may overlap and must not be added as independent error counts.

## Mechanism-aligned evidence

### Joint conflict solving

The connected stratum requires interacting edits to close together. V2 Joint is correct on 10/10 connected cases versus 7/10 for Greedy. This is directly aligned with conflict-component construction and joint search: a locally plausible edit can leave or create a coupled violation, while the joint solver evaluates compatible edit sets against rebuilt whole-model closure.

This comparison supports the statement that joint handling improves the tested connected faults. It does not isolate conflict-graph construction from candidate completeness, preconditions, or closure because these mechanisms are bundled in V2.

### Edit-set uniqueness and abstention

The ambiguity stratum supplies equal-quality, non-equivalent repair alternatives. V2 satisfies the contract on 10/10 by preserving the input and returning `NEEDS_INPUT`; Greedy is correct on 0/10 and records 10 unsafe commits. This is the strongest mechanism-specific evidence in the Final: an automatic edit is allowed only when the optimal semantic edit set is unique.

Uniqueness testing and abstention are inseparable in this experiment. The data support their combined safety effect, not independent effect sizes for “uniqueness” and “abstention.”

### Preconditions, exact provenance, and global closure

V2 records 0 wrong modifications, 0 unsafe commits, 0 partial-as-full outcomes, and 95/95 non-target preservation. These outcomes are consistent with materialized field/relation preconditions, exact provenance edits, and post-edit global closure. The Greedy baseline's 19 wrong modifications show the risk of committing a locally chosen candidate without the full safety envelope.

The comparison does not prove how many of the 19 errors would be prevented by each individual guard. A causal numerical allocation across preconditions, provenance, uniqueness, and closure would require preregistered factorial ablations that were not part of the frozen Final.

## Defensible claim

The evidence supports a composition-level claim:

> On the frozen source-held-out benchmark, conflict-component joint solving plus equal-optimum uniqueness testing and safe abstention improved connected/ambiguous contract behavior while eliminating the wrong and unsafe commits observed for the frozen greedy policy.

It does not support claims that the solver is a new general optimization theory, that any one guard alone accounts for the full 26-point contract difference, or that the comparison establishes production safety outside the admitted relation and version frontier.

## Source records

The numbers above are copied without reinterpretation from `reports/semantic_graph_final/main_results.json`, `greedy_comparison.md`, and `safety_results.md`. No post-Final prediction or score was generated.

