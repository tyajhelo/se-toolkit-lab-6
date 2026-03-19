#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent
MAX_TOOL_CALLS = 10
DEFAULT_API_BASE_URL = "http://localhost:42002"


def eprint(*args: Any, **kwargs: Any) -> None:
    print(*args, file=sys.stderr, **kwargs)


def load_env() -> None:
    load_dotenv(REPO_ROOT / ".env.agent.secret", override=False)
    load_dotenv(REPO_ROOT / ".env.docker.secret", override=False)
    load_dotenv(REPO_ROOT / ".env", override=False)


def required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def safe_resolve(user_path: str) -> Path:
    target = (REPO_ROOT / user_path).resolve()
    root = REPO_ROOT.resolve()
    if target != root and root not in target.parents:
        raise ValueError("Access denied: path escapes repository root")
    return target


def slugify_heading(text: str) -> str:
    chars = []
    prev_dash = False
    for ch in text.strip().lower():
        if ch.isalnum():
            chars.append(ch)
            prev_dash = False
        elif ch in " -_":
            if not prev_dash:
                chars.append("-")
                prev_dash = True
    return "".join(chars).strip("-")


def best_section_anchor(content: str, answer: str) -> str | None:
    answer_lower = answer.lower()
    for line in content.splitlines():
        if line.startswith("#"):
            heading = line.lstrip("#").strip()
            if heading and any(word in answer_lower for word in heading.lower().split()):
                return slugify_heading(heading)
    return None


def read_file(path: str) -> str:
    try:
        target = safe_resolve(path)
        if not target.exists():
            return f"ERROR: File does not exist: {path}"
        if not target.is_file():
            return f"ERROR: Not a file: {path}"
        return target.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return f"ERROR: {exc}"


def list_files(path: str) -> str:
    try:
        target = safe_resolve(path)
        if not target.exists():
            return f"ERROR: Path does not exist: {path}"
        if not target.is_dir():
            return f"ERROR: Not a directory: {path}"
        entries = sorted(p.name + ("/" if p.is_dir() else "") for p in target.iterdir())
        return "\n".join(entries)
    except Exception as exc:
        return f"ERROR: {exc}"


def query_api(method: str, path: str, body: str | None = None) -> str:
    try:
        base_url = os.getenv("AGENT_API_BASE_URL", DEFAULT_API_BASE_URL).rstrip("/")
        api_key = required_env("LMS_API_KEY")
        url = f"{base_url}/{path.lstrip('/')}"
        headers = {"X-API-Key": api_key}
        kwargs: dict[str, Any] = {
            "method": method.upper(),
            "url": url,
            "headers": headers,
            "timeout": 20,
        }
        if body is not None and body != "":
            headers["Content-Type"] = "application/json"
            kwargs["data"] = body
        response = requests.request(**kwargs)
        try:
            payload_body = response.json()
        except Exception:
            payload_body = response.text
        return json.dumps(
            {"status_code": response.status_code, "body": payload_body},
            ensure_ascii=False,
        )
    except Exception as exc:
        return json.dumps({"status_code": 0, "body": f"ERROR: {exc}"}, ensure_ascii=False)


TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Read a file from the repository. Use this for wiki questions, source-code questions, "
                "Docker config, backend code, debugging, and finding exact implementation details."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path from the repository root, for example wiki/git-workflow.md or backend/app/main.py",
                    }
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": (
                "List files and directories at a repository path. Use this to discover wiki files, backend modules, "
                "router modules, ETL pipeline code, and overall project structure."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative directory path from the repository root, for example wiki or backend",
                    }
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_api",
            "description": (
                "Call the running backend API for live system facts and data-dependent questions. "
                "Use this for item counts, auth behavior, analytics endpoints, and real runtime responses."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "method": {
                        "type": "string",
                        "description": "HTTP method such as GET, POST, PUT, DELETE",
                    },
                    "path": {
                        "type": "string",
                        "description": "API path such as /items/ or /analytics/completion-rate?lab=lab-99",
                    },
                    "body": {
                        "type": "string",
                        "description": "Optional JSON request body as a string",
                    },
                },
                "required": ["method", "path"],
                "additionalProperties": False,
            },
        },
    },
]


def call_tool(name: str, arguments: dict[str, Any]) -> str:
    if name == "read_file":
        return read_file(arguments["path"])
    if name == "list_files":
        return list_files(arguments["path"])
    if name == "query_api":
        return query_api(arguments["method"], arguments["path"], arguments.get("body"))
    return f"ERROR: Unknown tool: {name}"


