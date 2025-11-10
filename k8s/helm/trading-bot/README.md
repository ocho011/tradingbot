# Trading Bot Helm Chart

Kubernetes deployment for the Trading Bot application with comprehensive monitoring, persistence, and security features.

## Prerequisites

- Kubernetes 1.19+
- Helm 3.0+
- kubectl configured to access your cluster
- (Optional) metrics-server for HPA

## Quick Start

### 1. Install Helm Chart

```bash
# Development environment
helm install trading-bot ./trading-bot -f values-dev.yaml -n trading-dev --create-namespace

# Staging environment
helm install trading-bot ./trading-bot -f values-staging.yaml -n trading-staging --create-namespace

# Production environment
helm install trading-bot ./trading-bot -f values-prod.yaml -n trading-prod --create-namespace
```

### 2. Verify Deployment

```bash
# Check pod status
kubectl get pods -n trading-dev

# Check service
kubectl get svc -n trading-dev

# Check HPA (if enabled)
kubectl get hpa -n trading-dev

# View logs
kubectl logs -f deployment/trading-bot -n trading-dev
```

### 3. Test Health Endpoints

```bash
# Port-forward to access locally
kubectl port-forward svc/trading-bot 8000:8000 -n trading-dev

# Check health endpoints
curl http://localhost:8000/health
curl http://localhost:8000/ready
curl http://localhost:8000/metrics
```

## Configuration

### Environment-Specific Values

The chart includes pre-configured values files for each environment:

- **values-dev.yaml**: Development with minimal resources, debug logging
- **values-staging.yaml**: Staging with moderate resources, HPA enabled
- **values-prod.yaml**: Production with high availability, full monitoring

### Key Configuration Parameters

#### Application Settings

| Parameter | Description | Default |
|-----------|-------------|---------|
| `replicaCount` | Number of replicas | `1` |
| `image.repository` | Docker image repository | `trading-bot` |
| `image.tag` | Docker image tag | `latest` |
| `image.pullPolicy` | Image pull policy | `IfNotPresent` |

#### Resources

| Parameter | Description | Default |
|-----------|-------------|---------|
| `resources.limits.cpu` | CPU limit | `1000m` |
| `resources.limits.memory` | Memory limit | `2Gi` |
| `resources.requests.cpu` | CPU request | `500m` |
| `resources.requests.memory` | Memory request | `1Gi` |

#### Autoscaling

| Parameter | Description | Default |
|-----------|-------------|---------|
| `autoscaling.enabled` | Enable HPA | `true` |
| `autoscaling.minReplicas` | Minimum replicas | `1` |
| `autoscaling.maxReplicas` | Maximum replicas | `5` |
| `autoscaling.targetCPUUtilizationPercentage` | Target CPU % | `70` |

#### Trading Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `config.trading.maxPositions` | Maximum concurrent positions | `3` |
| `config.trading.riskPerTrade` | Risk per trade (%) | `0.02` |
| `config.trading.tradingEnabled` | Enable live trading | `false` |

#### Persistence

| Parameter | Description | Default |
|-----------|-------------|---------|
| `persistence.enabled` | Enable persistence | `true` |
| `persistence.size` | Storage size | `10Gi` |
| `persistence.storageClass` | Storage class | `""` |

## Secrets Management

**IMPORTANT**: Never commit actual secrets to git!

### Development

For development, you can use placeholder values in `values-dev.yaml`:

```yaml
secrets:
  binanceApiKey: "dev-testnet-key"
  binanceApiSecret: "dev-testnet-secret"
```

### Production

For staging and production, use external secret management:

#### Option 1: Kubernetes Secrets (Manual)

```bash
# Create secret manually
kubectl create secret generic trading-bot \
  --from-literal=binance-api-key=YOUR_API_KEY \
  --from-literal=binance-api-secret=YOUR_API_SECRET \
  --from-literal=database-user=YOUR_DB_USER \
  --from-literal=database-password=YOUR_DB_PASSWORD \
  --from-literal=redis-password=YOUR_REDIS_PASSWORD \
  --from-literal=encryption-key=YOUR_ENCRYPTION_KEY \
  -n trading-prod

# Then deploy without secrets in values file
helm install trading-bot ./trading-bot -f values-prod.yaml -n trading-prod
```

#### Option 2: Sealed Secrets (Recommended)

```bash
# Install sealed-secrets controller
kubectl apply -f https://github.com/bitnami-labs/sealed-secrets/releases/download/v0.18.0/controller.yaml

# Create sealed secret
echo -n YOUR_API_KEY | kubectl create secret generic trading-bot-secrets \
  --dry-run=client \
  --from-file=binance-api-key=/dev/stdin \
  -o yaml | \
  kubeseal -o yaml > sealed-secret.yaml

# Apply sealed secret
kubectl apply -f sealed-secret.yaml -n trading-prod
```

#### Option 3: HashiCorp Vault

```bash
# Enable Vault secrets engine
vault secrets enable -path=trading-bot kv-v2

# Store secrets
vault kv put trading-bot/prod \
  binance-api-key=YOUR_API_KEY \
  binance-api-secret=YOUR_API_SECRET

# Use Vault injector in Helm chart
```

## Deployment Strategies

### Rolling Update (Default)

```bash
# Update image tag
helm upgrade trading-bot ./trading-bot \
  --set image.tag=1.1.0 \
  -f values-prod.yaml \
  -n trading-prod
```

### Blue-Green Deployment

