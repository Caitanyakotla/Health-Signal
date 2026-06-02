# HealthSignal Platform
### Nordic HealthTech ML Infrastructure
A cloud-native ML inference platform for predicting employee sick leave  built as a personal project to demonstrate  production-grade DevOps and MLOps practices in a healthcare context.

## About the Project

This is a personal portfolio project. The concept itself is real healthcare organisations use similar platforms today 
to manage workforce sick leave. In production this kind of system can help hospital HR(health  record) teams anticipate staff shortages before they happen, helping protect patient care.

Infrastructure:
**AWS · Kubernetes · ElasticSearch · CI/CD · Prometheus · Grafana · Docker**

---

## Architecture

```
load_test.py
     │  POST /predict
     ▼
FastAPI (port 8000)          ← My ML inference service
  ├── GradientBoosting model  ← trained on 5000 synthetic employee records
  ├── ElasticSearch           ← logs every prediction event (port 9200)
  └── Prometheus metrics      ← /metrics endpoint (scraped every 15s)
          │
          ▼
     Prometheus (port 9090)
          │
          ▼
     Grafana (port 3000)      ← dashboard: predictions, latency, risk breakdown
     Kibana  (port 5601)      ← explore raw prediction events in ES
```

---

## Quick Start (Docker Compose — easiest)

### Prerequisites
- Docker + Docker Compose (or Podman + podman-compose)


```bash
# 1. Clone / enter project
cd healthsignal-platform

# 2. Train the model first
python3 ml/train_model.py

# 3. Start all services
docker compose up --build -d

# 4. Wait ~60s for ElasticSearch to be ready, then run load test
python3 load_test.py
```

### Access services
| Service | URL | Credentials |
|---------|-----|-------------|
| API docs (Swagger) | http://localhost:8000/docs | — |
| API health | http://localhost:8000/health | — |
| Prometheus | http://localhost:9090 | — |
| Grafana | http://localhost:3000 | admin / admin123 |
| Kibana | http://localhost:5601 | — |
| ElasticSearch | http://localhost:9200 | — |

---

## Screenshots

**HealthSignal Dashboard — Risk Overview**
![Dashboard overview](Screenshots/Dashboard%201.jpg)

**Employee Risk Table — High / Low classification**
![Employee risk table](Screenshots/Dashboard%202.jpg)

**Live API Prediction — HIGH risk employee (curl)**
![API prediction response](Screenshots/Prediction%20data.jpg)

**Grafana — Prediction rate by risk level (Prometheus)**
![Grafana prediction metrics](Screenshots/Grafana%20dashboard%20Risk%20Predicition%202%20.jpg)

**Kubernetes — Pods, Services, Deployment, HPA running**
![Kubernetes resources](Screenshots/k8s%20Resources.jpg)

---

## Kubernetes (kind cluster — local)

### Prerequisites
```bash
# Install kind
curl -Lo ./kind https://kind.sigs.k8s.io/dl/v0.22.0/kind-linux-amd64
chmod +x ./kind && sudo mv ./kind /usr/local/bin/kind

# Install kubectl
curl -LO "https://dl.k8s.io/release/$(curl -sL https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
chmod +x kubectl && sudo mv kubectl /usr/local/bin/
```

### Deploy
```bash
# 1. Create local cluster
kind create cluster --name sickleave

# 2. Build image and load into kind
docker build -t healthsignal-predictor:latest .
kind load docker-image healthsignal-predictor:latest --name sickleave

# 3. Apply manifests
kubectl apply -f k8s/manifests.yaml

# 4. Watch pods come up
kubectl get pods -n sickleave -w

# 5. Port-forward the API
kubectl port-forward svc/predictor-service 8000:80 -n sickleave

# 6. Test it
curl http://localhost:8000/health
```

### Install monitoring on k8s
```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

helm install monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace \
  --set grafana.adminPassword=admin123

# Port-forward Grafana
kubectl port-forward svc/monitoring-grafana 3000:80 -n monitoring
```

---

## Kyverno Policy Enforcement

