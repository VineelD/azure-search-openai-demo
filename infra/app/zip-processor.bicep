// Zip Processor Function App - processes chunked zip uploads asynchronously when _job.json is written to blob storage.
// Triggered by blob creation in user storage: _sessions/{upload_id}/_job.json
// Provisioned when useUserUpload is true.
//
// Required permissions (one-to-one; all assigned below so the function has no surprises at runtime):
// - Runtime storage (this RG): Blob/Queue/Table Data (for AzureWebJobsStorage coordination)
// - User storage: Storage Blob Data Owner + Storage Queue Data Contributor (trigger + read/write/delete session)
// - Search: Search Index Data Contributor (index uploaded documents)
// - OpenAI: Cognitive Services User (embeddings, chat if needed)
// - Vision (if useMultimodal): Cognitive Services User (figure processing)
// - Content Understanding (if useMediaDescriberAzureCU): Cognitive Services User (media describe)
param location string = resourceGroup().location
param tags object = {}
param applicationInsightsName string
param searchServiceResourceGroupName string
param openAiResourceGroupName string
param visionResourceGroupName string = ''
param contentUnderstandingResourceGroupName string = ''
param visionServiceName string = ''
param contentUnderstandingServiceName string = ''
param useMultimodal bool = false
param useMediaDescriberAzureCU bool = false

// App environment variables from main.bicep
param appEnvVariables object

// User storage for blob trigger and processing
param userStorageAccountName string
param userStorageResourceGroupName string
@secure()
param userStorageConnectionString string

param zipProcessorName string

var abbrs = loadJsonContent('../abbreviations.json')
var resourceToken = toLower(uniqueString(subscription().id, resourceGroup().id, location))

var zipProcessorRuntimeStorageName = '${abbrs.storageStorageAccounts}zpp${take(resourceToken, 18)}'
var deploymentContainerName = 'app-package-deployment'

var runtimeStorageRoles = [
  {
    suffix: 'blob'
    roleDefinitionId: 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
  }
  {
    suffix: 'queue'
    roleDefinitionId: '974c5e8b-45b9-4653-ba55-5f855dd0fb88'
  }
  {
    suffix: 'table'
    roleDefinitionId: '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3'
  }
]

// Runtime storage account for Flex Consumption
module zipProcessorRuntimeStorageAccount '../core/storage/storage-account.bicep' = {
  name: 'zip-processor-runtime-storage'
  params: {
    name: zipProcessorRuntimeStorageName
    location: location
    tags: tags
    allowBlobPublicAccess: false
    containers: [
      {
        name: deploymentContainerName
      }
    ]
  }
}

resource zipProcessorRuntimeStorage 'Microsoft.Storage/storageAccounts@2024-01-01' existing = {
  name: zipProcessorRuntimeStorageName
}

// Flex Consumption plan (one per function app)
module zipProcessorPlan 'br/public:avm/res/web/serverfarm:0.1.1' = {
  name: 'zip-processor-plan'
  params: {
    name: '${abbrs.webServerFarms}zpp-${resourceToken}'
    sku: {
      name: 'FC1'
      tier: 'FlexConsumption'
    }
    reserved: true
    location: location
    tags: tags
  }
}

module zipProcessorIdentity 'br/public:avm/res/managed-identity/user-assigned-identity:0.4.1' = {
  name: 'zip-processor-identity'
  params: {
    location: location
    tags: tags
    name: 'zip-processor-identity-${resourceToken}'
  }
}

// Role assignments on runtime storage
resource zipProcessorRuntimeStorageRoles 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for role in runtimeStorageRoles: {
  name: guid(zipProcessorRuntimeStorage.id, role.roleDefinitionId, 'zpp-storage-roles')
  scope: zipProcessorRuntimeStorage
  properties: {
    principalId: zipProcessorIdentity.outputs.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: resourceId('Microsoft.Authorization/roleDefinitions', role.roleDefinitionId)
  }
  dependsOn: [
    zipProcessorRuntimeStorageAccount
  ]
}]

// Storage Blob Data Owner on user storage (required for blob trigger + read/write/delete for zip processing)
module userStorageBlobOwner '../core/security/storage-role.bicep' = {
  scope: resourceGroup(userStorageResourceGroupName)
  name: 'zip-processor-user-storage-owner'
  params: {
    storageAccountName: userStorageAccountName
    principalId: zipProcessorIdentity.outputs.principalId
    roleDefinitionId: 'b7e6dc6d-f1e8-4753-8033-0f276bb0955b' // Storage Blob Data Owner
    principalType: 'ServicePrincipal'
  }
}

