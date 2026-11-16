# RedLine Makefile -- Phase 2 k3d deployment workflow

CLUSTER_NAME  := redline
NAMESPACE     := redline
HELM_RELEASE  := redline
CHART_PATH    := ./helm/redline
SERVICES      := eval_service agent_service gate_service

.PHONY: help cluster-up cluster-down images-build images-import keda-install \
        helm-install helm-upgrade helm-uninstall helm-status \
        infra-up infra-down deploy teardown logs

help:
	@echo "RedLine Phase 2 targets:"
	@echo "  infra-up        Start docker-compose infrastructure"
	@echo "  infra-down      Stop infrastructure containers"
	@echo "  cluster-up      Create k3d cluster (idempotent)"
	@echo "  cluster-down    Delete k3d cluster"
	@echo "  images-build    Build all service Docker images"
	@echo "  images-import   Import built images into k3d (no registry needed)"
	@echo "  keda-install    Install KEDA into the cluster"
	@echo "  helm-install    Install the RedLine Helm chart (first time)"
	@echo "  helm-upgrade    Upgrade an already-installed release"
	@echo "  helm-status     Show all deployed resources"
	@echo "  deploy          Full: images-build + images-import + helm-upgrade"
	@echo "  logs            Follow logs for all RedLine pods"
	@echo "  teardown        Uninstall chart + delete cluster"

infra-up:
	docker compose up -d
	@until docker exec redline_postgres pg_isready -U redline -d redline > /dev/null 2>&1; do sleep 1; done
	@echo "Infrastructure ready."

infra-down:
	docker compose down

cluster-up:
	@if k3d cluster list | grep -q "$(CLUSTER_NAME)"; then \
		echo "Cluster '$(CLUSTER_NAME)' already exists."; \
	else \
		k3d cluster create $(CLUSTER_NAME) --port "8090:80@loadbalancer" --agents 1; \
	fi
	kubectl cluster-info

cluster-down:
	k3d cluster delete $(CLUSTER_NAME)

images-build:
	@for svc in $(SERVICES); do \
		echo "Building redline-$$svc ..."; \
		docker build -t redline-$$svc:latest -f apps/$$svc/Dockerfile . ; \
	done
	@echo "Building redline-gateway ..."
	docker build -t redline-gateway:latest -f infra/gateway/Dockerfile .

images-import:
	@for svc in $(SERVICES); do \
		echo "Importing redline-$$svc into k3d ..."; \
		k3d image import redline-$$svc:latest -c $(CLUSTER_NAME); \
	done
	@echo "Importing redline-gateway into k3d ..."
	k3d image import redline-gateway:latest -c $(CLUSTER_NAME)

keda-install:
	@if helm status keda -n keda > /dev/null 2>&1; then \
		echo "KEDA already installed."; \
	else \
		helm repo add kedacore https://kedacore.github.io/charts; \
		helm repo update; \
		helm install keda kedacore/keda --namespace keda --create-namespace --wait; \
	fi

helm-install: keda-install
	helm install $(HELM_RELEASE) $(CHART_PATH) \
		--namespace $(NAMESPACE) \
		--create-namespace \
		--set image.tag="$${IMAGE_TAG:-latest}" \
		--set secrets.jwtSecretKey="$${JWT_SECRET_KEY:-change_me_in_production}" \
		--set secrets.geminiApiKey="$${GEMINI_API_KEY:-}" \
		--atomic --wait

helm-upgrade:
	helm upgrade $(HELM_RELEASE) $(CHART_PATH) \
		--namespace $(NAMESPACE) \
		--set image.tag="$${IMAGE_TAG:-latest}" \
		--set secrets.jwtSecretKey="$${JWT_SECRET_KEY:-change_me_in_production}" \
		--set secrets.geminiApiKey="$${GEMINI_API_KEY:-}" \
		--atomic --wait

helm-uninstall:
	helm uninstall $(HELM_RELEASE) --namespace $(NAMESPACE)

