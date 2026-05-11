import json
import os
import shutil
import socket
import subprocess
import tempfile
from datetime import datetime, timezone
from dataclasses import dataclass
import argparse
from typing import Optional


@dataclass(frozen=True)
class BenchmarkResult:
    rps: float
    avg_ms: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    cpu_avg_pct: Optional[float] = None
    cpu_max_pct: Optional[float] = None
    rss_max_mb: Optional[float] = None


@dataclass(frozen=True)
class PayloadSizes:
    rest_json_bytes: int
    grpc_protobuf_bytes: int


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


def _is_port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.2)
        return s.connect_ex((host, port)) == 0


def _wait_for_port(host: str, port: int, timeout_s: float) -> None:
    start = datetime.now(timezone.utc).timestamp()
    while True:
        if _is_port_open(host, port):
            return
        if datetime.now(timezone.utc).timestamp() - start > timeout_s:
            raise RuntimeError(f"Timed out waiting for {host}:{port}")


def _pid_listening_on_port(port: int) -> Optional[int]:
    try:
        out = subprocess.check_output(["lsof", "-ti", f"tcp:{port}"], text=True).strip()
    except Exception:
        return None
    if not out:
        return None
    first = out.splitlines()[0].strip()
    try:
        return int(first)
    except ValueError:
        return None


def _ps_snapshot(pid: int) -> Optional[tuple[float, int]]:
    try:
        out = subprocess.check_output(["ps", "-p", str(pid), "-o", "%cpu=,rss="], text=True).strip()
    except Exception:
        return None
    if not out:
        return None
    parts = out.split()
    if len(parts) < 2:
        return None
    try:
        cpu = float(parts[0])
        rss_kb = int(parts[1])
        return cpu, rss_kb
    except ValueError:
        return None


def _run_with_resource_sampling(cmd: list[str], pid: Optional[int], sample_interval_s: float) -> tuple[subprocess.CompletedProcess[str], Optional[tuple[float, float, float]]]:
    with tempfile.NamedTemporaryFile(mode="w+", suffix=".stdout.txt", delete=False) as stdout_f, tempfile.NamedTemporaryFile(
        mode="w+", suffix=".stderr.txt", delete=False
    ) as stderr_f:
        stdout_path = stdout_f.name
        stderr_path = stderr_f.name
        proc = subprocess.Popen(cmd, stdout=stdout_f, stderr=stderr_f, text=True)
        cpu_values: list[float] = []
        rss_values_kb: list[int] = []

        while proc.poll() is None:
            if pid is not None:
                snap = _ps_snapshot(pid)
                if snap is not None:
                    cpu, rss_kb = snap
                    cpu_values.append(cpu)
                    rss_values_kb.append(rss_kb)
            try:
                proc.wait(timeout=sample_interval_s)
            except subprocess.TimeoutExpired:
                pass

    try:
        with open(stdout_path, "r", encoding="utf-8", errors="replace") as f:
            stdout = f.read()
        with open(stderr_path, "r", encoding="utf-8", errors="replace") as f:
            stderr = f.read()
    finally:
        try:
            os.unlink(stdout_path)
        except OSError:
            pass
        try:
            os.unlink(stderr_path)
        except OSError:
            pass

    completed = subprocess.CompletedProcess(cmd, proc.returncode or 0, stdout, stderr)

    if not cpu_values or not rss_values_kb:
        return completed, None

    cpu_avg = sum(cpu_values) / len(cpu_values)
    cpu_max = max(cpu_values)
    rss_max_mb = max(rss_values_kb) / 1024.0
    return completed, (cpu_avg, cpu_max, rss_max_mb)


