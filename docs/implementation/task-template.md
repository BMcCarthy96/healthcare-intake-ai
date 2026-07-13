# Task packet template

## Outcome

One visible, verifiable behavior.

## Read first

- Exact files and sections.
- Any schema or ADR that governs the change.

## In scope

- Exhaustive allowed behavior.

## Out of scope

- Adjacent work that must not be performed.

## Contract

- Public endpoint/type/state-transition changes.
- Error and idempotency behavior.

## Allowed files

- An explicit file allowlist.

## Acceptance tests

- Named test scenarios and expected outputs.

## Verification

1. Syntax/types
2. Lint
3. Focused tests
4. Broader tests when the workflow boundary changes

## Stop conditions

Stop and escalate for missing contracts, secret requirements, real-data requests, new architecture, or changes outside the allowlist.

## Completion report

- Files changed
- Tests and exact results
- Deviations and limitations
- Next safe packet
