// Function app for zip-processor (blob-triggered, no Easy Auth required)
param name string
param location string = resourceGroup().location
param tags object = {}
@description('Name of an existing Application Insights component. Leave empty to disable.')
param applicationInsightsName string
param appServicePlanId string
param appSettings object = {}
param runtimeName string
param runtimeVersion string
param storageAccountName string
param deploymentStorageContainerName string
param instanceMemoryMB int = 4096
param maximumInstanceCount int = 10
param identityId string
param identityClientId string
@secure()
param azureWebJobsStorageConnectionString string

// AVM expects authentication.type values: SystemAssignedIdentity | UserAssignedIdentity | StorageAccountConnectionString
// Use UserAssignedIdentity for deployment storage (package pull). Runtime uses connection string for AzureWebJobsStorage.
var identityType = 'UserAssignedIdentity'
var kind = 'functionapp,linux'
var applicationInsightsIdentity = 'ClientId=${identityClientId};Authorization=AAD'

// Reference existing resources
resource stg 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}

resource applicationInsights 'Microsoft.Insights/components@2020-02-02' existing = if (!empty(applicationInsightsName)) {
  name: applicationInsightsName
}

// AzureWebJobsStorage must be a connection string for the Functions host to start reliably (identity-based often fails)
var baseAppSettings = {
  AzureWebJobsStorage: azureWebJobsStorageConnectionString
  FUNCTIONS_EXTENSION_VERSION: '~4'
  AZURE_CLIENT_ID: identityClientId
}

// Optional Application Insights settings
var appInsightsSettings = !empty(applicationInsightsName) ? {
  APPLICATIONINSIGHTS_AUTHENTICATION_STRING: applicationInsightsIdentity
  APPLICATIONINSIGHTS_CONNECTION_STRING: applicationInsights.?properties.ConnectionString ?? ''
} : {}

// Merge all app settings (no Easy Auth for blob-triggered function)
var allAppSettings = union(appSettings, baseAppSettings, appInsightsSettings)

// Create Flex Consumption Function App using AVM
module functionApp 'br/public:avm/res/web/site:0.15.1' = {
  name: '${name}-func-app'
  params: {
    kind: kind
    name: name
    location: location
    tags: tags
    serverFarmResourceId: appServicePlanId
    managedIdentities: {
      userAssignedResourceIds: [
        '${identityId}'
      ]
    }
    functionAppConfig: {
      deployment: {
        storage: {
          type: 'blobContainer'
          value: '${stg.properties.primaryEndpoints.blob}${deploymentStorageContainerName}'
          authentication: {
            type: identityType
            userAssignedIdentityResourceId: identityId
          }
        }
      }
      scaleAndConcurrency: {
        instanceMemoryMB: instanceMemoryMB
        maximumInstanceCount: maximumInstanceCount
      }
      runtime: {
        name: runtimeName
        version: runtimeVersion
      }
    }
    siteConfig: {
      alwaysOn: false
      httpsOnly: true
      ftpsState: 'Disabled'
      cors: {
        allowedOrigins: ['https://portal.azure.com']
      }
    }
    appSettingsKeyValuePairs: allAppSettings
  }
}

// Outputs
output name string = functionApp.outputs.name
output defaultHostname string = functionApp.outputs.defaultHostname
output resourceId string = functionApp.outputs.resourceId
