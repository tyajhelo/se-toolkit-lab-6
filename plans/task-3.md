# Task 3 Plan

## query_api tool
I will add a third tool:
- `query_api(method, path, body=None)`

It will call the backend API using:
- `LMS_API_KEY` for authentication
- `AGENT_API_BASE_URL` as the base URL, defaulting to `http://localhost:42002`

## Prompt update
The system prompt will instruct the LLM to:
- use `read_file` for wiki and source-code questions
- use `list_files` to discover files and modules
- use `query_api` for live system and data-dependent questions

## Benchmark strategy
I will run `uv run run_eval.py`, inspect failures, and refine:
- tool descriptions
- source-code reading behavior
- final answer precision
- handling of tool-call responses with null content

## Initial benchmark notes
Initial benchmark score: not run yet.
First failures: not run yet.
Iteration strategy: run benchmark, inspect failed questions, improve tool selection and file-reading coverage, rerun until all 10 local checks pass.
