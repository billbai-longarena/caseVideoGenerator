# 成片发布与批量上传

## 两层文件结构

渲染链路和发布链路使用不同的文件名，避免为了改标题或集数破坏 Remotion、QA 和服务器约定：

```text
output/<project>/video/
├── case_video.mp4                    # 内部 master，稳定机器文件名
└── case_video_compressed_50m.mp4     # 内部上传副本，稳定机器文件名

publish/
├── FDE不复杂/S001_标题.mp4          # 一个主题的全部网站上传文件
├── 杯中故事/S030_标题.mp4
├── _masters/<主题>/S001_标题_master.mp4 # 可选 master 发布视图
├── manifest.json
├── manifest.csv
└── upload-list.txt
```

`output/<project>/video/`、`audio/`、`images/`、`qa/` 和根目录 `publish/` 都是可重建生成物，保持 Git 忽略。可提交内容仍是 `title.txt`、`narration.txt`、`storyboard_plan.json`、可选 `publication.json` 等源数据和配置。每个主题目录只放可上传 MP4；清单统一留在 `publish/` 根目录，因此打开主题目录即可连续选择 S001-S100 上传。

## 发布命名

默认文件名为 `S001_标题.mp4`：

- `S` 是默认前缀。
- `001` 是默认三位集数，保证一个 100 条的主题在文件管理器和上传工具中始终按 S001-S100 正确排序。
- 标题只读取项目根目录的一行 `title.txt`。
- `/ \\ : * ? " < > |` 会转换为安全的全角中文符号，控制字符和不安全尾部符号会被清理；旁白和封面标题不会被修改。

常用项目目录会自动推断栏目和集数，例如：

- `fde_ep01_*` → `publish/FDE不复杂/S001_标题.mp4`
- `baijiu_ep30_*` → `publish/杯中故事/S030_标题.mp4`
- `sales_case02_*` → `publish/销售不复杂/S002_标题.mp4`
- `sales_management_case20_*` → `publish/销售管理/S020_标题.mp4`

自定义栏目、目录名无法推断或需要停用旧版本时，在项目根目录添加 `publication.json`：

```json
{
  "enabled": true,
  "series": "custom-column",
  "seriesLabel": "自定义栏目",
  "outputFolder": "自定义主题第一季",
  "sequence": 3,
  "sequenceWidth": 3,
  "filenamePrefix": "S"
}
```

废弃或被新版本替代的项目设置 `"enabled": false`，批量发布时会跳过。栏目 slug 只使用 ASCII 字母、数字、点、横线和下划线；面向人的栏目名放在 `seriesLabel`。主题文件夹默认使用 `seriesLabel`，需要把同一栏目拆成多季或不同上传批次时用 `outputFolder` 单独指定。

## 单条发布

成片通过 QA 后运行：

```bash
scripts/case-video publish output/<project>
```

命令会：

1. 用 `ffprobe` 验证 master 同时包含视频流和音频流。
2. 按实际时长生成约 50 MB 的两遍 x264/AAC 副本；已有且仍然有效的新副本会直接复用。
3. 校验压缩前后分辨率、帧率和时长，并限制目标大小。
4. 优先用硬链接建立集中发布文件；跨文件系统时自动复制，避免无意义地占用双份磁盘。
5. 写入文件 SHA-256 和媒体规格并刷新三种清单。

只查看计划路径、不压缩也不写文件：

```bash
scripts/case-video publish output/<project> --dry-run
```

需要同时集中整理 master：

```bash
scripts/case-video publish output/<project> --include-master
```

## 批量发布

按一个或多个目录通配符选择已经渲染的项目：

```bash
scripts/case-video publish-batch output --pattern 'fde_ep*'
scripts/case-video publish-batch output --pattern 'fde_ep*' --pattern 'baijiu_ep*'
```

不传 `--pattern` 时会扫描 `output/` 下一层所有带 `video/case_video.mp4` 的项目。建议首次先加 `--dry-run`，确认历史实验项目没有进入队列。

批处理会拒绝同一主题文件夹中重复的集数，即使它们使用了不同的内部栏目 slug。遇到旧版、测试版和正式版共存时，应给被替代项目设置 `"enabled": false`，或为正式项目明确指定正确集数，不能让上传顺序依赖文件名碰巧不同。

## 上传清单

- `manifest.csv`：适合人工核对或导入表格，使用 UTF-8 BOM，中文标题在常用表格软件中可直接打开。
- `manifest.json`：适合发布网站脚本、API 客户端或后续自动化读取。
- `upload-list.txt`：按栏目和集数排序的一行一个相对路径，可交给批量上传脚本。

清单包含栏目、集数、标题、发布文件名、来源项目、相对路径、时长、字节数、画面规格、帧率和 SHA-256。`publish/` 可整体删除后重建，不承担版本历史；Git 只记录生成它的代码和项目元数据。
