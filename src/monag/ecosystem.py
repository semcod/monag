"""Dynamic ecosystem tooling and API discovery for monag.

Detects installed CLI tools, importable libraries, local services,
and MCP servers so autonomous agents and developers know exactly what
capabilities are available in the current environment.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import socket
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

# Standard known ecosystem tools and their descriptions
KNOWN_TOOLS: dict[str, dict[str, Any]] = {
    "git": {"role": "version control and worktree lifecycle", "aliases": ("git",), "module": None},
    "gh": {"role": "GitHub CLI integration and PR automation", "aliases": ("gh",), "module": None},
    "diagit": {"role": "fleet git audits and worktree diagnostics", "aliases": ("diagit",), "module": "diagit"},
    "redup": {"role": "AST code duplication analysis and detector", "aliases": ("redup",), "module": "redup"},
    "prefact": {"role": "automated refactoring and pre-refactor checks", "aliases": ("prefact",), "module": "prefact"},
    "koru": {"role": "closed-loop agent automation and living execution gate", "aliases": ("koru",), "module": "koru"},
    "planfile": {"role": "ticket lifecycle source of truth and queue", "aliases": ("planfile",), "module": "planfile"},
    "subllm": {"role": "centralized LLM gateway, models, and usage panel", "aliases": ("subllm",), "module": "subllm"},
    "nxdo": {"role": "intent execution and workflow orchestrator", "aliases": ("nxdo",), "module": "nxdo"},
    "tagi": {"role": "semantic tagging and code indexer", "aliases": ("tagi",), "module": "tagi"},
    "tillm": {"role": "shell LLM client control plane and provider failover", "aliases": ("tillm",), "module": "tillm"},
    "wup": {"role": "real-time file and service watcher", "aliases": ("wup",), "module": "wup"},
    "testql": {"role": "behavioural HTTP probes and scenario testing", "aliases": ("testql",), "module": "testql"},
    "regix": {"role": "regression metrics gate", "aliases": ("regix",), "module": "regix"},
    "todo2code": {"role": "NL/TODO/CHANGELOG to planfile tickets", "aliases": ("t2c", "todo2code"), "module": None},
    "code2llm": {"role": "whole-project LLM analysis and snapshot", "aliases": ("code2llm", "sumd"), "module": None},
    "pfix": {"role": "self-healing Python auto-fix", "aliases": ("pfix",), "module": "pfix"},
    "vallm": {"role": "syntax and semantic validation", "aliases": ("vallm",), "module": "vallm"},
    "redsl": {"role": "quality gate and LLM-backed improve lane", "aliases": ("redsl",), "module": "redsl"},
    "llx": {"role": "LLM model router", "aliases": ("llx",), "module": "llx"},
    "doql": {"role": "declarative infrastructure and app sync", "aliases": ("doql",), "module": "doql"},
    "redeploy": {"role": "deployment planning and rollout", "aliases": ("redeploy",), "module": "redeploy"},
    "goal": {"role": "strategic goal alignment", "aliases": ("goal",), "module": "goal"},
    "costs": {"role": "AI cost tracking and badge", "aliases": ("costs",), "module": "costs"},
    "op3": {"role": "multi-layer infrastructure observation", "aliases": ("op3",), "module": "op3"},
    "toonic": {"role": "TOON format conversion", "aliases": ("toonic",), "module": "toonic"},
    "protogate": {"role": "bounded legacy migration gates", "aliases": ("protogate",), "module": "protogate"},
    "rebuild": {"role": "git history walker and quality replay", "aliases": ("rebuild",), "module": "rebuild"},
    "mdflow": {"role": "markdown dependency analyzer", "aliases": ("mdflow",), "module": "mdflow"},
    "metrun": {"role": "execution intelligence and bottlenecks", "aliases": ("metrun",), "module": "metrun"},
    "paxlet": {"role": "lightweight task paxlet runner", "aliases": ("paxlet",), "module": "paxlet"},
    "monag": {"role": "agent monitor, triage, doctor, and MCP server", "aliases": ("monag",), "module": "monag"},
}


@dataclass
class ToolCapability:
    """Discovered capability of an ecosystem tool."""
    name: str
    role: str
    available: bool
    via: str  # "PATH" | "module" | "missing"
    path: str | None = None
    version: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ServiceCapability:
    """Discovered local daemon, API endpoint, or MCP server."""
    name: str
    kind: str  # "systemd" | "http" | "socket" | "mcp"
    status: str  # "active" | "inactive" | "listening"
    endpoint: str
    description: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _probe_version(executable_path: str) -> str | None:
    """Safely obtain version string from an executable."""
    try:
        proc = subprocess.run(
            [executable_path, "--version"],
            capture_output=True,
            text=True,
            timeout=1.0,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout:
            first_line = proc.stdout.strip().splitlines()[0]
            # Strip excessive length
            return first_line[:60]
    except (subprocess.SubprocessError, OSError):
        pass
    return None


def audit_ecosystem_tools() -> dict[str, ToolCapability]:
    """Scan and return all known and discovered ecosystem tools."""
    results: dict[str, ToolCapability] = {}

    # 1. Audit predefined tools
    for tool_id, meta in KNOWN_TOOLS.items():
        found_path: str | None = None
        for alias in meta.get("aliases", (tool_id,)):
            p = shutil.which(alias)
            if p:
                found_path = p
                break

        if found_path:
            version = _probe_version(found_path)
            results[tool_id] = ToolCapability(
                name=tool_id,
                role=meta["role"],
                available=True,
                via="PATH",
                path=found_path,
                version=version,
            )
            continue

        # Check Python module importability
        mod_name = meta.get("module")
        if mod_name:
            try:
                spec = importlib.util.find_spec(mod_name)
                if spec is not None:
                    results[tool_id] = ToolCapability(
                        name=tool_id,
                        role=meta["role"],
                        available=True,
                        via="module",
                        path=spec.origin,
                        version=None,
                    )
                    continue
            except (ImportError, ValueError, AttributeError):
                pass

        results[tool_id] = ToolCapability(
            name=tool_id,
            role=meta["role"],
            available=False,
            via="missing",
            path=None,
            version=None,
        )

    # 2. Dynamic discovery: search PATH for semcod / subactor binaries not in predefined list
    paths = os.environ.get("PATH", "").split(os.pathsep)
    for p_dir in paths:
        d = Path(p_dir)
        if not d.is_dir():
            continue
        try:
            for item in d.iterdir():
                if item.is_file() and os.access(item, os.X_OK):
                    name = item.name
                    # Filter relevant prefixes if not already recorded
                    if (name.startswith("semcod-") or name.startswith("subactor-")) and name not in results:
                        results[name] = ToolCapability(
                            name=name,
                            role="dynamically discovered ecosystem executable",
                            available=True,
                            via="PATH",
                            path=str(item),
                            version=_probe_version(str(item)),
                        )
        except (OSError, PermissionError):
            continue

    return results


def _check_tcp_port(port: int, host: str = "127.0.0.1") -> bool:
    """Check if a TCP port is currently listening."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex((host, port)) == 0


