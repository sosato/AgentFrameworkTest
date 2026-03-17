@description('Azure region for all resources')
param location string

@description('Project name used as prefix for resource names')
param projectName string

@description('Environment name (dev, staging, prod)')
param environmentName string

@description('Common tags to apply to all resources')
param tags object

@description('Custom domain name for the application (optional, leave empty to skip)')
param customDomainName string = ''

// ---------------------------------------------------------------------------
// Azure Static Web Apps — Standard SKU
// Spec: フロントエンド SPA ホスティング
// ---------------------------------------------------------------------------
resource staticWebApp 'Microsoft.Web/staticSites@2023-01-01' = {
  name: '${projectName}-swa-${environmentName}'
  location: location
  tags: tags
  sku: {
    name: 'Standard'
    tier: 'Standard'
  }
  properties: {
    stagingEnvironmentPolicy: 'Enabled'
    allowConfigFileUpdates: true
    // Enterprise-grade CDN is disabled because Azure Front Door is used instead
    enterpriseGradeCdnStatus: 'Disabled'
  }
}

// Optional custom domain binding
resource swaCustomDomain 'Microsoft.Web/staticSites/customDomains@2023-01-01' = if (!empty(customDomainName)) {
  parent: staticWebApp
  name: customDomainName
  properties: {}
}

// ---------------------------------------------------------------------------
// WAF Policy — Standard_AzureFrontDoor SKU
// Spec: OWASP ルールセット + レート制限 100 req/min/IP
// ---------------------------------------------------------------------------
// WAF policy names must be alphanumeric only (no hyphens)
var wafPolicyName = '${take(replace(projectName, '-', ''), 14)}waf${take(replace(environmentName, '-', ''), 4)}'

resource wafPolicy 'Microsoft.Network/FrontDoorWebApplicationFirewallPolicies@2022-05-01' = {
  name: wafPolicyName
  location: 'global'
  tags: tags
  sku: {
    name: 'Standard_AzureFrontDoor'
  }
  properties: {
    policySettings: {
      enabledState: 'Enabled'
      // Prevention mode: block threats rather than only detect them
      mode: 'Prevention'
      requestBodyCheck: 'Enabled'
      customBlockResponseStatusCode: 403
    }
    managedRules: {
      managedRuleSets: [
        {
          // OWASP-based default rule set
          ruleSetType: 'Microsoft_DefaultRuleSet'
          ruleSetVersion: '2.1'
          ruleSetAction: 'Block'
        }
        {
          ruleSetType: 'Microsoft_BotManagerRuleSet'
          ruleSetVersion: '1.0'
          ruleSetAction: 'Block'
        }
      ]
    }
    customRules: {
      rules: [
        {
          // Rate limit: 100 requests per minute per source IP
          name: 'RateLimitPerIp'
          priority: 100
          enabledState: 'Enabled'
          ruleType: 'RateLimitRule'
          rateLimitDurationInMinutes: 1
          rateLimitThreshold: 100
          matchConditions: [
            {
              // Match all source IPs (IPv4 + IPv6) to apply universal rate limiting
              matchVariable: 'RemoteAddr'
              operator: 'IPMatch'
              negateCondition: false
              matchValue: [
                '0.0.0.0/0'
                '::/0'
              ]
              transforms: []
            }
          ]
          action: 'Block'
        }
      ]
    }
  }
}

// ---------------------------------------------------------------------------
// Azure Front Door Profile — Standard SKU
// Spec: CDN、WAF、カスタムドメイン
// ---------------------------------------------------------------------------
resource frontDoorProfile 'Microsoft.Cdn/profiles@2023-05-01' = {
  name: '${projectName}-afd-${environmentName}'
  location: 'global'
  tags: tags
  sku: {
    name: 'Standard_AzureFrontDoor'
  }
}

// Front Door Endpoint
resource frontDoorEndpoint 'Microsoft.Cdn/profiles/afdEndpoints@2023-05-01' = {
  parent: frontDoorProfile
  name: '${projectName}-ep-${environmentName}'
  location: 'global'
  properties: {
    enabledState: 'Enabled'
  }
}

// Origin Group for Static Web Apps
resource swaOriginGroup 'Microsoft.Cdn/profiles/originGroups@2023-05-01' = {
  parent: frontDoorProfile
  name: 'swa-origin-group'
  properties: {
    loadBalancingSettings: {
      sampleSize: 4
      successfulSamplesRequired: 3
      additionalLatencyInMilliseconds: 50
    }
    healthProbeSettings: {
      probePath: '/'
      probeRequestType: 'HEAD'
      probeProtocol: 'Https'
      probeIntervalInSeconds: 100
    }
    sessionAffinityState: 'Disabled'
  }
}

// Origin pointing to the Static Web Apps default hostname
resource swaOrigin 'Microsoft.Cdn/profiles/originGroups/origins@2023-05-01' = {
  parent: swaOriginGroup
  name: 'swa-origin'
  properties: {
    hostName: staticWebApp.properties.defaultHostname
    httpPort: 80
    httpsPort: 443
    originHostHeader: staticWebApp.properties.defaultHostname
    priority: 1
    weight: 1000
    enabledState: 'Enabled'
    enforceCertificateNameCheck: true
  }
}

// Route: all traffic (/*) → SWA with HTTPS redirect
resource swaRoute 'Microsoft.Cdn/profiles/afdEndpoints/routes@2023-05-01' = {
  parent: frontDoorEndpoint
  name: 'swa-route'
  dependsOn: [
    swaOrigin
  ]
  properties: {
    originGroup: {
      id: swaOriginGroup.id
    }
    supportedProtocols: [
      'Https'
    ]
    patternsToMatch: [
      '/*'
    ]
    forwardingProtocol: 'HttpsOnly'
    linkToDefaultDomain: 'Enabled'
    httpsRedirect: 'Enabled'
    enabledState: 'Enabled'
  }
}

// WAF Security Policy attached to the Front Door endpoint
resource securityPolicy 'Microsoft.Cdn/profiles/securityPolicies@2023-05-01' = {
  parent: frontDoorProfile
  name: '${projectName}-waf-policy-${environmentName}'
  properties: {
    parameters: {
      type: 'WebApplicationFirewall'
      wafPolicy: {
        id: wafPolicy.id
      }
      associations: [
        {
          domains: [
            {
              id: frontDoorEndpoint.id
            }
          ]
          patternsToMatch: [
            '/*'
          ]
        }
      ]
    }
  }
}

// ---------------------------------------------------------------------------
// Outputs
// ---------------------------------------------------------------------------
@description('Static Web Apps default hostname (without https://)')
output staticWebAppHostname string = staticWebApp.properties.defaultHostname

@description('Static Web Apps resource ID')
output staticWebAppId string = staticWebApp.id

@description('Static Web Apps name')
output staticWebAppName string = staticWebApp.name

@description('Front Door endpoint hostname (without https://)')
output frontDoorEndpointHostname string = frontDoorEndpoint.properties.hostName

@description('Front Door profile resource ID')
output frontDoorProfileId string = frontDoorProfile.id

@description('Front Door endpoint resource ID')
output frontDoorEndpointId string = frontDoorEndpoint.id
