# n8n Workflow Sync Scripts

These PowerShell scripts help sync n8n workflows between machines using the Git-tracked `workflows/workflows-export.json` file.

## Folder layout assumed

This version assumes the scripts are stored here:

```text
C:\projects\gunpla-tracker-verified\scripts\powershell\
```

and your repo root is:

```text
C:\projects\gunpla-tracker-verified\
```

The scripts automatically calculate the repo root from their own folder, so you can run them from inside `scripts\powershell` without breaking the path check.

## Docker volume assumed

Your Docker Compose should include this bind mount:

```yaml
- ./workflows:/home/node/.n8n/workflows
```

## Files

- `export-workflows.ps1` - Exports all workflows from the running n8n container into `workflows/workflows-export.json`
- `import-workflows.ps1` - Imports `workflows/workflows-export.json` into the running n8n container

## How to run

Once inside the directory run this once: Set-ExecutionPolicy -Scope Process Bypass

If you are inside `scripts\powershell`:

```powershell
.\export-workflows.ps1
.\import-workflows.ps1
```

If you are at repo root:

```powershell
.\scripts\powershell\export-workflows.ps1
.\scripts\powershell\import-workflows.ps1
```

## Optional container override

```powershell
.\export-workflows.ps1 -ContainerName "your-container-name"
.\import-workflows.ps1 -ContainerName "your-container-name"
```

## Typical sync flow

1. Run export on machine A.
2. Commit and push `workflows/workflows-export.json`.
3. Pull latest changes on machine B.
4. Run import on machine B.

## If PowerShell blocks script execution

Run this for the current session only:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
```