```bash
# Deploy new version (green)
helm install trading-bot-green ./trading-bot \
  --set image.tag=1.1.0 \
  -f values-prod.yaml \
  -n trading-prod

# Switch traffic (update service selector)
kubectl patch service trading-bot \
  -p '{"spec":{"selector":{"version":"green"}}}' \
  -n trading-prod

# Remove old version (blue)
helm uninstall trading-bot -n trading-prod
```

## Testing

### Dry Run

```bash
# Test template rendering
helm template trading-bot ./trading-bot -f values-dev.yaml

# Test installation without deploying
helm install trading-bot ./trading-bot \
  -f values-dev.yaml \
  --dry-run --debug \
  -n trading-dev
```

### Validation

```bash
# Validate manifests
helm lint ./trading-bot

# Check resource creation
kubectl apply -f <(helm template trading-bot ./trading-bot -f values-dev.yaml) --dry-run=client

# Verify all resources
kubectl get all -n trading-dev -l app.kubernetes.io/name=trading-bot
```

### Integration Testing

```bash
# Port-forward for testing
kubectl port-forward svc/trading-bot 8000:8000 -n trading-dev

# Test health checks
curl http://localhost:8000/health
# Expected: {"status": "healthy"}

curl http://localhost:8000/ready
# Expected: {"status": "ready"}

# Test metrics endpoint
curl http://localhost:8000/metrics
# Expected: Prometheus metrics

# Check logs for errors
kubectl logs -f deployment/trading-bot -n trading-dev --tail=100

# Test autoscaling (if enabled)
kubectl run -it --rm load-generator \
  --image=busybox \
  --restart=Never \
  -- /bin/sh -c "while true; do wget -q -O- http://trading-bot:8000/health; done"

# Watch HPA scale up
kubectl get hpa -n trading-dev --watch
```

## Monitoring

### Prometheus Integration

The chart automatically exposes metrics at `/metrics`:

```yaml
podAnnotations:
  prometheus.io/scrape: "true"
  prometheus.io/port: "8000"
  prometheus.io/path: "/metrics"
```

### Grafana Dashboard

Import the trading bot dashboard (ID: TBD) or create custom dashboards using metrics:

- `trading_signals_generated_total`
- `order_execution_latency_seconds`
- `risk_violations_total`
- `position_pnl_dollars`

## Troubleshooting

### Pod Not Starting

```bash
# Check events
kubectl describe pod <pod-name> -n trading-dev

# Check logs
kubectl logs <pod-name> -n trading-dev

# Common issues:
# - Image pull errors: Check image repository/tag
# - Secret missing: Verify secrets are created
# - Resource limits: Check node resources
```

### Health Check Failures

```bash
# Check liveness probe
kubectl get events -n trading-dev | grep Unhealthy

# Test health endpoint directly
kubectl exec -it <pod-name> -n trading-dev -- curl localhost:8000/health

# Adjust probe settings if needed
helm upgrade trading-bot ./trading-bot \
  --set livenessProbe.initialDelaySeconds=60 \
  -f values-dev.yaml
```

### HPA Not Scaling

```bash
# Check metrics-server
kubectl get apiservice v1beta1.metrics.k8s.io -o yaml

# Check HPA status
kubectl describe hpa trading-bot -n trading-dev

# Check resource metrics
kubectl top pods -n trading-dev
```

### Database Connection Issues

```bash
# Check ConfigMap
kubectl get configmap trading-bot -n trading-dev -o yaml

# Test database connectivity
kubectl run -it --rm debug \
  --image=postgres:13 \
  --restart=Never \
  -- psql -h postgres-dev -U devuser -d tradingbot_dev
```

## Upgrade Guide

### Minor Version Upgrade

```bash
# Backup current config
helm get values trading-bot -n trading-prod > backup-values.yaml

# Upgrade
helm upgrade trading-bot ./trading-bot \
  -f values-prod.yaml \
  -n trading-prod

# Verify
kubectl rollout status deployment/trading-bot -n trading-prod
```

### Rollback

```bash
# List releases
helm history trading-bot -n trading-prod

# Rollback to previous version
helm rollback trading-bot -n trading-prod

# Rollback to specific revision
helm rollback trading-bot 3 -n trading-prod
```

## Uninstallation

```bash
# Uninstall release
helm uninstall trading-bot -n trading-dev

# Delete PVC (if needed)
kubectl delete pvc trading-bot -n trading-dev

# Delete namespace
kubectl delete namespace trading-dev
```

## Security Best Practices

1. **Never commit secrets to git** - Use external secret management
2. **Use specific image tags** - Avoid `latest` in production
3. **Enable RBAC** - Limit pod permissions
4. **Run as non-root** - Set `runAsNonRoot: true`
5. **Enable network policies** - Restrict pod-to-pod communication
6. **Regular updates** - Keep images and dependencies updated
7. **Audit logs** - Enable audit logging for compliance

## Production Checklist

Before deploying to production:

- [ ] Secrets configured via external management (Vault/Sealed Secrets)
- [ ] Resource limits and requests properly set
- [ ] HPA enabled and tested
- [ ] Persistent storage configured with backups
- [ ] Monitoring and alerting configured
- [ ] Health checks validated
- [ ] RBAC policies reviewed
- [ ] Network policies configured
- [ ] TLS/SSL enabled for ingress
- [ ] Disaster recovery plan documented
- [ ] Runbook created for common issues

## Support

For issues and questions:
- GitHub Issues: [repository-url]
- Documentation: [docs-url]
- Slack Channel: #trading-bot

## License

[Your License]
