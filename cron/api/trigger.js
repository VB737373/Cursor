/** Будит GitHub Actions каждые 15 мин (Vercel Cron, бесплатно). */
export default async function handler(req, res) {
  const auth = req.headers.authorization;
  if (process.env.CRON_SECRET && auth !== `Bearer ${process.env.CRON_SECRET}`) {
    return res.status(401).json({ error: "unauthorized" });
  }

  const pat = process.env.GITHUB_PAT;
  if (!pat) {
    return res.status(500).json({ error: "GITHUB_PAT not set in Vercel env" });
  }

  const repo = process.env.GITHUB_REPO || "VB737373/Cursor";
  const r = await fetch(`https://api.github.com/repos/${repo}/dispatches`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${pat}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ event_type: "scan" }),
  });

  if (r.status === 204) {
    return res.status(200).json({ ok: true, message: "scan triggered" });
  }
  const text = await r.text();
  return res.status(r.status).json({ ok: false, status: r.status, body: text.slice(0, 300) });
}
