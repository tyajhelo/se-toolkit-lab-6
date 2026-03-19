# Task 1 Plan

## LLM provider
I will use an OpenAI-compatible chat completions provider configured through environment variables:
- LLM_API_KEY
- LLM_API_BASE
- LLM_MODEL

Recommended model: qwen3-coder-plus.

## Agent structure
The CLI program `agent.py` will:
1. Read the user question from the first command-line argument.
2. Load environment variables from `.env.agent.secret` if present.
3. Send a chat completion request to the configured endpoint.
4. Extract the text answer from the model response.
5. Print a single JSON object to stdout with:
   - `answer`
   - `tool_calls` (empty list for Task 1)

## Output rules
- stdout contains only valid JSON
- debug output goes to stderr
- exit code 0 on success
- request timeout stays below 60 seconds

## Testing
A regression test will run `agent.py` as a subprocess, parse stdout as JSON, and verify that `answer` and `tool_calls` are present.

Implementation completed and verified on the VM.
