targetScope = 'resourceGroup'

// ---------------------------------------------------------------------------
// Parameters
// ---------------------------------------------------------------------------

@description('Azure region for all resources. Defaults to the resource group location.')
param location string = resourceGroup().location

@description('Short project name used as a prefix for all resource names (3-20 chars, alphanumeric and hyphens).')
@minLength(3)
@maxLength(20)
param projectName string = 'esg-groupchat'

@description('Environment name. Use short identifiers to stay within Azure naming limits.')
@allowed([
  'dev'
  'staging'
  'prod'
])
param environmentName string = 'dev'

@description('Common tags applied to every resource.')
param tags object = {}

@description('LLM deployment name in Azure AI Foundry (e.g. gpt-4.1).')
param azureDeploymentName string = 'gpt-4.1'

@description('Entra ID tenant ID. Defaults to the current tenant.')
param entraTenantId string = tenant().tenantId

@description('Entra ID client ID for the backend Web API app registration.')
param entraClientId string

@description('Custom domain name for the front-end (optional, leave empty to skip).')
param customDomainName string = ''

// ---------------------------------------------------------------------------
// Computed values
// ---------------------------------------------------------------------------

var mergedTags = union(
  {
    project: 'ESG GroupChat'
    environment: environmentName
    managedBy: 'bicep'
  },
  tags
)

// ---------------------------------------------------------------------------
// User-assigned managed identity for the Container App
//
// Created here (before Key Vault and the backend module) so that:
//   • Key Vault can grant the "Key Vault Secrets User" role during the same
//     deployment.
//   • Cosmos DB can grant the "Cosmos DB Built-in Data Contributor" role.
//   • The backend module can reference the identity without circular deps.
// ---------------------------------------------------------------------------
resource containerAppIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${projectName}-backend-id-${environmentName}'
  location: location
  tags: mergedTags
}

// ---------------------------------------------------------------------------
// Module: Monitoring (Log Analytics + Application Insights)
// No upstream dependencies.
// ---------------------------------------------------------------------------
module monitoring 'modules/monitoring.bicep' = {
  name: 'monitoring'
  params: {
    location: location
    projectName: projectName
    environmentName: environmentName
    tags: mergedTags
  }
}

// ---------------------------------------------------------------------------
// Module: Network (VNet + subnets)
// No upstream dependencies.
// ---------------------------------------------------------------------------
module network 'modules/network.bicep' = {
  name: 'network'
  params: {
    location: location
    projectName: projectName
    environmentName: environmentName
    tags: mergedTags
  }
}

// ---------------------------------------------------------------------------
// Module: Frontend (Static Web Apps + Front Door + WAF)
// No upstream dependencies.
// ---------------------------------------------------------------------------
module frontend 'modules/frontend.bicep' = {
  name: 'frontend'
  params: {
    location: location
    projectName: projectName
    environmentName: environmentName
    tags: mergedTags
    customDomainName: customDomainName
  }
}

// ---------------------------------------------------------------------------
// Module: Storage (Cosmos DB + Private Endpoint)
// Depends on: network (for private endpoint subnet), containerAppIdentity
// ---------------------------------------------------------------------------
module storage 'modules/storage.bicep' = {
  name: 'storage'
  params: {
    location: location
    projectName: projectName
    environmentName: environmentName
    tags: mergedTags
    vnetId: network.outputs.vnetId
    privateEndpointsSubnetId: network.outputs.privateEndpointsSubnetId
    containerAppPrincipalId: containerAppIdentity.properties.principalId
  }
}

// ---------------------------------------------------------------------------
// Module: Key Vault (Key Vault + Private Endpoint + RBAC)
// Depends on: network (for private endpoint subnet), containerAppIdentity
// ---------------------------------------------------------------------------
module keyvault 'modules/keyvault.bicep' = {
  name: 'keyvault'
  params: {
    location: location
    projectName: projectName
    environmentName: environmentName
    tags: mergedTags
    vnetId: network.outputs.vnetId
    privateEndpointsSubnetId: network.outputs.privateEndpointsSubnetId
    containerAppPrincipalId: containerAppIdentity.properties.principalId
  }
}

// ---------------------------------------------------------------------------
// Module: Backend (ACR + Container Apps Environment + Container App)
// Depends on: monitoring, network, keyvault, storage, frontend,
//             containerAppIdentity
// ---------------------------------------------------------------------------
module backend 'modules/backend.bicep' = {
  name: 'backend'
  params: {
    location: location
    projectName: projectName
    environmentName: environmentName
    tags: mergedTags
    backendAppsSubnetId: network.outputs.backendAppsSubnetId
    logAnalyticsWorkspaceId: monitoring.outputs.logAnalyticsWorkspaceId
    keyVaultUri: keyvault.outputs.keyVaultUri
    containerAppIdentityId: containerAppIdentity.id
    containerAppIdentityClientId: containerAppIdentity.properties.clientId
    cosmosDbEndpoint: storage.outputs.cosmosDbEndpoint
    azureDeploymentName: azureDeploymentName
    entraTenantId: entraTenantId
    entraClientId: entraClientId
    staticWebAppHostname: frontend.outputs.staticWebAppHostname
    staticWebAppName: frontend.outputs.staticWebAppName
    frontDoorEndpointHostname: frontend.outputs.frontDoorEndpointHostname
  }
}

// ---------------------------------------------------------------------------
// Outputs
// ---------------------------------------------------------------------------

@description('Public URL of the Static Web App (via Azure Front Door).')
output frontDoorUrl string = 'https://${frontend.outputs.frontDoorEndpointHostname}'

@description('Direct URL of the Static Web App (bypass Front Door).')
output staticWebAppUrl string = 'https://${frontend.outputs.staticWebAppHostname}'

@description('Internal FQDN of the FastAPI Container App (accessible within VNet only).')
output backendFqdn string = backend.outputs.containerAppFqdn

@description('Container Registry login server (push images here before deploying).')
output containerRegistryLoginServer string = backend.outputs.containerRegistryLoginServer

@description('Key Vault URI. Store secrets here before deploying the Container App.')
output keyVaultUri string = keyvault.outputs.keyVaultUri

@description('Cosmos DB document endpoint.')
output cosmosDbEndpoint string = storage.outputs.cosmosDbEndpoint

@description('Application Insights connection string (informational).')
output applicationInsightsConnectionString string = monitoring.outputs.applicationInsightsConnectionString

@description('Container App managed identity client ID (set as AZURE_CLIENT_ID in the app).')
output containerAppIdentityClientId string = containerAppIdentity.properties.clientId
