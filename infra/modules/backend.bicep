@description('Azure region for all resources')
param location string

@description('Project name used as prefix for resource names')
param projectName string

@description('Environment name (dev, staging, prod)')
param environmentName string

@description('Common tags to apply to all resources')
param tags object

@description('Resource ID of the backend-apps subnet (Container Apps Environment VNet integration)')
param backendAppsSubnetId string

@description('Log Analytics Workspace resource ID for Container Apps Environment logs')
param logAnalyticsWorkspaceId string

@description('Key Vault URI for secret references')
param keyVaultUri string

@description('Resource ID of the user-assigned managed identity for the Container App')
param containerAppIdentityId string

@description('Client ID of the user-assigned managed identity (AZURE_CLIENT_ID env var)')
param containerAppIdentityClientId string

@description('Cosmos DB document endpoint')
param cosmosDbEndpoint string

@description('LLM deployment name (e.g. gpt-4.1)')
param azureDeploymentName string

@description('Entra ID tenant ID')
param entraTenantId string

@description('Entra ID client ID for the backend Web API app registration')
param entraClientId string

@description('Static Web Apps hostname for CORS allow-list (without https://)')
param staticWebAppHostname string = ''

@description('Static Web Apps resource name (required for linked-backend association)')
param staticWebAppName string = ''

@description('Front Door endpoint hostname for CORS allow-list (without https://)')
param frontDoorEndpointHostname string = ''

// Container Registry name must be alphanumeric only, 5-50 chars.
// The @minLength(3) + @allowed constraints on the parameters guarantee the
// resulting name is always ≥ 6 chars in practice; suppress the linter's
// conservative minimum-length estimate.
var acrName = '${take(replace(projectName, '-', ''), 14)}acr${take(replace(environmentName, '-', ''), 4)}'

// Build CORS allowed-origins list, filtering out empty placeholder entries
var corsAllowedOrigins = filter(
  [
    empty(staticWebAppHostname) ? '' : 'https://${staticWebAppHostname}'
    empty(frontDoorEndpointHostname) ? '' : 'https://${frontDoorEndpointHostname}'
  ],
  origin => !empty(origin)
)

// ---------------------------------------------------------------------------
// Azure Container Registry — Basic SKU
// Spec: Docker イメージ管理
// ---------------------------------------------------------------------------
resource containerRegistry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  #disable-next-line BCP334
  name: acrName
  location: location
  tags: tags
  sku: {
    name: 'Basic'
  }
  properties: {
    // Admin credentials disabled; Container App uses managed identity (AcrPull role)
    adminUserEnabled: false
    publicNetworkAccess: 'Enabled'
    policies: {
      retentionPolicy: {
        status: 'enabled'
        days: 7
      }
    }
  }
}

// AcrPull role for the Container App managed identity
resource acrPullRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  // AcrPull built-in role: 7f951dda-4ed3-4680-a7ca-43fe172d538d
  name: guid(containerRegistry.id, containerAppIdentityId, '7f951dda-4ed3-4680-a7ca-43fe172d538d')
  scope: containerRegistry
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '7f951dda-4ed3-4680-a7ca-43fe172d538d'
    )
    principalId: reference(containerAppIdentityId, '2023-01-31').principalId
    principalType: 'ServicePrincipal'
  }
}

// ---------------------------------------------------------------------------
// Container Apps Environment — Consumption plan with VNet integration
// Spec: VNet 統合（内部専用）
// ---------------------------------------------------------------------------
resource containerAppsEnvironment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${projectName}-cae-${environmentName}'
  location: location
  tags: tags
  properties: {
    vnetConfiguration: {
      infrastructureSubnetId: backendAppsSubnetId
      // internal = true: Container Apps are not reachable from the public internet
      internal: true
    }
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: reference(logAnalyticsWorkspaceId, '2022-10-01').customerId
        sharedKey: listKeys(logAnalyticsWorkspaceId, '2022-10-01').primarySharedKey
      }
    }
    zoneRedundant: false
  }
}

