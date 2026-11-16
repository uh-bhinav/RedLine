# RedLine Production Readiness Roadmap

> **Goal**: Make RedLine 100% production-ready, end-to-end complete, and deployable on Render (free tier) before adding new features.

**Analogy**: "GitHub for AI Agents" — catch agent errors before deployment, not after.

---

## Current State Analysis

### ✅ What We Have (Working)
- **Backend**: 3 FastAPI microservices (eval, agent, gate) + nginx gateway
- **APIs**: 10 complete routers (auth, agents, eval_runs, suites, CI, dashboard, diff, load, mining)
- **Auth**: JWT + refresh tokens (email/password)
- **Dashboard**: React/TypeScript with 9 pages
  - Login, Agents List, Agent Detail, Run Detail, Diff Viewer, Failure Clusters, Load Test Reports, Trace Viewer
- **Infrastructure**: Postgres, Redis, Redpanda, ClickHouse, Tempo
- **Features**: Eval runs, gate checks, behavioral diffs, load testing, failure mining, drift detection

### ❌ What's Missing (Blockers for Production)
1. **No user registration** — users can't sign up
2. **No GitHub OAuth** — only email/password
3. **No public landing page** — dashboard assumes logged-in user
4. **No onboarding flow** — new users don't know what to do
5. **No API key management UI** — users can't create keys in dashboard
6. **No Render deployment config** — all setup assumes docker-compose
7. **Incomplete error UX** — many errors just show 500/404
8. **No user documentation** — no in-app help or quickstart
9. **No agent registration from UI** — must use CLI
10. **Dashboard not production-polished** — functional but not "wow"

---

## Roadmap — 6 Phases (3-4 weeks total)

### **Phase 1: Auth & User Management (Week 1, Part 1)**
*Make it possible for anyone to sign up and start using RedLine*

#### 1.1 User Registration Flow
- [ ] `POST /auth/register` endpoint (email, password, name)
- [ ] Email validation + password strength checks
- [ ] Auto-create first tenant for new user
- [ ] Registration page in dashboard (`/register`)
- [ ] "Sign up" link on login page
- [ ] Success redirect to onboarding

**API Design:**
```python
# apps/api/routers/auth.py
@router.post("/register", response_model=TokenResponse, status_code=201)
def register(
    payload: RegisterRequest,  # email, password, name
    db: Session = Depends(get_db)
) -> TokenResponse:
    # 1. Validate email not already registered
    # 2. Hash password with bcrypt
    # 3. Create new tenant (name="{user_name}'s Workspace")
    # 4. Create user with role="admin"
    # 5. Return access + refresh tokens (auto-login)
```

#### 1.2 GitHub OAuth Integration
- [ ] `POST /auth/github` endpoint (receives GitHub code)
- [ ] GitHub OAuth app setup (client_id, client_secret in .env)
- [ ] GitHub user info fetch (email, name, avatar)
- [ ] User lookup/creation by email
- [ ] "Sign in with GitHub" button on login page
- [ ] OAuth callback page (`/auth/callback/github`)

**Flow:**
1. User clicks "Sign in with GitHub"
2. Redirect to `https://github.com/login/oauth/authorize?client_id=...`
3. GitHub redirects back to `https://yourapp.com/auth/callback/github?code=...`
4. Frontend sends code to `POST /auth/github`
5. Backend exchanges code for access token, fetches user info
6. Return JWT pair (same as email/password login)

#### 1.3 Password Reset Flow
- [ ] `POST /auth/request-password-reset` (email)
- [ ] `POST /auth/reset-password` (token, new_password)
- [ ] "Forgot password?" link on login page
- [ ] Reset password page (`/auth/reset-password`)
- [ ] Email sending (optional for MVP — log token to console)

**Acceptance Criteria:**
- ✅ New user can sign up with email/password
- ✅ New user can sign in with GitHub
- ✅ User sees "Welcome" screen after first login
- ✅ Registration creates tenant + gives admin role

