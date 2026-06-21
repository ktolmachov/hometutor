#!/usr/bin/env python3
"""
Localhost-only readiness gate for home-rag.

The script is intentionally lightweight: it checks the local files, ports, and
optional running endpoints needed for a dependable "start on localhost" path.
It does not import app.provider or create LLM clients.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


DEFAULT_API_URL = "http://127.0.0.1:8000"
DEFAULT_UI_URL = "http://127.0.0.1:8501"
DEFAULT_LLM_API_BASE = "http://127.0.0.1:1234/v1"


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str
    message: str
    detail: str | None = None


def _strip_inline_comment(value: str) -> str:
    in_single = False
    in_double = False
    for idx, ch in enumerate(value):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            if idx == 0 or value[idx - 1].isspace():
                return value[:idx].strip()
    return value.strip()


def read_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, raw_value = line.split("=", 1)
        name = name.strip()
        if not name:
            continue
        value = _strip_inline_comment(raw_value).strip().strip('"').strip("'")
        values[name] = value
    return values


def _data_root(root: Path) -> Path:
    return Path(os.environ.get("HOME_RAG_HOME", "D:/AI/app"))


def read_runtime_env(root: Path) -> dict[str, str]:
    """Read runtime defaults the same way app/config.py does: config.env, then .env overrides."""
    values = read_dotenv(root / "config.env")
    values.update(read_dotenv(_data_root(root) / ".env"))
    return values


def _result(name: str, status: str, message: str, detail: str | None = None) -> CheckResult:
    return CheckResult(name=name, status=status, message=message, detail=detail)


def _is_loopback_url(url: str) -> bool:
    value = url.lower()
    return "127.0.0.1" in value or "localhost" in value or "::1" in value


def _models_url(base_url: str) -> str:
    base = base_url.strip().rstrip("/")
    if not base:
        return ""
    if base.endswith("/v1"):
        return f"{base}/models"
    return f"{base}/v1/models"


def _http_probe(url: str, timeout_sec: float) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout_sec) as response:
            status = getattr(response, "status", 200)
            if 200 <= status < 300:
                return True, f"HTTP {status}"
            return False, f"HTTP {status}"
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}"
    except OSError as exc:
        return False, str(exc)


def _port_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def check_repo_layout(root: Path) -> list[CheckResult]:
    expected = [
        ("FastAPI app", root / "app" / "api.py"),
        ("Streamlit app", root / "app" / "ui" / "main.py"),
        ("ingest entrypoint", root / "ingest.py"),
        ("requirements", root / "requirements.txt"),
    ]
    results: list[CheckResult] = []
    for label, path in expected:
        if path.exists():
            results.append(_result(label, "pass", f"Found {path.relative_to(root)}"))
        else:
            results.append(_result(label, "fail", f"Missing {path.relative_to(root)}"))
    return results


def check_python(root: Path) -> CheckResult:
    py = root / ".venv" / "Scripts" / "python.exe"
    if py.is_file():
        return _result("venv python", "pass", f"Using {py.relative_to(root)}")
    return _result(
        "venv python",
        "fail",
        "Missing .venv\\Scripts\\python.exe",
        "Create it with: python -m venv .venv && .\\.venv\\Scripts\\python.exe -m pip install -r requirements.txt",
    )


def check_env(root: Path, values: dict[str, str]) -> list[CheckResult]:
    env_path = _data_root(root) / ".env"
    if not env_path.is_file():
        return [
            _result(
                ".env",
                "fail",
                "Missing .env",
                "Copy .env.example to .env, then set OPENAI_API_KEY=local for local providers or a real API key.",
            )
        ]
    if not env_path.stat().st_size:
        return [_result(".env", "fail", ".env is empty")]

    key = values.get("OPENAI_API_KEY", "").strip()
    if not key:
        return [_result("OPENAI_API_KEY", "fail", "OPENAI_API_KEY is empty")]
    if key == "your-key-here":
        return [
            _result(
                "OPENAI_API_KEY",
                "fail",
                "OPENAI_API_KEY still has the placeholder value",
                "Use OPENAI_API_KEY=local for Ollama/LM Studio, or set a real provider key.",
            )
        ]
    return [_result(".env", "pass", ".env exists and OPENAI_API_KEY is set")]


def check_dirs(root: Path, mode: str) -> list[CheckResult]:
    results: list[CheckResult] = []
    for name in ("data", "chroma_db", "logs"):
        path = root / name
        if path.is_dir():
            results.append(_result(f"{name}/", "pass", f"Found {name}/"))
        elif name in {"data", "chroma_db"} and mode == "demo" and (root / "demo_data").exists():
            results.append(
                _result(
                    f"{name}/",
                    "warn",
                    f"Missing {name}/; demo_data/ is available for demo setup",
                )
            )
        else:
            results.append(_result(f"{name}/", "warn", f"Missing {name}/; bootstrap.py can create it"))
    return results


def check_ports(host: str, allow_running: bool) -> list[CheckResult]:
    results: list[CheckResult] = []
    for label, port in (("FastAPI port", 8000), ("Streamlit port", 8501)):
        available = _port_available(host, port)
        if available:
            results.append(_result(label, "pass", f"{host}:{port} is free"))
        elif allow_running:
            results.append(_result(label, "warn", f"{host}:{port} is already in use"))
        else:
            results.append(
                _result(
                    label,
                    "fail",
                    f"{host}:{port} is already in use",
                    "Stop the existing process or run with --allow-running when checking an active stack.",
                )
            )
    return results


def check_provider_urls(values: dict[str, str], probe_models: bool, timeout_sec: float) -> list[CheckResult]:
    llm_base = values.get("LLM_API_BASE") or DEFAULT_LLM_API_BASE
    embed_base = values.get("EMBED_API_BASE") or values.get("OPENAI_API_BASE") or ""
    ssr_raw = values.get("SSR_LLM_API_BASE")
    ssr_base = llm_base if ssr_raw == "" else (ssr_raw or "")

    configured = [
        ("LLM_API_BASE", llm_base),
        ("EMBED_API_BASE", embed_base),
        ("SSR_LLM_API_BASE", ssr_base),
    ]
    results: list[CheckResult] = []
    seen: set[str] = set()
    for name, url in configured:
        if not url:
            results.append(_result(name, "warn", f"{name} is not set"))
            continue
        locality = "loopback" if _is_loopback_url(url) else "remote"
        results.append(_result(name, "pass", f"{name} -> {url} ({locality})"))
        if not probe_models or not _is_loopback_url(url):
            continue
        models_url = _models_url(url)
        if not models_url or models_url in seen:
            continue
        seen.add(models_url)
        ok, detail = _http_probe(models_url, timeout_sec)
        status = "pass" if ok else "warn"
        results.append(_result(f"{name} /models", status, f"Probe {models_url}: {detail}"))
    return results


def check_running_stack(api_url: str, ui_url: str, timeout_sec: float) -> list[CheckResult]:
    checks = [
        ("FastAPI /health", f"{api_url.rstrip('/')}/health"),
        ("Streamlit health", f"{ui_url.rstrip('/')}/_stcore/health"),
    ]
    results: list[CheckResult] = []
    for name, url in checks:
        ok, detail = _http_probe(url, timeout_sec)
        status = "pass" if ok else "fail"
        results.append(_result(name, status, f"{url}: {detail}"))
    return results


def summarize(results: list[CheckResult]) -> dict[str, Any]:
    counts = {"pass": 0, "warn": 0, "fail": 0}
    for item in results:
        counts[item.status] = counts.get(item.status, 0) + 1
    return {
        "ok": counts.get("fail", 0) == 0,
        "counts": counts,
        "checks": [asdict(item) for item in results],
    }


def print_human(summary: dict[str, Any]) -> None:
    print("Localhost readiness")
    print("===================")
    for item in summary["checks"]:
        marker = {"pass": "OK", "warn": "WARN", "fail": "FAIL"}[item["status"]]
        print(f"[{marker}] {item['name']}: {item['message']}")
        if item.get("detail"):
            print(f"       {item['detail']}")
    counts = summary["counts"]
    print()
    print(f"Result: {counts['pass']} pass, {counts['warn']} warn, {counts['fail']} fail")
    if summary["ok"]:
        print("Ready for localhost launch.")
    else:
        print("Fix failed checks before launching.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="Repository root. Defaults to current directory.")
    parser.add_argument("--mode", choices=("normal", "demo"), default="normal")
    parser.add_argument("--allow-running", action="store_true", help="Treat occupied 8000/8501 ports as warnings.")
    parser.add_argument("--check-running", action="store_true", help="Probe already-running API and Streamlit health endpoints.")
    parser.add_argument("--probe-models", action="store_true", help="Probe loopback OpenAI-compatible /models endpoints.")
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    parser.add_argument("--ui-url", default=DEFAULT_UI_URL)
    parser.add_argument("--timeout-sec", type=float, default=2.0)
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root).resolve()
    values = read_runtime_env(root)

    results: list[CheckResult] = []
    results.extend(check_repo_layout(root))
    results.append(check_python(root))
    results.extend(check_env(root, values))
    results.extend(check_dirs(root, args.mode))
    results.extend(check_ports("127.0.0.1", allow_running=args.allow_running))
    results.extend(check_provider_urls(values, args.probe_models, args.timeout_sec))
    if args.check_running:
        results.extend(check_running_stack(args.api_url, args.ui_url, args.timeout_sec))

    summary = summarize(results)
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print_human(summary)
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
