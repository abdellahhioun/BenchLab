Generated at: 2026-04-27T07:58:49+00:00

## Payload sizes (application payload only)

| Format | What we measure | Bytes |
|---|---|---:|
| REST JSON | POST /sensors body | 113 |
| gRPC Protobuf | CreateSensorRequest serialized bytes | 40 |
| Ratio | JSON / Protobuf | 2.83× |

## Method

- Payload: JSON bytes for REST POST body vs Protobuf bytes for CreateSensorRequest (no HTTP/1.1 or HTTP/2 headers included).
- Resources: server process %CPU and RSS sampled every 200ms during each load test run (macOS ps).

## Scenario: Write (Create/POST)

| Test | RPS | Avg (ms) | p50 (ms) | p95 (ms) | p99 (ms) |
|---|---:|---:|---:|---:|---:|
| gRPC (ghz) | 4926.28 | 1.79 | 0.47 | 4.20 | 21.25 |
| REST (k6) | 2422.72 | 3.94 | 2.25 | 10.33 | 37.72 |

| Test | CPU avg (%) | CPU max (%) | RSS max (MB) |
|---|---:|---:|---:|
| gRPC (ghz) | 21.80 | 37.50 | 31.30 |
| REST (k6) | 63.18 | 96.40 | 43.12 |

## Scenario: Read (Get/GET by id)

| Test | RPS | Avg (ms) | p50 (ms) | p95 (ms) | p99 (ms) |
|---|---:|---:|---:|---:|---:|
| gRPC (ghz) | 5828.83 | 1.65 | 1.57 | 2.43 | 3.24 |
| REST (k6) | 2875.62 | 3.34 | 3.13 | 4.40 | 11.38 |

| Test | CPU avg (%) | CPU max (%) | RSS max (MB) |
|---|---:|---:|---:|
| gRPC (ghz) | 0.00 | 0.00 | 28.23 |
| REST (k6) | 84.17 | 123.40 | 43.25 |

## Scenario: Ramp (Progressive load)

| Test | RPS | Avg (ms) | p50 (ms) | p95 (ms) | p99 (ms) |
|---|---:|---:|---:|---:|---:|
| gRPC (ghz) | 5940.97 | 16.80 | 16.49 | 18.84 | 22.17 |
| REST (k6) | 2976.74 | 11.84 | 9.26 | 30.00 | 33.52 |

| Test | CPU avg (%) | CPU max (%) | RSS max (MB) |
|---|---:|---:|---:|
| gRPC (ghz) | 310.87 | 330.90 | 35.50 |
| REST (k6) | 171.77 | 212.20 | 50.50 |

## RGESN (Éco-conception) mapping

- Volume de données échangées: le tableau “Payload sizes” alimente directement l’analyse réseau (moins d’octets => moins d’énergie côté réseau).
- Sollicitation des ressources: le tableau “Resource consumption” alimente l’analyse CPU/RAM (plus de CPU => plus d’énergie et potentiellement plus de matériel requis).
