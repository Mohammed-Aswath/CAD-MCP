---
name: init
description: Build a complete mental model of a repository by mapping structure, entry points, core modules, and runtime behavior. Use when the user asks to initialize context, run `/init`, understand the whole codebase, or identify core functions and functionalities.
disable-model-invocation: true
---

# Init

## Goal

Create a concise but complete project understanding: structure, core functions, main flows, and critical constraints.

## Workflow

1. Discover top-level layout and tech stack.
2. Identify entry points, startup flow, and runtime boundaries.
3. Map core modules and responsibilities.
4. Trace key data/control flows end-to-end.
5. Extract important constraints, invariants, and risk areas.
6. Produce an onboarding report with actionable next reads.

## Step-by-step

### 1) Structural scan

- List top-level directories and classify them (app, engine, tests, tooling, docs).
- Detect languages, build systems, and package managers.
- Find architecture docs and configuration files.

### 2) Runtime map

- Locate primary entry points (CLI, app bootstrap, service start, plugin init).
- Record initialization order and component wiring.
- Identify execution contexts (audio thread, control thread, UI thread, background jobs).

### 3) Core functionality extraction

- Identify modules that implement core product behavior.
- For each core module, capture:
  - purpose
  - key public APIs
  - major internal algorithms
  - direct dependencies

### 4) Flow tracing

- Trace 3-5 most important flows (input -> processing -> output).
- For each flow, note:
  - trigger
  - involved modules
  - state transitions
  - failure handling

### 5) Constraint and performance checks

- Surface hard constraints from code/docs (real-time, memory, threading, determinism).
- Highlight any places where violations are likely.
- For DSP/engine code, explicitly call out:
  - where memory is allocated (init vs runtime)
  - thread ownership of data
  - real-time safety risks
  - expected performance impact

### 6) Testing and reliability map

- List current test layers (unit, integration, e2e, perf).
- Map test coverage to core modules and identify obvious gaps.
- Note crash/NaN/clip guards and fallback behavior where present.

## Output format

Return findings in this structure:

```markdown
# Codebase Init Report

## 1. Project snapshot
- Stack:
- Top-level architecture:
- Primary entry points:

## 2. Core modules
- Module:
  - Responsibility:
  - APIs:
  - Dependencies:

## 3. Critical flows
- Flow:
  - Trigger:
  - Path:
  - Failure handling:

## 4. Runtime and thread model
- Thread/Context:
  - Owns:
  - Reads:
  - Writes:

## 5. Performance and safety constraints
- Constraint:
  - Evidence:
  - Risk:

## 6. Tests and confidence
- Existing tests:
- Gaps:
- Highest-risk untested behavior:

## 7. Suggested next reads
1.
2.
3.
```

## Operating rules

- Prefer repository evidence over assumptions.
- Keep explanations brief and concrete.
- Use exact file paths when citing findings.
- If unsure, mark as "unknown" and list the precise file/area to inspect next.
