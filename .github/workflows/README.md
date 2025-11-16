# GitHub Actions Workflows

This directory contains automated CI/CD workflows for the Trading Bot project.

## 📋 Available Workflows

### 1. CI Pipeline (`ci.yml`)
**Purpose:** Continuous Integration - automated testing and code quality checks

**Triggers:**
- Push to `main` or `develop` branches
- Pull requests to `main` or `develop`
- Manual dispatch

**Jobs:**
- ✅ **Test Suite** - pytest with coverage (Python 3.9, 3.10, 3.11)
- 🎨 **Linting** - flake8, black, isort
- 🔍 **Type Checking** - mypy static analysis
- 🔒 **Security Scan** - bandit, safety
- 🐳 **Docker Build** - image build validation

**Status Badge:**
```markdown
![CI Pipeline](https://github.com/your-username/tradingbot/actions/workflows/ci.yml/badge.svg)
```

### 2. CD Pipeline (`cd.yml`)
**Purpose:** Continuous Deployment with Blue-Green strategy

**Triggers:**
- Successful CI completion on `main`
- Manual dispatch

**Deployment Flow:**
```
Build & Push → Dev (auto) → Staging (auto) → Production (manual approval)
```

**Environments:**
- **Development** - Automatic deployment, smoke tests
- **Staging** - Integration & performance tests
- **Production** - Manual approval required, comprehensive validation

**Features:**
- 🔵🟢 Blue-Green deployment strategy
- 🚦 Gradual traffic shifting (10% → 50% → 100%)
- 🏥 Health checks at each stage
- 🔄 Automatic rollback on failure
- 📊 Post-deployment monitoring

### 3. Rollback Workflow (`rollback.yml`)
**Purpose:** Emergency rollback to previous stable version

**Triggers:**
- Manual dispatch only

**Required Inputs:**
- Environment (development/staging/production)
- Target version (or "previous")
- Rollback reason

**Process:**
1. Validate rollback request
2. Create backup of current state
3. Execute rollback
4. Verify health
5. Monitor post-rollback metrics

## 🚀 Quick Start

### First Time Setup

1. **Configure GitHub Secrets**
   ```
   Settings → Secrets and variables → Actions → New repository secret
   ```

   Required secrets:
   - `GITHUB_TOKEN` (automatically provided)
   - Optional: External registry credentials

2. **Create GitHub Environments**
   ```
   Settings → Environments → New environment
   ```

   Create three environments:
   - `development` - No approval required
   - `staging` - No approval required
   - `production` - Add required reviewers

3. **Enable GitHub Actions**
   ```
   Settings → Actions → General → Allow all actions
   ```

4. **Verify Workflows**
   ```bash
   # Validate YAML syntax
   yamllint .github/workflows/*.yml

   # Or use GitHub's workflow validator
   # Actions tab → New workflow → Set up a workflow yourself
   ```

### Testing the Pipeline

#### Test CI Pipeline

```bash
# Create a test branch
git checkout -b test/ci-pipeline

# Make a small change
echo "# CI Test" >> README.md

# Commit and push
git add README.md
git commit -m "test: trigger CI pipeline"
git push origin test/ci-pipeline

# Create PR to main
# CI should run automatically
```

#### Test CD Pipeline (Manual)

```bash
# Go to Actions tab
# Select "CD Pipeline"
# Click "Run workflow"
# Choose:
#   - Branch: main
#   - Environment: development
#   - Skip tests: false
# Click "Run workflow"
```

#### Test Rollback

```bash
# Go to Actions tab
# Select "Rollback Deployment"
# Click "Run workflow"
# Fill in:
#   - Environment: development
#   - Version: previous
#   - Reason: "Testing rollback functionality"
# Click "Run workflow"
```

## 📊 Monitoring Workflows

### View Workflow Status

```bash
# Via GitHub UI
Repository → Actions → Select workflow → View runs

# Via GitHub CLI
gh run list
gh run view <run-id>
gh run watch <run-id>
```

### Check Deployment Status

```bash
# List deployments
gh api repos/:owner/:repo/deployments

# Check specific environment
gh api repos/:owner/:repo/deployments \
  --jq '.[] | select(.environment=="production")'
```

### Download Artifacts

```bash
# Security reports, test results, etc.
gh run download <run-id>

# Or via UI: Actions → Workflow run → Artifacts section
```

## 🔧 Customization

### Modify CI Checks

Edit `.github/workflows/ci.yml`:

```yaml
# Add new linting tool
- name: Run custom linter
  run: |
    pip install your-linter
    your-linter src/

# Add new test environment
strategy:
  matrix:
    python-version: ['3.9', '3.10', '3.11', '3.12']  # Added 3.12
```

### Modify Deployment Strategy

Edit `.github/workflows/cd.yml`:

```yaml
# Change traffic shift strategy
echo "🔀 Gradual traffic shift (25% → 75% → 100%)..."  # Modified percentages

# Add custom health check
- name: Custom health check
  run: |
    curl -f http://example.com/api/metrics
    # Add your custom checks
```

### Add Notification

```yaml
# Add to any workflow
- name: Notify on Slack
  if: always()
  uses: 8398a7/action-slack@v3
  with:
    status: ${{ job.status }}
    webhook_url: ${{ secrets.SLACK_WEBHOOK_URL }}
```

## 🐛 Troubleshooting

### Common Issues

#### Workflow Not Triggering
```bash
# Check workflow file syntax
yamllint .github/workflows/ci.yml

# Verify branch names match
git branch --show-current

# Check Actions are enabled
# Settings → Actions → General
```

#### Authentication Failures
```bash
# Verify secrets are set
# Settings → Secrets and variables → Actions

# Check token permissions
# Settings → Actions → General → Workflow permissions
```

#### Deployment Failures
```bash
# Check environment configuration
# Settings → Environments → [environment-name]

# Verify protection rules
# Settings → Environments → [environment-name] → Protection rules

# Check deployment logs
# Actions → Workflow run → Job details
```

### Debug Mode

Enable debug logging:
```bash
# Add repository secret
ACTIONS_STEP_DEBUG = true
ACTIONS_RUNNER_DEBUG = true
```

### Re-run Failed Jobs

```bash
# Via UI: Actions → Failed run → Re-run failed jobs

# Via CLI
gh run rerun <run-id> --failed
```

## 📚 Best Practices

1. **Always test in development first**
   - Never deploy directly to production
   - Use staging for integration testing

2. **Monitor metrics after deployment**
   - Check error rates
   - Monitor response times
   - Verify business metrics

3. **Keep workflows fast**
   - Use caching for dependencies
   - Parallelize independent jobs
   - Optimize Docker builds

4. **Security**
   - Never commit secrets to repository
   - Use environment secrets when possible
   - Rotate credentials regularly

5. **Documentation**
   - Document all manual steps
   - Keep runbooks updated
   - Record deployment decisions

## 🔗 Related Documentation

- [CI/CD Setup Guide](../../docs/CI-CD-SETUP.md) - Complete setup instructions
- [GitHub Actions Docs](https://docs.github.com/en/actions)
- [Deployment Strategies](https://martinfowler.com/bliki/BlueGreenDeployment.html)

## 📞 Support

For issues or questions:
- Check workflow logs in Actions tab
- Review [CI-CD-SETUP.md](../../docs/CI-CD-SETUP.md)
- Create an issue in the repository
- Contact DevOps team

---

**Last Updated:** 2025-11-13