---

### **Phase 2: Dashboard Polish & UX (Week 1, Part 2)**
*Make the dashboard feel like a real product, not a dev tool*

#### 2.1 Landing Page (Public)
- [ ] New route: `GET /` (no auth required)
- [ ] Hero section: "GitHub for AI Agents — Stop Bad Agents Before Production"
- [ ] 3-step explainer:
  1. **Register your agent** (with code snippet)
  2. **Run evals automatically** (CI check example)
  3. **See pass/fail gates** (red/green status)
- [ ] "Get Started" CTA → `/register` or `/login`
- [ ] GitHub stars badge, docs link

**Design Inspiration:** Linear, Vercel, GitHub Actions landing pages

#### 2.2 Onboarding Flow (First-Time User)
- [ ] Welcome modal on first dashboard load
- [ ] Step 1: "Create your first agent"
  - Show CLI command: `agentbench init --agent my-agent`
  - Or "Create agent" button in dashboard
- [ ] Step 2: "Generate API key"
  - Show key once, copy button
- [ ] Step 3: "Run your first eval"
  - Show CLI command with their actual API key
- [ ] Dismissible + "Show onboarding again" in settings

#### 2.3 API Key Management UI
- [ ] New page: `/settings/api-keys`
- [ ] List all keys (name, created_at, last_used, revoked status)
- [ ] "Create new key" button → dialog
- [ ] "Revoke key" action
- [ ] Show key only once after creation (copy button)
- [ ] Role-based: only admins can create keys

**Backend:**
```python
# apps/api/routers/api_keys.py (new router)
@router.get("/api-keys", response_model=list[ApiKeyListItem])
def list_api_keys(ctx: TenantContext = Depends(get_tenant_context))

@router.post("/api-keys", response_model=ApiKeyCreateResponse, status_code=201)
def create_api_key(payload: ApiKeyCreate, ...)

@router.delete("/api-keys/{key_id}", status_code=204)
def revoke_api_key(key_id: UUID, ...)
```

#### 2.4 Agent Registration from Dashboard
- [ ] New dialog on agents list: "Register Agent"
- [ ] Form fields:
  - Name (e.g., "customer-support-bot")
  - Description (optional)
  - Entrypoint (e.g., `http://localhost:9100/turn` or `agents.my_agent:run`)
- [ ] Calls `POST /agents` directly (already exists)
- [ ] After creation → redirect to agent detail page
- [ ] Show "next steps" (register version, push suite)

#### 2.5 Improved Agent Detail Page
- [ ] **Hero Section:**
  - Agent name + description
  - Latest version badge (v1, v2, etc.)
  - Status indicator (✅ last run passed / ❌ failed)
- [ ] **Quick Actions:**
  - "Run Eval" button → dialog (select suite)
  - "Register New Version" button
  - "View All Runs" → runs tab
- [ ] **Tabs:**
  - Overview (latest run, ARS trend, error budget)
  - Runs History (table with filters)
  - Versions (list all versions + content hashes)
  - Settings (edit name/description, delete agent)
- [ ] **Widgets:**
  - ARS trend chart (last 30 days)
  - Error budget gauge (circle progress)
  - Drift alerts (if any)

#### 2.6 Better Error Handling
- [ ] Global error boundary in React (show "Something went wrong")
- [ ] 401 → redirect to login
- [ ] 403 → "You don't have permission" page
- [ ] 404 → "Agent not found" page
- [ ] Network error → "Can't reach server" toast
- [ ] Loading states on all buttons (spinner)

**Acceptance Criteria:**
- ✅ Public can see landing page
- ✅ New user completes onboarding in <2 minutes
- ✅ User creates API key from dashboard
- ✅ User creates agent from dashboard
- ✅ Dashboard feels polished (no broken UI, proper loading states)

---

### **Phase 3: CLI Improvements (Week 2, Part 1)**
*Make CLI dead simple to use*

