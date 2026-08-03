# Kimi Code 连接 Azure K3 配置指南

本文记录一套已经实际验证的配置：在 Kimi Code 中调用 Azure AI Foundry 上的 Kimi K3，并让直接输入 `kimi` 时默认进入 YOLO 权限模式，Thinking 可选 `Low / High / Max`。

## 已验证环境

- 验证日期：2026-07-30
- 操作系统：macOS，zsh
- Kimi Code：`0.30.0`
- Azure OpenAI 兼容端点：`https://bill-3691-resource.services.ai.azure.com/api/projects/bill-3691/openai/v1`
- Azure 部署名：`FW-Kimi-K3`
- 默认权限模式：`yolo`
- 默认 Thinking：`high`
- Thinking 档位：`low`、`high`、`max`

这套配置走 Kimi Code 的 OpenAI Chat Completions 兼容 provider。它和 Codex 调用 OpenAI Responses API 时出现的 `annotations is missing` 错误不是同一条协议链路。

## 1. 安装 Kimi Code

macOS 或 Linux：

```bash
curl -fsSL https://code.kimi.com/kimi-code/install.sh | bash
```

Windows PowerShell：

```powershell
irm https://code.kimi.com/kimi-code/install.ps1 | iex
```

确认安装成功：

```bash
kimi --version
```

本文后续命令以 macOS/Linux 的 zsh 为准。Kimi 的主配置文件位于：

```text
~/.kimi-code/config.toml
```

## 2. 保存 Azure API Key

将 Azure Key 保存到本机 shell 环境，不要把真实 Key 写进本文、Git 仓库或共享脚本。

在 `~/.zshrc` 中加入：

```zsh
export AZURE_OPENAI_API_KEY="<填写 Azure Key>"
```

然后重新加载：

```zsh
source ~/.zshrc
```

检查变量是否存在，但不要输出 Key 本身：

```zsh
[[ -n "${AZURE_OPENAI_API_KEY:-}" ]] && echo "Azure Key 已设置" || echo "Azure Key 未设置"
```

## 3. 配置静态 Azure K3 模型

如果已有 Kimi 配置，先备份：

```bash
mkdir -p ~/.kimi-code
if [[ -f ~/.kimi-code/config.toml ]]; then
  cp ~/.kimi-code/config.toml ~/.kimi-code/config.toml.bak.$(date +%Y%m%d-%H%M%S)
fi
```

编辑 `~/.kimi-code/config.toml`，合并以下配置。不要在同一个文件中重复声明已有的顶层字段或同名表。

```toml
default_model = "azure-k3/FW-Kimi-K3"
default_permission_mode = "yolo"

[thinking]
enabled = true
effort = "high"

[providers.azure-k3]
type = "openai"
api_key = ""
base_url = "https://bill-3691-resource.services.ai.azure.com/api/projects/bill-3691/openai/v1"

[models."azure-k3/FW-Kimi-K3"]
provider = "azure-k3"
model = "FW-Kimi-K3"
max_context_size = 1048576
capabilities = ["thinking", "always_thinking", "image_in", "tool_use"]
display_name = "Azure K3"
support_efforts = ["low", "high", "max"]
default_effort = "high"
```

关键字段说明：

- `type = "openai"`：使用 OpenAI Chat Completions 兼容接口。
- `default_permission_mode = "yolo"`：启动后默认允许执行工具操作，不再逐项确认。
- `support_efforts`：决定 `/model` 中显示哪些 Thinking 档位。缺少它时通常只会看到 `On / Off`。
- `default_effort = "high"`：Azure K3 默认使用 High Thinking。
- `api_key = ""`：本方案不把 Key 明文写入 Kimi 配置；下一步由启动函数临时传入。

如果你的 Azure 项目、区域或部署名不同，需要同时替换 `base_url` 和 `model`，模型 ID 中的部署名也应保持一致。

## 4. 让输入 `kimi` 自动使用 Azure K3

在 `~/.zshrc` 中加入下面的函数。相比写死完整用户名路径，这个版本只依赖 `$HOME`，复制到另一台 macOS/Linux 电脑更方便。

```zsh
export PATH="$HOME/.kimi-code/bin:$PATH"

unalias kimi 2>/dev/null
kimi() {
  if [[ -z "${AZURE_OPENAI_API_KEY:-}" ]]; then
    print -u2 "AZURE_OPENAI_API_KEY is not set"
    return 2
  fi

  OPENAI_API_KEY="$AZURE_OPENAI_API_KEY" \
    "$HOME/.kimi-code/bin/kimi" -m "azure-k3/FW-Kimi-K3" "$@"
}
```

重新加载配置：

