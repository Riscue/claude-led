# GitLab pipeline → LED

A Python poller that hits the GitLab API every 15 s and mirrors each active
pipeline's status onto the strip. Best when you want a status LED on your
own machine reflecting shared CI.

## Setup

1. Install the state profile so `led` knows what `gitlab.running` means:

   ```bash
   cp states-gitlab.json ~/.claude-led/states/gitlab.json
   ```

2. Install dependencies:

   ```bash
   pip3 install requests
   ```

3. Run the poller:

   ```bash
   GITLAB_URL=https://gitlab.example.com \
   GITLAB_TOKEN=<personal-access-token-with-read_api> \
   PROJECTS=myteam/backend,myteam/frontend \
   ./poller.py
   ```

   `--once` polls a single time and exits (cron-friendly); the default loops
   every 15 s (`--interval N` to override).

The poller tracks which pipeline sessions it has seen and clears any that
disappear from the API response — no stale state lingers on the strip.
Priorities come from `states-gitlab.json`: `failed` (90) beats `running` (50)
beats `pending` (40) beats `success` (20).

## Files

| File                 | Purpose                                    |
|----------------------|--------------------------------------------|
| `poller.py`          | Workstation-side API poller                |
| `states-gitlab.json` | Copy to `~/.claude-led/states/gitlab.json` |
