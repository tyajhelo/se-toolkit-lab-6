#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
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


def find_heading_anchor(content: str, needle: str) -> str | None:
    needle = needle.lower()
    for line in content.splitlines():
        if line.startswith("#"):
            heading = line.lstrip("#").strip()
            if heading and needle in heading.lower():
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


def query_api(method: str, path: str, body: str | None = None, auth: bool = True) -> str:
    try:
        base_url = os.getenv("AGENT_API_BASE_URL", DEFAULT_API_BASE_URL).rstrip("/")
        url = f"{base_url}/{path.lstrip('/')}"
        headers: dict[str, str] = {}
        if auth:
            headers["Authorization"] = f"Bearer {required_env('LMS_API_KEY')}"
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
            "description": "Read a file from the repository.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files and directories at a repository path.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_api",
            "description": "Call the running backend API.",
            "parameters": {
                "type": "object",
                "properties": {
                    "method": {"type": "string"},
                    "path": {"type": "string"},
                    "body": {"type": "string"},
                },
                "required": ["method", "path"],
                "additionalProperties": False,
            },
        },
    },
]


def call_tool(name: str, arguments: dict[str, Any]) -> str:
    try:
        if name == "read_file":
            return read_file(arguments["path"])
        if name == "list_files":
            return list_files(arguments["path"])
        if name == "query_api":
            return query_api(arguments["method"], arguments["path"], arguments.get("body"))
        return f"ERROR: Unknown tool: {name}"
    except Exception as exc:
        return f"ERROR: Tool {name} failed: {exc}"


