#!/bin/bash
short_token="EAFeZCtl9tRaIBRNRXEVDjAIpPNY7d3t77QiHrE3VnoOYpmhVFnngVzeymPuvIqPV8dKblzDw4aLMhiRuhZBox66LrRSTrRcBoIJ336AV00bZCBTu25rV62ZAOqzsaO8fGjnxE4VDF4ybkKX1Yc14KC7JCCcCJgVZCRZBmZCwQop9XW1W5CkJoI4UypikzaMdZBFIMPlJtNBPnGVwsVQOWeWZAgpaVFhS3ZCT7kw8GJL6cZD"
client_id="24699112979776930"
client_secret="1e140daa1bab0f3fe1c27903cea8b2de"
response=$(curl -s "https://graph.facebook.com/v25.0/oauth/access_token?grant_type=fb_exchange_token&client_id=$client_id&client_secret=$client_secret&fb_exchange_token=$short_token")
echo "New long-lived token: $(echo $response | jq -r .access_token)"