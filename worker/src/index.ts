// Ground station Worker: the spacecraft (data.py) POSTs readings here after a
// simulated Earth-communication delay; the ground team can GET them all.
// Every request must carry the shared secret header X-Sync-Key.
//
// Env (env.DB, env.SYNC_KEY) is generated into worker-configuration.d.ts by
// `npm run types` from wrangler.jsonc and .dev.vars.

import { type AlertEnv, sendAlert } from "./alert";

// At most one WhatsApp alert per 30 minutes, however many red rows arrive.
const ALERT_COOLDOWN_MS = 30 * 60 * 1000;

// Shared row format (must match COLUMNS in data.py; never rename).
const COLUMNS = [
  "timestamp", "dose_rate", "total_dose", "heart_rate",
  "crp", "cortisol", "glucose", "reaction_ms", "mood",
] as const;
const NUMBER_COLUMNS = COLUMNS.slice(1);

// Extra ground-side column: alert color from rules.py on the ship (optional).
const STATUS_VALUES = ["green", "yellow", "red"];
const DB_COLUMNS = [...COLUMNS, "status"] as const;

type Reading = Record<(typeof DB_COLUMNS)[number], string | number | null>;

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    // Hook: check the key first, then route by path + method.
    if (!(await hasValidKey(request, env))) {
      return json({ error: "Missing or wrong X-Sync-Key" }, 401);
    }

    const { pathname } = new URL(request.url);
    if (pathname !== "/readings") {
      return json({ error: "Not found" }, 404);
    }
    if (request.method === "POST") return saveReading(request, env);
    if (request.method === "GET") return listReadings(env);
    return json({ error: "Use GET or POST" }, 405);
  },
} satisfies ExportedHandler<Env>;

async function hasValidKey(request: Request, env: Env): Promise<boolean> {
  // Hook: compare the header to the secret without leaking timing hints.
  const given = request.headers.get("X-Sync-Key");
  if (!env.SYNC_KEY || !given) return false; // no secret set = reject everyone
  const encoder = new TextEncoder();
  const a = encoder.encode(given);
  const b = encoder.encode(env.SYNC_KEY);
  // timingSafeEqual needs equal lengths; different lengths can't match anyway.
  if (a.byteLength !== b.byteLength) return false;
  return crypto.subtle.timingSafeEqual(a, b);
}

async function saveReading(request: Request, env: Env): Promise<Response> {
  // Hook: one JSON reading in -> one row in D1 (same timestamp = replace).
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return json({ error: "Body must be JSON" }, 400);
  }

  const result = parseReading(body);
  if (typeof result === "string") return json({ error: result }, 400);

  // INSERT OR REPLACE: if the ship retries a sync, we don't get duplicates.
  const placeholders = DB_COLUMNS.map(() => "?").join(", ");
  await env.DB.prepare(
    `INSERT OR REPLACE INTO readings (${DB_COLUMNS.join(", ")}) VALUES (${placeholders})`,
  )
    .bind(...DB_COLUMNS.map((col) => result[col]))
    .run();

  // The reading is safely stored before we try any alert, so a Twilio
  // problem can never lose data. `alert` tells the sender what happened.
  const alert = await maybeAlert(env, result);
  return json({ ok: true, timestamp: result.timestamp, alert }, 201);
}

async function maybeAlert(env: AlertEnv, row: Reading): Promise<string> {
  // Hook: WhatsApp only on a NEW red (previous not red) and not within 30 min.
  try {
    if (row.status !== "red") return "not_red";

    // The reading just before this one in mission time.
    const previous = await env.DB.prepare(
      "SELECT status FROM readings WHERE timestamp < ? ORDER BY timestamp DESC LIMIT 1",
    ).bind(row.timestamp).first<{ status: string | null }>();
    if (previous?.status === "red") return "previous_red"; // still the same red episode

    // Cooldown uses real time, so a re-sync of old data can't spam the phone.
    const last = await env.DB.prepare(
      "SELECT value FROM alert_log WHERE key = 'last_alert_at'",
    ).first<{ value: string }>();
    if (last && Date.now() - Date.parse(last.value) < ALERT_COOLDOWN_MS) {
      return "cooldown";
    }

    if (!(await sendAlert(env, row))) return "failed";
    // Only a delivered alert starts the cooldown; a failed one can be retried.
    await env.DB.prepare(
      "INSERT OR REPLACE INTO alert_log (key, value) VALUES ('last_alert_at', ?)",
    ).bind(new Date().toISOString()).run();
    return "sent";
  } catch (e) {
    // e.g. alert_log table missing: log it, but the reading is already saved.
    console.error(`alert check failed: ${e instanceof Error ? e.message : e}`);
    return "error";
  }
}

async function listReadings(env: Env): Promise<Response> {
  // Hook: every stored reading, oldest first (like load_mission()), plus status.
  const { results } = await env.DB.prepare(
    `SELECT ${DB_COLUMNS.join(", ")} FROM readings ORDER BY timestamp`,
  ).all();
  return json(results);
}

function parseReading(body: unknown): Reading | string {
  // Hook: check the shape; return the clean row, or an error message.
  if (typeof body !== "object" || body === null || Array.isArray(body)) {
    return "Body must be one JSON object (one reading)";
  }
  const input = body as Record<string, unknown>;

  const timestamp = input.timestamp;
  if (typeof timestamp !== "string" || Number.isNaN(Date.parse(timestamp))) {
    return "timestamp is required, e.g. \"2026-11-16 08:00:00\"";
  }

  const row = { timestamp } as Reading;
  for (const col of NUMBER_COLUMNS) {
    const value = input[col];
    // Missing/null is fine: blood and check columns are empty most hours.
    if (value === undefined || value === null) {
      row[col] = null;
    } else if (typeof value === "number" && Number.isFinite(value)) {
      row[col] = value;
    } else {
      return `${col} must be a number or null`;
    }
  }

  // status is optional; if given it must be one of the three colors.
  const status = input.status;
  if (status === undefined || status === null) {
    row.status = null;
  } else if (typeof status === "string" && STATUS_VALUES.includes(status)) {
    row.status = status;
  } else {
    return `status must be one of ${STATUS_VALUES.join(", ")} (or null)`;
  }
  return row;
}

function json(data: unknown, status = 200): Response {
  // Hook: every reply is JSON with the right header.
  return Response.json(data, { status });
}
