# Azure Speech TTS 调用说明

> 定位说明：本文保留 Azure Speech 的历史调用细节。当前默认音色、profile、时间轴和生产命令以 `docs/knowledge-base/tts-and-timing.md` 与 `scripts/case-video` 为准。

本文档用于其他项目复用 Azure Speech 文本转语音调用方式。默认使用 Azure Speech REST API，不依赖 Speech SDK。

## 1. 环境变量

推荐在项目 `.env` 中配置：

```bash
AZURE_SPEECH_KEY="你的 Azure Speech key"
AZURE_SPEECH_REGION="eastus"
```

也可以使用兼容命名：

```bash
AZURE_TTS_KEY="你的 Azure Speech key"
AZURE_TTS_REGION="eastus"
```

可选默认音色：

```bash
AZURE_TTS_GENDER="female"  # female 或 male
AZURE_TTS_PROFILE="dragon-broadcast"
```

如果设置 `AZURE_TTS_VOICE`，完整 voice name 会覆盖 `AZURE_TTS_GENDER`。命令行 `--gender` 又会覆盖环境里的 `AZURE_TTS_VOICE`，方便部署端按用户选择切换男女声。

当前 casevideo 项目已验证 `.env` 里的 `AZURE_DOCUMENT_INTELLIGENCE_KEY` 也能用于 Azure Speech TTS，因为该 key 对应的 Azure 资源可访问 Speech 服务。其他项目不要默认假设 Document Intelligence key 可用，优先使用正式的 `AZURE_SPEECH_KEY`。

不要把 key 打印到日志、文档或提交记录中。`.env` 不要提交。

## 2. 已验证配置

本项目已验证：

```text
region = eastus
voice list endpoint = 200 OK
output format = riff-24khz-16bit-mono-pcm
sample rate = 24000 Hz
channels = mono
codec = pcm_s16le
```

已验证中文 Dragon HD Latest 音色：

```text
女声：zh-CN-Xiaochen:DragonHDLatestNeural
男声：zh-CN-Yunfan:DragonHDLatestNeural
```

默认采用 `B_broadcast.mp3` 对应配置：男声 `rate=+14%`、`pitch=+4%`；女声 `rate=+7%`、`pitch=+1%`；整段合成；段间静音 `0.45s`。

## 3. REST Endpoint

查询 voice list：

```text
GET https://{region}.tts.speech.microsoft.com/cognitiveservices/voices/list
```

合成语音：

```text
POST https://{region}.tts.speech.microsoft.com/cognitiveservices/v1
```

必需请求头：

```text
Ocp-Apim-Subscription-Key: <Azure Speech key>
Content-Type: application/ssml+xml
X-Microsoft-OutputFormat: riff-24khz-16bit-mono-pcm
User-Agent: your-app-name
```

## 4. 最小连通性测试

```bash
set -a
source .env
set +a

curl -sS \
  -H "Ocp-Apim-Subscription-Key: ${AZURE_SPEECH_KEY:-$AZURE_TTS_KEY}" \
  "https://${AZURE_SPEECH_REGION:-$AZURE_TTS_REGION}.tts.speech.microsoft.com/cognitiveservices/voices/list" \
  -o azure_voices.json
```

如果返回 JSON 列表，说明 key 和 region 匹配。若返回 `401`，通常是 key 和 region 不匹配，或 key 不属于 Speech/可访问 Speech 的 multi-service 资源。

## 5. Python 最小合成示例

保存为 `azure_tts_sample.py`：

