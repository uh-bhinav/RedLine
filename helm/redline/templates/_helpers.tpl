{{- define "redline.name" -}}
{{- .Chart.Name | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "redline.labels" -}}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "redline.commonEnv" -}}
- name: DATABASE_URL
  valueFrom:
    secretKeyRef:
      name: redline-secrets
      key: database-url
- name: JWT_SECRET_KEY
  valueFrom:
    secretKeyRef:
      name: redline-secrets
      key: jwt-secret-key
- name: GEMINI_API_KEY
  valueFrom:
    secretKeyRef:
      name: redline-secrets
      key: gemini-api-key
- name: REDIS_URL
  valueFrom:
    configMapKeyRef:
      name: redline-config
      key: redis-url
- name: REDPANDA_BOOTSTRAP_SERVERS
  valueFrom:
    configMapKeyRef:
      name: redline-config
      key: redpanda-bootstrap-servers
- name: CLICKHOUSE_HOST
  valueFrom:
    configMapKeyRef:
      name: redline-config
      key: clickhouse-host
- name: CLICKHOUSE_PORT
  valueFrom:
    configMapKeyRef:
      name: redline-config
      key: clickhouse-port
- name: CLICKHOUSE_DB
  valueFrom:
    configMapKeyRef:
      name: redline-config
      key: clickhouse-db
- name: CLICKHOUSE_USER
  valueFrom:
    configMapKeyRef:
      name: redline-config
      key: clickhouse-user
- name: CLICKHOUSE_PASSWORD
  valueFrom:
    secretKeyRef:
      name: redline-secrets
      key: clickhouse-password
- name: OTEL_EXPORTER_ENDPOINT
  valueFrom:
    configMapKeyRef:
      name: redline-config
      key: otel-exporter-endpoint
{{- end }}