// Storage Queue Data Contributor on user storage (required for blob trigger - it uses a queue on the connection storage)
module userStorageQueueContributor '../core/security/storage-role.bicep' = {
  scope: resourceGroup(userStorageResourceGroupName)
  name: 'zip-processor-user-storage-queue-contributor'
  params: {
    storageAccountName: userStorageAccountName
    principalId: zipProcessorIdentity.outputs.principalId
    roleDefinitionId: '974c5e8b-45b9-4653-ba55-5f855dd0fb88' // Storage Queue Data Contributor
    principalType: 'ServicePrincipal'
  }
}

// Search Index Data Contributor
module searchIndexContributor '../core/security/role.bicep' = {
  scope: resourceGroup(searchServiceResourceGroupName)
  name: 'zip-processor-search-contributor'
  params: {
    principalId: zipProcessorIdentity.outputs.principalId
    roleDefinitionId: '8ebe5a00-799e-43f5-93ac-243d3dce84a7'
    principalType: 'ServicePrincipal'
  }
}

// OpenAI Cognitive Services User
module openAiUser '../core/security/role.bicep' = {
  scope: resourceGroup(openAiResourceGroupName)
  name: 'zip-processor-openai-user'
  params: {
    principalId: zipProcessorIdentity.outputs.principalId
    roleDefinitionId: '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
    principalType: 'ServicePrincipal'
  }
}

// Vision Cognitive Services User (if multimodal)
module visionUser '../core/security/role.bicep' = if (useMultimodal && !empty(visionServiceName)) {
  scope: resourceGroup(visionResourceGroupName)
  name: 'zip-processor-vision-user'
  params: {
    principalId: zipProcessorIdentity.outputs.principalId
    roleDefinitionId: 'a97b65f3-24c7-4388-baec-2e87135dc908'
    principalType: 'ServicePrincipal'
  }
}

// Content Understanding Cognitive Services User (if media describer)
module contentUnderstandingUser '../core/security/role.bicep' = if (useMediaDescriberAzureCU && !empty(contentUnderstandingServiceName)) {
  scope: resourceGroup(contentUnderstandingResourceGroupName)
  name: 'zip-processor-content-understanding-user'
  params: {
    principalId: zipProcessorIdentity.outputs.principalId
    roleDefinitionId: 'a97b65f3-24c7-4388-baec-2e87135dc908'
    principalType: 'ServicePrincipal'
  }
}

// Zip Processor Function App (deployed after all role assignments so permissions are in place)
module zipProcessorFunc 'zip-processor-app.bicep' = {
  name: 'zip-processor-func'
  params: {
    name: zipProcessorName
    location: location
    tags: union(tags, { 'azd-service-name': 'zip-processor' })
    applicationInsightsName: applicationInsightsName
    appServicePlanId: zipProcessorPlan.outputs.resourceId
    runtimeName: 'python'
    runtimeVersion: '3.11'
    storageAccountName: zipProcessorRuntimeStorageName
    deploymentStorageContainerName: deploymentContainerName
    identityId: zipProcessorIdentity.outputs.resourceId
    identityClientId: zipProcessorIdentity.outputs.clientId
    azureWebJobsStorageConnectionString: 'DefaultEndpointsProtocol=https;AccountName=${zipProcessorRuntimeStorageName};AccountKey=${listKeys(resourceId(resourceGroup().name, 'Microsoft.Storage/storageAccounts', zipProcessorRuntimeStorageName), '2024-01-01').keys[0].value};EndpointSuffix=${environment().suffixes.storage}'
    // Blob trigger uses connection "UserStorage" - must be connection string for reliable binding
    appSettings: union(appEnvVariables, {
      UserStorage: userStorageConnectionString
    })
    instanceMemoryMB: 4096
    maximumInstanceCount: 10
  }
  dependsOn: [
    zipProcessorRuntimeStorageAccount
    zipProcessorRuntimeStorageRoles
    userStorageBlobOwner
    userStorageQueueContributor
    searchIndexContributor
    openAiUser
  ]
}

output name string = zipProcessorFunc.outputs.name
output defaultHostname string = zipProcessorFunc.outputs.defaultHostname
