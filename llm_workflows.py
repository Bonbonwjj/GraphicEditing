"""Validated, skill-driven LLM workflows for chart splitting and editing."""
import ast
import json
import os
import re
from pathlib import Path

import llm_client


ROOT = Path(__file__).resolve().parent
SKILLS = ROOT / "skills"
BLOCKED_IMPORTS = {"http", "requests", "socket", "subprocess", "urllib"}
BLOCKED_CALLS = {"compile", "eval", "exec", "__import__"}
BLOCKED_OS_CALLS = {"popen", "spawnl", "spawnle", "spawnlp", "spawnlpe", "spawnv",
                    "spawnve", "spawnvp", "spawnvpe", "system"}


def _skill(name):
    return (SKILLS / name / "SKILL.md").read_text(encoding="utf-8")


def _strip_fence(text):
    text = text.strip()
    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline >= 0 and text.endswith("```"):
            return text[first_newline + 1:-3].strip()
    return text


def _json_object(text):
    text = _strip_fence(text)
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("expected one JSON object")
        try:
            value = json.loads(text[start:end + 1])
        except json.JSONDecodeError as error:
            raise ValueError("invalid JSON: " + str(error)) from error
    if not isinstance(value, dict):
        raise ValueError("top-level response must be a JSON object")
    return value


def validate_chart_source(source):
    if not isinstance(source, str) or not source.strip():
        raise ValueError("chart code is empty")
    if len(source) > 100_000:
        raise ValueError("chart code exceeds 100000 characters")
    try:
        tree = ast.parse(source)
    except SyntaxError as error:
        raise ValueError(f"invalid Python: {error}") from error
    if "CHART_PROJECT_DIR" not in source:
        raise ValueError("chart code must preserve CHART_PROJECT_DIR")
    if "CHART_OUTPUT" not in source:
        raise ValueError("chart code must write to CHART_OUTPUT")
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            if any(name.split(".")[0] in BLOCKED_IMPORTS for name in names):
                raise ValueError("network or subprocess imports are not allowed")
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in BLOCKED_CALLS:
                raise ValueError(f"{node.func.id}() is not allowed")
            if (isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and
                    node.func.value.id == "os" and node.func.attr in BLOCKED_OS_CALLS):
                raise ValueError(f"os.{node.func.attr}() is not allowed")
    return source.rstrip() + "\n"


def _repair(messages, bad_output, error, output_contract):
    repair = (_skill("chart-code-repair") + "\n\nThe rejected output was:\n" + bad_output +
              "\n\nValidator error: " + str(error) + "\n\nRequired output: " + output_contract)
    return llm_client.chat(messages + [{"role": "assistant", "content": bad_output},
                                       {"role": "user", "content": repair}], temperature=0)


def edit_chart(request, source, data, validator=None):
    system = _skill("chart-code-edit") + "\n\n" + _skill("plot-style")
    user = json.dumps({"request": request, "csv_files": data, "current_code": source}, ensure_ascii=False)
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    output = llm_client.chat(messages)
    repairs = max(0, min(int(os.environ.get("LLM_MAX_REPAIRS", "1")), 2))
    for attempt in range(repairs + 1):
        try:
            proposed = validate_chart_source(_strip_fence(output))
            if validator:
                validator(proposed)
            return proposed
        except Exception as error:
            if attempt == repairs:
                raise ValueError("Model returned unusable chart code: " + str(error)) from error
            output = _repair(messages, output, error, "complete raw Python source")


def split_chart(source_name, source, data_catalog):
    system = _skill("chart-code-split") + "\n\n" + _skill("plot-style")
    user = json.dumps({"source_file": source_name, "data_files": data_catalog,
                       "source_code": source}, ensure_ascii=False)
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    output = llm_client.chat(messages)
    repairs = max(0, min(int(os.environ.get("LLM_MAX_REPAIRS", "1")), 2))
    for attempt in range(repairs + 1):
        try:
            value = _json_object(output)
            charts = value.get("charts")
            if not isinstance(charts, list) or not charts:
                raise ValueError("charts must be a non-empty array")
            clean = []
            for item in charts:
                if not isinstance(item, dict) or set(item) != {"name", "code"}:
                    raise ValueError("each chart needs exactly name and code")
                name = re.sub(r"[^A-Za-z0-9_]+", "_", str(item["name"])).strip("_")
                if not name:
                    raise ValueError("chart name is empty")
                clean.append({"name": name, "code": validate_chart_source(item["code"])})
            return clean
        except (ValueError, TypeError) as error:
            if attempt == repairs:
                raise ValueError("Model returned an unusable chart split: " + str(error)) from error
            output = _repair(messages, output, error, "one JSON object with a non-empty charts array")
