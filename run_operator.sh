#!/bin/bash
# WVOID-FM Operator - Launch Claude Code for maintenance
# Run via cron every 2 hours: 0 */2 * * * /path/to/run_operator.sh

cd /Volumes/K3/agent-working-space/projects/active/2025-12-29-radio-station

# Read the operator prompt
PROMPT=$(cat mac/operator_prompt.md)

# Launch Claude Code with the prompt
claude -p "$PROMPT" --allowedTools "Bash,Read,Write,Edit,Glob,Grep"