#### 3.1 Better `agentbench login` UX
- [ ] Save credentials to `~/.redline/config.json` (not just env vars)
- [ ] Auto-detect API from config (no need to pass `--base-url` every time)
- [ ] `agentbench whoami` — shows logged-in user + tenant
- [ ] `agentbench logout` — clears saved config

#### 3.2 Simplified Agent Registration
- [ ] `agentbench register agent` interactive wizard:
  - Prompt: "Agent name?"
  - Prompt: "Description?"
  - Prompt: "Entrypoint (HTTP URL or Python path)?"
  - Auto-detect content hash from file
  - Auto-register first version as "v1"
- [ ] Confirmation: "Agent 'my-agent' (v1) registered! ID: abc-123"

#### 3.3 Better Eval Suite Management
- [ ] `agentbench suites list` — show all suites for this agent
- [ ] `agentbench suites push <file>` — auto-validates YAML schema
- [ ] `agentbench run --suite <name>` — no need for suite ID
- [ ] Show live progress: "Running case 1/10... ✓ passed"

#### 3.4 CI Integration Example
- [ ] Add `.github/workflows/redline-check.yml` template
- [ ] README section: "Add to Your CI"
- [ ] Example for GitHub Actions, GitLab CI, CircleCI

**Acceptance Criteria:**
- ✅ CLI feels like `gh` (GitHub CLI) — intuitive commands
- ✅ Zero-config after first login
- ✅ Clear error messages (no stack traces to user)

---

### **Phase 4: Render Deployment Setup (Week 2, Part 2)**
*One-click deploy to Render (free tier)*

#### 4.1 Render Blueprint (`render.yaml`)
```yaml
services:
  - type: web
    name: redline-gateway
    env: docker
    dockerfilePath: ./infra/gateway/Dockerfile
    envVars:
      - key: DATABASE_URL
        fromDatabase:
          name: redline-db
          property: connectionString
      - key: REDIS_URL
        fromService:
          name: redline-redis
          type: redis
          property: connectionString
      - key: JWT_SECRET_KEY
        generateValue: true
      - key: GEMINI_API_KEY
        sync: false  # User provides

  - type: web
    name: redline-api
    env: docker
    dockerfilePath: ./apps/eval_service/Dockerfile

databases:
  - name: redline-db
    databaseName: redline
    plan: free

  - name: redline-redis
    plan: free
```

#### 4.2 Free-Tier Architecture
**Problem:** Render free tier has limitations:
- No Redpanda (Kafka) — use Postgres job queue instead
- No ClickHouse — skip trace storage (or use Postgres)
- 512MB RAM per service

**Solution: Monolith Mode**
- [ ] Add `DEPLOYMENT_MODE=monolith` env var
- [ ] If monolith → use `PostgresJobQueue` (not Redpanda)
- [ ] If monolith → skip ClickHouse traces (log to stdout)
- [ ] Single FastAPI app serves all routes
- [ ] Worker runs in same container (background thread)

**Code:**
```python
# apps/api/main.py
from apps.api.core.config import get_settings

settings = get_settings()

if settings.deployment_mode == "monolith":
    # Use PostgresJobQueue
    from apps.api.core.jobqueue import PostgresJobQueue
    queue = PostgresJobQueue()
else:
    # Use RedpandaJobQueue
    from apps.api.core.redpanda_queue import RedpandaJobQueue
    queue = RedpandaJobQueue()
```

#### 4.3 One-Click Deploy Button
- [ ] Add "Deploy to Render" badge to README
- [ ] Link: `https://render.com/deploy?repo=https://github.com/uh-bhinav/RedLine`
- [ ] User enters:
  - `GEMINI_API_KEY` (or `ANTHROPIC_API_KEY`)
  - `GITHUB_CLIENT_ID` + `GITHUB_CLIENT_SECRET` (optional)
- [ ] Auto-runs migrations on first deploy

