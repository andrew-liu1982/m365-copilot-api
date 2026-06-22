# 在 Opencode 中使用 M365 Copilot

**架构：** Opencode → 本地 API 桥 → M365 Copilot Web UI（Playwright DOM 自动化）

## 1. 安装依赖

```bash
cd /home/andrew/AI/Windows-Copilot-API
pip install -r requirements.txt
playwright install chromium
```

## 2. 登录 M365 Copilot

打开浏览器窗口，手动登录 Microsoft 365：

```bash
COPILOT_MODE=m365 python -m copilot login
```

浏览器会打开 `https://m365.cloud.microsoft/chat`。用公司账号登录后，回到终端按 **Enter** 保存 session。

验证登录状态：

```bash
ls -la session/profile/
```

如果该目录有文件就表示 session 已保存。

## 3. 启动服务

```bash
COPILOT_MODE=m365 python app.py
```

看到以下输出即启动成功：

```
Copilot OpenAI-compatible API on http://127.0.0.1:8000  (POST /v1/chat/completions)
```

## 4. 测试（curl）

新建终端，执行：

```bash
curl http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "copilot",
    "messages": [{"role": "user", "content": "用中文回答，你好"}],
    "stream": true
  }'
```

应该能看到 SSE 流式输出。首次请求因为要启动浏览器，可能需等待 5-10 秒。

## 5. 配置 Opencode

编辑 `~/.config/opencode/opencode.json`（或项目根目录下的 `opencode.json`），添加自定义模型：

```json
{
  "models": [
    {
      "name": "Copilot (M365)",
      "provider": "openai",
      "apiBase": "http://localhost:8000/v1",
      "apiKey": "none"
    }
  ]
}
```

在 opencode 中按 `Ctrl+L` 或执行：

```
/model Copilot (M365)
```

即可切换到此模型。

## 注意事项

| 项目 | 说明 |
|------|------|
| 速度 | 每次请求约 6-10 秒（浏览器渲染 + DOM 解析） |
| 无并发 | 服务自带 `_upstream_lock`，同一时间只能处理一个请求 |
| 限流 | 默认 12 RPM / 4 burst，`RATE_LIMIT_RPM=0` 可关闭 |
| 超时 | M365 模式超时上限 60 秒 |
| Session | 浏览器是持久化的，服务关闭时自动清理 |
| 见 | `server/config.py` 可调整限流参数 |