helm-status:
	@echo "=== Pods ===" && kubectl get pods -n $(NAMESPACE)
	@echo "" && echo "=== Services ===" && kubectl get svc -n $(NAMESPACE)
	@echo "" && echo "=== Ingress ===" && kubectl get ingress -n $(NAMESPACE)
	@echo "" && echo "=== ScaledObjects ===" && kubectl get scaledobjects -n $(NAMESPACE) 2>/dev/null || true
	@echo "" && echo "=== HPA ===" && kubectl get hpa -n $(NAMESPACE) 2>/dev/null || true

deploy:
	$(MAKE) images-build
	$(MAKE) images-import
	$(MAKE) helm-upgrade
	kubectl rollout restart deployment/eval-service -n redline
	kubectl rollout restart deployment/agent-service -n redline
	kubectl rollout restart deployment/gate-service -n redline
	kubectl rollout restart deployment/eval-worker -n redline
	kubectl rollout restart deployment/gateway -n redline

logs:
	kubectl logs -n $(NAMESPACE) -l app.kubernetes.io/instance=$(HELM_RELEASE) \
		--all-containers --follow --prefix

teardown: helm-uninstall cluster-down

monitoring-install:
	helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
	helm repo add grafana https://grafana.github.io/helm-charts
	helm repo update
	helm install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
		--namespace monitoring \
		--create-namespace \
		--set grafana.adminPassword=redline_admin \
		--set prometheus.prometheusSpec.serviceMonitorSelectorNilUsesHelmValues=false \
		--wait
	helm install loki grafana/loki-stack \
		--namespace monitoring \
		--set grafana.enabled=false \
		--wait

monitoring-port-forward:
	kubectl port-forward -n monitoring svc/kube-prometheus-stack-grafana 3000:80 &
	kubectl port-forward -n monitoring svc/kube-prometheus-stack-prometheus 9090:9090 &
	echo "Grafana: http://localhost:3000 (admin/redline_admin)"
	echo "Prometheus: http://localhost:9090"

# Phase 5.3 (dashboard v2) -- generates TypeScript types from the monolith's
# OpenAPI schema via pure schema introspection (app.openapi()), no DB/Redis/
# Kafka needed, so CI can run this with nothing else running. Source of truth
# is the monolith even though production runs 3 separate services, since it's
# the single combined schema covering all 21+ routes.
generate-openapi-schema:
	python3 -c "import json; from apps.api.main import app; print(json.dumps(app.openapi()))" > /tmp/redline-openapi.json

generate-types: generate-openapi-schema
	cd apps/dashboard && npx openapi-typescript /tmp/redline-openapi.json -o src/lib/api-types.ts

# Phase 5.5(c) -- load-tests RedLine's OWN /eval-runs endpoint (not an agent
# under test -- see apps/api/services/load_engine.py for that). Containerized
# k6, no host install needed. Requires REDLINE_API_KEY, AGENT_VERSION_ID,
# SUITE_ID in the environment; VUS/DURATION optional (default 10/30s).
#
# host.docker.internal, not localhost/--network host: on macOS Docker Desktop
# (this project's primary dev target), a separate `docker run` container is
# not on the compose project's bridge network and --network host is
# Linux-only/unsupported there -- host.docker.internal is the one address
# that reliably reaches a host-published port from any standalone container
# on both macOS and Linux Docker Desktop.
k6-load-test:
	docker run --rm -i \
		-e VUS="$${VUS:-10}" \
		-e DURATION="$${DURATION:-30s}" \
		-e REDLINE_BASE_URL="$${REDLINE_BASE_URL:-http://host.docker.internal:8085}" \
		-e REDLINE_API_KEY="$${REDLINE_API_KEY}" \
		-e AGENT_VERSION_ID="$${AGENT_VERSION_ID}" \
		-e SUITE_ID="$${SUITE_ID}" \
		-v $(PWD)/scripts/k6:/scripts \
		grafana/k6 run /scripts/eval_trigger_load.js