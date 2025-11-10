#!/bin/bash
# Helm Chart Validation Script

set -e

CHART_DIR="$(dirname "$0")"
CHART_NAME="trading-bot"

echo "==================================="
echo "Helm Chart Validation Script"
echo "==================================="
echo ""

# Check if helm is installed
if ! command -v helm &> /dev/null; then
    echo "❌ Helm is not installed. Please install Helm 3.0+ first."
    echo "   Visit: https://helm.sh/docs/intro/install/"
    exit 1
fi

echo "✅ Helm version:"
helm version --short
echo ""

# Lint chart
echo "📋 Linting Helm chart..."
if helm lint "$CHART_DIR"; then
    echo "✅ Chart lint passed"
else
    echo "❌ Chart lint failed"
    exit 1
fi
echo ""

# Test template rendering for each environment
for ENV in dev staging prod; do
    echo "🔍 Testing template rendering for $ENV environment..."
    VALUES_FILE="$CHART_DIR/values-$ENV.yaml"

    if [ ! -f "$VALUES_FILE" ]; then
        echo "⚠️  Values file not found: $VALUES_FILE"
        continue
    fi

    if helm template "$CHART_NAME" "$CHART_DIR" -f "$VALUES_FILE" > /dev/null; then
        echo "✅ Template rendering successful for $ENV"
    else
        echo "❌ Template rendering failed for $ENV"
        exit 1
    fi
done
echo ""

# Dry-run installation
echo "🧪 Testing dry-run installation (dev environment)..."
if helm install "$CHART_NAME-test" "$CHART_DIR" \
    -f "$CHART_DIR/values-dev.yaml" \
    --dry-run --debug > /tmp/helm-dry-run.log 2>&1; then
    echo "✅ Dry-run installation successful"
else
    echo "❌ Dry-run installation failed"
    echo "Check /tmp/helm-dry-run.log for details"
    exit 1
fi
echo ""

# Check for required files
echo "📂 Checking required files..."
REQUIRED_FILES=(
    "Chart.yaml"
    "values.yaml"
    "values-dev.yaml"
    "values-staging.yaml"
    "values-prod.yaml"
    "templates/_helpers.tpl"
    "templates/deployment.yaml"
    "templates/service.yaml"
    "templates/configmap.yaml"
    "templates/secret.yaml"
    "templates/hpa.yaml"
    "templates/serviceaccount.yaml"
    "templates/role.yaml"
    "templates/rolebinding.yaml"
    "templates/pvc.yaml"
    "templates/NOTES.txt"
    ".helmignore"
    "README.md"
)

for FILE in "${REQUIRED_FILES[@]}"; do
    if [ -f "$CHART_DIR/$FILE" ]; then
        echo "  ✅ $FILE"
    else
        echo "  ❌ Missing: $FILE"
        exit 1
    fi
done
echo ""

# Summary
echo "==================================="
echo "✅ All validation checks passed!"
echo "==================================="
echo ""
echo "Next steps:"
echo "1. Review the chart configuration in values files"
echo "2. Configure secrets for your environment"
echo "3. Install the chart with:"
echo "   helm install $CHART_NAME $CHART_DIR -f values-dev.yaml -n trading-dev --create-namespace"
echo ""