#### 4.4 Health Checks & Monitoring
- [ ] `/health` returns 200 only if DB connection works
- [ ] Render auto-restarts if health check fails
- [ ] Add Sentry integration (optional — just DSN in env)

**Acceptance Criteria:**
- ✅ User clicks "Deploy to Render"
- ✅ App starts in <5 minutes
- ✅ User can register + login immediately
- ✅ Postgres + Redis work on free tier
- ✅ No Redpanda/ClickHouse needed for basic usage

---

### **Phase 5: Documentation & Help (Week 3)**
*Make sure users can succeed without asking for help*

#### 5.1 In-App Help
- [ ] "?" icon in top nav → opens help sidebar
- [ ] Contextual help on each page:
  - Agents page: "What is an agent?"
  - Runs page: "What is an eval run?"
  - Gate result: "What does 'gate failed' mean?"
- [ ] Link to docs for each topic

#### 5.2 Quickstart Guide (Interactive)
- [ ] New page: `/quickstart`
- [ ] Step-by-step with code snippets:
  1. Install CLI
  2. Login
  3. Create agent
  4. Push eval suite
  5. Run eval
  6. See results in dashboard
- [ ] Copy buttons for all commands
- [ ] "I did this step" checkboxes (saved to localStorage)

#### 5.3 API Documentation
- [ ] Auto-generated OpenAPI docs at `/docs` (FastAPI built-in)
- [ ] Add descriptions to all endpoints
- [ ] Add example requests/responses
- [ ] "Try it out" works with user's own API key

#### 5.4 Video Walkthrough
- [ ] 5-minute Loom recording:
  - "Welcome to RedLine"
  - Register → Create agent → Run eval → See gate result
- [ ] Embed on landing page

**Acceptance Criteria:**
- ✅ New user can onboard without external docs
- ✅ In-app help answers common questions
- ✅ API docs are complete and usable

---

### **Phase 6: Polish & Launch Prep (Week 4)**
*Final touches before public launch*

#### 6.1 UI/UX Polish
- [ ] Consistent spacing/padding across all pages
- [ ] Dark mode support (toggle in settings)
- [ ] Loading skeletons (not just spinners)
- [ ] Empty states with helpful CTAs
  - "No agents yet" → "Create your first agent" button
  - "No runs yet" → "Run your first eval" button
- [ ] Animations (subtle fade-ins, no jank)
- [ ] Mobile-responsive (at least readable on phone)

#### 6.2 Performance Optimization
- [ ] React.lazy() for code splitting
- [ ] Memoize expensive components
- [ ] Virtualized lists for >100 items
- [ ] API response caching (React Query)
- [ ] Dashboard loads in <1s (on Render)

#### 6.3 Security Hardening
- [ ] Rate limiting on `/auth/login` (10 attempts/minute)
- [ ] Rate limiting on `/auth/register` (5/hour per IP)
- [ ] CORS restricted to dashboard domain
- [ ] CSP headers (no inline scripts)
- [ ] Helmet.js for security headers

#### 6.4 Testing
- [ ] E2E tests with Playwright:
  - Register → login → create agent → run eval
  - GitHub OAuth flow
- [ ] Frontend unit tests for critical components
- [ ] API integration tests (already exist, verify coverage)

#### 6.5 Launch Checklist
- [ ] README updated with new flow
- [ ] CHANGELOG.md documenting all changes
- [ ] Screenshots in README (dashboard, CLI, gate result)
- [ ] Demo video embedded
- [ ] Twitter/LinkedIn announcement draft
- [ ] Product Hunt submission ready
- [ ] Hacker News "Show HN" post ready

**Acceptance Criteria:**
- ✅ Dashboard loads fast (<1s)
- ✅ No UI bugs on Chrome/Firefox/Safari
- ✅ Mobile-usable (can view runs on phone)
- ✅ Security headers pass Mozilla Observatory scan
- ✅ E2E tests pass on Render deployment

---

