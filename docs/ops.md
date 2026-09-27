# pulse-scout — operations

How the digest gets built every day, how the phone reaches it, and how to take all of it out
again. Installed on this machine on 2026-09-27.

## What runs

| Unit | What | When |
|---|---|---|
| `pulse-scout.timer` → `pulse-scout.service` | `scripts/daily.sh` → `build_digest.py --skip-if-built` | daily 20:30, `Persistent=true` |
| `pulse-scout-web.service` | `scripts/serve.py --require-token`: API + built PWA on `0.0.0.0:8430` | always |
| `tailscale serve` (port 8443) | HTTPS in front of `127.0.0.1:8430`, tailnet only | always |

All three are free and local. The unit files live in `deploy/` and are copied to
`~/.config/systemd/user/` by the installer; linger is already on for this user, so they run
without an interactive login.

**Why 20:30.** Evening, per spec §6, and clear of equity-scout's weekday 18:00–18:45 jobs on
the same CPU. **Why `Persistent=true`.** WSL stops when Windows sleeps or shuts down; without it
a missed slot is simply lost. With it, the run happens at the next start.

**One digest per Berlin day.** `daily.sh` holds a `flock`, so a second start while one runs
exits at once, and `--skip-if-built` exits 0 before fetching anything when today's digest
already exists. Consequence of the catch-up: if the evening slot was missed and WSL starts the
next morning, the morning run builds *that* day's digest, and the evening slot that day skips.
Nothing is lost — the seen-set and the 72-hour window carry the items into the next build.

A run that fails (source outage above 30 %, validator rejection, model unreachable) exits
non-zero and writes nothing; the previous digest stays the latest, and from the second day
without a new one the PWA shows "Seit N Tagen kein neuer Digest".

## Install / update

```bash
uv sync
(cd frontend && npm ci && npm run build)     # the PWA the web unit serves
cp .env.example .env                         # then set PULSE_DASH_TOKEN (any long random string)
bash scripts/install_systemd.sh              # copies units, reloads, enables timer + web
tailscale serve --bg --https=8443 http://127.0.0.1:8430   # once; survives restarts
```

The installer is idempotent; run it again after editing anything in `deploy/`. It only enables
the web unit when `.env` has a token — the unit refuses to start without one, because
`tailscale serve` forwards the tailnet from 127.0.0.1 and a loopback bind would keep no one out.

After `npm run build`, restart the web unit if `frontend/dist` did not exist when it started:
`systemctl --user restart pulse-scout-web.service`.

## On the phone

The token: `grep PULSE_DASH_TOKEN .env` (on the laptop; never paste it anywhere else).

1. **Installable, readable offline (use this):**
   open `https://<host>.<tailnet>.ts.net:8443/?token=<TOKEN>` once in Chrome, with Tailscale
   on. The server sets an httpOnly cookie for 180 days and the page drops the token from the
   address bar. Then Chrome menu → *App installieren*. From then on the icon opens the digest;
   without a connection it shows the last one it loaded, labelled
   "Offline — gespeicherte Fassung, zuletzt geladen am …".
2. **Fallback, online only:** `http://<tailscale-ip>:8430/?token=<TOKEN>`. Reads fine, but
   plain HTTP is not a secure context, so there is no service worker: no offline copy, no
   install.

The `.ts.net` name does not resolve *on this WSL node itself* (Tailscale runs with
`--accept-dns=false` here); from the laptop, test with
`curl --resolve <host>.<tailnet>.ts.net:8443:<tailscale-ip> https://<host>.<tailnet>.ts.net:8443/api/digests`
(→ 401 without the token, which is correct).

## Everyday commands

```bash
systemctl --user list-timers pulse-scout.timer         # next and last run
journalctl --user -u pulse-scout.service -n 80         # the last build's output
journalctl --user -u pulse-scout-web.service -n 40     # the server
systemctl --user start pulse-scout.service             # run now (skips if today's exists)
tailscale serve status                                 # what the tailnet can reach
```

There is no "rebuild today's digest": a second build on the same day finds nothing new — the
seen-set already holds every item the first one fetched — and writes nothing, so the first
digest stays. That is the seen-set doing its job, not a failure.

## Undo (everything this project installed)

```bash
systemctl --user disable --now pulse-scout.timer pulse-scout-web.service
rm ~/.config/systemd/user/pulse-scout.service ~/.config/systemd/user/pulse-scout.timer \
   ~/.config/systemd/user/pulse-scout-web.service
systemctl --user daemon-reload
tailscale serve --https=8443 off
```

That leaves equity-scout's own `tailscale serve` on 443 untouched.
