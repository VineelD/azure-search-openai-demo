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

// When provided, use this shared user-assigned identity instead of creating a dedicated zip-processor identity (roles assigned in main.bicep).
param appSharedIdentityResourceId string = ''
param appSharedIdentityClientId string = ''

var abbrs = loadJsonContent('../abbreviations.json')
var useSharedIdentity = !empty(appSharedIdentityResourceId) && !empty(appSharedIdentityClientId)
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

// Role assignments on runtime storage (use shared identity principal when useSharedIdentity; runtime storage is always in this RG)
var zipProcessorPrincipalId = useSharedIdentity ? reference(appSharedIdentityResourceId, '2023-01-31').principalId : zipProcessorIdentity.outputs.principalId

// Use distinct name suffix when using shared identity so we create new assignments instead of updating existing ones
resource zipProcessorRuntimeStorageRoles 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for role in runtimeStorageRoles: {
  name: guid(zipProcessorRuntimeStorage.id, role.roleDefinitionId, useSharedIdentity ? 'zpp-storage-roles-shared' : 'zpp-storage-roles')
  scope: zipProcessorRuntimeStorage
  properties: {
    principalId: zipProcessorPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: resourceId('Microsoft.Authorization/roleDefinitions', role.roleDefinitionId)
  }
  dependsOn: [
    zipProcessorRuntimeStorageAccount
  ]
}]

// When not using shared identity, assign roles for the dedicated zip-processor identity (main.bicep assigns these for shared identity).
module userStorageBlobOwner '../core/security/storage-role.bicep' = if (!useSharedIdentity) {
  scope: resourceGroup(userStorageResourceGroupName)
  name: 'zip-processor-user-storage-owner'
  params: {
    storageAccountName: userStorageAccountName
    principalId: zipProcessorIdentity.outputs.principalId
    roleDefinitionId: 'b7e6dc6d-f1e8-4753-8033-0f276bb0955b' // Storage Blob Data Owner
    principalType: 'ServicePrincipal'
  }
}

module userStorageQueueContributor '../core/security/storage-role.bicep' = if (!useSharedIdentity) {
  scope: resourceGroup(userStorageResourceGroupName)
  name: 'zip-processor-user-storage-queue-contributor'
  params: {
    storageAccountName: userStorageAccountName
    principalId: zipProcessorIdentity.outputs.principalId
    roleDefinitionId: '974c5e8b-45b9-4653-ba55-5f855dd0fb88' // Storage Queue Data Contributor
    principalType: 'ServicePrincipal'
  }
}

module searchIndexContributor '../core/security/role.bicep' = if (!useSharedIdentity) {
  scope: resourceGroup(searchServiceResourceGroupName)
  name: 'zip-processor-search-contributor'
  params: {
    principalId: zipProcessorIdentity.outputs.principalId
    roleDefinitionId: '8ebe5a00-799e-43f5-93ac-243d3dce84a7'
    principalType: 'ServicePrincipal'
  }
}

module openAiUser '../core/security/role.bicep' = if (!useSharedIdentity) {
  scope: resourceGroup(openAiResourceGroupName)
  name: 'zip-processor-openai-user'
  params: {
    principalId: zipProcessorIdentity.outputs.principalId
    roleDefinitionId: '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
    principalType: 'ServicePrincipal'
  }
}

module visionUser '../core/security/role.bicep' = if (!useSharedIdentity && useMultimodal && !empty(visionServiceName)) {
  scope: resourceGroup(visionResourceGroupName)
  name: 'zip-processor-vision-user'
  params: {
    principalId: zipProcessorIdentity.outputs.principalId
    roleDefinitionId: 'a97b65f3-24c7-4388-baec-2e87135dc908'
    principalType: 'ServicePrincipal'
  }
}

module contentUnderstandingUser '../core/security/role.bicep' = if (!useSharedIdentity && useMediaDescriberAzureCU && !empty(contentUnderstandingServiceName)) {
  scope: resourceGroup(contentUnderstandingResourceGroupName)
  name: 'zip-processor-content-understanding-user'
  params: {
    principalId: zipProcessorIdentity.outputs.principalId
    roleDefinitionId: 'a97b65f3-24c7-4388-baec-2e87135dc908'
    principalType: 'ServicePrincipal'
  }
}

// Zip Processor Function App (deployed after all role assignments so permissions are in place)
var zipProcessorIdentityId = useSharedIdentity ? appSharedIdentityResourceId : zipProcessorIdentity.outputs.resourceId
var zipProcessorIdentityClientId = useSharedIdentity ? appSharedIdentityClientId : zipProcessorIdentity.outputs.clientId

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
    identityId: zipProcessorIdentityId
    identityClientId: zipProcessorIdentityClientId
    azureWebJobsStorageConnectionString: 'DefaultEndpointsProtocol=https;AccountName=${zipProcessorRuntimeStorageName};AccountKey=${listKeys(resourceId(resourceGroup().name, 'Microsoft.Storage/storageAccounts', zipProcessorRuntimeStorageName), '2024-01-01').keys[0].value};EndpointSuffix=${environment().suffixes.storage}'
    // Blob trigger uses connection "UserStorage" - must be connection string for reliable binding
    appSettings: union(
      appEnvVariables,
      {
        UserStorage: userStorageConnectionString
      },
      useSharedIdentity ? { AZURE_CLIENT_ID: appSharedIdentityClientId } : {}
    )
    instanceMemoryMB: 4096
    maximumInstanceCount: 10
  }
  dependsOn: useSharedIdentity
    ? [zipProcessorRuntimeStorageAccount, zipProcessorRuntimeStorageRoles]
    : [
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