```zsh
source ~/.zshrc
```

从此直接运行：

```zsh
kimi
```

等价于选择 `azure-k3/FW-Kimi-K3`，同时保留所有额外参数。例如：

```zsh
kimi doctor
kimi -p '只输出：AZURE_K3_OK'
```

## 5. 清理旧的临时模型变量

如果以前使用过 `KIMI_MODEL_*` 方式连接 Azure，请从 `~/.zshrc`、`~/.zprofile` 或其他启动脚本中删除这些旧变量，并在当前终端执行：

```zsh
unset KIMI_MODEL_NAME KIMI_MODEL_API_KEY KIMI_MODEL_PROVIDER_TYPE \
  KIMI_MODEL_BASE_URL KIMI_MODEL_MAX_CONTEXT_SIZE \
  KIMI_MODEL_CAPABILITIES KIMI_MODEL_THINKING_EFFORT
```

原因是 `KIMI_MODEL_*` 会创建临时模型，可能覆盖静态模型配置；临时模型没有完整的 `support_efforts` 定义，所以界面容易退回只有 `Thinking On / Off`。

## 6. 验证

先检查配置：

```zsh
kimi doctor
```

再做最小联网测试：

```zsh
kimi -p '只输出：AZURE_K3_OK'
```

最后进入交互界面：

```zsh
kimi
```

正常情况下，状态栏应包含类似信息：

```text
yolo  Azure K3  thinking: high
```

在交互界面输入 `/model`，应该能看到：

```text
Low / High / Max
```

可以在 `/model` 中切换档位，也可以修改 `~/.kimi-code/config.toml`：

```toml
[thinking]
enabled = true
effort = "low" # 也可以是 high 或 max
```

## 7. 常见问题

### Thinking 仍然只有 On / Off

依次检查：

1. 当前选择的模型是否是 `azure-k3/FW-Kimi-K3`。
2. 静态模型是否包含 `support_efforts = ["low", "high", "max"]`。
3. shell 中是否仍有 `KIMI_MODEL_*` 变量。
4. 修改配置后是否重启了 Kimi 交互会话。

### 返回 401 或 403

通常是 API Key 错误、Key 不属于该 Azure 资源，或当前账号/资源没有调用该部署的权限。检查 `AZURE_OPENAI_API_KEY` 的来源，但不要在终端历史、截图或日志中打印完整 Key。

### 返回 404

重点检查：

- `base_url` 是否是 Azure AI Foundry 项目的 OpenAI v1 兼容端点。
- 部署名是否确实为 `FW-Kimi-K3`。
- URL 末尾是否为 `/openai/v1`，不要自行追加 Chat Completions 的完整路径。

### `kimi doctor` 报配置错误

TOML 不允许重复键。已有 `[thinking]`、`[providers.azure-k3]` 或同名模型时，应修改原段落，不要再粘贴一份。必要时恢复备份：

```bash
cp ~/.kimi-code/config.toml.bak.<时间戳> ~/.kimi-code/config.toml
```

### 新版 Kimi 不接受空 `api_key`

上述“环境变量映射到 `OPENAI_API_KEY`”方案已在 Kimi Code `0.30.0` 上验证。Kimi 的 provider 凭据规则以后可能变化。

如果升级后确认不再接受该方式，可把 Key 直接写入 provider：

```toml
[providers.azure-k3]
type = "openai"
api_key = "<填写 Azure Key>"
base_url = "https://bill-3691-resource.services.ai.azure.com/api/projects/bill-3691/openai/v1"
```

这种兜底方式会在磁盘上留下明文 Key，使用后至少执行：

```bash
chmod 600 ~/.kimi-code/config.toml
```

不要提交或共享该配置文件。

## 8. 换电脑速查清单

1. 安装 Kimi Code，并确认版本。
2. 在新电脑设置 `AZURE_OPENAI_API_KEY`。
3. 把静态 provider/model 配置合并到 `~/.kimi-code/config.toml`。
4. 把 `kimi()` 启动函数加入 `~/.zshrc`。
5. 清理旧的 `KIMI_MODEL_*` 变量。
6. 依次运行 `kimi doctor`、最小联网测试和交互界面的 `/model`。
7. 确认状态为 YOLO，Thinking 菜单为 `Low / High / Max`。

## 官方资料

- Kimi Code 开源仓库：<https://github.com/MoonshotAI/kimi-code>
- Getting Started：<https://moonshotai.github.io/kimi-code/en/guides/getting-started>
- Provider 配置：<https://moonshotai.github.io/kimi-code/en/configuration/providers>
- 配置文件说明：<https://moonshotai.github.io/kimi-code/en/configuration/config-files>
