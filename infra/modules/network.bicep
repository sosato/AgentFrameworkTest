@description('Azure region for all resources')
param location string

@description('Project name used as prefix for resource names')
param projectName string

@description('Environment name (dev, staging, prod)')
param environmentName string

@description('Common tags to apply to all resources')
param tags object

// ---------------------------------------------------------------------------
// Virtual Network
// Spec: esg-groupchat-vnet (10.0.0.0/16) with 4 subnets
// ---------------------------------------------------------------------------
resource virtualNetwork 'Microsoft.Network/virtualNetworks@2023-11-01' = {
  name: '${projectName}-vnet-${environmentName}'
  location: location
  tags: tags
  properties: {
    addressSpace: {
      addressPrefixes: [
        '10.0.0.0/16'
      ]
    }
    subnets: [
      // SWA Managed Env / Front Door Origin (no delegation required for SWA)
      {
        name: 'frontend-integration'
        properties: {
          addressPrefix: '10.0.1.0/24'
          privateEndpointNetworkPolicies: 'Disabled'
          privateLinkServiceNetworkPolicies: 'Enabled'
        }
      }
      // Container Apps Environment — requires Microsoft.App/environments delegation
      {
        name: 'backend-apps'
        properties: {
          addressPrefix: '10.0.2.0/24'
          delegations: [
            {
              name: 'containerApps'
              properties: {
                serviceName: 'Microsoft.App/environments'
              }
            }
          ]
          privateEndpointNetworkPolicies: 'Disabled'
          privateLinkServiceNetworkPolicies: 'Enabled'
        }
      }
      // Private endpoints for Foundry, Cosmos DB, Key Vault
      {
        name: 'private-endpoints'
        properties: {
          addressPrefix: '10.0.3.0/24'
          privateEndpointNetworkPolicies: 'Disabled'
          privateLinkServiceNetworkPolicies: 'Disabled'
        }
      }
      // Reserved for future VPN GW / ExpressRoute
      {
        name: 'gateway'
        properties: {
          addressPrefix: '10.0.4.0/24'
          privateEndpointNetworkPolicies: 'Disabled'
          privateLinkServiceNetworkPolicies: 'Enabled'
        }
      }
    ]
  }
}

// ---------------------------------------------------------------------------
// Outputs
// ---------------------------------------------------------------------------
@description('Virtual Network resource ID')
output vnetId string = virtualNetwork.id

@description('Virtual Network name')
output vnetName string = virtualNetwork.name

@description('frontend-integration subnet resource ID')
output frontendIntegrationSubnetId string = virtualNetwork.properties.subnets[0].id

@description('backend-apps subnet resource ID')
output backendAppsSubnetId string = virtualNetwork.properties.subnets[1].id

@description('private-endpoints subnet resource ID')
output privateEndpointsSubnetId string = virtualNetwork.properties.subnets[2].id

@description('gateway subnet resource ID')
output gatewaySubnetId string = virtualNetwork.properties.subnets[3].id
