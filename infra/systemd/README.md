# Scheduled URTLog triage

Each systemd user timer runs Monag for one URTLog producer. Use the principal recorded by Reflex and the directory containing its `urilog.sqlite3`. Reuse that principal's profile for each cycle so that an OQLLM receipt or a recovered Reflex episode clears the corresponding alarm.

Place the service and timer templates in the target user's unit directory. Copy `triage.env.example` to `~/.config/monag/urtlog-triage/<profile>.env` and fill in the executable, workspace, journal directory and principal from the deployment inventory. Set the bridge health URL when that installation expects Planfile events. The workspace should be a parent of repositories. Depth zero keeps each observation focused on the runtime probes and avoids traversing the repository fleet.

After the files are installed for the target user, verify the profile once, then start the timer. Replace `production` with the chosen profile name.

```sh
systemctl --user daemon-reload
systemctl --user start monag-urtlog-triage@production.service
journalctl --user -u monag-urtlog-triage@production.service -o cat
systemctl --user enable --now monag-urtlog-triage@production.timer
systemctl --user list-timers monag-urtlog-triage@production.timer
```

The journal contains a JSON triage report on each run. Inspect its recommendations for the episode, deadline and retry status. A missing journal or an unobserved producer also yields a recommendation. A successful systemd exit means the scan ran. Read the recommendations to determine the health of the route. The timer reruns a minute after the service finishes.
