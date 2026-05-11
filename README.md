# HealthSignal Platform
### Nordic HealthTech ML Infrastructure

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
│   └── manifests.yaml          # K8s Deployment, Service, HPA
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
| ElasticSearch | ES container, prediction logging, /stats endpoint |
| CI/CD pipelines | GitHub Actions: train → build → push → deploy |
| Monitoring & observability | Prometheus + Grafana with custom metrics |
| Docker containerization | Multi-stage Dockerfile, docker-compose |
| ML platform knowledge | Understands the model they're running infra for |

---

## Stopping everything

```bash
# Docker Compose
docker compose down -v

# kind cluster
kind delete cluster --name sickleave
```