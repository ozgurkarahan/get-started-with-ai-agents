@description('Name of the existing APIM instance')
param apimServiceName string

@description('URL of the A2A server Container App (backend)')
param a2aServerUrl string

@description('Display name for the A2A agent in APIM')
param a2aAgentDisplayName string = 'AI Foundry Search Agent'

@description('Application Insights name for APIM logger (optional)')
param applicationInsightsName string = ''

// Reference the existing APIM instance
resource apim 'Microsoft.ApiManagement/service@2023-09-01-preview' existing = {
  name: apimServiceName
}

// Named value for the A2A backend URL
resource a2aBackendUrl 'Microsoft.ApiManagement/service/namedValues@2023-09-01-preview' = {
  parent: apim
  name: 'a2a-backend-url'
  properties: {
    displayName: 'a2a-backend-url'
    value: a2aServerUrl
    secret: false
  }
}

// Backend pointing to the A2A Container App
resource a2aBackend 'Microsoft.ApiManagement/service/backends@2023-09-01-preview' = {
  parent: apim
  name: 'a2a-foundry-agent'
  properties: {
    title: a2aAgentDisplayName
    description: 'Backend for A2A server wrapping Azure AI Foundry agent'
    url: a2aServerUrl
    protocol: 'http'
  }
  dependsOn: [a2aBackendUrl]
}

// Product for A2A agent consumers
resource a2aProduct 'Microsoft.ApiManagement/service/products@2023-09-01-preview' = {
  parent: apim
  name: 'a2a-agents'
  properties: {
    displayName: 'A2A Agents'
    description: 'Product for Agent-to-Agent protocol consumers'
    subscriptionRequired: true
    approvalRequired: false
    state: 'published'
  }
}

// APIM logger for Application Insights (if available)
resource appInsights 'Microsoft.Insights/components@2020-02-02' existing = if (!empty(applicationInsightsName)) {
  name: applicationInsightsName
}

resource a2aLogger 'Microsoft.ApiManagement/service/loggers@2023-09-01-preview' = if (!empty(applicationInsightsName)) {
  parent: apim
  name: 'a2a-appinsights-logger'
  properties: {
    loggerType: 'applicationInsights'
    resourceId: !empty(applicationInsightsName) ? appInsights.id : ''
    credentials: {
      instrumentationKey: !empty(applicationInsightsName) ? appInsights.properties.InstrumentationKey : ''
    }
  }
}

output apimGatewayUrl string = apim.properties.gatewayUrl
output backendId string = a2aBackend.id
output productId string = a2aProduct.id
