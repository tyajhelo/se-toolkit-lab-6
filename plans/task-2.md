# Task 2 Plan

## Tool schemas
I will define two function-calling tools:
- `read_file(path)`
- `list_files(path)`

Each tool will be registered as an OpenAI-compatible function-calling schema.

## Agentic loop
The loop will:
1. Send the question plus tool definitions to the LLM.
2. Execute tool calls when requested.
3. Append tool results back into the conversation.
4. Continue until the model returns a final answer or the tool-call limit is reached.

## Security
Both file tools will resolve paths relative to the repository root and reject path traversal attempts such as `../`.
The agent will not read or list files outside the project directory.

## Output
Task 2 output JSON will include:
- `answer`
- `source`
- `tool_calls`

## Testing
Regression tests will verify that:
- `read_file` is used for wiki lookup questions
- `list_files` is used for directory listing questions

Documentation Agent workflow update.
