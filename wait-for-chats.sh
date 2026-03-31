#!/bin/bash
TOKEN=$(cat /root/.config/agent-wechat/token)
for i in $(seq 1 60); do
    STATUS=$(curl -sf http://localhost:6174/api/chats -H "Authorization: Bearer $TOKEN" 2>/dev/null)
    if [ -n "$STATUS" ] && [ "$STATUS" != "[]" ]; then
        echo "Chats available!"
        exit 0
    fi
    echo "Waiting for WeChat chats... attempt $i/60"
    sleep 5
done
echo "Timeout waiting for chats"
exit 1