def audit_local_services() -> list[ServiceCapability]:
    """Audit active local daemons, HTTP APIs, and IPC sockets."""
    services: list[ServiceCapability] = []

    # 1. Check known HTTP API ports
    api_ports = [
        (18988, "SubLLM Usage Panel", "http://127.0.0.1:18988/"),
        (8789, "SubLLM Unified Gateway Pilot", "https://127.0.0.1:8789/"),
        (8765, "Monag Web Panel", "http://127.0.0.1:8765/"),
    ]
    for port, label, endpoint in api_ports:
        is_listening = _check_tcp_port(port)
        if is_listening:
            services.append(
                ServiceCapability(
                    name=label,
                    kind="http",
                    status="listening",
                    endpoint=endpoint,
                    description=f"Local HTTP service listening on port {port}",
                )
            )

    # 2. Check active systemd user services
    candidate_services = [
        ("subllm-usage-panel.service", "SubLLM Dashboard"),
        ("subllm-gateway-pilot.service", "SubLLM Gateway Pilot"),
        ("koru-lane-koru.service", "Koru Autonomous Lane (semcod/koru)"),
        ("koru-lane-prefact.service", "Koru Autonomous Lane (semcod/prefact)"),
        ("koru-lane-repatch.service", "Koru Autonomous Lane (semcod/repatch)"),
        ("koru-lane-tagi.service", "Koru Autonomous Lane (semcod/tagi)"),
        ("koru-lane-nxdo.service", "Koru Autonomous Lane (semcod/nxdo)"),
    ]

    for unit, label in candidate_services:
        try:
            proc = subprocess.run(
                ["systemctl", "--user", "is-active", unit],
                capture_output=True,
                text=True,
                timeout=0.8,
                check=False,
            )
            state = proc.stdout.strip()
            if state in ("active", "activating"):
                services.append(
                    ServiceCapability(
                        name=label,
                        kind="systemd",
                        status=state,
                        endpoint=unit,
                        description=f"Systemd user unit '{unit}' is {state}",
                    )
                )
        except (subprocess.SubprocessError, OSError):
            pass

    # 3. Check Unix domain sockets in /run/user/<uid>
    uid = os.getuid()
    run_user = Path(f"/run/user/{uid}")
    if run_user.is_dir():
        try:
            for sock_file in run_user.glob("koru-autopilot*.sock"):
                services.append(
                    ServiceCapability(
                        name=f"Autopilot Socket ({sock_file.name})",
                        kind="socket",
                        status="active",
                        endpoint=str(sock_file),
                        description="Koru autopilot UNIX IPC domain socket",
                    )
                )
        except (OSError, PermissionError):
            pass

    # 4. Standard MCP capabilities
    if shutil.which("monag"):
        services.append(
            ServiceCapability(
                name="Monag MCP Server",
                kind="mcp",
                status="available",
                endpoint="monag mcp",
                description="Model Context Protocol stdio server for workspace observation",
            )
        )

    return services


