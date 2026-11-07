# Running Chat2Cart in the background (macOS)

pm2 keeps two processes running: `chat2cart-listener` (WhatsApp, Node.js) and `chat2cart-agent`
(Python, started through `uv`). Both restart on their own after a crash, with a growing delay
(starting at 1 second) so a crash loop does not spin. Logs go to `logs/` in the repository.

pm2 and the sleep settings are for the Mac host only. The Docker image stays toolchain-only.

## Before you start

- Complete the setup first: `.env`, `rulebook.md`, `chat2cart login swiggy`, `chat2cart swiggy address`,
  and `chat2cart-wa login`. Both processes exit at start-up if something is missing; see the logs.
- `uv` must be on the PATH that pm2 uses. Check with `which uv`.

## Install and start

```bash
npm i -g pm2
```

```bash
npm run service:start
```

This builds the listener, then starts both apps. Check them with `pm2 status`.

```bash
npm run service:logs
```

```bash
npm run service:stop
```

`service:stop` stops both apps and keeps them registered. To start them again, run
`npm run service:start`. To remove them from pm2 completely: `pm2 delete ecosystem.config.cjs`.

## Start again after a reboot

Run these once, after `npm run service:start`:

```bash
pm2 startup
```

pm2 prints one `sudo env PATH=... pm2 startup launchd ...` command. Copy it and run it as printed.

```bash
pm2 save
```

After a reboot, `pm2 status` should show both apps as `online`. Run `pm2 save` again whenever you
change which apps are registered.

## Keep the Mac awake

A sleeping Mac stops both processes and misses the 07:00 IST overnight release.

- System Settings > Battery (or Energy) > Options: on power adapter, turn on
  "Prevent automatic sleeping on power adapter when the display is off".
- Or from a terminal:

```bash
sudo pmset -c sleep 0
```

`-c` applies to the power adapter only. Keep the Mac plugged in. Closing the lid still sleeps a
laptop unless it is connected to power and an external display.

## The 14-day phone rule

WhatsApp unlinks a linked device if the phone has not been online for about 14 days. Open WhatsApp on
the phone at least every 14 days. If the device is unlinked anyway, the listener reports
`logged_out` (see `chat2cart status`); run `chat2cart-wa logout`, then `chat2cart-wa login`.

## Manual check

1. `npm run service:start`, then `pm2 status` shows both apps `online`.
2. Kill each process (`pm2 status` shows its pid) and see it restart.
3. `npm run service:logs`, then `npm run service:stop`.
4. `pm2 startup`, `pm2 save`, reboot, and confirm both apps return.
