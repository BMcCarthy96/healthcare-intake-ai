# ADR 0001: Keep the model outside workflow control

## Decision

The extraction provider may propose typed administrative fields and evidence only. Deterministic validation, routing, reviewer approval, and export state transitions remain application-owned.

## Consequences

Provider changes can be evaluated without changing policy semantics, prompt-injection text is treated as data, and every automatic route is explainable. The trade-off is that uncertain packets stop for review instead of maximizing automation.
