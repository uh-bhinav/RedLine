## What changed and why

<!-- The "why" matters more than the "what" here — the diff already shows the what. -->

## Which architectural rules apply

<!-- See CONTRIBUTING.md. Delete lines that don't apply; check the ones that do. -->

- [ ] Touches `eval_engine.py` / a scorer / `gate_engine.py` — confirmed still synchronous
- [ ] Touches `JobQueue` or `AgentAdapter` — confirmed no signature change (STABLE CONTRACT)
- [ ] Adds/changes a model name — confirmed it's in `config/model_profiles.yaml`, not a literal
- [ ] Adds an `emit_trace()` call — confirmed wrapped in `try/except`
- [ ] Touches `apps/cli/` — confirmed no `apps.api` import (`pytest apps/api/tests/unit/test_packaging.py`)
- [ ] Adds a new dependency — confirmed `pyproject.toml` and `requirements.txt` still agree
- [ ] Adds a new test file — confirmed it has `pytestmark = pytest.mark.unit` or `.integration`

## Testing

```bash
pytest -m unit -q
pytest -m integration -q   # if this PR touches anything DB/Redis/Redpanda/LLM-backed
```

Paste real output, not a description of what should happen.

## Is this a decision worth an ADR?

<!-- New datastore, deployment target, frontend framework, scaling model, or anything
     else expensive to reverse. If yes, link the ADR in docs/adr/. -->
