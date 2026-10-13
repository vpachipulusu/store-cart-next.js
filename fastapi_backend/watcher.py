import os
import re
import subprocess
import time
from threading import Timer

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

# Updated regex to include main.py, schemas.py, and all .py files in app/routes
WATCHER_REGEX_PATTERN = re.compile(r"(main\.py|schemas\.py|routes/.*\.py)$")
APP_PATH = "app"
FRONTEND_PATH = os.path.join("..", "nextjs-frontend")


class MyHandler(FileSystemEventHandler):
    def __init__(self):
        super().__init__()
        self.debounce_timer = None
        self.last_modified = 0

    def on_modified(self, event):
        if not event.is_directory and WATCHER_REGEX_PATTERN.search(
            os.path.relpath(event.src_path, APP_PATH)
        ):
            current_time = time.time()
            if current_time - self.last_modified > 1:
                self.last_modified = current_time
                if self.debounce_timer:
                    self.debounce_timer.cancel()
                self.debounce_timer = Timer(1.0, self.execute_command, [event.src_path])
                self.debounce_timer.start()

    def execute_command(self, file_path):
        print(f"File {file_path} has been modified and saved.")
        self.run_mypy_checks()
        if self.run_openapi_schema_generation():
            self.run_client_generation()

    def run_mypy_checks(self):
        """Run mypy type checks and print output."""
        print("Running mypy type checks...")
        result = subprocess.run(
            ["uv", "run", "mypy", "app"],
            capture_output=True,
            text=True,
            check=False,
        )
        print(result.stdout, result.stderr, sep="\n")
        print(
            "Type errors detected! We recommend checking the mypy output for "
            "more information on the issues."
            if result.returncode
            else "No type errors detected."
        )

    def run_openapi_schema_generation(self) -> bool:
        """Write nextjs-frontend/openapi.json; return whether it succeeded."""
        print("Proceeding with OpenAPI schema generation...")
        try:
            subprocess.run(
                [
                    "uv",
                    "run",
                    "python",
                    "-m",
                    "commands.generate_openapi_schema",
                ],
                check=True,
            )
            print("OpenAPI schema generation completed successfully.")
            return True
        except subprocess.CalledProcessError as e:
            print(f"An error occurred while generating OpenAPI schema: {e}")
            return False

    def run_client_generation(self) -> None:
        """Regenerate the TypeScript client from the fresh schema (dev only)."""
        print("Regenerating the TypeScript client...")
        try:
            subprocess.run(
                ["npm", "run", "generate:client"],
                cwd=FRONTEND_PATH,
                check=True,
                shell=os.name == "nt",  # npm is npm.cmd on Windows
            )
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            print(f"Client generation failed (run `npm run generate:client`): {e}")


if __name__ == "__main__":
    observer = Observer()
    observer.schedule(MyHandler(), APP_PATH, recursive=True)
    observer.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
