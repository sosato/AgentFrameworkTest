// Example parameter file for the ESG GroupChat web-stack Bicep deployment.
// Copy this file, fill in the required values, and use it with:
//
//   az deployment group create \
//     --resource-group <rg-name> \
//     --template-file main.bicep \
//     --parameters main.bicepparam
//
// NOTE: Do NOT commit real secrets or client IDs to source control.
//       Use Azure Key Vault or a CI/CD secret store instead.

using './main.bicep'

// ── Required parameters ────────────────────────────────────────────────────

// Entra ID client ID for the backend Web API app registration
param entraClientId = '<backend-app-client-id>'

// NOTE: Azure AI Foundry project endpoint is NOT a Bicep parameter.
//       Store it as a Key Vault secret named "foundry-project-endpoint" after
//       the Key Vault has been created. See infra/README.md for details.

// ── Optional — override defaults ──────────────────────────────────────────

// Target region (must support Azure Static Web Apps)
param location = 'japaneast'

// Short project prefix used in all resource names
param projectName = 'esg-groupchat'

// Environment: 'dev' | 'staging' | 'prod'
param environmentName = 'dev'

// LLM deployment name registered in Azure AI Foundry
param azureDeploymentName = 'gpt-4.1'

// Entra ID tenant ID (defaults to the current tenant if omitted)
// param entraTenantId = '<tenant-id>'

// Custom domain (leave empty to use the auto-generated Front Door hostname)
// param customDomainName = 'groupchat.example.com'

// Additional tags merged with the defaults
param tags = {
  owner: 'your-team'
  costCenter: 'engineering'
}
