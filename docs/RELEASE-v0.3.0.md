# XingGou v0.3.0 · 完整素材便携版

本版提供工具、GLB 素材库和官方 Python Windows x64 运行时。Windows 64 位用户完整解压后双击启动即可，无需预装 Python 或另配素材库；单独源码版继续提供。

## 选择下载包

| 下载包 | 内容 | 启动准备 |
| --- | --- | --- |
| `XingGou-0.3.0-full.zip`（推荐） | 工具、完整 `library/`、官方 Python 3.15.1 Windows x64 运行时 | Windows x64 直接双击启动 |
| `XingGou-0.3.0-source.zip` | 工具源码，不含模型、贴图和运行时 | 自备 Python 3.10+ 与资产库 |

完整素材版使用单个 ZIP，无需分卷。GLB 文件合计 **1,579,584,336 字节，约 1.58 GB / 1.47 GiB（压缩前）**；最终下载体积以发布文件为准。

## 素材内容

- **2,996 个独立 GLB 模型**，共 **3,291 张实际内嵌图片**。
- **2,367 个模型已绑定游戏模板编号**；其余模型可预览，需自行确认绑定，工具不会猜测编号。
- 3,032 行目录索引包含 2 行模型别名和 34 行无静态模型的状态记录，独立模型数按实际 GLB 统计。
- 附目录索引和尺寸统计，启动时自动检测 `library/inventory.json`。

这是本次整理的完整库，不表示游戏所有版本的全部资产均已收录。包含未绑定模型的 GIA 导出会明确拦截，避免错误替换。

## 快速开始

Windows x64：下载并完整解压 `XingGou-0.3.0-full.zip`，双击 `启动星构.cmd`。保留 `library/`、`runtime/python/` 与工具文件的相对位置；无需复制配置文件。停止服务可双击 `停止星构.cmd`。

其他平台也可使用完整包中的工具和 `library/`，自行安装 Python 3.10+ 后运行：

```sh
python launch.py
```

附带 Python 运行时仅适用于 Windows x64。需要切换资产库时，可使用 `config.local.json`、`XINGGOU_ASSET_ROOT` 或兼容的 `STARSCENE_ASSET_ROOT`。详细结构见 [README](../README.md)。

## 验证与旧版区别

便携 Python 运行时已实际通过 CMD 启动、服务健康检查及静态 GIA 导出。已有工具测试与静态 V4 定性实机反馈的范围见[验证记录](VALIDATION.md)；本版不宣称新增性能提升。

[v0.2.0 宣传片](https://github.com/Crazyfourrrrrrrrrrr/XingGou/releases/download/v0.2.0/XingGou-promo-1080p.mp4)与[发布说明](RELEASE-v0.2.0.md)保留为历史记录。片中“资产自行准备”针对当时的源码分发方式；v0.3.0 完整包已提供模型、贴图和索引，源码版仍需自备。

本版保持现成完整原生资产优先、固定布景独立静态单位、离线规则和 OpenAI 兼容接口，以及 GIA/GLB 导出；旧 `.starscene.json` 工程和环境变量继续兼容。

## 来源与许可

工具代码采用 GPL-3.0。游戏模型和贴图保留原有权利，不按 GPL 重新授权。官方 Python 3.15.1 Windows x64 embeddable 运行时按 PSF 许可分发，许可文件随包保留。工具及第三方代码来源见 [THIRD_PARTY.md](../THIRD_PARTY.md)。
