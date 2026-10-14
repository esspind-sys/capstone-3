import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bedrock_client import invoke_claude

result = invoke_claude("Say hello in one sentence.", max_tokens=50)
print(result["text"])
print(f"input_tokens={result['input_tokens']} output_tokens={result['output_tokens']}")