def _start_server_if_needed(kind: str, host: str, port: int) -> tuple[Optional[subprocess.Popen[str]], Optional[int]]:
    if _is_port_open(host, port):
        return None, _pid_listening_on_port(port)

    if kind == "grpc":
        proc = subprocess.Popen(["python3", "grpc_server.py"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)
        _wait_for_port(host, port, timeout_s=10)
        return proc, proc.pid

    if kind == "rest":
        proc = subprocess.Popen(["python3", "-m", "uvicorn", "rest_server:app", "--port", str(port)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)
        _wait_for_port(host, port, timeout_s=10)
        return proc, proc.pid

    raise ValueError("Unknown server kind")


def _stop_server(proc: Optional[subprocess.Popen[str]]) -> None:
    if proc is None:
        return
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=3)


def _compute_payload_sizes() -> PayloadSizes:
    rest_payload = {
        "name": "Payload-Size",
        "type": "TEMPERATURE",
        "location": "BenchLab",
        "unit": "C",
        "status": "ACTIVE",
        "last_value": 1.23,
    }
    rest_json = json.dumps(rest_payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    import sensor_pb2

    msg = sensor_pb2.CreateSensorRequest(
        name="Payload-Size",
        type=sensor_pb2.TEMPERATURE,
        location="BenchLab",
        unit="C",
        status=sensor_pb2.ACTIVE,
        last_value=1.23,
    )
    pb = msg.SerializeToString()

    return PayloadSizes(rest_json_bytes=len(rest_json), grpc_protobuf_bytes=len(pb))


def _ghz_base_cmd() -> list[str]:
    _require_binary("ghz")
    return [
        "ghz",
        "--insecure",
        "--format",
        "json",
        "--import-paths",
        "shared/proto",
        "--proto",
        "sensor.proto",
    ]


def _run_ghz_call(*, call: str, data_json: str, concurrency: int, total: Optional[int] = None, duration: Optional[str] = None) -> BenchmarkResult:
    cmd = _ghz_base_cmd()
    cmd += ["--call", call, "-c", str(concurrency), "-d", data_json]
    if duration is not None:
        cmd += ["-z", duration]
    else:
        cmd += ["-n", str(total or 1000)]
    cmd.append("localhost:50051")

    server_proc, pid = _start_server_if_needed(kind="grpc", host="127.0.0.1", port=50051)
    try:
        completed, stats = _run_with_resource_sampling(cmd, pid=pid, sample_interval_s=0.2)
        if completed.returncode != 0:
            raise RuntimeError(f"ghz failed:\n{completed.stderr or completed.stdout}")
    finally:
        _stop_server(server_proc)

    data = json.loads(completed.stdout)

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
        cpu_avg_pct=stats[0] if stats else None,
        cpu_max_pct=stats[1] if stats else None,
        rss_max_mb=stats[2] if stats else None,
    )


def _grpc_seed_sensor_id() -> str:
    import grpc
    import sensor_pb2
    import sensor_pb2_grpc

    channel = grpc.insecure_channel("127.0.0.1:50051")
    stub = sensor_pb2_grpc.SensorServiceStub(channel)
    resp = stub.CreateSensor(
        sensor_pb2.CreateSensorRequest(
            name="Seed",
            type=sensor_pb2.TEMPERATURE,
            location="BenchLab",
            unit="C",
            status=sensor_pb2.ACTIVE,
            last_value=1.0,
        ),
        timeout=5,
    )
    channel.close()
    return resp.id


def _run_ghz_create_sensor() -> BenchmarkResult:
    return _run_ghz_call(
        call="benchlab.sensor.v1.SensorService.CreateSensor",
        data_json='{"name":"GHZ-Write","type":"TEMPERATURE","location":"BenchLab","unit":"C","status":"ACTIVE","lastValue":1.23}',
        concurrency=10,
        total=1000,
    )


def _run_ghz_get_sensor(*, sensor_id: str, concurrency: int, total: Optional[int] = None, duration: Optional[str] = None) -> BenchmarkResult:
    return _run_ghz_call(
        call="benchlab.sensor.v1.SensorService.GetSensor",
        data_json=json.dumps({"id": sensor_id}, separators=(",", ":"), ensure_ascii=False),
        concurrency=concurrency,
        total=total,
        duration=duration,
    )


def _run_k6(*, scenario: str, vus: int, iterations: int) -> BenchmarkResult:
    _require_binary("k6")

    with tempfile.NamedTemporaryFile(mode="w+", suffix=".json", delete=False) as f:
        summary_path = f.name

    cmd = [
        "k6",
        "run",
        "-e",
        f"SCENARIO={scenario}",
        "-e",
        f"VUS={vus}",
        "-e",
        f"ITERATIONS={iterations}",
        "--summary-export",
        summary_path,
        "k6_rest.js",
    ]

    server_proc, pid = _start_server_if_needed(kind="rest", host="127.0.0.1", port=8000)
    try:
        completed, stats = _run_with_resource_sampling(cmd, pid=pid, sample_interval_s=0.2)
        if completed.returncode != 0:
            raise RuntimeError(f"k6 failed:\n{completed.stderr or completed.stdout}")
    finally:
        _stop_server(server_proc)

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

    return BenchmarkResult(
        rps=rps,
        avg_ms=avg_ms,
        p50_ms=p50_ms,
        p95_ms=p95_ms,
        p99_ms=p99_ms,
        cpu_avg_pct=stats[0] if stats else None,
        cpu_max_pct=stats[1] if stats else None,
        rss_max_mb=stats[2] if stats else None,
    )


def _format_table_rows(grpc_result: BenchmarkResult, rest_result: BenchmarkResult) -> list[tuple[str, BenchmarkResult]]:
    return [("gRPC (ghz)", grpc_result), ("REST (k6)", rest_result)]


def _print_console_table(*, title: str, grpc_result: BenchmarkResult, rest_result: BenchmarkResult) -> None:
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

    print(title)
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


def _append_perf_section(lines: list[str], *, title: str, grpc_result: BenchmarkResult, rest_result: BenchmarkResult) -> None:
    rows = _format_table_rows(grpc_result, rest_result)
    lines.append(f"## Scenario: {title}")
    lines.append("")
    lines.append("| Test | RPS | Avg (ms) | p50 (ms) | p95 (ms) | p99 (ms) |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for test, r in rows:
        lines.append(f"| {test} | {r.rps:.2f} | {r.avg_ms:.2f} | {r.p50_ms:.2f} | {r.p95_ms:.2f} | {r.p99_ms:.2f} |")
    lines.append("")
    lines.append("| Test | CPU avg (%) | CPU max (%) | RSS max (MB) |")
    lines.append("|---|---:|---:|---:|")
    for test, r in rows:
        cpu_avg = f"{r.cpu_avg_pct:.2f}" if r.cpu_avg_pct is not None else "n/a"
        cpu_max = f"{r.cpu_max_pct:.2f}" if r.cpu_max_pct is not None else "n/a"
        rss_max = f"{r.rss_max_mb:.2f}" if r.rss_max_mb is not None else "n/a"
        lines.append(f"| {test} | {cpu_avg} | {cpu_max} | {rss_max} |")
    lines.append("")


def _render_markdown(*, write_grpc: BenchmarkResult, write_rest: BenchmarkResult, read_grpc: BenchmarkResult, read_rest: BenchmarkResult, ramp_grpc: BenchmarkResult, ramp_rest: BenchmarkResult) -> str:
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload = _compute_payload_sizes()
    ratio = payload.rest_json_bytes / payload.grpc_protobuf_bytes if payload.grpc_protobuf_bytes else 0.0

    lines = []
    lines.append(f"Generated at: {ts}")
    lines.append("")
    lines.append("## Payload sizes (application payload only)")
    lines.append("")
    lines.append("| Format | What we measure | Bytes |")
    lines.append("|---|---|---:|")
    lines.append(f"| REST JSON | POST /sensors body | {payload.rest_json_bytes} |")
    lines.append(f"| gRPC Protobuf | CreateSensorRequest serialized bytes | {payload.grpc_protobuf_bytes} |")
    lines.append(f"| Ratio | JSON / Protobuf | {ratio:.2f}× |")
    lines.append("")
    lines.append("## Method")
    lines.append("")
    lines.append("- Payload: JSON bytes for REST POST body vs Protobuf bytes for CreateSensorRequest (no HTTP/1.1 or HTTP/2 headers included).")
    lines.append("- Resources: server process %CPU and RSS sampled every 200ms during each load test run (macOS ps).")
    lines.append("")
    _append_perf_section(lines, title="Write (Create/POST)", grpc_result=write_grpc, rest_result=write_rest)
    _append_perf_section(lines, title="Read (Get/GET by id)", grpc_result=read_grpc, rest_result=read_rest)
    _append_perf_section(lines, title="Ramp (Progressive load)", grpc_result=ramp_grpc, rest_result=ramp_rest)
    lines.append("## RGESN (Éco-conception) mapping")
    lines.append("")
    lines.append("- Volume de données échangées: le tableau “Payload sizes” alimente directement l’analyse réseau (moins d’octets => moins d’énergie côté réseau).")
    lines.append("- Sollicitation des ressources: le tableau “Resource consumption” alimente l’analyse CPU/RAM (plus de CPU => plus d’énergie et potentiellement plus de matériel requis).")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-md", default="watch.md")
    args = parser.parse_args()

    write_grpc = _run_ghz_create_sensor()
    write_rest = _run_k6(scenario="unit_write", vus=10, iterations=1000)
    _print_console_table(title="Write (Create/POST)", grpc_result=write_grpc, rest_result=write_rest)

    server_proc, _ = _start_server_if_needed(kind="grpc", host="127.0.0.1", port=50051)
    try:
        seeded_id = _grpc_seed_sensor_id()
    finally:
        _stop_server(server_proc)

    read_grpc = _run_ghz_get_sensor(sensor_id=seeded_id, concurrency=10, total=1000)
    read_rest = _run_k6(scenario="unit_read", vus=10, iterations=1000)
    _print_console_table(title="Read (Get/GET by id)", grpc_result=read_grpc, rest_result=read_rest)

    ramp_grpc = _run_ghz_get_sensor(sensor_id=seeded_id, concurrency=100, duration="90s")
    ramp_rest = _run_k6(scenario="progressive", vus=1, iterations=1)
    _print_console_table(title="Ramp (Progressive load)", grpc_result=ramp_grpc, rest_result=ramp_rest)

    md = _render_markdown(
        write_grpc=write_grpc,
        write_rest=write_rest,
        read_grpc=read_grpc,
        read_rest=read_rest,
        ramp_grpc=ramp_grpc,
        ramp_rest=ramp_rest,
    )
    with open(args.output_md, "w", encoding="utf-8") as f:
        f.write(md)


if __name__ == "__main__":
    main()
