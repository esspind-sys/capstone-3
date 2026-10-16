
set -euo pipefail

FUNCTION=multi-agent-orchestrator
BUCKET=lambda-deploy-886021210116-espind
KEY=orchestrator_function.zip
ENV_FILE=/tmp/lambda-env-update.json
trap 'rm -f "$ENV_FILE"' EXIT   # env file contains the DB password: always deleted

echo "=== 1. Build ==="
./build_lambda.sh

echo "=== 2. Upload and update code ==="
aws s3 cp lambda.zip "s3://${BUCKET}/${KEY}"
aws lambda update-function-code --function-name "$FUNCTION" \
  --s3-bucket "$BUCKET" --s3-key "$KEY" --query "{State:LastUpdateStatus}" --output table
aws lambda wait function-updated-v2 --function-name "$FUNCTION"

echo "=== 3. Add CONFIRMATION_SECRET, keeping existing variables ==="
aws lambda get-function-configuration --function-name "$FUNCTION" \
  --query Environment --output json > "$ENV_FILE"
chmod 600 "$ENV_FILE"
.venv/bin/python - <<'PY'
import json, secrets
path = "/tmp/lambda-env-update.json"
env = json.load(open(path))
if "CONFIRMATION_SECRET" not in env["Variables"]:   # keep the same secret on later redeploys
    env["Variables"]["CONFIRMATION_SECRET"] = secrets.token_hex(32)
json.dump(env, open(path, "w"))
print("variable names:", sorted(env["Variables"]))
PY
aws lambda update-function-configuration --function-name "$FUNCTION" \
  --environment "file://${ENV_FILE}" --query "{State:LastUpdateStatus}" --output table
aws lambda wait function-updated-v2 --function-name "$FUNCTION"
echo "DEPLOYED"