```python
import html
import os
import urllib.request
from pathlib import Path


def load_dotenv(path=".env"):
    p = Path(path)
    if not p.exists():
        return
    for raw in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_dotenv()

region = os.getenv("AZURE_SPEECH_REGION") or os.getenv("AZURE_TTS_REGION") or "eastus"
key = os.getenv("AZURE_SPEECH_KEY") or os.getenv("AZURE_TTS_KEY")
if not key:
    raise RuntimeError("Missing AZURE_SPEECH_KEY or AZURE_TTS_KEY")

voice = "zh-CN-Xiaochen:DragonHDLatestNeural"
text = "这里是销售不复杂。帮你揭开销售的魔法秘密，让销售不再复杂。"

ssml = f"""<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="zh-CN">
  <voice name="{html.escape(voice)}">
    <prosody rate="+7%" pitch="+1%">{html.escape(text)}</prosody>
  </voice>
</speak>""".encode("utf-8")

request = urllib.request.Request(
    f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1",
    data=ssml,
    method="POST",
    headers={
        "Ocp-Apim-Subscription-Key": key,
        "Content-Type": "application/ssml+xml",
        "X-Microsoft-OutputFormat": "riff-24khz-16bit-mono-pcm",
        "User-Agent": "azure-tts-sample",
    },
)

with urllib.request.urlopen(request, timeout=60) as response:
    audio = response.read()

Path("azure_tts_sample.wav").write_bytes(audio)
print("saved azure_tts_sample.wav")
```

运行：

```bash
python3 azure_tts_sample.py
ffprobe -v error -show_entries stream=codec_name,sample_rate,channels,duration -of json azure_tts_sample.wav
```

## 6. SSML 语速和音色

女声：

```xml
<voice name="zh-CN-Xiaochen:DragonHDLatestNeural">
  <prosody rate="+7%" pitch="+1%">要合成的中文文本</prosody>
</voice>
```

男声：

```xml
<voice name="zh-CN-Yunfan:DragonHDLatestNeural">
  <prosody rate="+14%" pitch="+4%">要合成的中文文本</prosody>
</voice>
```

语速建议：

```text
默认广播档：男声 +14% / +4% pitch；女声 +7% / +1% pitch
旧的全局 +4%：仅用于 legacy sentence 模式兼容
```

不要一次提交整篇长稿。按空行分隔的完整段落合成；段内不手工插入句间静音，段间统一拼接 0.45 秒静音，并通过 Azure word boundary 生成 unit 时间轴。

## 7. 在 casevideo 项目中生成全片旁白

推荐使用统一 TTS 入口，默认走 Azure Speech，并按空行分隔的段落交替使用 Yunfan 男声和 Xiaochen 女声：

```bash
.venv/bin/python output/budweiser_apac_story_video/tts_compare/generate_tts.py \
  --engine azure \
  --project output/medical_device_case_video
```

需要女声先开场：

```bash
.venv/bin/python output/budweiser_apac_story_video/tts_compare/generate_tts.py \
  --engine azure \
  --project output/medical_device_case_video \
  --gender female
```

需要全片单一音色时，加 `--single-voice`。直接指定 `--voice` 也会使用单音色；同时提供 `--alternate-voice` 才会恢复双音色交替。

需要直接指定完整 Azure voice name 时，也可以调用底层脚本：

```bash
.venv/bin/python output/budweiser_apac_story_video/tts_compare/generate_azure_full.py \
  --project output/medical_device_case_video \
  --voice 'zh-CN-Xiaochen:DragonHDLatestNeural' \
  --single-voice
```

脚本会生成：

```text
<project>/audio/narration_azure.wav
<project>/narration.tts.txt
<project>/narration.tts.plan.txt
<project>/narration.timeline.json
```

如果 `<project>/rich_storyboard.json` 存在，脚本会自动把其中的 `audio` 字段更新为：

```json
"audio": "audio/narration_azure.wav"
```

## 8. 常见错误

`401 Unauthorized`：

```text
key 和 region 不匹配；或该 key 不是 Speech/multi-service 资源 key。
```

`400 Bad Request`：

```text
SSML 格式错误、voice name 不存在、output format 不支持。
```

语音生成成功但项目渲染没声音：

```text
确认 storyboard 的 audio 字段指向生成的 wav。
确认渲染前已把音频复制到播放器或 Remotion 的 public/audio 目录。
确认 timeline.duration 和 wav 时长接近。
```

中文数字读法不对：

```text
先在送入 TTS 前做文本归一化，例如把 2019 年改成 二零一九年。
不要只改屏幕字幕。
```
