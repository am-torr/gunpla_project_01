# n8n Encryption Key Sync & Credential Import

This directory contains PowerShell scripts for securely syncing the n8n encryption key between machines and importing encrypted credentials — without ever exporting credentials in plain text.

---

## Overview

n8n encrypts all credentials using a master `encryptionKey`. When credentials are exported from Machine A and imported into Machine B, both machines **must share the same encryption key**, otherwise the import will fail with:

> `Credentials could not be decrypted. The likely reason is that a different "encryptionKey" was used to encrypt the data.`

These scripts solve that problem by:
1. Locating and extracting the key from the source machine's container
2. Syncing the key into the destination machine's `docker-compose.yml`
3. Restarting the destination n8n instance with the new key
4. Importing the encrypted credentials file

---

## Scripts

| Script | Machine | Purpose |
|--------|---------|---------|
| `get_encryption_key.ps1` | Source | Diagnoses and extracts the active encryption key |
| `export_credentials.ps1` | Source | Exports encrypted credentials to a JSON file |
| `sync_and_import_credentials.ps1` | Destination / Main | Syncs key into Compose, restarts n8n, imports credentials |

---

## Step-by-Step Usage

### Step 1 — On the Source Machine: Get the Encryption Key

Run this on the machine where credentials are working to extract the active key:

```powershell
.\get_encryption_key.ps1 -SourceContainer "gunpla-n8n"
```

**Expected output:**
```
Attempting to retrieve encryption key from container 'gunpla-n8n'...
N8N_ENCRYPTION_KEY not found in environment. Trying to read from config file...
Encryption key extracted from config file (via JSON parsing).
Encryption Key: <your-key-here>
```

Copy the key value that is printed.

---

### Step 2 — On the Source Machine: Export Encrypted Credentials

Export the credentials as an encrypted JSON file:

```powershell
.\export_credentials.ps1 -ContainerName "gunpla-n8n"
```

This creates `credentials-export.json` inside:
```
workflows\credentials-export.json
```

Copy this file to the destination machine (via USB, network share, or git commit).

---

### Step 3 — On the Destination/Main Machine: Sync Key & Import

Run this on the **main machine**, passing in the key you copied in Step 1:

```powershell
.\sync_and_import_credentials.ps1 `
  -ComposeFilePath "C:\PROJECTS\gunpla-tracker-verified\docker-compose.yml" `
  -CredentialsFilePath "C:\PROJECTS\gunpla-tracker-verified\workflows\credentials-export.json" `
  -SourceEncryptionKey "<paste-the-key-from-step-1>" `
  -ContainerName "gunpla-n8n"
```

**What the script does internally:**
1. Patches `N8N_ENCRYPTION_KEY` inside `docker-compose.yml`
2. Runs `docker compose down`
3. Runs `docker compose up -d`
4. Copies the credentials file into the container using `docker cp`
5. Runs `n8n import:credentials` inside the container

---

## Parameters Reference

### `get_encryption_key.ps1`

| Parameter | Default | Description |
|-----------|---------|-------------|
| `-SourceContainer` | `gunpla-n8n` | Name of the running n8n Docker container |

### `export_credentials.ps1`

| Parameter | Default | Description |
|-----------|---------|-------------|
| `-ContainerName` | `gunpla-n8n` | Name of the running n8n Docker container |

### `sync_and_import_credentials.ps1`

| Parameter | Default | Description |
|-----------|---------|-------------|
| `-ComposeFilePath` | `C:\PROJECTS\gunpla-tracker-verified\docker-compose.yml` | Path to the destination machine's `docker-compose.yml` |
| `-CredentialsFilePath` | `C:\PROJECTS\gunpla-tracker-verified\workflows\credentials-export.json` | Path to the exported credentials JSON file |
| `-SourceEncryptionKey` | *(required)* | The encryption key extracted from the source machine |
| `-ContainerName` | `gunpla-n8n` | Name of the running n8n Docker container |

---

## Security Notes

- The credentials JSON file is **always encrypted** — plain text export is never used
- The encryption key is passed via a `-SourceEncryptionKey` parameter and written directly into `docker-compose.yml` — it is never printed to a log file or stored in a separate file
- Transfer the encryption key **out-of-band** (e.g., paste it manually, use a password manager, or a secure channel) — never commit the raw key to git
- The `credentials-export.json` file itself is safe to commit to a private repo since it is encrypted, but avoid committing it to any public repository

---

## Troubleshooting

### `Cannot index into a null array` on `$matches[1]`
The regex failed to match the config file content. Run `get_encryption_key.ps1` first to confirm the key is readable before running the sync script.

### `Credentials could not be decrypted` after import
The encryption key used during import does not match the one used during export. Double-check that you pasted the correct key from `get_encryption_key.ps1` without any extra whitespace or characters.

### `docker compose down` fails
Make sure Docker Desktop is running and that you are inside the correct directory. The script automatically `Push-Location` to the `docker-compose.yml` directory before running Compose commands.

### `N8N_ENCRYPTION_KEY not found in compose file`
Your `docker-compose.yml` does not have an `N8N_ENCRYPTION_KEY` entry yet. Add it manually under the n8n service's `environment` section:

```yaml
services:
  n8n:
    environment:
      N8N_ENCRYPTION_KEY: "<your-key-here>"
```

Then rerun `sync_and_import_credentials.ps1`.

---

## File Structure

```
scripts/
└── powershell/
    ├── get_encryption_key.ps1
    ├── export_credentials.ps1
    ├── sync_and_import_credentials.ps1
    └── ENCRYPTION_KEY_SYNC_README.md

workflows/
└── credentials-export.json   ← generated by export_credentials.ps1
```
