---
name: Bug report
about: Something in RedLine itself is broken
title: ''
labels: bug
assignees: ''
---

**What broke**
A clear description of what happened vs. what you expected.

**Which layer**
- [ ] API / a specific router (which route?)
- [ ] Eval engine / a scorer (which one?)
- [ ] Gate engine
- [ ] A benchmark agent (`rag-agent`, `stateful-support-agent`, `research-pipeline-agent`)
- [ ] CLI (`agentbench ...`)
- [ ] Infrastructure (Redpanda / Redis / ClickHouse / k3d / Helm)
- [ ] Dashboard

**Reproduction**
Exact commands, or the smallest failing test, if you have one.

```
paste here
```

**Real output** (not what you expected — the actual error, traceback, or `curl`
response). Per this project's own convention: real verification output beats a
theoretical description of the bug.

**Environment**
- OS:
- Python version:
- Running via docker compose, k3d, or a bare venv:
