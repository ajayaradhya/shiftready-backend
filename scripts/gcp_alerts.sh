#!/usr/bin/env bash
# Set up GCP budget alerts + Cloud Monitoring uptime checks + alert policies.
# Run once after deploy. Requires gcloud authed as project owner.
# Usage: bash scripts/gcp_alerts.sh <project-id> <notification-email>

set -euo pipefail

PROJECT_ID="${1:-$GCP_PROJECT_ID}"
NOTIFY_EMAIL="${2:-}"
REGION="australia-southeast1"
SERVICE_URL="${3:-}"  # e.g. https://myrio-api-xxx-ts.a.run.app

if [[ -z "$PROJECT_ID" ]]; then
  echo "Usage: $0 <project-id> <notification-email> [service-url]"
  exit 1
fi

echo "=== GCP Alerts setup for project: $PROJECT_ID ==="

# ── 1. Budget alert ($100/mo at 50/80/100%) ──────────────────────────────────
echo "Creating budget alert..."
gcloud billing budgets create \
  --billing-account="$(gcloud billing projects describe "$PROJECT_ID" --format='value(billingAccountName)' | sed 's|billingAccounts/||')" \
  --display-name="Myrio Monthly Budget" \
  --budget-amount=100AUD \
  --threshold-rule=percent=0.50 \
  --threshold-rule=percent=0.80 \
  --threshold-rule=percent=1.00 \
  --project="$PROJECT_ID" \
  2>/dev/null || echo "Budget may already exist — skipping."

# ── 2. Notification channel (email) ──────────────────────────────────────────
if [[ -n "$NOTIFY_EMAIL" ]]; then
  echo "Creating email notification channel for $NOTIFY_EMAIL ..."
  CHANNEL_ID=$(gcloud monitoring channels create \
    --display-name="Myrio Alerts" \
    --type=email \
    --channel-labels="email_address=$NOTIFY_EMAIL" \
    --project="$PROJECT_ID" \
    --format='value(name)' 2>/dev/null | sed 's|.*/||') || true
  echo "Channel ID: $CHANNEL_ID"
fi

# ── 3. Uptime check ───────────────────────────────────────────────────────────
if [[ -n "$SERVICE_URL" ]]; then
  echo "Creating uptime check for $SERVICE_URL ..."
  # Extract hostname
  HOST=$(echo "$SERVICE_URL" | sed 's|https://||' | sed 's|/.*||')
  gcloud monitoring uptime create "myrio-api-uptime" \
    --resource-type=uptime-url \
    --resource-labels="host=$HOST,project_id=$PROJECT_ID" \
    --protocol=HTTPS \
    --path=/health \
    --period=60 \
    --project="$PROJECT_ID" \
    2>/dev/null || echo "Uptime check may already exist — skipping."
fi

# ── 4. Alert policy: 5xx error rate > 1% ─────────────────────────────────────
echo "Creating 5xx alert policy..."
cat > /tmp/sr_5xx_policy.json <<POLICY
{
  "displayName": "Myrio 5xx Error Rate > 1%",
  "conditions": [{
    "displayName": "5xx rate",
    "conditionThreshold": {
      "filter": "resource.type=\"cloud_run_revision\" AND resource.label.service_name=\"myrio-api\" AND metric.type=\"run.googleapis.com/request_count\" AND metric.label.response_code_class=\"5xx\"",
      "aggregations": [{
        "alignmentPeriod": "300s",
        "perSeriesAligner": "ALIGN_RATE",
        "crossSeriesReducer": "REDUCE_SUM"
      }],
      "comparison": "COMPARISON_GT",
      "thresholdValue": 0.01,
      "duration": "60s"
    }
  }],
  "alertStrategy": { "notificationRateLimit": { "period": "3600s" } },
  "combiner": "OR"
}
POLICY

gcloud monitoring policies create \
  --policy-from-file=/tmp/sr_5xx_policy.json \
  --project="$PROJECT_ID" \
  2>/dev/null || echo "5xx policy may already exist — skipping."

rm -f /tmp/sr_5xx_policy.json

echo ""
echo "=== Done ==="
echo "Remaining manual steps:"
echo "  1. Create Sentry project at sentry.io → add DSN to Cloud Build trigger as _SENTRY_DSN"
echo "  2. Verify budget alert in GCP Console → Billing → Budgets"
echo "  3. Verify uptime check in GCP Console → Monitoring → Uptime checks"
