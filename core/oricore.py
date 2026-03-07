import subprocess
from pathlib import Path
import time
import uuid
from rich import print
import yaml
from pathlib import Path
from datetime import datetime
import json


COMMAND_POLICY = {
    "ls": "safe",
    "cat": "safe",
    "echo": "safe",
    "pwd": "safe",
    "git": "safe",
    "python": "safe",

    # We'll add dangerous later only when we need them:
    # "rm": "dangerous",
}

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

INBOX_DIR = Path(__file__).resolve().parent.parent / "inbox"
INBOX_DIR.mkdir(exist_ok=True)
OUTBOX_DIR = Path(__file__).resolve().parent.parent / "outbox"
OUTBOX_DIR.mkdir(exist_ok=True)

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.yaml"


def load_config():
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r") as f:
            return yaml.safe_load(f)
    else:
        print("[yellow]No config found. Running with defaults.[/yellow]")
        return {}

def startup_banner():
    print("\n[bold green]Auri Core Initializing...[/bold green]")
    print(f"[cyan]Timestamp:[/cyan] {datetime.now()}")
    print("[cyan]Mode:[/cyan] Controlled Startup\n")

def main():
    startup_banner()
    config = load_config()

    print("[blue]Loaded Configuration:[/blue]")
    print(config if config else "Default configuration active.")

    result = submit_and_wait("ping", {}, config, timeout=30)
    if result:
        print("[bold green]Result received:[/bold green]")
        print(result)
    else:
        print("[red]No result (denied or timed out).[/red]")

def approval_gate(action_description):
    print(f"\n[yellow]Proposed Action:[/yellow] {action_description}")
    response = input("[bold]Approve? (y/n): [/bold]").strip().lower()

    if response == "y":
        print("[green]Action approved.[/green]")
        return True
    else:
        print("[red]Action denied.[/red]")
        return False

def log_event(message):
    log_file = LOG_DIR / "oricore.log"
    with open(log_file, "a") as f:
        f.write(f"{datetime.now()} - {message}\n")

def execute_command(args):
    command_name = args[0]
    risk = COMMAND_POLICY.get(command_name)

    if risk is None:
        print("[red]Command not allowed.[/red]")
        log_event(f"Blocked command: {command_name}")
        return None

    if risk == "dangerous":
        print("[bold red]Dangerous command requires extra confirmation.[/bold red]")
        confirm = input("Type EXACTLY 'I UNDERSTAND' to proceed: ").strip()
        if confirm != "I UNDERSTAND":
            print("[red]Dangerous command denied.[/red]")
            log_event(f"Dangerous command denied: {' '.join(args)}")
            return None

    print(f"[magenta]Executing:[/magenta] {' '.join(args)}")
    log_event(f"Executing: {' '.join(args)}")

    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            check=False
        )
        log_event(f"Output: {result.stdout.strip()}")
        if result.stderr:
            log_event(f"Error: {result.stderr.strip()}")
        return result.stdout
    except Exception as e:
        log_event(f"Execution failed: {str(e)}")
        return None  

def submit_job(action, params):
    job = {
        "job_id": str(uuid.uuid4()),
        "action": action,
        "params": params,
    }

    job_file = INBOX_DIR / f"{job['job_id']}.json"
    job_file.write_text(json.dumps(job, indent=2))
    print(f"Job submitted: {job['job_id']} action={action} file={job_file.name}")
    return job

def submit_and_wait(action, params, config, timeout=30):
    if config.get("approval_required", True):
        if not approval_gate(f"Submit job: {action} {params}"):
            print("[red]Job submission denied.[/red]")
            return None
    job = submit_job(action, params)
    print("[cyan]Waiting for result...[/cyan]")
    return wait_for_result(job["job_id"], timeout=timeout)

def wait_for_result(job_id, timeout=30):
    result_file = OUTBOX_DIR / f"{job_id}.json"
    start = time.time()
    while time.time() - start < timeout:
        if result_file.exists():
            return json.loads(result_file.read_text())
        time.sleep(1)
    return None

if __name__ == "__main__":
    main()


