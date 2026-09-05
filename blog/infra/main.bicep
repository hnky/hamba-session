targetScope = 'subscription'

@minLength(1)
param environmentName string
param location string

@secure()
@description('Author session secret and password/API-key hashes. Empty disables author login.')
param authorConfig string = ''

var resourceToken = toLower(uniqueString(subscription().id, environmentName, location))
var tags = {
  'azd-env-name': environmentName
  application: 'hamba'
}
var storageAccountName = take('st${resourceToken}', 24)
var registryName = take('cr${resourceToken}', 50)
var identityName = 'id-${environmentName}-${resourceToken}'
var blobContainerName = 'images'
var tableName = 'posts'

resource resourceGroup 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: 'rg-${environmentName}'
  location: location
  tags: tags
}

module resources 'resources.bicep' = {
  name: 'hamba-resources'
  scope: resourceGroup
  params: {
    location: location
    environmentName: environmentName
    tags: tags
    storageAccountName: storageAccountName
    registryName: registryName
    identityName: identityName
    blobContainerName: blobContainerName
    tableName: tableName
    authorConfig: authorConfig
  }
}

output AZURE_LOCATION string = location
output AZURE_RESOURCE_GROUP string = resourceGroup.name
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = resources.outputs.registryEndpoint
output AZURE_CONTAINER_REGISTRY_NAME string = resources.outputs.registryName
output SERVICE_WEB_NAME string = resources.outputs.containerAppName
output SERVICE_WEB_URI string = resources.outputs.containerAppUri
