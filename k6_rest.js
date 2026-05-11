import http from "k6/http";
import { check } from "k6";

const BASE_URL = __ENV.BASE_URL || "http://127.0.0.1:8000";
const SCENARIO = __ENV.SCENARIO || "unit_read";

export const options = (() => {
  if (SCENARIO === "unit_write") {
    return {
      vus: Number(__ENV.VUS || 1),
      iterations: Number(__ENV.ITERATIONS || 200),
      summaryTrendStats: ["avg", "med", "p(50)", "p(90)", "p(95)", "p(99)", "min", "max"],
      thresholds: {
        http_req_failed: ["rate==0"],
      },
    };
  }

  if (SCENARIO === "progressive") {
    return {
      stages: [
        { duration: "20s", target: 10 },
        { duration: "20s", target: 25 },
        { duration: "20s", target: 50 },
        { duration: "20s", target: 100 },
        { duration: "10s", target: 0 },
      ],
      summaryTrendStats: ["avg", "med", "p(50)", "p(90)", "p(95)", "p(99)", "min", "max"],
      thresholds: {
        http_req_failed: ["rate<0.01"],
      },
    };
  }

  return {
    vus: Number(__ENV.VUS || 1),
    iterations: Number(__ENV.ITERATIONS || 500),
    summaryTrendStats: ["avg", "med", "p(50)", "p(90)", "p(95)", "p(99)", "min", "max"],
    thresholds: {
      http_req_failed: ["rate==0"],
    },
  };
})();

export function setup() {
  if (SCENARIO === "unit_read" || SCENARIO === "progressive") {
    const payload = JSON.stringify({
      name: `K6-Seed-${Date.now()}`,
      type: "TEMPERATURE",
      location: "BenchLab",
      unit: "C",
      status: "ACTIVE",
      last_value: 42.0,
    });

    const res = http.post(`${BASE_URL}/sensors`, payload, {
      headers: { "Content-Type": "application/json" },
    });

    check(res, { "seed create: 200": (r) => r.status === 200 });

    const body = res.json();
    return { sensorId: body.id };
  }

  return {};
}

export default function (data) {
  if (SCENARIO === "unit_write") {
    const payload = JSON.stringify({
      name: `K6-Write-${__VU}-${__ITER}-${Date.now()}`,
      type: "PRESSURE",
      location: "BenchLab",
      unit: "bar",
      status: "ACTIVE",
      last_value: 12.34,
    });

    const res = http.post(`${BASE_URL}/sensors`, payload, {
      headers: { "Content-Type": "application/json" },
    });

    check(res, { "write: 200": (r) => r.status === 200 });
    return;
  }

  const res = http.get(`${BASE_URL}/sensors/${data.sensorId}`);
  check(res, { "read: 200": (r) => r.status === 200 });
}
