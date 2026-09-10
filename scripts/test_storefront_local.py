"""Run integration tests in a private, disposable PostgreSQL cluster on Windows.

Uses installed PostgreSQL binaries; never connects to the application's .env DB.
The cluster is stopped in finally and retained in ignored .pg-test for diagnosis.
"""

import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
from urllib.request import urlopen


def main():
    root = Path(__file__).resolve().parents[1]
    binary = Path(os.environ.get("PG_BIN", r"C:\Program Files\PostgreSQL\18\bin"))
    work = root / ".pg-test" / secrets.token_hex(6)
    work.mkdir(parents=True)
    password = secrets.token_hex(24)
    password_file = work / "password.txt"
    password_file.write_text(password)
    data = work / "data"
    port = "55439"
    environment = {**os.environ, "PGPASSWORD": password}
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}

    def run(args, cwd=root):
        output = work / "command.log"
        with output.open("w", encoding="utf-8") as log:
            result = subprocess.run(
                [str(x) for x in args],
                cwd=cwd,
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
                **flags,
            )
        print(output.read_text(encoding="utf-8", errors="replace"), flush=True)
        result.check_returncode()

    run(
        [
            binary / "initdb.exe",
            "-D",
            data,
            "-U",
            "sf_test",
            "--auth=scram-sha-256",
            "--pwfile",
            password_file,
            "--encoding=UTF8",
            "--locale=C",
        ]
    )
    password_file.unlink()
    started = False
    try:
        run(
            [
                binary / "pg_ctl.exe",
                "-D",
                data,
                "-l",
                work / "server.log",
                "-o",
                f"-h 127.0.0.1 -p {port}",
                "-w",
                "start",
            ]
        )
        started = True
        run(
            [
                binary / "createdb.exe",
                "-h",
                "127.0.0.1",
                "-p",
                port,
                "-U",
                "sf_test",
                "sf_test_storefront",
            ]
        )
        url = f"postgresql+asyncpg://sf_test:{password}@127.0.0.1:{port}/sf_test_storefront"
        environment.update(
            DATABASE_URL=url,
            DATABASE_MIGRATION_URL=url,
            TEST_DATABASE_URL=url,
            ENVIRONMENT="dev",
            AUTH0_DOMAIN="example.auth0.com",
            AUTH0_AUDIENCE="https://test.example",
            REQUESTS_PER_MINUTE="100000",
            SANDBOX_BROWSER_PAYMENTS_ENABLED="true",
            PAYMENT_PROVIDER="sandbox",
            TOKEN_SIGNING_SECRET=secrets.token_hex(32),
            SANDBOX_PAYMENT_SECRET=secrets.token_hex(32),
            APPLICATIONINSIGHTS_CONNECTION_STRING="",
            SEMANTIC_SEARCH_ENABLED="false",
        )
        run([sys.executable, "-m", "alembic", "upgrade", "head"])
        run([sys.executable, "-m", "pytest", "-q"])
        run(
            [
                sys.executable,
                "-m",
                "scripts.export_openapi",
                ".test-artifacts/openapi.json",
            ]
        )
        run([sys.executable, "-m", "scripts.seed_apparel"])
        run([sys.executable, "-m", "scripts.seed_inventory"])
        run([sys.executable, "-m", "scripts.seed_flagship"])
        environment["TEST_API_URL"] = "http://127.0.0.1:18000/api/v1"
        with (work / "api.log").open("w") as log:
            api = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "app.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "18000",
                ],
                cwd=root,
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
                **flags,
            )
            try:
                for _ in range(60):
                    try:
                        with urlopen("http://127.0.0.1:18000/health/live", timeout=1):
                            break
                    except OSError:
                        if api.poll() is not None:
                            raise RuntimeError(
                                "Test API failed to start; see .pg-test API log"
                            )
                        time.sleep(0.5)
                else:
                    raise RuntimeError("Test API startup timed out")
                run(
                    ["node", "scripts/test-api.mjs"],
                    cwd=root.parent / "special-affair-webapp",
                )
                if "--serve" in sys.argv:
                    stop = root / ".test-artifacts" / "stop-storefront"
                    stop.unlink(missing_ok=True)
                    print(
                        "TEST API READY: http://127.0.0.1:18000; create .test-artifacts/stop-storefront to stop",
                        flush=True,
                    )
                    while not stop.exists():
                        time.sleep(1)
            finally:
                api.terminate()
                api.wait(timeout=15)
    finally:
        if started:
            run([binary / "pg_ctl.exe", "-D", data, "-m", "fast", "-w", "stop"])


if __name__ == "__main__":
    main()
