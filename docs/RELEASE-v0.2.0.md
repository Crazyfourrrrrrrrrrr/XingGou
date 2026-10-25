# XingGou v0.2.0 · 星构工具箱

StarScene Studio 现更名为 **XingGou / 星构工具箱**，GitHub 仓库同步更名为 [Crazyfourrrrrrrrrrr/XingGou](https://github.com/Crazyfourrrrrrrrrrr/XingGou)。本版更新品牌、文档、发布名称，并保留旧工程与配置兼容性。

[观看宣传视频 · 1080p](https://github.com/Crazyfourrrrrrrrrrr/XingGou/releases/download/v0.2.0/XingGou-promo-1080p.mp4)

## 工具能力

- 在本机浏览器搜索、拖放和编辑千星原生资产，支持组合、撤销重做与工程自动保存。
- 通过离线规则或 OpenAI 兼容接口，将文字想法转成设计草案与可编辑场景。
- 优先复用游戏现成完整原生模型，缺资源时明确显示，不自动用白模拼搭代替。
- 固定布景默认导出为独立静态单位 GIA；导出带材质 GLB 后可在 Blender 中继续使用。
- 提供 stdio MCP，让外部 AI 客户端编辑同一工程。

## 更名与兼容

- 新源码包为 `XingGou-0.2.0-source.zip`，目录和界面使用 XingGou 品牌。
- 既有 `.starscene.json` 和 `starscene/1` 工程继续使用，不要求转换工程格式。
- 新增 `XINGGOU_*` 环境变量，保留旧 `STARSCENE_*` 配置兼容。MCP 示例服务名改为 `xinggou`。
- 历史 [v0.1.3](RELEASE-v0.1.3.md)、[v0.1.4](RELEASE-v0.1.4.md) 发布说明与验证记录保留当时名称和实际结果。

本版更名不改变原生资产优先、固定布景默认静态导出的策略，也不宣称新增性能提升。

## 本版验证与宣传素材

- 无外部资产库运行 33 项检查：23 项通过、10 项资源集成测试跳过；实际验证新旧请求头兼容、环境变量优先级及测试密钥不落盘。
- 新品牌界面的独立浏览器实录无脚本错误；实际下载包含 47 个静态单位、0 个动态父级、0 个装饰组件的 GIA 与带材质 GLB。
- 发布页附 57 秒横版 1080p 宣传片、封面与中文字幕文件。视频明确标注离线规则布局演示；接口画面只展示配置能力，没有冒充已连接的 AI 服务。

## 运行与资产

需要 Python 3.10+、支持 WebGL 2 的现代浏览器，以及自行准备的本地资产库。下载源码、配置 `config.local.json` 后运行：

```sh
python launch.py
```

源码不附游戏模型、贴图或完整资产目录，不会自动下载缺失资源。资产库结构、配置与导入步骤见 [README](../README.md)。

既有静态 V4 的用户实机反馈确认负载恢复正常，属于定性确认，没有具体降幅数值。主变更、历史浏览器和 Blender 测试的范围见[验证记录](VALIDATION.md)；新版自动检查结果以仓库 Actions 为准。

XingGou 采用 GPL-3.0，第三方来源见 [THIRD_PARTY.md](../THIRD_PARTY.md)。游戏资产不因软件开源而获得新的分发授权。
