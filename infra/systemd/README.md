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

## Continuation snapshot

For an existing `monag-worktree-continuation.service`, install the
`atomic-snapshot.conf` drop-in from the adjacent directory. Bind the following
environment variables in the user unit to absolute paths from the installation.

| Variable | Value |
| --- | --- |
| `MONAG_EXECUTABLE` | Installed Monag supporting `resume --snapshot-file` |
| `MONAG_ROOT` | Workspace scanned by this timer |
| `MONAG_RESUME_SNAPSHOT` | Scheduled JSON file read by the continuation consumer |

Use the same pinned runtime for the scan and its history command. After
`systemctl --user daemon-reload`, let the timer run and wait for its oneshot
service to finish. Parse the snapshot, verify its `monag.resume/v1` schema,
workspace root and fresh observation timestamp, then inspect the expected
project. Monag replaces the complete document atomically. The unit sends
standard output to null so subsequent service commands cannot truncate it.
