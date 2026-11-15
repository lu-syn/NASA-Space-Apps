// WhatsApp alert through the Twilio Sandbox.
// Secrets live only in Cloudflare (`wrangler secret put ...`), never in code
// or git. They are typed as optional here because `wrangler types` only sees
// .dev.vars, and a missing secret must mean "no alert", not a crash.

export type AlertEnv = Env & {
  TWILIO_ACCOUNT_SID?: string;
  TWILIO_AUTH_TOKEN?: string;
  TWILIO_FROM?: string; // e.g. "whatsapp:+14155238886" (Twilio Sandbox number)
  ALERT_TO?: string; // e.g. "whatsapp:+1..." (phone that joined the sandbox)
};

// No health numbers in the message: WhatsApp is not a private medical channel,
// and the dashboard (with context and the flight surgeon) is where details belong.
export const ALERT_TEXT =
  "ASTRO ALERT (simulated): crew status RED. Open the mission dashboard for details.";

export async function sendAlert(
  env: AlertEnv,
  row: { timestamp: unknown },
): Promise<boolean> {
  // Hook: one WhatsApp message via Twilio; true if Twilio accepted it. Never throws.
  const { TWILIO_ACCOUNT_SID: sid, TWILIO_AUTH_TOKEN: token,
          TWILIO_FROM: from, ALERT_TO: to } = env;
  if (!sid || !token || !from || !to) {
    console.error("alert: Twilio secrets missing, alert not sent");
    return false;
  }

  try {
    const response = await fetch(
      `https://api.twilio.com/2010-04-01/Accounts/${sid}/Messages.json`,
      {
        method: "POST",
        headers: {
          // Basic auth = base64("SID:TOKEN"), Twilio's standard login.
          Authorization: `Basic ${btoa(`${sid}:${token}`)}`,
          "Content-Type": "application/x-www-form-urlencoded",
        },
        // Twilio expects a form, not JSON.
        body: new URLSearchParams({ To: to, From: from, Body: ALERT_TEXT }),
      },
    );
    if (response.ok) {
      console.log(`alert: WhatsApp sent for reading ${String(row.timestamp)}`);
      return true;
    }
    // Twilio errors come back as JSON with a numeric code (e.g. 63015 =
    // recipient hasn't joined the sandbox). Log the code only, never secrets.
    const err = (await response.json().catch(() => ({}))) as { code?: number };
    console.error(`alert: Twilio refused (HTTP ${response.status}, code ${err.code ?? "?"})`);
    return false;
  } catch (e) {
    console.error(`alert: could not reach Twilio (${e instanceof Error ? e.message : e})`);
    return false;
  }
}
