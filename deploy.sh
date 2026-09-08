#!/usr/bin/env bash
set -e

PROJECT_ID="cjlinn-471522"
REGION="europe-west1"
SERVICE_NAME="voice-spark-pwa"
GCS_BUCKET="voice-spark-data-cjlinn-471522"

# Ensure gcloud is available in PATH
if ! command -v gcloud &>/dev/null; then
  if [ -d "$HOME/Downloads/google-cloud-sdk/bin" ]; then
    export PATH="$HOME/Downloads/google-cloud-sdk/bin:$PATH"
  elif [ -d "$HOME/google-cloud-sdk/bin" ]; then
    export PATH="$HOME/google-cloud-sdk/bin:$PATH"
  fi
fi

echo "=================================================="
echo "🚀 开始部署 VoiceSpark 到 Google Cloud Run"
echo "项目 ID: ${PROJECT_ID}"
echo "部署区域: ${REGION}"
echo "服务名称: ${SERVICE_NAME}"
echo "存储桶: gs://${GCS_BUCKET}"
echo "关键规则: GCS云端持久化, min-instances=1, max-instances=1, no-cpu-throttling"
echo "=================================================="

# Ensure GCS bucket exists
if ! gcloud storage buckets describe "gs://${GCS_BUCKET}" --project="${PROJECT_ID}" &>/dev/null; then
  echo "📦 创建持久化存储桶: gs://${GCS_BUCKET}..."
  gcloud storage buckets create "gs://${GCS_BUCKET}" \
    --location="${REGION}" \
    --project="${PROJECT_ID}" \
    --uniform-bucket-level-access
fi

# Deploy to Cloud Run with required persistence and background execution settings
gcloud run deploy "${SERVICE_NAME}" \
  --source . \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --memory=1Gi \
  --timeout=600 \
  --min-instances=1 \
  --max-instances=1 \
  --no-cpu-throttling \
  --no-allow-unauthenticated \
  --set-env-vars="GCS_BUCKET=${GCS_BUCKET},STORAGE_SYNC_ENABLED=true,GCP_PROJECT=${PROJECT_ID}" \
  --quiet

echo ""
echo "✅ 部署完成！已确保 min-instances=1, max-instances=1, no-cpu-throttling 持续生效。"
SERVICE_URL=$(gcloud run services describe "${SERVICE_NAME}" --region="${REGION}" --project="${PROJECT_ID}" --format="value(status.url)")
echo "后端地址: ${SERVICE_URL}"
echo "公网网关: https://voice-spark-gateway-5lquvkm5.ew.gateway.dev"
echo "=================================================="
