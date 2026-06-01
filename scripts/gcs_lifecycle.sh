#!/usr/bin/env bash
# Configure GCS lifecycle rules for ShiftReady buckets.
# Run once: bash scripts/gcs_lifecycle.sh
# Requires: gcloud authed + GCP_UPLOAD_BUCKET set (or pass as arg)

set -euo pipefail

BUCKET="${1:-$GCP_UPLOAD_BUCKET}"
if [[ -z "$BUCKET" ]]; then
  echo "Usage: $0 <bucket-name>  OR  export GCP_UPLOAD_BUCKET=<name>"
  exit 1
fi

echo "Applying lifecycle rules to gs://$BUCKET ..."

# Write lifecycle JSON to temp file
LIFECYCLE_FILE=$(mktemp /tmp/gcs_lifecycle_XXXX.json)
cat > "$LIFECYCLE_FILE" <<'EOF'
{
  "lifecycle": {
    "rule": [
      {
        "action": { "type": "Delete" },
        "condition": {
          "age": 7,
          "matchesPrefix": ["captures/"]
        }
      },
      {
        "action": { "type": "SetStorageClass", "storageClass": "NEARLINE" },
        "condition": {
          "age": 90,
          "matchesStorageClass": ["STANDARD"]
        }
      },
      {
        "action": { "type": "SetStorageClass", "storageClass": "COLDLINE" },
        "condition": {
          "age": 180,
          "matchesStorageClass": ["NEARLINE"]
        }
      },
      {
        "action": { "type": "Delete" },
        "condition": {
          "age": 365,
          "matchesStorageClass": ["COLDLINE"]
        }
      }
    ]
  }
}
EOF

gcloud storage buckets update "gs://$BUCKET" --lifecycle-file="$LIFECYCLE_FILE"
rm -f "$LIFECYCLE_FILE"
echo "Done. Lifecycle rules applied to gs://$BUCKET"
echo ""
echo "Next: configure Firestore TTL on notifications subcollection."
echo "  gcloud firestore fields ttls update expireAt \\"
echo "    --collection-group=notifications \\"
echo "    --project=\$GCP_PROJECT_ID \\"
echo "    --enable-ttl"
