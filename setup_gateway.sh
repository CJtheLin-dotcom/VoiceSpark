#!/usr/bin/env bash
set -e

PROJECT_ID="cjlinn-471522"
REGION="europe-west1"
SERVICE_NAME="voice-spark-pwa"
SA_NAME="voice-spark-gateway-sa"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
API_ID="voice-spark-api"
CONFIG_ID="voice-spark-config-$(date +%s)"
GATEWAY_ID="voice-spark-gateway"
SPEC_FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/openapi.yaml"

echo "=================================================="
echo "🚀 开始部署 VoiceSpark · 灵感闪念与语音胶囊"
echo "项目 ID: ${PROJECT_ID}"
echo "部署区域: ${REGION}"
echo "=================================================="

# 1. 设置当前默认项目
gcloud config set project "${PROJECT_ID}"

# 2. 部署 Cloud Run 私有后端 (配置常驻、无 CPU 节流、单实例)
echo "📦 [1/6] 部署 Cloud Run 私有容器服务 (${SERVICE_NAME})..."
gcloud run deploy "${SERVICE_NAME}" \
  --source . \
  --region "${REGION}" \
  --project="${PROJECT_ID}" \
  --no-allow-unauthenticated \
  --no-cpu-throttling \
  --min-instances=1 \
  --max-instances=1

CLOUD_RUN_URL=$(gcloud run services describe "${SERVICE_NAME}" \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --format="value(status.url)")
echo "✅ Cloud Run 后端地址: ${CLOUD_RUN_URL}"

# 同步更新 openapi.yaml 里的后端真实地址
python3 -c "import sys, re; p, u = sys.argv[1], sys.argv[2]; c = open(p).read(); open(p, 'w').write(re.sub(r'address:.*', f'address: {u}', c))" "${SPEC_FILE}" "${CLOUD_RUN_URL}"

# 3. 启用所需 API
echo "🔧 [2/6] 启用 API Gateway 相关服务..."
gcloud services enable apigateway.googleapis.com \
  servicemanagement.googleapis.com \
  servicecontrol.googleapis.com \
  --project="${PROJECT_ID}"

# 4. 创建专用 Service Account
echo "🔑 [3/6] 配置网关服务账号 (${SA_NAME})..."
if ! gcloud iam service-accounts describe "${SA_EMAIL}" --project="${PROJECT_ID}" &>/dev/null; then
  gcloud iam service-accounts create "${SA_NAME}" \
    --display-name="VoiceSpark Gateway SA" \
    --description="Service account for API Gateway to invoke backend Cloud Run" \
    --project="${PROJECT_ID}"
  echo "✅ 服务账号创建成功，等待 IAM 权限同步..."
  sleep 10
else
  echo "ℹ️ 服务账号已存在，跳过创建"
fi

# 5. 赋予服务账号 Cloud Run 调用权限
echo "🛡️ [4/6] 赋予服务账号 Cloud Run 调用权限..."
gcloud run services add-iam-policy-binding "${SERVICE_NAME}" \
  --region="${REGION}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/run.invoker" \
  --project="${PROJECT_ID}"

# 6. 创建 API 接口与配置
echo "⚙️ [5/6] 上传 API Gateway OpenAPI 配置..."
if ! gcloud api-gateway apis describe "${API_ID}" --project="${PROJECT_ID}" &>/dev/null; then
  gcloud api-gateway apis create "${API_ID}" \
    --display-name="VoiceSpark Public API" \
    --project="${PROJECT_ID}"
fi

gcloud api-gateway api-configs create "${CONFIG_ID}" \
  --api="${API_ID}" \
  --openapi-spec="${SPEC_FILE}" \
  --backend-auth-service-account="${SA_EMAIL}" \
  --project="${PROJECT_ID}"

# 7. 创建或更新 Gateway 实例
echo "🌐 [6/6] 部署公网 API Gateway (约需 2~3 分钟)..."
if ! gcloud api-gateway gateways describe "${GATEWAY_ID}" --location="${REGION}" --project="${PROJECT_ID}" &>/dev/null; then
  gcloud api-gateway gateways create "${GATEWAY_ID}" \
    --api="${API_ID}" \
    --api-config="${CONFIG_ID}" \
    --location="${REGION}" \
    --project="${PROJECT_ID}"
else
  gcloud api-gateway gateways update "${GATEWAY_ID}" \
    --api="${API_ID}" \
    --api-config="${CONFIG_ID}" \
    --location="${REGION}" \
    --project="${PROJECT_ID}"
fi

# 8. 获取并输出公网 HTTPS 地址
GATEWAY_URL=$(gcloud api-gateway gateways describe "${GATEWAY_ID}" \
  --location="${REGION}" \
  --project="${PROJECT_ID}" \
  --format="value(defaultHostname)")

echo ""
echo "=================================================="
echo "🎉 部署大功告成！"
echo "🌐 你的永久专属 HTTPS 访问链接："
echo "👉 https://${GATEWAY_URL}"
echo "=================================================="