## Success Metrics (Post-Launch)

### Week 1 After Launch
- [ ] 50+ user registrations
- [ ] 10+ GitHub stars
- [ ] 5+ agents registered by external users
- [ ] 20+ eval runs triggered

### Month 1 After Launch
- [ ] 200+ users
- [ ] 50+ GitHub stars
- [ ] Featured in a newsletter (e.g., TLDR AI, Superhuman AI)
- [ ] 1-2 blog posts by users

---

## Render Free Tier Limits

| Resource | Limit | Impact |
|----------|-------|--------|
| Web Services | 1 free | ✅ OK (monolith mode) |
| Postgres | 1 free (90 days) | ✅ OK then $7/month |
| Redis | 25MB | ✅ OK for MVP |
| RAM | 512MB/service | ⚠️ Tight (optimize) |
| Build Time | 15min | ✅ OK (~5min build) |
| Monthly Hours | 750hrs/service | ✅ OK (31 days) |

**After 90 days:** User must upgrade Postgres to paid ($7/mo) or migrate.

---

## Development Order

### Week 1 (Auth & Dashboard)
- **Mon-Tue:** User registration + GitHub OAuth
- **Wed-Thu:** Landing page + onboarding flow
- **Fri:** API key management UI

### Week 2 (CLI & Render)
- **Mon-Tue:** CLI improvements
- **Wed-Thu:** Render deployment setup
- **Fri:** Test full deploy flow

### Week 3 (Docs)
- **Mon-Tue:** In-app help + quickstart
- **Wed-Thu:** API docs polish
- **Fri:** Record video walkthrough

### Week 4 (Polish)
- **Mon-Tue:** UI/UX polish
- **Wed:** Performance optimization
- **Thu:** Security hardening + E2E tests
- **Fri:** Launch prep

---

## Post-Launch: Phase 7 (Future Features)

**ONLY AFTER Phase 6 is complete:**
- [ ] Slack notifications (gate failed → post to #engineering)
- [ ] Email notifications (weekly digest of runs)
- [ ] Team management (invite teammates to tenant)
- [ ] Cost analysis dashboard (LLM spend over time)
- [ ] Canary deployments (route 10% of traffic to new version)
- [ ] Multi-model support (compare GPT-4 vs Claude)
- [ ] Agent versioning UI (see full diff between versions)

---

## Questions to Answer

1. **Do we need user email verification?**
   - ❌ Not for MVP (blocks onboarding)
   - ✅ Add later if spam becomes an issue

2. **Support multiple tenants per user?**
   - ❌ Not for MVP (1 user = 1 tenant)
   - ✅ Add "Organizations" later

3. **Support team invites?**
   - ❌ Not for MVP
   - ✅ Phase 7 feature

4. **Free plan limits?**
   - ✅ 100 eval runs/month
   - ✅ 5 agents max
   - ✅ Upgrade prompt at 80% usage

---

## Done Means

- ✅ User can sign up in <1 minute
- ✅ User can deploy to Render in <5 minutes
- ✅ User completes first eval in <10 minutes
- ✅ Dashboard is "wow" (not "meh")
- ✅ No confusing errors or broken UI
- ✅ Works on free tier (Postgres + Redis only)
- ✅ README has "Deploy to Render" button
- ✅ Video walkthrough published
- ✅ Ready for Product Hunt launch

---

## Implementation Notes

### GitHub OAuth Setup
1. Go to GitHub Settings → Developer settings → OAuth Apps
2. Create new app:
   - Name: "RedLine"
   - Homepage: `https://your-app.onrender.com`
   - Callback: `https://your-app.onrender.com/auth/callback/github`
3. Copy `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET` to `.env`

### Render Deployment
1. Push code to GitHub
2. Create new Web Service on Render
3. Connect GitHub repo
4. Set environment variables (Render dashboard)
5. Deploy!

---

**Next Step:** Start Phase 1.1 (User Registration) 🚀