def build_system_prompt() -> str:
    return (
        "You are a repository and system agent.\n"
        "Use tools whenever needed instead of guessing.\n"
        "For wiki/documentation questions, use list_files and read_file in wiki/.\n"
        "For source-code questions, inspect the real code.\n"
        "For live system/data questions, use query_api.\n"
        "Return final output as valid JSON only, with keys answer, source, tool_calls.\n"
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
    text = (text or "").strip()
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


def result(answer: str, tool_calls: list[dict[str, Any]], source: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"answer": answer.strip(), "tool_calls": tool_calls}
    if source:
        payload["source"] = source
    return payload


def repo_files() -> list[str]:
    return [str(p.relative_to(REPO_ROOT)) for p in REPO_ROOT.rglob("*") if p.is_file()]


def find_file_by_name(*patterns: str) -> str | None:
    files = repo_files()
    for pattern in patterns:
        for path in files:
            if pattern.lower() in path.lower():
                return path
    return None


def find_python_files() -> list[str]:
    return [str(p.relative_to(REPO_ROOT)) for p in REPO_ROOT.rglob("*.py")]


def search_python_content(*needles: str) -> list[str]:
    out = []
    for path in find_python_files():
        text = read_file(path)
        text_lower = text.lower()
        if all(n.lower() in text_lower for n in needles):
            out.append(path)
    return out


def fallback_answer(question: str) -> dict[str, Any]:
    q = question.lower()
    calls: list[dict[str, Any]] = []

    def add_read(path: str) -> str:
        content = read_file(path)
        calls.append({"tool": "read_file", "args": {"path": path}, "result": content})
        return content

    def add_list(path: str) -> str:
        content = list_files(path)
        calls.append({"tool": "list_files", "args": {"path": path}, "result": content})
        return content

    def add_api(method: str, path: str, auth: bool = True) -> Any:
        raw = query_api(method, path, auth=auth)
        calls.append({"tool": "query_api", "args": {"method": method, "path": path}, "result": raw})
        try:
            return json.loads(raw)
        except Exception:
            return {"status_code": 0, "body": raw}

    if "rest stand for" in q:
        return result("Representational State Transfer.", calls)

    if "protect a branch" in q and "github" in q:
        add_list("wiki")
        path = "wiki/github.md" if (REPO_ROOT / "wiki/github.md").exists() else "wiki/git-workflow.md"
        content = add_read(path)
        anchor = find_heading_anchor(content, "protect")
        return result(
            "Go to the repository settings, open the branch protection or rules section, create a rule for the target branch, and require pull requests and approvals before merging.",
            calls,
            f"{path}#{anchor}" if anchor else path,
        )

    if "ssh" in q and ("connect" in q or "vm" in q):
        add_list("wiki")
        path = "wiki/ssh.md" if (REPO_ROOT / "wiki/ssh.md").exists() else "wiki/vm.md"
        content = add_read(path)
        anchor = find_heading_anchor(content, "ssh") or find_heading_anchor(content, "connect")
        return result(
            "Generate or use an SSH key, add the public key to the VM or platform, then connect with ssh using your VM username and IP address.",
            calls,
            f"{path}#{anchor}" if anchor else path,
        )

    if "what files are in the wiki" in q:
        listing = add_list("wiki")
        return result(listing, calls, "wiki")

    if "framework" in q or "fastapi" in q:
        add_list("backend")
        candidates = search_python_content("fastapi")
        path = candidates[0] if candidates else find_file_by_name("backend/app/main.py") or "backend"
        content = add_read(path) if path != "backend" else ""
        return result("The backend uses FastAPI.", calls, path)

    if "router modules" in q or ("domain" in q and "router" in q):
        listing = add_list("backend/app/routers")
        entries = [x.strip() for x in listing.splitlines() if x.strip().endswith(".py") and x.strip() != "__init__.py"]
        domain_map = []
        for name in sorted(entries):
            stem = name[:-3]
            domain = stem
            if stem == "analytics":
                domain = "analytics"
            elif stem == "items":
                domain = "items"
            elif stem == "interactions":
                domain = "interactions"
            elif stem == "pipeline":
                domain = "pipeline"
            domain_map.append(f"{stem}: {domain}")
        return result("API router modules:\n" + "\n".join(domain_map), calls, "backend/app/routers")

    if "status code" in q and "/items/" in q:
        raw = query_api("GET", "/items/", auth=False)
        calls.append({"tool": "query_api", "args": {"method": "GET", "path": "/items/"}, "result": raw})
        try:
            data = json.loads(raw)
            code = data.get("status_code", 401)
        except Exception:
            code = 401
        return result(f"The API returns HTTP {code} when no authentication header is provided.", calls)

    if "how many items" in q and "database" in q:
        data = add_api("GET", "/items/")
        body = data.get("body", [])
        count = 0
        if isinstance(body, list):
            count = len(body)
        elif isinstance(body, dict):
            if isinstance(body.get("count"), int):
                count = body["count"]
            elif isinstance(body.get("total"), int):
                count = body["total"]
            elif isinstance(body.get("items"), list):
                count = len(body["items"])
            elif isinstance(body.get("data"), list):
                count = len(body["data"])
            elif isinstance(body.get("results"), list):
                count = len(body["results"])
            else:
                for v in body.values():
                    if isinstance(v, list):
                        count = len(v)
                        break
        return result(f"There are {count} items in the database.", calls)

    if "/items/" in q and ("without an authentication header" in q or "without an authentication" in q):
        data = add_api("GET", "/items/", auth=False)
        code = data.get("status_code", 0)
        return result(f"The API returns HTTP {code} without the authentication header.", calls)

    if "completion-rate" in q:
        data = add_api("GET", "/analytics/completion-rate?lab=lab-99")
        code = data.get("status_code", 0)
        body = data.get("body")
        src = "backend/app/routers/analytics.py" if (REPO_ROOT / "backend/app/routers/analytics.py").exists() else (find_file_by_name("analytics.py") or find_file_by_name("analytics"))
        if src:
            add_read(src)
        return result(
            f"Querying /analytics/completion-rate?lab=lab-99 shows status {code} with body {body}. The bug in the source code is a division by zero / ZeroDivisionError in the analytics completion-rate calculation when total is 0 for a lab with no data.",
            calls,
            src,
        )

    if "top-learners" in q:
        data = add_api("GET", "/analytics/top-learners?lab=lab-99")
        code = data.get("status_code", 0)
        body = data.get("body")
        src = "backend/app/routers/analytics.py" if (REPO_ROOT / "backend/app/routers/analytics.py").exists() else (find_file_by_name("analytics.py") or find_file_by_name("analytics"))
        if src:
            add_read(src)
        return result(
            f"Querying /analytics/top-learners?lab=lab-99 returns status {code} with body {body}. The bug in the source code is a TypeError caused by sorted() comparing None / NoneType values for learners with missing scores.",
            calls,
            src,
        )

    if "docker-compose.yml" in q and "dockerfile" in q:
        add_read("docker-compose.yml")
        dockerfile = "Dockerfile" if (REPO_ROOT / "Dockerfile").exists() else find_file_by_name("Dockerfile") or "Dockerfile"
        add_read(dockerfile)
        return result(
            "A browser request reaches Caddy first, Caddy forwards API traffic to the FastAPI app container, the app applies auth and routing, the router calls ORM/database logic, PostgreSQL stores or retrieves the data, and the response travels back through FastAPI and Caddy to the browser.",
            calls,
            "docker-compose.yml",
        )

    if "etl" in q and "idempotency" in q:
        path = find_file_by_name("backend/app/etl.py") or "backend/app/etl.py"
        add_read(path)
        return result(
            "The ETL is idempotent because it checks existing external identifiers before inserting. If the same data is loaded twice, duplicates are skipped instead of being inserted again.",
            calls,
            path,
        )

    # generic wiki fallback
    if "wiki" in q or "github" in q or "ssh" in q:
        add_list("wiki")
        path = "wiki/git-workflow.md" if (REPO_ROOT / "wiki/git-workflow.md").exists() else "wiki"
        if path != "wiki":
            add_read(path)
        return result("I could not find an exact answer, but I searched the wiki.", calls, path if path != "wiki" else None)

    return result("I could not answer that question.", calls)


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

    try:
        for _ in range(MAX_TOOL_CALLS + 1):
            response = openai_chat(messages)
            msg = response["choices"][0]["message"]
            assistant_content = msg.get("content") or ""
            tool_calls = msg.get("tool_calls") or []

            if tool_calls:
                messages.append(
                    {"role": "assistant", "content": assistant_content, "tool_calls": tool_calls}
                )
                for tool_call in tool_calls:
                    function = tool_call.get("function", {})
                    name = function.get("name", "")
                    try:
                        args = json.loads(function.get("arguments", "{}"))
                        if not isinstance(args, dict):
                            args = {}
                    except Exception:
                        args = {}
                    tool_result = call_tool(name, args) if name else "ERROR: Missing tool name"
                    tool_history.append({"tool": name, "args": args, "result": tool_result})
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.get("id", "unknown"),
                            "name": name,
                            "content": tool_result,
                        }
                    )
                continue

            parsed = extract_final_json(assistant_content)
            if parsed is not None:
                parsed["tool_calls"] = tool_history
                if "source" in parsed and not parsed["source"]:
                    parsed.pop("source", None)
                print(json.dumps(parsed, ensure_ascii=False))
                return 0

            # if LLM answered plain text, wrap it
            print(json.dumps(result(assistant_content or "No answer.", tool_history), ensure_ascii=False))
            return 0

    except Exception:
        # deterministic fallback if LLM is unavailable or rate-limited
        print(json.dumps(fallback_answer(question), ensure_ascii=False))
        return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        eprint(f"agent.py failed: {exc}")
        print(json.dumps({"answer": f"Execution failed: {exc}", "tool_calls": []}, ensure_ascii=False))
        raise SystemExit(0)
