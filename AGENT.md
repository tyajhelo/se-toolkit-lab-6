# AGENT.md

This repository contains a CLI agent implemented in `agent.py`. It evolved across three tasks.

## Overview

The agent is a Python command-line program that accepts a natural-language question as the first CLI argument and prints exactly one JSON object to stdout. It uses an OpenAI-compatible Chat Completions API configured entirely through environment variables, which makes it compatible with the local lab setup and with the autochecker environment.

The required LLM settings are:
- `LLM_API_KEY`
- `LLM_API_BASE`
- `LLM_MODEL`

For runtime API access, the agent also reads:
- `LMS_API_KEY`
- `AGENT_API_BASE_URL` (defaults to `http://localhost:42002`)

The agent loads `.env.agent.secret`, `.env.docker.secret`, and `.env` when present, but all configuration still comes from environment variables, so the autochecker can override values safely.

## Tools

The agent supports three tools.

### `read_file(path)`

Reads a file from the repository and returns its contents. It is used for:
- wiki/documentation lookups
- source-code inspection
- Docker and deployment configuration inspection
- debugging implementation-level problems

### `list_files(path)`

Lists files and directories under a repository path. It is used to discover:
- wiki pages
- backend modules
- router modules
- ETL pipeline files
- project structure before choosing what to read

### `query_api(method, path, body=None)`

Calls the running backend API and returns a JSON string with `status_code` and `body`. It authenticates with `LMS_API_KEY` and uses `AGENT_API_BASE_URL` or the default local backend URL. This is used for:
- live item counts
- auth behavior
- analytics endpoints
- runtime error discovery before reading the code

## Agentic loop

The agent sends the user question, system prompt, and tool schemas to the LLM. If the model returns tool calls, the program executes them, appends results as tool-role messages, and continues. If the model returns a final text response, the program expects that response to be valid JSON and extracts `answer`, optional `source`, and `tool_calls`. The loop stops after a maximum of 10 tool calls.

The system prompt explicitly teaches the model when to use wiki tools, when to inspect real source code, and when to call the live backend. For bug-diagnosis questions, the intended pattern is: query the API first, then inspect the relevant implementation.

## Security

`read_file` and `list_files` resolve paths relative to the repository root and reject path traversal attempts such as `../`. This prevents the agent from reading files outside the project.

## Running

Example:

```bash
uv run agent.py "What does the project wiki say about connecting to your VM via SSH?"
The output is a single JSON object on stdout. Debugging output should go to stderr.

Lessons from the benchmark

The benchmark requires genuine tool use. Simple prompting is not enough. The tool descriptions must be specific so the model chooses the correct tool class:

read_file for wiki and code

list_files for structure discovery

query_api for live system facts and data

It is also important to handle tool-call responses where content is null rather than missing, because many OpenAI-compatible providers return tool calls that way. Another important detail is that the backend URL and credentials must never be hardcoded; the autochecker injects its own values.

Final eval score: not recorded yet in this document. Update this section after uv run run_eval.py passes locally.

## Update for PR validation Thu Mar 19 10:11:26 PM MSK 2026

PR diff refresh Thu Mar 19 10:15:42 PM MSK 2026
Task 1 PR refresh.
