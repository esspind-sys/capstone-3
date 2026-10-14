export NAME=espind
export AWS_DEFAULT_REGION=us-east-1
export ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export MY_ARN=$(aws sts get-caller-identity --query Arn --output text)
