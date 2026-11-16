// Phase 5.5(c) -- k6 load test of RedLine's OWN API (POST /eval-runs), distinct
// from apps/api/services/load_engine.py, which load-tests an AGENT under
// RedLine. This tests the control plane itself: how does eval-service's own
// job-trigger endpoint (auth -> DB write -> Redpanda publish -> return) hold
// up at concurrency?
//
// Usage:
//   make k6-load-test VUS=10 DURATION=30s
//
// Required env vars:
//   REDLINE_API_KEY    -- an API key with admin/developer role (POST /eval-runs
//                          requires it -- see routers/eval_runs.py)
//   AGENT_VERSION_ID    -- a real, already-registered agent_version id
//   SUITE_ID            -- a real, already-pushed suite id
// Optional:
//   REDLINE_BASE_URL   -- default http://localhost:8085 (docker-compose gateway)

import http from 'k6/http';
import { check } from 'k6';

export const options = {
  vus: __ENV.VUS ? parseInt(__ENV.VUS) : 10,
  duration: __ENV.DURATION || '30s',
  thresholds: {
    http_req_duration: ['p(95)<2000'],
    http_req_failed: ['rate<0.01'],
  },
};

const BASE_URL = __ENV.REDLINE_BASE_URL || 'http://localhost:8085';
const API_KEY = __ENV.REDLINE_API_KEY;
const AGENT_VERSION_ID = __ENV.AGENT_VERSION_ID;
const SUITE_ID = __ENV.SUITE_ID;

export default function () {
  const res = http.post(
    `${BASE_URL}/eval-runs`,
    JSON.stringify({
      agent_version_id: AGENT_VERSION_ID,
      suite_id: SUITE_ID,
      triggered_by: 'ci',
    }),
    {
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${API_KEY}`,
      },
    },
  );

  check(res, {
    'status is 201': (r) => r.status === 201,
    'response has an id': (r) => {
      try {
        return JSON.parse(r.body).id !== undefined;
      } catch (e) {
        return false;
      }
    },
  });
}
