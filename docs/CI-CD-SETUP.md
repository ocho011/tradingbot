# CI/CD Pipeline Setup Guide

Complete guide for GitHub Actions CI/CD pipeline with Blue-Green deployment strategy.

## 📋 Table of Contents

- [Overview](#overview)
- [Pipeline Architecture](#pipeline-architecture)
- [Prerequisites](#prerequisites)
- [Initial Setup](#initial-setup)
- [Workflow Details](#workflow-details)
- [Deployment Process](#deployment-process)
- [Rollback Procedures](#rollback-procedures)
- [Troubleshooting](#troubleshooting)

## 🎯 Overview

This project implements a comprehensive CI/CD pipeline with:

- **Continuous Integration (CI)**: Automated testing, linting, type checking, and security scanning
- **Continuous Deployment (CD)**: Blue-Green deployment to dev → staging → production
- **Rollback Capability**: Quick rollback to previous stable versions
- **Security**: Automated security scanning and approval gates

## 🏗️ Pipeline Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         CI Pipeline                             │
├─────────────────────────────────────────────────────────────────┤
│  Push/PR → Test → Lint → Type Check → Security → Docker Build  │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                         CD Pipeline                             │
├─────────────────────────────────────────────────────────────────┤
│  Build → Dev Deploy → Staging Deploy → [Approval] → Prod Deploy│
│         (Auto)        (Auto)            (Manual)    (Blue-Green)│
└─────────────────────────────────────────────────────────────────┘
```

### Blue-Green Deployment Strategy

```
┌──────────────┐
│   Traffic    │
│ Load Balancer│
└──────┬───────┘
       │
       ├─────────────┐
       │             │
   ┌───▼────┐   ┌───▼────┐
   │  Blue  │   │ Green  │
   │ (Old)  │   │ (New)  │
   └────────┘   └────────┘
       │             │
       └─────┬───────┘
             │
      ┌──────▼──────┐
      │  Database   │
      └─────────────┘

Process:
1. Deploy new version (Green)
2. Run health checks on Green
3. Gradually shift traffic: 10% → 50% → 100%
4. Monitor metrics and errors
5. Remove old version (Blue)
6. Rollback if issues detected
```

## 📦 Prerequisites

### Required Tools

- GitHub repository with Actions enabled
- Docker and Docker Hub / GitHub Container Registry account
- Target deployment environment (cloud provider, VPS, or Kubernetes)

### Required GitHub Secrets

Navigate to: `Repository → Settings → Secrets and variables → Actions`

#### Required Secrets:

```bash
# Container Registry (GitHub Container Registry is used by default)
GHCR_TOKEN                  # GitHub Personal Access Token with packages:write permission

# Optional: External Container Registry
# DOCKER_USERNAME           # Docker Hub username
# DOCKER_PASSWORD           # Docker Hub password or access token

# Deployment Targets (if using external servers)
# DEV_SSH_KEY               # SSH private key for development server
# STAGING_SSH_KEY           # SSH private key for staging server
# PROD_SSH_KEY              # SSH private key for production server

# API Keys (if needed for deployment validation)
# BINANCE_API_KEY           # For production deployment validation
# BINANCE_API_SECRET        # For production deployment validation

# Notification Services (optional)
# SLACK_WEBHOOK_URL         # For deployment notifications
# DISCORD_WEBHOOK_URL       # For deployment notifications
```

### Required GitHub Environments

Create environments with protection rules:

1. **development**
   - No approvals required
   - URL: `https://dev.tradingbot.example.com`

2. **staging**
   - No approvals required (auto-deploy after dev)
   - URL: `https://staging.tradingbot.example.com`

3. **production**
   - **Required reviewers**: Add team members who can approve
   - **Wait timer**: Optional 5-minute wait before allowing approval
   - URL: `https://tradingbot.example.com`

**To create environments:**
```
Repository → Settings → Environments → New environment
```

For each environment:
- Add environment secrets if needed
- Configure protection rules
- Set deployment branch restrictions (optional)

## 🚀 Initial Setup

### 1. Enable GitHub Actions

```bash
# Ensure workflows are in the correct location
.github/
└── workflows/
    ├── ci.yml           # CI pipeline
    ├── cd.yml           # CD pipeline
    └── rollback.yml     # Rollback workflow
```

### 2. Configure Container Registry

**Option A: GitHub Container Registry (Recommended)**

```bash
# Create personal access token with packages:write permission
# Go to: Settings → Developer settings → Personal access tokens → Generate new token

# Add token as repository secret named GITHUB_TOKEN (auto-provided by GitHub Actions)
```

**Option B: Docker Hub**

```bash
# Add Docker Hub credentials as secrets
DOCKER_USERNAME=your-docker-username
DOCKER_PASSWORD=your-docker-password
```

### 3. Update Workflow Configuration

Edit `.github/workflows/cd.yml` if using Docker Hub:

```yaml
env:
  REGISTRY: docker.io  # Change from ghcr.io
  IMAGE_NAME: your-username/tradingbot
```

### 4. Configure Deployment Environments

Update environment URLs in workflow files to match your infrastructure:

```yaml
environment:
  name: production
  url: https://your-actual-domain.com  # Update this
```

### 5. Test CI Pipeline

```bash
# Push to a feature branch to trigger CI
git checkout -b test-ci
git commit --allow-empty -m "Test CI pipeline"
git push origin test-ci

# Create a pull request to main
# CI should run automatically
```

## ⚙️ Workflow Details

### CI Pipeline (`ci.yml`)

Triggered on:
- Push to `main` or `develop` branches
- Pull requests to `main` or `develop`
- Manual workflow dispatch

**Jobs:**

1. **Test Suite** (`test`)
   - Runs on Python 3.9, 3.10, 3.11
   - Executes pytest with coverage
   - Uploads coverage to Codecov

2. **Code Linting** (`lint`)
   - Runs flake8
   - Checks code formatting with black
   - Verifies import sorting with isort

3. **Type Checking** (`type-check`)
   - Runs mypy for static type analysis
   - Non-blocking (continues on error)

4. **Security Scan** (`security`)
   - Runs Bandit for security vulnerabilities
   - Runs Safety for dependency vulnerabilities
   - Uploads security reports as artifacts

5. **Docker Build** (`docker-build`)
   - Validates Docker image can be built
   - Tests image execution
   - Uses layer caching for efficiency

6. **CI Status** (`ci-status`)
   - Aggregates results from all jobs
   - Fails if critical jobs fail

### CD Pipeline (`cd.yml`)

Triggered on:
- Successful CI completion on `main` branch
- Manual workflow dispatch

**Jobs:**

1. **Build and Push** (`build-and-push`)
   - Builds Docker image
   - Tags with multiple strategies (branch, SHA, version)
   - Pushes to container registry
   - Creates build attestation

2. **Deploy to Development** (`deploy-dev`)
   - Automatic deployment
   - Blue-Green deployment strategy
   - Runs smoke tests

3. **Deploy to Staging** (`deploy-staging`)
   - Deploys after successful dev deployment
   - Runs integration tests
   - Runs performance tests

4. **Deploy to Production** (`deploy-production`)
   - **Requires manual approval**
   - Creates backup before deployment
   - Blue-Green deployment with gradual traffic shift
   - Comprehensive health checks
   - Auto-rollback on failure

5. **CD Status** (`cd-status`)
   - Provides deployment summary
   - Notifies team of results

### Rollback Workflow (`rollback.yml`)

Triggered on:
- Manual workflow dispatch only

**Process:**
1. Validates rollback request
2. Creates backup of current state
3. Executes rollback to specified version
4. Verifies health after rollback
5. Monitors post-rollback metrics

## 🚢 Deployment Process

### Automatic Deployment (Dev/Staging)

```bash
# 1. Merge PR to main branch
git checkout main
git pull origin main

# 2. CI runs automatically
# 3. On CI success, CD pipeline starts
# 4. Automatically deploys to dev
# 5. Automatically deploys to staging
```

### Manual Deployment (Production)

```bash
# 1. Wait for staging deployment to complete
# 2. Review deployment in staging environment
# 3. Go to: Actions → CD Pipeline → Latest workflow run
# 4. Click "Review deployments"
# 5. Select "production" environment
# 6. Add approval comment
# 7. Click "Approve and deploy"
```

### Manual Deployment to Specific Environment

```bash
# Trigger workflow manually
# Go to: Actions → CD Pipeline → Run workflow

# Select:
# - Branch: main
# - Environment: production (or dev, staging)
# - Skip tests: false (recommended)

# Click "Run workflow"
```

## 🔄 Rollback Procedures

### When to Rollback

- Critical bugs discovered in production
- Performance degradation
- Service unavailability
- Database migration issues
- Security vulnerabilities

### How to Rollback

```bash
# 1. Go to: Actions → Rollback Deployment → Run workflow

# 2. Fill in details:
#    - Environment: production (or staging, development)
#    - Version: previous (or specific version tag)
#    - Reason: "Critical bug: user authentication failing"

# 3. Click "Run workflow"

# 4. Monitor rollback progress

# 5. Verify service is restored
```

### Rollback Process

```
1. Validate Request
   ↓
2. Create Backup
   ↓
3. Stop Current Version
   ↓
4. Deploy Previous Version
   ↓
5. Health Check
   ↓
6. Verify Success
   ↓
7. Notify Team
```

## 🐛 Troubleshooting

### CI Pipeline Failures

**Tests Failing:**
```bash
# Run tests locally
pytest --cov=src --cov-report=term-missing

# Check specific test
pytest tests/path/to/test_file.py::test_name -v
```

**Linting Failures:**
```bash
# Fix formatting issues
black src/ tests/
isort src/ tests/

# Check linting
flake8 src/ tests/ --max-line-length=100
```

**Docker Build Failures:**
```bash
# Build locally to debug
docker build -t tradingbot:test .

# Check for missing dependencies
docker run --rm tradingbot:test pip list
```

### CD Pipeline Failures

**Deployment Fails:**
```bash
# Check deployment logs in Actions tab
# Verify secrets are configured
# Test SSH access to servers (if applicable)
# Check resource availability (disk space, memory)
```

**Health Checks Failing:**
```bash
# SSH into server
ssh user@server.example.com

# Check container status
docker ps

# Check logs
docker logs tradingbot

# Test health endpoint
curl http://localhost:8000/health
```

**Database Migration Issues:**
```bash
# SSH into server
docker exec -it tradingbot bash

# Check migration status
alembic current

# Run migrations manually
alembic upgrade head

# Rollback migration if needed
alembic downgrade -1
```

### Rollback Issues

**Rollback Fails:**
```bash
# Manual rollback process:

# 1. SSH into server
ssh user@production-server.example.com

# 2. List available versions
docker images | grep tradingbot

# 3. Stop current version
docker-compose down

# 4. Update docker-compose to use old version
# Edit docker-compose.yml, change image tag

# 5. Start old version
docker-compose up -d

# 6. Verify health
curl http://localhost:8000/health
```

## 📊 Monitoring Deployments

### View Deployment Status

```bash
# GitHub Actions UI
Repository → Actions → Workflows

# Check specific deployment
Click on workflow run → View job details
```

### Monitor Production

```bash
# Application logs
docker logs -f tradingbot

# System metrics
docker stats tradingbot

# Prometheus metrics
http://your-domain.com:9090

# Grafana dashboard
http://your-domain.com:3000
```

## 🔐 Security Best Practices

1. **Secrets Management**
   - Never commit secrets to repository
   - Rotate secrets regularly
   - Use environment-specific secrets
   - Audit secret access

2. **Access Control**
   - Limit production approval to senior team members
   - Enable branch protection rules
   - Require code review before merge
   - Use least privilege principle

3. **Deployment Safety**
   - Always test in staging first
   - Monitor metrics after deployment
   - Have rollback plan ready
   - Document all production changes

## 📚 Additional Resources

- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [Docker Documentation](https://docs.docker.com/)
- [Blue-Green Deployment Pattern](https://martinfowler.com/bliki/BlueGreenDeployment.html)
- [Kubernetes Deployment Strategies](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/)

## 🆘 Support

For issues or questions:
1. Check workflow logs in Actions tab
2. Review this documentation
3. Contact DevOps team
4. Create issue in repository

---

**Last Updated:** 2025-11-13
**Maintained by:** DevOps Team
