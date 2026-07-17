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
		k3d cluster create $(CLUSTER_NAME) --port "8000:80@loadbalancer" --agents 1; \
	fi
	kubectl cluster-info

cluster-down:
	k3d cluster delete $(CLUSTER_NAME)

images-build:
	@for svc in $(SERVICES); do \
		echo "Building redline-$$svc ..."; \
		docker build -t redline-$$svc:latest -f apps/$$svc/Dockerfile . ; \
	done

images-import:
	@for svc in $(SERVICES); do \
		echo "Importing redline-$$svc into k3d ..."; \
		k3d image import redline-$$svc:latest -c $(CLUSTER_NAME); \
	done

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
		--set secrets.jwtSecretKey="$${JWT_SECRET_KEY:-change_me_in_production}" \
		--set secrets.geminiApiKey="$${GEMINI_API_KEY:-}" \
		--wait

helm-upgrade:
	helm upgrade $(HELM_RELEASE) $(CHART_PATH) \
		--namespace $(NAMESPACE) \
		--set secrets.jwtSecretKey="$${JWT_SECRET_KEY:-change_me_in_production}" \
		--set secrets.geminiApiKey="$${GEMINI_API_KEY:-}" \
		--wait

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