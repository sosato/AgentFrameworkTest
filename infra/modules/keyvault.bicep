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

@description('Principal ID of the Container App user-assigned managed identity (Key Vault Secrets User role)')
param containerAppPrincipalId string = ''

// Key Vault name: 3-24 chars, alphanumeric + hyphens
// Using a 14-char prefix to accommodate "staging"
var kvName = '${take(projectName, 14)}-kv-${take(environmentName, 4)}'

// ---------------------------------------------------------------------------
// Key Vault — Standard SKU, RBAC-based, public access disabled
// ---------------------------------------------------------------------------
resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: kvName
  location: location
  tags: tags
  properties: {
    sku: {
      family: 'A'
      name: 'standard'
    }
    tenantId: subscription().tenantId
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 90
    enablePurgeProtection: true
    publicNetworkAccess: 'Disabled'
    networkAcls: {
      bypass: 'AzureServices'
      defaultAction: 'Deny'
      ipRules: []
      virtualNetworkRules: []
    }
  }
}

// ---------------------------------------------------------------------------
// Key Vault Secrets User role for the Container App managed identity
// Allows the backend to read secrets (client-secret, connection-strings, etc.)
// ---------------------------------------------------------------------------
resource kvSecretsUserRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(containerAppPrincipalId)) {
  // Key Vault Secrets User built-in role: 4633458b-17de-408a-b874-0445c86b69e6
  name: guid(keyVault.id, containerAppPrincipalId, '4633458b-17de-408a-b874-0445c86b69e6')
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '4633458b-17de-408a-b874-0445c86b69e6'
    )
    principalId: containerAppPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// ---------------------------------------------------------------------------
// Private DNS Zone for Key Vault
// ---------------------------------------------------------------------------
resource kvPrivateDnsZone 'Microsoft.Network/privateDnsZones@2020-06-01' = {
  name: 'privatelink.vaultcore.azure.net'
  location: 'global'
  tags: tags
}

resource kvDnsZoneVnetLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = {
  parent: kvPrivateDnsZone
  name: '${projectName}-kv-dnslink-${take(environmentName, 4)}'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: vnetId
    }
  }
}

// ---------------------------------------------------------------------------
// Private Endpoint for Key Vault
// ---------------------------------------------------------------------------
resource kvPrivateEndpoint 'Microsoft.Network/privateEndpoints@2023-11-01' = {
  name: '${projectName}-kv-pe-${environmentName}'
  location: location
  tags: tags
  properties: {
    subnet: {
      id: privateEndpointsSubnetId
    }
    privateLinkServiceConnections: [
      {
        name: '${projectName}-kv-pe-conn-${environmentName}'
        properties: {
          privateLinkServiceId: keyVault.id
          groupIds: [
            'vault'
          ]
        }
      }
    ]
  }
}

resource kvPrivateDnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2023-11-01' = {
  parent: kvPrivateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'privatelink-vaultcore-azure-net'
        properties: {
          privateDnsZoneId: kvPrivateDnsZone.id
        }
      }
    ]
  }
}

// ---------------------------------------------------------------------------
// Outputs
// ---------------------------------------------------------------------------
@description('Key Vault resource ID')
output keyVaultId string = keyVault.id

@description('Key Vault URI (https://…)')
output keyVaultUri string = keyVault.properties.vaultUri

@description('Key Vault name')
output keyVaultName string = keyVault.name