def build_system_prompt() -> str:
    return (
        "You are a repository and system agent.\n"
        "Use tools whenever needed instead of guessing.\n"
        "Rules:\n"
        "1. For wiki or documentation questions, use list_files and read_file in wiki/.\n"
        "2. For source-code questions, inspect the real code with list_files and read_file.\n"
        "3. For live system facts and data-dependent questions, use query_api.\n"
        "4. For bug diagnosis, first query the API if relevant, then inspect the source code.\n"
        "5. Prefer concise, specific answers.\n"
        "6. Return final output as valid JSON only, with keys answer, source, tool_calls.\n"
        "7. source is required when the answer comes from a file and should be a file path with an anchor when possible.\n"
        "8. source may be omitted for pure runtime answers from query_api.\n"
        "9. tool_calls should be an array of objects containing tool, args, and result.\n"
        "10. Never invent file paths or sources.\n"
    )


def openai_chat(messages: list[dict[str, Any]]) -> dict[str, Any]:
    api_key = required_env("LLM_API_KEY")
    api_base = required_env("LLM_API_BASE").rstrip("/")
    model = required_env("LLM_MODEL")

    response = requests.post(
        f"{api_base}/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": messages,
            "tools": TOOLS,
            "tool_choice": "auto",
            "temperature": 0,
        },
        timeout=50,
    )
    response.raise_for_status()
    return response.json()


def extract_final_json(text: str) -> dict[str, Any] | None:
    text = text.strip()
    if not text:
        return None
    try:
        obj = json.loads(text)
        if isinstance(obj, dict) and "answer" in obj:
            return obj
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        snippet = text[start : end + 1]
        try:
            obj = json.loads(snippet)
            if isinstance(obj, dict) and "answer" in obj:
                return obj
        except json.JSONDecodeError:
            return None
    return None


def fallback_result(answer: str, source: str | None, tool_calls: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "answer": answer.strip(),
        "tool_calls": tool_calls,
    }
    if source:
        result["source"] = source
    return result


def main() -> int:
    load_env()

    if len(sys.argv) < 2:
        print(json.dumps({"answer": "No question provided.", "tool_calls": []}, ensure_ascii=False))
        return 0

    question = sys.argv[1]
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": build_system_prompt()},
        {"role": "user", "content": question},
    ]

    tool_history: list[dict[str, Any]] = []
    last_answer = ""
    last_source: str | None = None

    for _ in range(MAX_TOOL_CALLS + 1):
        response = openai_chat(messages)
        msg = response["choices"][0]["message"]
        assistant_content = msg.get("content") or ""
        tool_calls = msg.get("tool_calls") or []

        if tool_calls:
            messages.append(
                {
                    "role": "assistant",
                    "content": assistant_content,
                    "tool_calls": tool_calls,
                }
            )
            for tool_call in tool_calls:
                function = tool_call["function"]
                name = function["name"]
                args = json.loads(function["arguments"])
                result = call_tool(name, args)

                tool_history.append(
                    {
                        "tool": name,
                        "args": args,
                        "result": result,
                    }
                )

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
                        "name": name,
                        "content": result,
                    }
                )
            if len(tool_history) >= MAX_TOOL_CALLS:
                break
            continue

        parsed = extract_final_json(assistant_content)
        if parsed is not None:
            parsed["tool_calls"] = tool_history
            if "source" in parsed and not parsed["source"]:
                parsed.pop("source", None)
            print(json.dumps(parsed, ensure_ascii=False))
            return 0

        if assistant_content.strip():
            last_answer = assistant_content.strip()

        for entry in reversed(tool_history):
            if entry["tool"] == "read_file":
                content = entry["result"]
                path = entry["args"]["path"]
                if not content.startswith("ERROR:"):
                    anchor = best_section_anchor(content, last_answer or question)
                    last_source = f"{path}#{anchor}" if anchor else path
                    break

    result = fallback_result(
        answer=last_answer or "I could not complete the request within the tool-call limit.",
        source=last_source,
        tool_calls=tool_history,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        eprint(f"agent.py failed: {exc}")
        print(
            json.dumps(
                {
                    "answer": f"Execution failed: {exc}",
                    "tool_calls": [],
                },
                ensure_ascii=False,
            )
        )
        raise SystemExit(1)
# update Thu Mar 19 10:11:26 PM MSK 2026
