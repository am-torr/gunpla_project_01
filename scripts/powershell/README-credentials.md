# n8n Credential Sync Scripts

These PowerShell scripts export and import **encrypted** n8n credentials using the same repo-root path logic as the workflow scripts.

## Important

These scripts use the default encrypted credential export and do **not** use `--decrypted`.

That means:

- `credentials-export.json` still contains sensitive data and should be treated carefully.
- The target machine must use the same `N8N_ENCRYPTION_KEY` for imported credentials to work correctly.
- Do not switch to `--decrypted` unless you intentionally need plain-text credentials for a special migration case.

## Folder layout assumed

Scripts are stored in:

```text
C:\projects\gunpla-tracker-verified\scripts\powershell\
```

Repo root is:

```text
C:\projects\gunpla-tracker-verified\
```

## Docker volume assumed

```yaml
- ./workflows:/home/node/.n8n/workflows
```

## Files

- `export-credentials.ps1` - Exports all encrypted credentials into `workflows/credentials-export.json`
- `import-credentials.ps1` - Imports `workflows/credentials-export.json` into the running n8n container

## How to run

Once inside the directory run this once: Set-ExecutionPolicy -Scope Process Bypass

From `scripts\powershell`:

```powershell
.\export-credentials.ps1
.\import-credentials.ps1
```

From repo root:

```powershell
.\scripts\powershell\export-credentials.ps1
.\scripts\powershell\import-credentials.ps1
```

## Optional container override

```powershell
.\export-credentials.ps1 -ContainerName "your-container-name"
.\import-credentials.ps1 -ContainerName "your-container-name"
```

## Recommended sync order on another machine

1. Pull latest repo changes.
2. Import credentials.
3. Import workflows.

## If PowerShell blocks script execution

```powershell
Set-ExecutionPolicy -Scope Process Bypass
```