[Kyverno](https://kyverno.io) is a Kubernetes-native policy engine. HealthSignal uses it to enforce security and operational standards across the `healthsignal` namespace.

### Policies

| Policy | File | Scope | What it enforces |
|--------|------|-------|-----------------|
| Disallow Privileged Containers | `k8s/kyverno/disallow-privileged.yaml` | Pods | No container may run with `privileged: true` |
| Require Resource Limits | `k8s/kyverno/require-resource-limits.yaml` | Pods | Every container must define `cpu` and `memory` limits |
| Require Deployment Labels | `k8s/kyverno/require-labels.yaml` | Deployments | Must have `app`, `team`, and `version` labels |

All policies are set to `audit` mode — violations are logged but not blocked. Switch to `enforce` when ready to harden.

### Install Kyverno

```bash
helm repo add kyverno https://kyverno.github.io/kyverno/
helm repo update

helm install kyverno kyverno/kyverno \
  --namespace kyverno \
  --create-namespace
```

### Apply policies

```bash
kubectl apply -f k8s/kyverno/
```

### Check for violations

```bash
# List all policy reports
kubectl get policyreport -n healthsignal

# See detailed violations
kubectl describe policyreport -n healthsignal
```

### Switch a policy to enforce mode

Edit the relevant file and change `validationFailureAction`:

```yaml
validationFailureAction: enforce   # was: audit
```

Then re-apply:

```bash
kubectl apply -f k8s/kyverno/disallow-privileged.yaml
```

---

## SBOM — Software Bill of Materials

An SBOM is an ingredients list for the container image for every package, library, and version included. In MedTech and regulated sectors, SBOMs are required by frameworks like the EU.

Cyber Resilience Act: when a CVE is disclosed, security teams check the SBOM to instantly know which products are affected without re-scanning everything.

HealthSignal generates SBOMs automatically in the CI pipeline using [Syft](https://github.com/anchore/syft)

### Formats generated

| Format | File | Used for |
|--------|------|----------|
| SPDX JSON | `healthsignal-sbom.spdx.json` | Industry standard, EU CRA compliance |
| CycloneDX JSON | `healthsignal-sbom.cyclonedx.json` | Preferred in healthcare / regulated sectors |

### Generate locally

# Install Syft
curl -sSfL https://raw.githubusercontent.com/anchore/syft/main/install.sh | sh -s -- -b /usr/local/bin

# Build image
docker build -t healthsignal:sbom .

# Generate SPDX
syft healthsignal:sbom -o spdx-json > healthsignal-sbom.spdx.json

# Generate CycloneDX
syft healthsignal:sbom -o cyclonedx-json > healthsignal-sbom.cyclonedx.json

# Summary
syft healthsignal:sbom -o table
```

### In CI (GitHub Actions)

The `sbom-generate` job runs on every push to `main`/`dev`. Both SBOM files are uploaded as workflow artifacts and downloadable from the GitHub Actions UI under **healthsignal-sbom**.

---

## Manual API test (curl)

```bash
# Single prediction — HIGH risk employee
curl -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{
    "age": 52,
    "tenure_years": 3,
    "absences_last_year": 8,
    "absences_last_3months": 4,
    "department_stress_score": 9.2,
    "previous_long_term": 1,
    "part_time": 0,
    "manager_support_score": 3.1
  }'

# Single prediction — LOW risk employee
curl -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{
    "age": 29,
    "tenure_years": 7,
    "absences_last_year": 1,
    "absences_last_3months": 0,
    "department_stress_score": 3.5,
    "previous_long_term": 0,
    "part_time": 0,
    "manager_support_score": 9.0
  }'

# Prometheus metrics
curl http://localhost:8000/metrics

# ElasticSearch prediction stats
curl http://localhost:8000/stats
```

---

## Project Structure

```
healthsignal-platform/
├── ml/
│   └── train_model.py          # Data generation + model training
├── app/
│   ├── main.py                 # FastAPI service
│   ├── model.pkl               # Trained model (generated)
│   └── features.pkl            # Feature list (generated)
├── k8s/
│   ├── manifests.yaml          # K8s Deployment, Service, HPA
│   └── kyverno/
│       ├── disallow-privileged.yaml      # Block privileged containers
│       ├── require-resource-limits.yaml  # Enforce CPU/memory limits
│       └── require-labels.yaml           # Enforce app/team/version labels
├── monitoring/
│   ├── prometheus.yml          # Prometheus scrape config
│   ├── grafana-datasource.yml  # Grafana Prometheus datasource
│   ├── grafana-dashboard.json  # Pre-built dashboard
│   └── grafana-dashboard-config.yml
├── .github/
│   └── workflows/
│       └── deploy.yml          # GitHub Actions CI/CD (AWS EKS)
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── load_test.py                # Traffic generator
└── README.md
```

---

## Skills demonstrated

| Job requirement | This project |
|---|---|
| AWS infrastructure | Terraform EKS + ECR in deploy.yml |
| Kubernetes clusters | kind local + k8s/manifests.yaml with HPA |
| Policy-as-code | Kyverno ClusterPolicies for security + operational standards |
| Supply chain security | Syft SBOM generation (SPDX + CycloneDX) in CI, Trivy CVE scanning |
| ElasticSearch | ES container, prediction logging, /stats endpoint |
| CI/CD pipelines | GitHub Actions: train → build → push → deploy |
| Monitoring & observability | Prometheus + Grafana with custom metrics |
| Docker containerization | Multi-stage Dockerfile, docker-compose |
| ML platform knowledge | Understands the model they're running infra for |

---

## Stopping everything

```bash
# Docker Compose
docker images
docker compose down -v

# kind cluster
kind delete cluster --name sickleave
```
