---
name: warship-fact-guard
description: "Prevent hallucinations in Warship coding and documentation tasks. Enforce evidence-first claims, uncertainty handling, and explicit assumptions for FastAPI routes, SQL, and analytics units."
argument-hint: "Provide the task or claim set to validate."
user-invocable: true
disable-model-invocation: false
---

# Warship Fact Guard

## Purpose
Ensure outputs are evidence-based, unit-safe, and non-speculative.

## Core Policy
- Claim only what is verifiable from repository files.
- If verification is missing, say "not verified" and request the source.
- Do not infer schema fields, SQL behavior, or business rules without evidence.
- Separate facts, assumptions, and recommendations.

## Verification Workflow
1. Gather evidence:
- Read relevant router, schema, template, and docs files.
- Locate exact source for each claim.

2. Classify each statement:
- Verified fact
- Inference (supported but not explicit)
- Assumption (needs confirmation)

3. Validate data semantics:
- Unit correctness (lbs, dollars, c/lb)
- Time scope correctness (daily, monthly, YTD, full-year)
- Aggregation correctness (sum, avg, weighted avg)

4. Produce guarded output:
- Include only verified facts in definitive language.
- Mark uncertain items explicitly.
- Provide targeted follow-up questions for missing facts.

## Mandatory Response Sections
- Verified facts
- Assumptions (if any)
- Risks of uncertainty
- Required confirmations

## Failure Conditions (must not proceed as definitive)
- Missing source file for key claim
- Ambiguous unit conversion
- Unclear date-window semantics
- Inconsistent endpoint contract evidence
