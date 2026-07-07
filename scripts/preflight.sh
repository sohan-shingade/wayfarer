#!/usr/bin/env bash
# Confirm the `claude` CLI will run on your subscription, not API billing.
set -euo pipefail

if [[ -n "${ANTHROPIC_API_KEY:-}" ]]; then
  echo "WARNING: ANTHROPIC_API_KEY is set in this shell."
  echo "  wayfarer strips it from the agent subprocess, but you should unset it here too:"
  echo "    unset ANTHROPIC_API_KEY"
fi
if [[ -n "${ANTHROPIC_AUTH_TOKEN:-}" ]]; then
  echo "WARNING: ANTHROPIC_AUTH_TOKEN is set; unset it to use your subscription."
fi

echo
echo "Run this inside an interactive claude session to confirm auth route:"
echo "    /status        # 'Auth token' should read CLAUDE_CODE_OAUTH_TOKEN"
echo
echo "Then do ONE smoke run and watch total_cost_usd:"
claude -p "reply with the single word: ok" --output-format json --model sonnet \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('result=',d.get('result')); print('total_cost_usd=',d.get('total_cost_usd'),' (MUST be 0 or null for subscription)')"
