# MECE Interview Intelligence

An independent interview-assessment service for MECE (mece.in). From a CV and a job
description, it builds a role-specific interview plan and runs an adaptive 15–60 minute
interview. Afterwards it produces an evidence-traced assessment: every score points back to
a verbatim quote, untested competencies are reported as untested rather than weak, and
confidence is shown separately from the assessment.

MECE contributes exactly one thing: a short-lived Ed25519-signed assertion of *who the user
is, their effective tier and whether they are an admin*. Everything else — the API, database
schema, storage, prompts, model routing, scoring, admin and audit — lives here.

| Read | For |
|---|---|
| `docs/00_AUDIT.md` | What exists in MECE today, and what this service deliberately does not reuse |
| `docs/A_ARCHITECTURE.md` … `docs/L_ADVERSARIAL_QA_MATRIX.md` | Architecture, data model, API contract (incl. proposed C10), AI pipeline, interview state, competency model, question engine, scoring, feedback, admin/access, Drive, QA matrix |
| `docs/M_SELF_REVIEW.md` | The hostile review: what was found and fixed, and what is still open |
| `docs/BUILD_STATUS.md` | What is built and tested, what is not built, and known compromises |

## Layout

```
interview_intelligence/
  api/            REST v1 (candidate + admin)          auth/        assertion verification
  access/         policy, flags, limits, audit         documents/   upload, parse, redact, encrypt
  cv_intelligence/ jd_intelligence/ company_intelligence/          role_taxonomy/ (+ data/*.json)
  competency_engine/ question_engine/ interview_engine/ interview_memory/
  evidence_engine/ evaluation_engine/ feedback_engine/ report_engine/
  ai/             providers, routing, prompt registry, structured outputs, injection guard, simulator
  jobs/           durable DB queue + worker threads    drive_integration/   voice/
migrations/       generated SQL (idempotent, own role, RLS)
qa/               golden dataset, real-model evaluation harness, interview simulator
tests/            offline test suite (Postgres or SQLite)
```

## Run locally

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # II_ENV=dev uses the offline simulated models
python -m scripts.generate_keys # paste the public key into .env, the private key into the frontend's .env.local
uvicorn interview_intelligence.main:app --reload --port 8100
```

With `II_ENV=dev` and no AI keys, every model stage is served by a deterministic simulator,
so the whole flow works offline. The simulator checks plumbing, not judgement.

## Tests and QA

```bash
# Postgres is recommended (row locks, SKIP LOCKED and the 2-active race are only real there)
II_TEST_DATABASE_URL=postgresql+psycopg://postgres@localhost/ii_test pytest -q
pytest -q                                   # SQLite fallback (one Postgres-only test skipped)
python -m compileall -q interview_intelligence tests qa scripts

python -m qa.run_golden --simulated         # harness smoke test (offline)
python -m qa.run_golden --repeats 3 --record # REAL models: golden dataset, gates, regression vs last run
python -m qa.simulate_interview --all --simulated
python -m qa.simulate_interview --family sales --persona evasive --llm-candidate   # real models both sides
```

`qa.run_golden` exits non-zero if a hard gate fails (fairness gap for non-native phrasing
> 1 point, an off-topic answer scored as "weak", an injection raising a score, or keyword
stuffing rewarded). Run it before changing any prompt, model route or evaluator code.

## Deploy

Render web service from `render.yaml`; run `migrations/0001_interview_intel.sql` once (it is
idempotent); set the env vars listed in `.env.example`. The MECE frontend needs
`NEXT_PUBLIC_II_API_URL`, `II_ASSERTION_PRIVATE_KEY` and `II_ASSERTION_KID`. The launch flag
`ii.enabled_for_pro` starts **off**: only II admins and test users get in until an admin
turns it on in Admin → Interview Intelligence → Settings.
