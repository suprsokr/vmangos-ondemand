"""Action definitions, Docker compose helpers, and setup status checks."""

import json
import os
import subprocess

SERVICES = ("db", "mangosd", "realmd")

COMMANDS = {
    "clone-core": ("Clone Core Repository", "git clone https://github.com/vmangos/core.git core"),
    "update-core": ("Update Core Repository", "git -C core pull"),
    "build-image": ("Build Docker Image", "docker compose build"),
    "compile": ("Compile Server", "docker compose run --rm build"),
    "compile-extractors": ("Compile Extractors", "docker compose run --rm -e USE_EXTRACTORS=1 build"),
    "start-db": ("Start Database", "docker compose up -d db"),
    "stop-db": ("Stop Database", "docker compose stop db"),
    "import-db": ("Import Database", "docker compose run --rm db-import"),
    "start-mangosd": ("Start mangosd", "docker compose up -d mangosd"),
    "stop-mangosd": ("Stop mangosd", "docker compose stop mangosd"),
    "restart-mangosd": ("Restart mangosd", "docker compose restart mangosd"),
    "start-realmd": ("Start realmd", "docker compose up -d realmd"),
    "stop-realmd": ("Stop realmd", "docker compose stop realmd"),
    "restart-realmd": ("Restart realmd", "docker compose restart realmd"),
}

EXTRACT_LABELS = {
    "all": "Extract All Client Data",
    "maps": "Extract Maps & DBC",
    "vmaps": "Extract VMaps",
    "mmaps": "Generate Movement Maps",
}


def get_service_status(base_dir):
    """Query docker compose for running service states."""
    try:
        result = subprocess.run(
            ["docker", "compose", "ps", "--format", "json"],
            capture_output=True,
            text=True,
            cwd=base_dir,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None

    services = {
        name: {"state": "exited", "status": "", "health": ""}
        for name in SERVICES
    }

    if result.returncode == 0 and result.stdout.strip():
        for line in result.stdout.strip().split("\n"):
            try:
                svc = json.loads(line)
                svc_name = svc.get("Service", "")
                if svc_name in services:
                    services[svc_name] = {
                        "state": svc.get("State", "unknown"),
                        "status": svc.get("Status", ""),
                        "health": svc.get("Health", ""),
                    }
            except (json.JSONDecodeError, KeyError):
                pass

    return services


def get_setup_status(base_dir):
    """Check which setup steps have been completed."""
    return {
        "core_cloned": os.path.isfile(os.path.join(base_dir, "core", "CMakeLists.txt")),
        "server_compiled": os.path.isfile(os.path.join(base_dir, "server", "bin", "mangosd")),
        "data_extracted": os.path.isdir(os.path.join(base_dir, "data", "dbc")),
    }


def build_extract_command(action, client_path, client_build="5875"):
    """Build the docker compose command for data extraction."""
    step = action.replace("extract-", "") if "-" in action else "all"
    label = EXTRACT_LABELS.get(step, f"Extract ({step})")
    cmd = (
        f'docker compose run --rm '
        f'-e EXTRACT_STEPS={step} '
        f'-e CLIENT_BUILD={client_build} '
        f'-v "{client_path}:/wow:ro" '
        f'extract'
    )
    return label, cmd
