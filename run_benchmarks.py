import json
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from dataclasses import dataclass
import argparse


@dataclass(frozen=True)
class BenchmarkResult:
    rps: float
    avg_ms: float
    p50_ms: float
    p95_ms: float
    p99_ms: float


def _require_binary(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"Missing required tool: {name}")
    return path


def _percentile_from_ghz_ns(data: dict, percentile: int) -> float:
    for item in data.get("latencyDistribution", []):
        if float(item.get("percentage", -1)) == percentile:
            return float(item["latency"])
    raise RuntimeError(f"ghz output did not include p{percentile} latency")


def _run_ghz_create_sensor() -> BenchmarkResult:
    _require_binary("ghz")

    cmd = [
        "ghz",
        "--insecure",
        "-n",
        "1000",
        "-c",
        "10",
        "--format",
        "json",
        "--import-paths",
        "shared/proto",
        "--proto",
        "sensor.proto",
        "--call",
        "benchlab.sensor.v1.SensorService.CreateSensor",
        "-d",
        '{"name":"GHZ-Write","type":"TEMPERATURE","location":"BenchLab","unit":"C","status":"ACTIVE","lastValue":1.23}',
        "localhost:50051",
    ]

    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"ghz failed:\n{proc.stderr or proc.stdout}")

    data = json.loads(proc.stdout)

    rps = float(data["rps"])
    avg_ns = float(data["average"])
    p50_ns = _percentile_from_ghz_ns(data, 50)
    p95_ns = _percentile_from_ghz_ns(data, 95)
    p99_ns = _percentile_from_ghz_ns(data, 99)

    return BenchmarkResult(
        rps=rps,
        avg_ms=avg_ns / 1_000_000,
        p50_ms=p50_ns / 1_000_000,
        p95_ms=p95_ns / 1_000_000,
        p99_ms=p99_ns / 1_000_000,
    )


def _run_k6_rest_post_sensors() -> BenchmarkResult:
    _require_binary("k6")

    with tempfile.NamedTemporaryFile(mode="w+", suffix=".json", delete=False) as f:
        summary_path = f.name

    cmd = [
        "k6",
        "run",
        "-e",
        "SCENARIO=unit_write",
        "-e",
        "VUS=10",
        "-e",
        "ITERATIONS=1000",
        "--summary-export",
        summary_path,
        "k6_rest.js",
    ]

    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"k6 failed:\n{proc.stderr or proc.stdout}")

    with open(summary_path, "r", encoding="utf-8") as f:
        summary = json.load(f)

    metrics = summary.get("metrics", {})
    http_reqs = metrics.get("http_reqs", {})
    http_req_duration = metrics.get("http_req_duration", {})

    rps = float(http_reqs["rate"])
    avg_ms = float(http_req_duration["avg"])
    p50_ms = float(http_req_duration.get("p(50)", http_req_duration["med"]))
    p95_ms = float(http_req_duration["p(95)"])
    p99_ms = float(http_req_duration["p(99)"])
    return BenchmarkResult(rps=rps, avg_ms=avg_ms, p50_ms=p50_ms, p95_ms=p95_ms, p99_ms=p99_ms)


def _format_table_rows(grpc_result: BenchmarkResult, rest_result: BenchmarkResult) -> list[tuple[str, BenchmarkResult]]:
    return [
        ("gRPC (ghz) CreateSensor", grpc_result),
        ("REST (k6)  POST /sensors", rest_result),
    ]


def _print_console_table(grpc_result: BenchmarkResult, rest_result: BenchmarkResult) -> None:
    rows = _format_table_rows(grpc_result, rest_result)
    headers = ("Test", "RPS", "Avg (ms)", "p50 (ms)", "p95 (ms)", "p99 (ms)")

    test_width = max(len(headers[0]), max(len(r[0]) for r in rows))
    header_line = (
        f"{headers[0].ljust(test_width)} | "
        f"{headers[1].rjust(10)} | "
        f"{headers[2].rjust(8)} | "
        f"{headers[3].rjust(8)} | "
        f"{headers[4].rjust(8)} | "
        f"{headers[5].rjust(8)}"
    )

    print(header_line)
    print("-" * len(header_line))
    for test, r in rows:
        print(
            f"{test.ljust(test_width)} | "
            f"{r.rps:>10.2f} | "
            f"{r.avg_ms:>8.2f} | "
            f"{r.p50_ms:>8.2f} | "
            f"{r.p95_ms:>8.2f} | "
            f"{r.p99_ms:>8.2f}"
        )


def _render_markdown(grpc_result: BenchmarkResult, rest_result: BenchmarkResult) -> str:
    rows = _format_table_rows(grpc_result, rest_result)
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")

    lines = []
    lines.append(f"Generated at: {ts}")
    lines.append("")
    lines.append("| Test | RPS | Avg (ms) | p50 (ms) | p95 (ms) | p99 (ms) |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for test, r in rows:
        lines.append(f"| {test} | {r.rps:.2f} | {r.avg_ms:.2f} | {r.p50_ms:.2f} | {r.p95_ms:.2f} | {r.p99_ms:.2f} |")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-md", default="watch.md")
    args = parser.parse_args()

    grpc_result = _run_ghz_create_sensor()
    rest_result = _run_k6_rest_post_sensors()

    _print_console_table(grpc_result=grpc_result, rest_result=rest_result)

    md = _render_markdown(grpc_result=grpc_result, rest_result=rest_result)
    with open(args.output_md, "w", encoding="utf-8") as f:
        f.write(md)


if __name__ == "__main__":
    main()
