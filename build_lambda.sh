#!/usr/bin/env bash
set -euo pipefail

rm -rf build lambda.zip && mkdir -p build

pip install -q --target build \
  --platform manylinux2014_x86_64 \
  --platform manylinux_2_27_x86_64 \
  --platform manylinux_2_28_x86_64 \
  --implementation cp --python-version 3.12 --abi cp312 \
  --only-binary=:all: -r /tmp/req-lambda.txt

find build -type d \( -name "__pycache__" -o -name "tests" \) -prune -exec rm -rf {} +
rm -rf build/hf_xet build/hf_xet-*.dist-info

# model.onnx is NOT copied: it lives in S3 and is downloaded to /tmp at cold start
cp -r agents lambda_handler.py orchestrator.py tool_registry.py bedrock_client.py \
      tokenomics_logger.py onnx_embed.py confirmation.py tokenizer.json build/
[ ! -e build/model.onnx ] || { echo "model.onnx leaked into build/"; exit 1; }

.venv/bin/python -S -c "import sys; sys.path.insert(0, 'build'); \
import numpy, onnxruntime, tokenizers, huggingface_hub, langgraph, psycopg2, opensearchpy, requests_aws4auth, dotenv; \
print('IMPORTS OK, onnxruntime', onnxruntime.__version__)"

SIZE_MB=$(du -sm build | cut -f1)
echo "UNZIPPED TOTAL (MB): $SIZE_MB (limit 250)"
du -sm build/* | sort -rn | head -10
[ "$SIZE_MB" -le 250 ] || { echo "OVER LIMIT, not zipping"; exit 1; }

find build -type d -name "__pycache__" -prune -exec rm -rf {} +
(cd build && zip -qr ../lambda.zip .)
ls -lh lambda.zip
if unzip -l lambda.zip | grep -qE '(^|/)\.env$'; then echo ".env found in zip, remove it"; exit 1; fi
echo "ZIP READY"