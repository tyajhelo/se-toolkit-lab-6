from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def run_agent(question: str) -> dict:
    env = os.environ.copy()
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "agent.py"), question],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    assert result.stdout.strip(), f"stdout is empty; stderr={result.stderr}"
    return json.loads(result.stdout)


def test_agent_returns_answer_and_tool_calls():
    data = run_agent("What does REST stand for?")
    assert "answer" in data
    assert "tool_calls" in data
    assert isinstance(data["tool_calls"], list)


def test_merge_conflict_question_uses_read_file():
    data = run_agent("How do you resolve a merge conflict?")
    assert "answer" in data
    assert "tool_calls" in data
    assert any(call["tool"] == "read_file" for call in data["tool_calls"])


def test_list_wiki_question_uses_list_files():
    data = run_agent("What files are in the wiki?")
    assert "tool_calls" in data
    assert any(call["tool"] == "list_files" for call in data["tool_calls"])


def test_backend_framework_question_uses_read_file():
    data = run_agent("What Python web framework does this project's backend use?")
    assert "tool_calls" in data
    assert any(call["tool"] == "read_file" for call in data["tool_calls"])


def test_item_count_question_uses_query_api():
    data = run_agent("How many items are currently stored in the database?")
    assert "tool_calls" in data
    assert any(call["tool"] == "query_api" for call in data["tool_calls"])

# test update Thu Mar 19 10:11:26 PM MSK 2026
