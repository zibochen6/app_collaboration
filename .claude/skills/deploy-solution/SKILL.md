---
name: deploy-solution
description: Deploy an IoT solution via the provisioning station API
user_invocable: true
arguments:
  - name: solution_id
    description: "Solution ID to deploy (optional — will list available solutions if omitted)"
    required: false
---

# Deploy Solution Skill

Deploy IoT solutions through the provisioning station backend API.

## 1. Discover Backend Port

The backend may be running on a dynamic port. Find it:

```bash
# Check if dev server is running
ps aux | grep 'provisioning' | grep -v grep
# Look for --port argument, default is 3260

# Verify backend is up
curl -s http://127.0.0.1:3260/api/health
```

Set `BASE=http://127.0.0.1:<port>` for subsequent commands.

## 2. Deployment Flow

### Step 1: List available solutions

```bash
curl -s $BASE/api/solutions?lang=en
```

Pick the solution_id from the list, or use the one provided by the user.

### Step 2: Get deployment info (parameters + template)

```bash
curl -s $BASE/api/solutions/{solution_id}/deploy-info?lang=en
```

This returns:
- **presets**: Available deployment presets
- **steps**: Each step with its required **parameters** (key, type, required, default, description)
- **request_template**: A ready-to-fill JSON body for the deploy request

For a specific preset:
```bash
curl -s "$BASE/api/solutions/{solution_id}/deploy-info?preset_id=grafana"
```

### Step 3: Confirm parameters with user

Show the user what parameters are needed. Values marked `<REQUIRED: ...>` in the template must be filled in. Parameters with defaults can be accepted as-is.

Key things to confirm:
- **Device IPs** — the user must provide these
- **Passwords** — confirm defaults are correct or get actual credentials
- **Preset selection** — if multiple presets exist, ask which one

### Step 4: Start deployment

```bash
curl -s -X POST $BASE/api/deployments/start \
  -H "Content-Type: application/json" \
  -d '{
    "solution_id": "...",
    "preset_id": "...",
    "selected_devices": ["device1", "device2"],
    "device_connections": {
      "device1": { "host": "192.168.1.100", ... },
      "device2": {}
    }
  }'
```

The response contains `deployment_id`.

### Step 5: Check deployment result

```bash
# Concise summary with errors/warnings
curl -s $BASE/api/deployments/{deployment_id}/summary

# Full status with per-step progress
curl -s $BASE/api/deployments/{deployment_id}

# Detailed logs (for debugging failures)
curl -s $BASE/api/deployments/{deployment_id}/logs
```

## 3. Authentication

- **localhost**: No authentication needed
- **Remote access**: Add `X-API-Key: <key>` header (user configures key in settings)

## 4. Common Device Credentials

| Device | Default IP | Username | Password |
|--------|-----------|----------|----------|
| reCamera (USB) | 192.168.42.1 | recamera | recamera |
| reCamera (network) | varies (check router) | recamera | recamera |
| reComputer | varies | recomputer | 12345678 |

## 5. Debugging Failures

1. Check `summary.errors` for high-level error messages
2. Check `summary.warnings` for clock sync, timeout, or retry issues
3. Use `/logs` endpoint for full deployment log trace
4. Common issues:
   - **"Missing host"**: The `host` key was not provided in `device_connections`
   - **Clock sync**: reCamera via USB has no NTP — deployer syncs automatically, but check warnings
   - **SSH timeout**: Device may not be reachable — verify IP and that device is powered on

## 6. Complete Example: recamera_heatmap_grafana

```bash
BASE=http://127.0.0.1:3260

# 1. Get deploy info for the grafana preset
curl -s "$BASE/api/solutions/recamera_heatmap_grafana/deploy-info?preset_id=grafana" | python3 -m json.tool

# 2. Start deployment (fill in actual IPs)
curl -s -X POST $BASE/api/deployments/start \
  -H "Content-Type: application/json" \
  -d '{
    "solution_id": "recamera_heatmap_grafana",
    "preset_id": "grafana",
    "selected_devices": ["backend", "recamera"],
    "device_connections": {
      "backend": {},
      "recamera": {
        "host": "192.168.42.1",
        "password": "recamera",
        "influxdb_host": "192.168.1.100"
      }
    }
  }'

# 3. Check result (replace DEPLOY_ID with actual ID from step 2)
curl -s $BASE/api/deployments/DEPLOY_ID/summary | python3 -m json.tool
```
