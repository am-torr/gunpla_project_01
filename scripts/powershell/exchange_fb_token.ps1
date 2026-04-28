$shortToken = "EAFeZCtl9tRaIBRNRXEVDjAIpPNY7d3t77QiHrE3VnoOYpmhVFnngVzeymPuvIqPV8dKblzDw4aLMhiRuhZBox66LrRSTrRcBoIJ336AV00bZCBTu25rV62ZAOqzsaO8fGjnxE4VDF4ybkKX1Yc14KC7JCCcCJgVZCRZBmZCwQop9XW1W5CkJoI4UypikzaMdZBFIMPlJtNBPnGVwsVQOWeWZAgpaVFhS3ZCT7kw8GJL6cZD"
$clientId = "24699112979776930"
$clientSecret = "1e140daa1bab0f3fe1c27903cea8b2de"
$uri = "https://graph.facebook.com/v25.0/oauth/access_token?grant_type=fb_exchange_token&client_id=$clientId&client_secret=$clientSecret&fb_exchange_token=$shortToken"
$response = Invoke-RestMethod -Uri $uri -Method Get
Write-Output "New long-lived token: $($response.access_token)"