from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Type
from urllib.parse import urlparse

from crewai.tools import BaseTool
from pydantic import BaseModel, Field


WORKSPACE_DIR = Path(os.getenv("HELM_GEN_WORKSPACE", ".helm_gen_workspace")).resolve()
OUTPUT_DIR = Path(os.getenv("HELM_GEN_OUTPUT_DIR", "generated_charts")).resolve()
MAX_SCAN_FILE_BYTES = 256_000


class RepositoryCloneInput(BaseModel):
    repository_url: str = Field(..., description="HTTPS Git repository URL.")
    git_ref: str = Field("main", description="Branch, tag, or commit to checkout.")


class RepositoryCloneTool(BaseTool):
    name: str = "repository_clone_tool"
    description: str = (
        "Clones a Git repository into a local isolated workspace and returns the checkout path. "
        "Use this before repository scanning."
    )
    args_schema: Type[BaseModel] = RepositoryCloneInput

    def _run(self, repository_url: str, git_ref: str = "main") -> str:
        parsed = urlparse(repository_url)
        if parsed.scheme not in {"https", "http"} or not parsed.netloc:
            return json.dumps({"status": "error", "message": "Only HTTP(S) Git URLs are supported."})

        WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
        checkout_dir = Path(tempfile.mkdtemp(prefix="repo_", dir=str(WORKSPACE_DIR)))
        cmd = [
            "git",
            "clone",
            "--depth",
            "1",
            "--branch",
            git_ref or "main",
            repository_url,
            str(checkout_dir),
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if result.returncode != 0:
            shutil.rmtree(checkout_dir, ignore_errors=True)
            return json.dumps(
                {
                    "status": "error",
                    "command": "git clone",
                    "message": _redact(result.stderr or result.stdout),
                }
            )

        return json.dumps({"status": "ok", "checkout_path": str(checkout_dir), "git_ref": git_ref})


class RepositoryScanInput(BaseModel):
    checkout_path: str = Field(..., description="Local repository checkout path.")
    app_subdirectory: str = Field("", description="Optional application subdirectory inside the repository.")


class RepositoryScanTool(BaseTool):
    name: str = "repository_scan_tool"
    description: str = (
        "Scans a local repository checkout for application framework, Docker, Kubernetes, Helm, "
        "ports, scripts, dependencies, and config hints. It returns evidence without secret values."
    )
    args_schema: Type[BaseModel] = RepositoryScanInput

    def _run(self, checkout_path: str, app_subdirectory: str = "") -> str:
        root = Path(checkout_path).resolve()
        target = (root / app_subdirectory).resolve() if app_subdirectory else root
        if root not in target.parents and target != root:
            return json.dumps({"status": "error", "message": "app_subdirectory escapes repository root."})
        if not target.exists():
            return json.dumps({"status": "error", "message": f"Path not found: {target}"})

        files = _collect_files(target)
        scan: dict[str, Any] = {
            "status": "ok",
            "repository_root": str(root),
            "scanned_path": str(target),
            "file_count": len(files),
            "detected_stack": [],
            "build_files": [],
            "docker_files": [],
            "kubernetes_files": [],
            "helm_files": [],
            "ports": [],
            "env_keys": [],
            "scripts": {},
            "evidence": [],
        }

        for path in files:
            rel = path.relative_to(target).as_posix()
            name = path.name.lower()
            if name in {"package.json", "pyproject.toml", "requirements.txt", "pom.xml", "build.gradle", "build.gradle.kts"} or name.endswith(".csproj"):
                scan["build_files"].append(rel)
                _detect_stack(scan, path)
            if name == "dockerfile" or name.endswith(".dockerfile"):
                scan["docker_files"].append(rel)
                _scan_text_file(path, rel, scan)
            if path.suffix.lower() in {".yaml", ".yml"}:
                text = _read_small_text(path)
                if text and re.search(r"\b(apiVersion|kind|metadata):", text):
                    scan["kubernetes_files"].append(rel)
                if "chart.yaml" == name or "templates/" in rel:
                    scan["helm_files"].append(rel)
            if name in {".env", ".env.example", "appsettings.json", "application.properties", "application.yml"}:
                _scan_text_file(path, rel, scan)

        scan["detected_stack"] = sorted(set(scan["detected_stack"]))
        scan["ports"] = sorted(set(scan["ports"]))
        scan["env_keys"] = sorted(set(scan["env_keys"]))
        return json.dumps(_redact_obj(scan), indent=2)


class SecretRedactionInput(BaseModel):
    content: str = Field(..., description="Text content to redact.")


class SecretRedactionTool(BaseTool):
    name: str = "secret_redaction_tool"
    description: str = "Redacts likely secret values from text before reports or generated notes are shown."
    args_schema: Type[BaseModel] = SecretRedactionInput

    def _run(self, content: str) -> str:
        return _redact(content)


class HelmChartWriterInput(BaseModel):
    chart_name: str = Field(..., description="Name of the Helm chart output directory.")
    repository_root: str = Field(
        "",
        description="Optional local repository checkout path. When provided with write_to_repository=true, writes under repository_root/helm.",
    )
    write_to_repository: bool = Field(
        False,
        description="When true, write the chart under repository_root/helm instead of generated_charts/chart_name.",
    )
    chart_files_json: str = Field(
        ...,
        description="JSON object or list containing file paths and content for the generated Helm chart.",
    )


class HelmChartWriterTool(BaseTool):
    name: str = "helm_chart_writer_tool"
    description: str = (
        "Writes generated Helm chart files. By default it writes to generated_charts/chart_name. "
        "When repository_root and write_to_repository=true are provided, it writes safely under repository_root/helm. "
        "Input must be JSON path/content pairs."
    )
    args_schema: Type[BaseModel] = HelmChartWriterInput

    def _run(
        self,
        chart_name: str,
        chart_files_json: str,
        repository_root: str = "",
        write_to_repository: bool = False,
    ) -> str:
        safe_chart_name = re.sub(r"[^a-zA-Z0-9_.-]", "-", chart_name).strip("-") or "generated-chart"
        if write_to_repository:
            if not repository_root:
                return json.dumps(
                    {
                        "status": "error",
                        "message": "repository_root is required when write_to_repository is true.",
                    }
                )
            repo_root = Path(repository_root).resolve()
            if not repo_root.exists() or not repo_root.is_dir():
                return json.dumps({"status": "error", "message": f"Repository root not found: {repo_root}"})
            chart_dir = (repo_root / "helm").resolve()
            allowed_root = chart_dir
        else:
            chart_dir = (OUTPUT_DIR / safe_chart_name).resolve()
            allowed_root = chart_dir
            if OUTPUT_DIR not in chart_dir.parents and chart_dir != OUTPUT_DIR:
                return json.dumps({"status": "error", "message": "Invalid chart output path."})

        try:
            parsed = json.loads(chart_files_json)
        except json.JSONDecodeError as exc:
            return json.dumps({"status": "error", "message": f"Invalid chart_files_json: {exc}"})

        files = _normalize_chart_files(parsed)
        if not files:
            return json.dumps({"status": "error", "message": "No chart files were provided."})

        chart_dir.mkdir(parents=True, exist_ok=True)
        written: list[str] = []
        for relative_path, content in files.items():
            normalized_path = _normalize_helm_relative_path(relative_path)
            destination = (chart_dir / normalized_path).resolve()
            if allowed_root not in destination.parents:
                return json.dumps({"status": "error", "message": f"Unsafe chart path: {relative_path}"})
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(_redact(str(content)), encoding="utf-8")
            written.append(str(destination.relative_to(chart_dir)))

        return json.dumps(
            {
                "status": "ok",
                "chart_dir": str(chart_dir),
                "write_target": "repository" if write_to_repository else "generated_charts",
                "repository_root": str(Path(repository_root).resolve()) if repository_root else "",
                "files": sorted(written),
            },
            indent=2,
        )


class HelmValidationInput(BaseModel):
    chart_dir: str = Field(..., description="Local Helm chart directory to validate.")


class HelmValidationTool(BaseTool):
    name: str = "helm_validation_tool"
    description: str = (
        "Validates a local Helm chart with helm lint and helm template. "
        "Also runs kubeconform and checkov when those tools are installed."
    )
    args_schema: Type[BaseModel] = HelmValidationInput

    def _run(self, chart_dir: str) -> str:
        chart_path = Path(chart_dir).resolve()
        if not chart_path.exists():
            return json.dumps({"status": "error", "message": f"Chart directory not found: {chart_path}"})

        checks = [
            ["helm", "lint", str(chart_path)],
            ["helm", "template", str(chart_path)],
        ]
        if shutil.which("kubeconform"):
            checks.append(["kubeconform", "-summary", "-strict", "-"])
        if shutil.which("checkov"):
            checks.append(["checkov", "-d", str(chart_path), "--quiet"])

        results: list[dict[str, Any]] = []
        rendered_manifest = ""
        for command in checks:
            if command[0] == "kubeconform":
                if not rendered_manifest:
                    template = subprocess.run(
                        ["helm", "template", str(chart_path)],
                        capture_output=True,
                        text=True,
                        timeout=120,
                    )
                    rendered_manifest = template.stdout
                result = subprocess.run(
                    command,
                    input=rendered_manifest,
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
            else:
                result = subprocess.run(command, capture_output=True, text=True, timeout=120)
                if command[:2] == ["helm", "template"] and result.returncode == 0:
                    rendered_manifest = result.stdout
            results.append(
                {
                    "command": " ".join(command),
                    "exit_code": result.returncode,
                    "stdout": _redact(result.stdout[-4000:]),
                    "stderr": _redact(result.stderr[-4000:]),
                }
            )

        status = "ok" if all(item["exit_code"] == 0 for item in results) else "failed"
        return json.dumps({"status": status, "chart_dir": str(chart_path), "results": results}, indent=2)


def _collect_files(root: Path) -> list[Path]:
    ignored_dirs = {".git", ".venv", "venv", "node_modules", "dist", "build", "target", "__pycache__"}
    result: list[Path] = []
    for path in root.rglob("*"):
        if any(part in ignored_dirs for part in path.parts):
            continue
        if path.is_file():
            result.append(path)
    return result[:1000]


def _detect_stack(scan: dict[str, Any], path: Path) -> None:
    name = path.name.lower()
    text = _read_small_text(path)
    if name == "package.json":
        scan["detected_stack"].append("nodejs")
        try:
            package_json = json.loads(text or "{}")
            scan["scripts"] = package_json.get("scripts", {})
            deps = {**package_json.get("dependencies", {}), **package_json.get("devDependencies", {})}
            for framework in ["express", "next", "react", "vite", "nestjs", "@nestjs/core"]:
                if framework in deps:
                    scan["detected_stack"].append(framework)
        except json.JSONDecodeError:
            scan["evidence"].append(f"{path.name}: invalid package.json")
    elif name in {"requirements.txt", "pyproject.toml"}:
        scan["detected_stack"].append("python")
        for framework in ["fastapi", "flask", "django"]:
            if text and framework in text.lower():
                scan["detected_stack"].append(framework)
    elif name in {"pom.xml", "build.gradle", "build.gradle.kts"}:
        scan["detected_stack"].append("java")
        if text and "spring-boot" in text.lower():
            scan["detected_stack"].append("spring-boot")
    elif name.endswith(".csproj"):
        scan["detected_stack"].append("dotnet")
        if text and "microsoft.net.sdk.web" in text.lower():
            scan["detected_stack"].append("aspnet")


def _scan_text_file(path: Path, rel: str, scan: dict[str, Any]) -> None:
    text = _read_small_text(path)
    if not text:
        return
    for match in re.finditer(r"\b(?:EXPOSE|--port|PORT=|server\.port=)\s*[:=]?\s*(\d{2,5})\b", text, re.IGNORECASE):
        scan["ports"].append(match.group(1))
    for match in re.finditer(r"\b([A-Z][A-Z0-9_]{2,})\s*=", text):
        key = match.group(1)
        if not _looks_sensitive_key(key):
            scan["env_keys"].append(key)
    scan["evidence"].append(f"Scanned {rel}")


def _read_small_text(path: Path) -> str:
    try:
        if path.stat().st_size > MAX_SCAN_FILE_BYTES:
            return ""
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _normalize_chart_files(parsed: Any) -> dict[str, str]:
    if isinstance(parsed, dict):
        if "files" in parsed:
            return _normalize_chart_files(parsed["files"])
        return {str(key): str(value) for key, value in parsed.items()}
    if isinstance(parsed, list):
        normalized: dict[str, str] = {}
        for item in parsed:
            if isinstance(item, dict):
                path = item.get("path") or item.get("file_path") or item.get("name")
                content = item.get("content")
                if path and content is not None:
                    normalized[str(path)] = str(content)
        return normalized
    return {}


def _normalize_helm_relative_path(relative_path: str) -> str:
    safe_parts = []
    for part in Path(relative_path.replace("\\", "/")).parts:
        if part in {"", ".", "/"}:
            continue
        if part == "..":
            continue
        safe_parts.append(part)
    if safe_parts and safe_parts[0].lower() == "helm":
        safe_parts = safe_parts[1:]
    return str(Path(*safe_parts)) if safe_parts else "Chart.yaml"


def _redact_obj(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: ("<redacted>" if _looks_sensitive_key(str(key)) else _redact_obj(val)) for key, val in value.items()}
    if isinstance(value, list):
        return [_redact_obj(item) for item in value]
    if isinstance(value, str):
        return _redact(value)
    return value


def _redact(value: str) -> str:
    patterns = [
        r"(?i)(password|passwd|pwd|secret|token|apikey|api_key|connectionstring)\s*[:=]\s*['\"]?[^'\"\s,}]+",
        r"(?i)(AccountKey=)[^;]+",
        r"(?i)(SharedAccessKey=)[^;]+",
    ]
    redacted = value
    for pattern in patterns:
        redacted = re.sub(pattern, lambda m: m.group(0).split("=")[0].split(":")[0] + "=<redacted>", redacted)
    return redacted


def _looks_sensitive_key(key: str) -> bool:
    return bool(re.search(r"(?i)(password|passwd|pwd|secret|token|apikey|api_key|connection|string|key)", key))
