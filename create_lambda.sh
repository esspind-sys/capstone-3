set -euo pipefail

NAME=espind
FUNCTION=multi-agent-orchestrator
ROLE_ARN=$(aws iam get-role --role-name "orchestrator-lambda-role-${NAME}" --query Role.Arn --output text)
BUCKET="lambda-deploy-886021210116-${NAME}"
ENV_FILE=/tmp/lambda-env.json
trap 'rm -f "$ENV_FILE"' EXIT   # env file (contains password) is always deleted

echo "=== 1. Handler entry point ==="
grep -nE '^def handler\(' lambda_handler.py || { echo "No 'def handler(' in lambda_handler.py"; exit 1; }

echo "=== 2. Real AWS endpoints ==="
export RDS_REAL=$(aws rds describe-db-instances --db-instance-identifier "orchestrator-db-${NAME}" \
  --query "DBInstances[0].Endpoint.Address" --output text)
export OS_REAL=$(aws opensearch describe-domain --domain-name "orchestrator-search-${NAME}" \
  --query "DomainStatus.Endpoint" --output text)
export BUCKET

echo "=== 3. Build env JSON from .env (no values printed) ==="
.venv/bin/python - <<'PY'
import json, os
from dotenv import dotenv_values

env = dotenv_values(".env")
keep = ["RDS_HOST", "RDS_PORT", "RDS_DATABASE", "RDS_USER", "RDS_PASSWORD", "OPENSEARCH_ENDPOINT"]
missing = [k for k in keep if not env.get(k)]
if missing:
    raise SystemExit(f"Missing/empty in .env: {missing}")

def host(v):
    return v.replace("https://", "").replace("http://", "").strip().rstrip("/")

checks = {"RDS_HOST": (env["RDS_HOST"], os.environ["RDS_REAL"]),
          "OPENSEARCH_ENDPOINT": (env["OPENSEARCH_ENDPOINT"], os.environ["OS_REAL"])}
for key, (mine, real) in checks.items():
    ok = host(mine) == host(real)
    print(f"{key}: {'MATCHES real AWS endpoint' if ok else 'MISMATCH'}")
    if not ok:
        raise SystemExit(f"{key} in .env does not match AWS ({real}). Fix .env first.")

variables = {k: env[k] for k in keep}
variables["MODEL_S3_BUCKET"] = os.environ["BUCKET"]
variables["MODEL_S3_KEY"] = "models/model.onnx"
with open("/tmp/lambda-env.json", "w") as f:
    json.dump({"Variables": variables}, f)
os.chmod("/tmp/lambda-env.json", 0o600)
print("ENV JSON OK, keys:", sorted(variables))
PY

echo "=== 4. Create function ==="
aws lambda create-function \
  --function-name "$FUNCTION" \
  --runtime python3.12 \
  --architectures x86_64 \
  --role "$ROLE_ARN" \
  --handler lambda_handler.handler \
  --code "S3Bucket=${BUCKET},S3Key=orchestrator_function.zip" \
  --timeout 120 \
  --memory-size 512 \
  --environment "file://${ENV_FILE}" \
  --query "{FunctionArn:FunctionArn,State:State}" --output table

echo "=== 5. Wait until Active ==="
aws lambda wait function-active-v2 --function-name "$FUNCTION" && echo "ACTIVE"

echo "=== 6. Final config (env NAMES only) ==="
aws lambda get-function-configuration --function-name "$FUNCTION" \
  --query "{State:State,LastUpdateStatus:LastUpdateStatus,Runtime:Runtime,Arch:Architectures[0],Handler:Handler,MemoryMB:MemorySize,TimeoutS:Timeout,TmpMB:EphemeralStorage.Size,CodeSizeBytes:CodeSize,EnvKeys:keys(Environment.Variables)}" \
  --output json
  