param name string
param location string = resourceGroup().location
param tags object = {}

param containerRegistryName string
param identityName string
param containerAppsEnvironmentName string
param agentID string
param agentName string
param projectEndpoint string
param enableAzureMonitorTracing bool
param otelInstrumentationGenAICaptureMessageContent bool
param a2aServerBaseUrl string = ''

resource a2aIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: identityName
  location: location
}

var env = [
  {
    name: 'AZURE_CLIENT_ID'
    value: a2aIdentity.properties.clientId
  }
  {
    name: 'AZURE_EXISTING_AIPROJECT_ENDPOINT'
    value: projectEndpoint
  }
  {
    name: 'AZURE_EXISTING_AGENT_ID'
    value: agentID
  }
  {
    name: 'AZURE_AI_AGENT_NAME'
    value: agentName
  }
  {
    name: 'A2A_SERVER_BASE_URL'
    value: a2aServerBaseUrl
  }
  {
    name: 'A2A_SERVER_PORT'
    value: '8080'
  }
  {
    name: 'ENABLE_AZURE_MONITOR_TRACING'
    value: enableAzureMonitorTracing
  }
  {
    name: 'OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT'
    value: otelInstrumentationGenAICaptureMessageContent
  }
  {
    name: 'RUNNING_IN_PRODUCTION'
    value: 'true'
  }
]

module app 'core/host/container-app-upsert.bicep' = {
  name: 'a2a-container-app-module'
  params: {
    name: name
    location: location
    tags: union(tags, { 'azd-service-name': 'a2a_server' })
    identityName: a2aIdentity.name
    containerRegistryName: containerRegistryName
    containerAppsEnvironmentName: containerAppsEnvironmentName
    targetPort: 8080
    env: env
  }
}

output SERVICE_A2A_IDENTITY_PRINCIPAL_ID string = a2aIdentity.properties.principalId
output SERVICE_A2A_NAME string = app.outputs.name
output SERVICE_A2A_URI string = app.outputs.uri