// ---------------------------------------------------------------------------
// FastAPI Backend Container App
// Spec: FastAPI + Uvicorn; secrets resolved from Key Vault via managed identity
// ---------------------------------------------------------------------------
resource backendContainerApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: '${projectName}-backend-${environmentName}'
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${containerAppIdentityId}': {}
    }
  }
  properties: {
    managedEnvironmentId: containerAppsEnvironment.id
    configuration: {
      ingress: {
        // internal=true: only reachable within the VNet / from linked SWA backend
        external: false
        targetPort: 8000
        allowInsecure: false
        traffic: [
          {
            latestRevision: true
            weight: 100
          }
        ]
        corsPolicy: {
          allowedOrigins: empty(corsAllowedOrigins) ? [
            '*'
          ] : corsAllowedOrigins
          allowedMethods: [
            'GET'
            'POST'
            'DELETE'
            'OPTIONS'
          ]
          allowedHeaders: [
            'Authorization'
            'Content-Type'
            'Accept'
          ]
          allowCredentials: true
        }
      }
      registries: [
        {
          server: containerRegistry.properties.loginServer
          identity: containerAppIdentityId
        }
      ]
      // Key Vault secret references resolved via user-assigned managed identity
      secrets: [
        {
          name: 'entra-client-secret'
          keyVaultUrl: '${keyVaultUri}secrets/entra-client-secret'
          identity: containerAppIdentityId
        }
        {
          name: 'foundry-project-endpoint'
          keyVaultUrl: '${keyVaultUri}secrets/foundry-project-endpoint'
          identity: containerAppIdentityId
        }
        {
          name: 'appinsights-connection-string'
          keyVaultUrl: '${keyVaultUri}secrets/applicationinsights-connection-string'
          identity: containerAppIdentityId
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'backend'
          // Image must be pushed to ACR before first deployment
          image: '${containerRegistry.properties.loginServer}/esg-groupchat-backend:latest'
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            {
              // Used by DefaultAzureCredential to select the correct managed identity
              name: 'AZURE_CLIENT_ID'
              value: containerAppIdentityClientId
            }
            {
              name: 'ENTRA_TENANT_ID'
              value: entraTenantId
            }
            {
              name: 'ENTRA_CLIENT_ID'
              value: entraClientId
            }
            {
              name: 'ENTRA_CLIENT_SECRET'
              secretRef: 'entra-client-secret'
            }
            {
              name: 'FOUNDRY_PROJECT_ENDPOINT'
              secretRef: 'foundry-project-endpoint'
            }
            {
              name: 'AZURE_DEPLOYMENT_NAME'
              value: azureDeploymentName
            }
            {
              name: 'COSMOS_DB_ENDPOINT'
              value: cosmosDbEndpoint
            }
            {
              name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
              secretRef: 'appinsights-connection-string'
            }
          ]
          probes: [
            {
              type: 'Liveness'
              httpGet: {
                path: '/health'
                port: 8000
              }
              initialDelaySeconds: 10
              periodSeconds: 30
            }
            {
              type: 'Readiness'
              httpGet: {
                path: '/health'
                port: 8000
              }
              initialDelaySeconds: 5
              periodSeconds: 10
            }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 10
        rules: [
          {
            name: 'http-scaling'
            http: {
              metadata: {
                // Scale up when concurrent requests per replica exceeds 10
                concurrentRequests: '10'
              }
            }
          }
        ]
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Link the Static Web App to the internal Container App as its API backend
// This lets the SWA proxy /api/* requests to the Container App through the VNet
// ---------------------------------------------------------------------------
resource existingStaticWebApp 'Microsoft.Web/staticSites@2023-01-01' existing = if (!empty(staticWebAppName)) {
  name: staticWebAppName
}

resource swaLinkedBackend 'Microsoft.Web/staticSites/linkedBackends@2023-01-01' = if (!empty(staticWebAppName)) {
  parent: existingStaticWebApp
  name: 'backend'
  properties: {
    backendResourceId: backendContainerApp.id
    region: location
  }
}

// ---------------------------------------------------------------------------
// Outputs
// ---------------------------------------------------------------------------
@description('Container Registry login server (e.g. <name>.azurecr.io)')
output containerRegistryLoginServer string = containerRegistry.properties.loginServer

@description('Container Registry resource ID')
output containerRegistryId string = containerRegistry.id

@description('Container App FQDN (internal, reachable only within VNet)')
output containerAppFqdn string = backendContainerApp.properties.configuration.ingress.fqdn

@description('Container App resource ID')
output containerAppId string = backendContainerApp.id

@description('Container Apps Environment resource ID')
output containerAppsEnvironmentId string = containerAppsEnvironment.id
