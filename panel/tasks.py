"""Background task execution with SSE output streaming."""

import queue
import subprocess
import threading
import time
import uuid


class Task:
    """A single background command execution."""

    def __init__(self, task_id, name, cmd, cwd):
        self.id = task_id
        self.name = name
        self.cmd = cmd
        self.cwd = cwd
        self.output = []
        self.status = "running"
        self.exit_code = None
        self.started_at = time.time()
        self._subscribers = []
        self._lock = threading.Lock()

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            process = subprocess.Popen(
                self.cmd,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=self.cwd,
                text=True,
                bufsize=1,
            )
            for line in iter(process.stdout.readline, ""):
                self._broadcast(line)
            process.wait()
            self.exit_code = process.returncode
            self.status = "success" if self.exit_code == 0 else "failed"
        except Exception as e:
            self._broadcast(f"Error: {e}\n")
            self.status = "failed"
        finally:
            with self._lock:
                for q in self._subscribers:
                    q.put(None)

    def _broadcast(self, line):
        with self._lock:
            self.output.append(line)
            for q in self._subscribers:
                q.put(line)

    def subscribe(self):
        """Return a queue that receives all output (past and future)."""
        q = queue.Queue()
        with self._lock:
            for line in self.output:
                q.put(line)
            if self.status != "running":
                q.put(None)
            else:
                self._subscribers.append(q)
        return q


class TaskStore:
    """Registry of all tasks."""

    def __init__(self):
        self._tasks = {}

    def create(self, name, cmd, cwd):
        task_id = uuid.uuid4().hex[:8]
        task = Task(task_id, name, cmd, cwd)
        self._tasks[task_id] = task
        task.start()
        return task

    def get(self, task_id):
        return self._tasks.get(task_id)

    def recent(self, limit=20):
        return sorted(
            self._tasks.values(), key=lambda t: t.started_at, reverse=True
        )[:limit]