def get_ecosystem_overview() -> dict[str, Any]:
    """Aggregate complete ecosystem tooling and services."""
    tools = audit_ecosystem_tools()
    services = audit_local_services()

    installed = [t for t in tools.values() if t.available]
    missing = [t for t in tools.values() if not t.available]

    return {
        "tools_total": len(tools),
        "tools_installed": len(installed),
        "tools_missing": len(missing),
        "services_active": len(services),
        "tools": {k: v.to_dict() for k, v in tools.items()},
        "services": [s.to_dict() for s in services],
    }


def render_markdown(overview: dict[str, Any]) -> str:
    """Render ecosystem overview as GitHub-flavored markdown."""
    lines = [
        "# Ecosystem Tools & API Discovery",
        "",
        f"**Installed Tools:** `{overview['tools_installed']}/{overview['tools_total']}` · "
        f"**Active Services/APIs:** `{overview['services_active']}`",
        "",
        "## Installed Ecosystem CLI Tools",
        "",
        "| Tool | Role | Availability | Path | Version |",
        "| --- | --- | --- | --- | --- |",
    ]

    for name, tool in sorted(overview["tools"].items()):
        if tool["available"]:
            ver = tool["version"] or "—"
            path = tool["path"] or f"module ({tool['via']})"
            lines.append(f"| **{name}** | {tool['role']} | `{tool['via']}` | `{path}` | {ver} |")

    lines.extend([
        "",
        "## Missing / Candidate Tools",
        "",
        "| Tool | Role | Status |",
        "| --- | --- | --- |",
    ])

    for name, tool in sorted(overview["tools"].items()):
        if not tool["available"]:
            lines.append(f"| **{name}** | {tool['role']} | `not found in PATH` |")

    if overview.get("services"):
        lines.extend([
            "",
            "## Active Local Services, APIs & Daemons",
            "",
            "| Service | Kind | Status | Endpoint | Description |",
            "| --- | --- | --- | --- | --- |",
        ])
        for s in overview["services"]:
            lines.append(f"| **{s['name']}** | `{s['kind']}` | `{s['status']}` | `{s['endpoint']}` | {s['description']} |")

    return "\n".join(lines)


def render_terminal(overview: dict[str, Any]) -> str:
    """Render ecosystem overview in clean plain text / terminal format."""
    lines = [
        f"MONAG ECOSYSTEM | {overview['tools_installed']}/{overview['tools_total']} tools installed | {overview['services_active']} active services/APIs",
        "",
        "INSTALLED TOOLS:",
    ]
    for name, tool in sorted(overview["tools"].items()):
        if tool["available"]:
            ver = f" ({tool['version']})" if tool["version"] else ""
            lines.append(f"  ✓ {name:<12} {tool['role']} [{tool['via']}{ver}]")

    missing = [name for name, tool in overview["tools"].items() if not tool["available"]]
    if missing:
        lines.append("")
        lines.append(f"MISSING TOOLS ({len(missing)}):")
        lines.append("  " + ", ".join(sorted(missing)))

    if overview.get("services"):
        lines.append("")
        lines.append("ACTIVE SERVICES & APIS:")
        for s in overview["services"]:
            lines.append(f"  ● {s['name']:<32} [{s['kind']}] {s['endpoint']}")

    return "\n".join(lines)
