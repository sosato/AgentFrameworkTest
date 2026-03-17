# infra — Web Stack IaC (Bicep)

This directory contains the Azure Bicep templates that provision all web-layer
resources for the ESG GroupChat application, as specified in
[`specs/web-ui-spec.md`](../specs/web-ui-spec.md).

---

## Architecture overview

```
Internet
  │
  ▼
Azure Front Door (Standard) + WAF Policy
  │   OWASP 2.1 managed rules
  │   Rate limit: 100 req/min/IP
  │
  ▼
Azure Static Web Apps (Standard)   ← React SPA frontend
  │   SWA linked-backend (VNet private routing)
  │
  ▼
Azure Container Apps (Consumption, VNet-internal)   ← FastAPI backend
  │         │
  │         └─ Azure AI Foundry (existing, via VNet Private Endpoint)
  │
  ├─ Azure Cosmos DB Serverless (sessions, TTL 7 days) ← Private Endpoint
  ├─ Azure Key Vault (Standard)                        ← Private Endpoint
  └─ Azure Application Insights (workspace-based)
```

All backend resources reside in a **Virtual Network** (`10.0.0.0/16`) and are
not reachable from the public internet.

---

## Resource inventory

| Module | Resource | SKU / Config |
|--------|----------|--------------|
| `monitoring` | Log Analytics Workspace | PerGB2018, 90-day retention |
| `monitoring` | Application Insights | Workspace-based, 90-day retention |
| `network` | Virtual Network | `10.0.0.0/16`, 4 subnets |
| `frontend` | Azure Static Web Apps | Standard |
| `frontend` | Azure Front Door | Standard |
| `frontend` | WAF Policy | Standard_AzureFrontDoor, Prevention mode |
| `storage` | Cosmos DB (SQL API) | Serverless, session TTL 7 days |
| `keyvault` | Azure Key Vault | Standard, RBAC, purge-protected |
| `backend` | Azure Container Registry | Basic |
| `backend` | Container Apps Environment | Consumption, VNet-internal |
| `backend` | Container App (FastAPI) | 0.5 vCPU / 1 GiB, 1–10 replicas |
| `main` | User-assigned Managed Identity | — |

---

## Prerequisites

1. **Azure CLI** ≥ 2.50 and **Bicep** ≥ 0.22:
   ```bash
   az bicep install
   az bicep version
   ```

2. **Resource group** already created:
   ```bash
   az group create --name esg-groupchat-rg --location japaneast
   ```

3. **Entra ID app registrations** (frontend SPA + backend Web API) created
   manually in Entra ID before deployment.  
   See `specs/web-ui-spec.md §3.2` for the registration details.

4. **Secrets pre-loaded in Key Vault** after the first Bicep deployment:

   | Secret name | Description |
   |---|---|
   | `entra-client-secret` | Backend app client secret |
   | `foundry-project-endpoint` | Azure AI Foundry project endpoint URL |
   | `applicationinsights-connection-string` | App Insights connection string (output of this deployment) |

   ```bash
   KV=$(az deployment group show \
     --resource-group esg-groupchat-rg \
     --name main \
     --query properties.outputs.keyVaultUri.value -o tsv)

   az keyvault secret set --vault-name "${KV%%.*}" \
     --name entra-client-secret --value "<secret>"
   ```

5. **Docker image** pushed to ACR before the Container App can start:
   ```bash
   ACR=$(az deployment group show \
     --resource-group esg-groupchat-rg \
     --name main \
     --query properties.outputs.containerRegistryLoginServer.value -o tsv)

   az acr login --name "${ACR%%.*}"
   docker build -t ${ACR}/esg-groupchat-backend:latest ./backend
   docker push ${ACR}/esg-groupchat-backend:latest
   ```

---

## Deployment

### Copy and edit the parameter file

```bash
cp infra/main.bicepparam infra/main.<env>.bicepparam
# Edit main.<env>.bicepparam — fill in foundryProjectEndpoint and entraClientId
```

### Deploy

```bash
az deployment group create \
  --resource-group esg-groupchat-rg \
  --template-file infra/main.bicep \
  --parameters infra/main.<env>.bicepparam \
  --name main
```

### View outputs

```bash
az deployment group show \
  --resource-group esg-groupchat-rg \
  --name main \
  --query properties.outputs
```

---

## Module dependency graph

```
containerAppIdentity (inline in main.bicep)
       │
       ├──► keyvault  ──►─────────────────────────────────────┐
       │                                                        │
       ├──► storage   ──► (cosmosDbEndpoint)                   │
       │                        │                              │
monitoring ──────────────────── │ ──────────────────────────── ▼
network    ──────────────────── │ ──────────────────────────► backend
frontend   ──(hostnames)─────── │ ─────────────────────────────^
```

---

## Security notes

| Control | Implementation |
|---|---|
| No public internet access for backend | Container Apps Environment `internal: true` |
| Secrets not in code/env | Key Vault references via Managed Identity |
| WAF | OWASP 2.1 + Bot Manager, Prevention mode, rate-limit 100 req/min/IP |
| TLS | Front Door enforces HTTPS; `httpsRedirect: Enabled` |
| Least privilege | Managed Identity has only `Key Vault Secrets User` + `AcrPull` + `Cosmos DB Data Contributor` |
| Key Vault hardening | Soft-delete 90 days, purge protection, RBAC-only, private endpoint |
| Cosmos DB | Serverless, private endpoint, Tls12 minimum |

---

## Naming convention

| Resource type | Pattern | Example (dev) |
|---|---|---|
| General | `{project}-{abbr}-{env}` | `esg-groupchat-vnet-dev` |
| Key Vault | `{14-char project}-kv-{4-char env}` | `esg-groupchat-kv-dev` |
| Container Registry | `{14-char project, no hyphens}acr{4-char env}` | `esggroupchatacrdev` |
| WAF Policy | `{14-char project, no hyphens}waf{4-char env}` | `esggroupchatwafdev` |
