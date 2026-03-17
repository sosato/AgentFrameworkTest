@description('Azure region for all resources')
param location string

@description('Project name used as prefix for resource names')
param projectName string

@description('Environment name (dev, staging, prod)')
param environmentName string

@description('Common tags to apply to all resources')
param tags object

@description('Resource ID of the VNet for private endpoint DNS zone linking')
param vnetId string

@description('Resource ID of the private-endpoints subnet')
param privateEndpointsSubnetId string

@description('Principal ID of the Container App user-assigned managed identity for data-plane RBAC')
param containerAppPrincipalId string = ''

// Short suffix used in resources that have strict naming limits
var envShort = take(environmentName, 4)

// ---------------------------------------------------------------------------
// Cosmos DB Account — Serverless, SQL API
// Spec: セッション保存期間 7 日 (TTL 604800 s), Session consistency
// ---------------------------------------------------------------------------
resource cosmosDbAccount 'Microsoft.DocumentDB/databaseAccounts@2023-11-15' = {
  name: '${projectName}-cosmos-${environmentName}'
  location: location
  tags: tags
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    consistencyPolicy: {
      defaultConsistencyLevel: 'Session'
    }
    locations: [
      {
        locationName: location
        failoverPriority: 0
        isZoneRedundant: false
      }
    ]
    capabilities: [
      {
        name: 'EnableServerless'
      }
    ]
    enableAutomaticFailover: false
    enableMultipleWriteLocations: false
    publicNetworkAccess: 'Disabled'
    networkAclBypass: 'AzureServices'
    isVirtualNetworkFilterEnabled: false
    minimalTlsVersion: 'Tls12'
    backupPolicy: {
      type: 'Periodic'
      periodicModeProperties: {
        backupIntervalInMinutes: 1440
        backupRetentionIntervalInHours: 48
        backupStorageRedundancy: 'Local'
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Cosmos DB Database
// ---------------------------------------------------------------------------
resource cosmosDbDatabase 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2023-11-15' = {
  parent: cosmosDbAccount
  name: 'esg-groupchat'
  properties: {
    resource: {
      id: 'esg-groupchat'
    }
  }
}

// ---------------------------------------------------------------------------
// sessions container — partitioned by /userId, TTL 7 days
// ---------------------------------------------------------------------------
resource cosmosDbSessionContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2023-11-15' = {
  parent: cosmosDbDatabase
  name: 'sessions'
  properties: {
    resource: {
      id: 'sessions'
      partitionKey: {
        paths: [
          '/userId'
        ]
        kind: 'Hash'
      }
      defaultTtl: 604800
      indexingPolicy: {
        indexingMode: 'consistent'
        automatic: true
        includedPaths: [
          {
            path: '/*'
          }
        ]
        excludedPaths: [
          {
            path: '/"_etag"/?'
          }
        ]
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Cosmos DB Built-in Data Contributor role for Container App managed identity
// Allows the backend to read/write session documents
// ---------------------------------------------------------------------------
resource cosmosDbRoleAssignment 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2023-11-15' = if (!empty(containerAppPrincipalId)) {
  parent: cosmosDbAccount
  name: guid(cosmosDbAccount.id, containerAppPrincipalId, '00000000-0000-0000-0000-000000000002')
  properties: {
    // Built-in Cosmos DB Data Contributor
    roleDefinitionId: '${cosmosDbAccount.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002'
    principalId: containerAppPrincipalId
    scope: cosmosDbAccount.id
  }
}

// ---------------------------------------------------------------------------
// Private DNS Zone for Cosmos DB SQL API
// ---------------------------------------------------------------------------
resource cosmosDbPrivateDnsZone 'Microsoft.Network/privateDnsZones@2020-06-01' = {
  name: 'privatelink.documents.azure.com'
  location: 'global'
  tags: tags
}

resource cosmosDbDnsZoneVnetLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = {
  parent: cosmosDbPrivateDnsZone
  name: '${projectName}-cosmos-dnslink-${envShort}'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: vnetId
    }
  }
}

// ---------------------------------------------------------------------------
// Private Endpoint for Cosmos DB
// ---------------------------------------------------------------------------
resource cosmosDbPrivateEndpoint 'Microsoft.Network/privateEndpoints@2023-11-01' = {
  name: '${projectName}-cosmos-pe-${environmentName}'
  location: location
  tags: tags
  properties: {
    subnet: {
      id: privateEndpointsSubnetId
    }
    privateLinkServiceConnections: [
      {
        name: '${projectName}-cosmos-pe-conn-${environmentName}'
        properties: {
          privateLinkServiceId: cosmosDbAccount.id
          groupIds: [
            'Sql'
          ]
        }
      }
    ]
  }
}

resource cosmosDbPrivateDnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2023-11-01' = {
  parent: cosmosDbPrivateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'privatelink-documents-azure-com'
        properties: {
          privateDnsZoneId: cosmosDbPrivateDnsZone.id
        }
      }
    ]
  }
}

// ---------------------------------------------------------------------------
// Outputs
// ---------------------------------------------------------------------------
@description('Cosmos DB account resource ID')
output cosmosDbAccountId string = cosmosDbAccount.id

@description('Cosmos DB document endpoint')
output cosmosDbEndpoint string = cosmosDbAccount.properties.documentEndpoint

@description('Cosmos DB account name')
output cosmosDbAccountName string = cosmosDbAccount.name
