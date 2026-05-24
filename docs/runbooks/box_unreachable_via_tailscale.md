# Box unreachable via Tailscale — fallback recovery

**Authored:** 2026-05-24 (content-correctness sprint, operator-departure prep)
**When to suspect:**

- SSH to `aaats@100.95.126.39` times out, BUT
- Telegram alerts are still firing from `aaats-cron-alert.sh` AND/OR
- GitHub Actions L1 liveness shows commits arriving from origin

That combination means the box is alive and the network egress works; only
the Tailscale layer between operator workstation and the box is broken.

If Telegram is also silent for >30 min, this is a true box outage — escalate
to Contabo support (last step below) rather than Tailscale recovery.

## Step 1 — Confirm direction of breakage

```bash
# From operator workstation:
tailscale status         # any node showing offline? incl. self
ping -c 4 100.95.126.39
tailscale ping 100.95.126.39
```

If `tailscale status` shows the operator workstation itself offline, the
problem is local (re-auth needed on this side, not the box). Run:

```bash
tailscale up --auth-key=<saved-key>   # or re-auth via tailscale up + browser
```

If only the box appears offline in `tailscale status` while other nodes are
fine, proceed to Step 2.

## Step 2 — Contabo VNC console fallback

The box runs Contabo VPS. Contabo provides a browser-based VNC console that
bypasses ssh + tailscale entirely.

**URL:** Contabo customer panel → "Cloud VPS" → vmi3275738 → "VNC Console"
(operator confirms the exact URL + login flow on first use — bookmarked
under "Tailscale-down recovery" in browser).

**Credentials:** root password + the second-factor TOTP. Both stored in
operator's password manager under "Contabo / aaats VPS root". DO NOT commit
either to the repo.

Once VNC console is open, log in as root. Then check Tailscale:

```bash
systemctl status tailscaled
journalctl -u tailscaled --since "1 hour ago" | tail -50
```

If tailscaled is dead, restart it:

```bash
systemctl restart tailscaled
sleep 5
tailscale status   # should show this node and the operator workstation
```

If the daemon is up but the connection is unauthorized (auth expired),
re-auth via:

```bash
tailscale up   # prints a URL; copy it, open in operator browser, complete login
```

After Tailscale is restored, verify from the operator workstation:

```bash
ssh aaats@100.95.126.39 'hostname'   # should return vmi3275738
```

## Step 3 — Contabo console also unreachable

If even the Contabo VNC console fails to load, the VPS itself is the
problem (host failure, network at Contabo, billing issue, etc).

Open a support ticket via the Contabo panel using this template:

```
Subject: VPS vmi3275738 unreachable via SSH and VNC console

Last successful SSH:       <YYYY-MM-DD HH:MM UTC>
Last GitHub Actions push:  <SHA, time>  (verify by going to
                            github.com/Puneethmp/AAATS/actions)
Symptoms:                  SSH timeout from multiple networks. Tailscale
                            shows node offline. VNC console returns
                            <error message or "unreachable">.
Requested:                 (1) confirm VPS is running, (2) reboot if hung,
                           (3) provide any host-side incident timing.
```

If the bot is suspected halted during the outage, the L1 GitHub Actions
liveness alert will already have fired to Telegram. The AAATS bot is
designed to halt safely if it cannot push: open positions continue to
mark-to-market against last cached prices; new entries are blocked by the
in-cron heartbeat check. NO real money is at risk during a Contabo outage
because the entire D.5 soak window is paper-only.

## Step 4 — After recovery

Run the standard post-outage checks (mirrors `auto_cron_recovery.md`):

```bash
ssh aaats@100.95.126.39 'bash /home/aaats/bin/aaats-diagnose.sh --quick'
```

The diagnose script reports container health, heartbeat freshness, recent
trade activity, and the state of all 4 cron-resilience layers (L1-L4) +
the 6 content-correctness layers (L5-L10).
