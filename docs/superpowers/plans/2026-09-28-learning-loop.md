# Education Learning Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Connect tutoring answers to a diagnostic prompt, one assessed follow-up question, visible source evidence, and actionable learning recommendations.

**Architecture:** Keep DeepTutor's existing chat, DeepQuestion, practice and Mastery Path stores authoritative. Add small authenticated API seams for a one-question check, enrich the existing digital-human bridge, and show existing data through the student and teacher pages. A generated check is explicitly requested after an answer and is saved to the student's scoped practice store only on submission.

**Tech Stack:** Python/FastAPI, DeepTutor SDK, Next.js/React/TypeScript, SQLite practice and mastery stores.

**Spec:** User's four requested improvements in this conversation: learning loop, learning difficulty diagnosis, visible sources, and next-step recommendations.

## Global Constraints

- Preserve the existing user scope and class consent boundaries.
- Never expose a generated check's answer before submission.
- Use real saved practice/mastery evidence; do not invent mastery or cite unavailable material.
- Do not install local models or configure deployment.

## Review Focus

- A tutoring turn without a knowledge base still answers and displays no fabricated sources.
- A check cannot be read or submitted by another user or after expiration.
- Repeated check submission has clear idempotence/conflict behavior.
- An unrecognized learning difficulty cannot silently change the tutor prompt.
- Partial teacher data does not become an unwarranted recommendation.

---

### Task 1: Assessed follow-up check

- [ ] Add an authenticated create/submit API using DeepQuestion and the scoped practice store.
- [ ] Test generation validation, answer secrecy, submission, wrong-answer review, user isolation and repeat requests.
- [ ] Add an explicit student button and check-answer card after a completed explanation.

### Task 2: Student-reported difficulty

- [ ] Validate a small difficulty enum and optional short student note on the server.
- [ ] Feed the selected difficulty into the tutoring turn as a teaching hint without claiming automatic diagnosis.
- [ ] Add a clear picker and test prompt construction and invalid inputs.

### Task 3: Source evidence

- [ ] Collect real source events from the DeepTutor turn stream.
- [ ] Show safe external links or expandable local excerpts with titles and location metadata.
- [ ] Test that source events are returned and no-source turns show no false provenance.

### Task 4: Next-step advice

- [ ] Derive student and class suggestions from due reviews, weak assessed objectives and unresolved errors.
- [ ] Show actionable links only within the caller's account scope.
- [ ] Test incomplete data and class membership boundaries.

### Task 5: Integration verification

- [ ] Run targeted and existing Python tests; inspect final diffs and contracts.
- [ ] Run frontend checks only if dependencies are already present; otherwise report the unverified surface.
