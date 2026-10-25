# 星构工具箱 XingGou

![星构工具箱 XingGou](docs/images/banner.svg)

在本机浏览器里，用千星奇域的现有原生资产设计场景，把文字想法转成可编辑布局，再导出 GIA 或带材质的 GLB。

**v0.3.0 · Windows x64 便携完整版 · 工具源码 GPL-3.0**

原 StarScene Studio 现更名为 **XingGou / 星构工具箱**；继续兼容旧 `.starscene.json` 工程和 `STARSCENE_*` 环境变量。

[![Tests](https://github.com/Crazyfourrrrrrrrrrr/XingGou/actions/workflows/tests.yml/badge.svg)](https://github.com/Crazyfourrrrrrrrrrr/XingGou/actions/workflows/tests.yml)

[下载完整素材版](https://github.com/Crazyfourrrrrrrrrrr/XingGou/releases/download/v0.3.0/XingGou-0.3.0-full.zip) · [源码版](https://github.com/Crazyfourrrrrrrrrrr/XingGou/releases/download/v0.3.0/XingGou-0.3.0-source.zip) · [观看 v0.2.0 宣传视频 · 1080p](https://github.com/Crazyfourrrrrrrrrrr/XingGou/releases/download/v0.2.0/XingGou-promo-1080p.mp4) · [报告问题](https://github.com/Crazyfourrrrrrrrrrr/XingGou/issues/new/choose)

- 搜索本地模型、拖放布景、变换编辑、多选组合、撤销重做和自动保存。
- 优先复用完整原生模型与原材质；缺资源时列出缺项，不自动用白模拼搭替代。
- 固定布景导出为独立静态单位，工程分组在导出时展开，无动态父实体。
- 无密钥的离线规则布局，以及可配置的 OpenAI 兼容接口：文字 → 草案 → 场景。
- GIA 引用游戏原生模板；GLB 可导入 Blender。另提供 stdio MCP，让外部 AI 客户端编辑同一工程。

**首选下载完整素材版。** 包含 **2,996 个独立 GLB 模型、3,291 张实际内嵌图片**及目录索引，附官方 Python 3.15.1 Windows x64 运行时。Windows 64 位用户完整解压后双击启动即可，**无需预装 Python 或另配素材库**。单独源码版不附素材和运行时，供自行配置使用。工具代码按 GPL-3.0 发布；模型、贴图保留原有权利，Python 运行时采用 PSF 许可。

[发布说明](docs/RELEASE-v0.3.0.md) · [验证记录](docs/VALIDATION.md) · [贡献指南](docs/CONTRIBUTING.md) · [第三方来源](THIRD_PARTY.md)

[![观看 XingGou 星构工具箱宣传视频](docs/images/editor-example.png)](https://github.com/Crazyfourrrrrrrrrrr/XingGou/releases/download/v0.2.0/XingGou-promo-1080p.mp4)

截图来自实际编辑器测试。上方宣传片为 v0.2.0 的历史介绍，片中“资产自行准备”针对当时的源码版；v0.3.0 完整素材版已包含模型、贴图和索引。

## 快速开始

日常使用需要支持 WebGL 2 的现代浏览器，无需 npm、pip、Blender、CDN 或云端托管。

### Windows x64 完整素材版（推荐）

1. 下载 `XingGou-0.3.0-full.zip`，完整解压。
2. 双击 **`启动星构.cmd`**。包内已含 Python 3.15.1 x64 和模型库，无需预装 Python、复制配置文件或另找素材。
3. 关闭服务时双击 `停止星构.cmd`。

程序通常打开 <http://127.0.0.1:8770>，端口占用时在 8771–8790 中选择空闲端口。保留解压后的相对目录结构：

```text
XingGou/
├─ 启动星构.cmd
├─ 停止星构.cmd
├─ launch.py
├─ library/             # 模型、内嵌贴图、索引及尺寸统计
│  └─ inventory.json
└─ runtime/
   └─ python/           # 官方 Windows x64 运行时及 PSF 许可
      └─ python.exe
```

完整包同时可供其他平台使用其中的工具和 `library/`；需要自行安装 Python 3.10+，再运行 `python launch.py`。附带的 `runtime/python/` 仅适用于 Windows x64。

### 单独源码版

下载 `XingGou-0.3.0-source.zip`。此包不附模型、贴图或 Python 运行时，需自行安装 **Python 3.10+**，将 `config.example.json` 复制为 `config.local.json`，按下文配置资产库，再启动：

```sh
python launch.py
# 仅启动服务，显示网址
python launch.py --no-browser
# 停止当前目录启动的服务
python launch.py --stop
```

没有资产库也能打开编辑器，但默认生成会显示缺少可用原生资源。11 种基元仍可手动使用，默认自动布局不以这些基元填补资源缺项。

## 资产库与自定义路径

完整素材版会自动检测工具目录下的 `library/inventory.json`，通常无需修改配置。本次素材库包含 **2,996 个独立模型，其中 2,367 个已绑定游戏模板编号**；其余可预览，需自行确认绑定，不猜测编号。GLB 文件合计约 **1.58 GB（压缩前）**。

索引共有 3,032 行，包含 2 行模型别名和 34 行无静态模型的状态记录；独立模型数量按实际 GLB 文件统计。本节其余内容适用于源码版或需要切换到其他资产库的用户。

资产库由 GLB 文件、索引和可选尺寸统计组成，也可放在工具目录之外：

```text
MyAssetLibrary/
├─ inventory.json
├─ master-verification.json     # 可选：尺寸与网格统计
└─ models/
   └─ example_house.glb         # 自行准备的模型及材质
```

`config.local.json` 示例：

```json
{
  "assetRoot": "../MyAssetLibrary"
}
```

相对路径以工具源码目录为起点。也可使用绝对路径，或设置环境变量 `XINGGOU_ASSET_ROOT`（兼容 `STARSCENE_ASSET_ROOT`）；修改配置后重启服务。未显式指定路径时先检测包内 `library/`；没有内置库时沿用旧版的 `../Miliastra-Asset-Library` 路径。

`inventory.json` 是 JSON 数组。下面仅演示结构：

```json
[
  {
    "id": "local_house",
    "name": "示例房屋",
    "group": "建筑",
    "internal_name": "example_house",
    "glb": "models/example_house.glb"
  }
]
```

- `glb` 是相对资产库根目录的路径；GLB 应包含可在浏览器加载的模型和材质。
- `internal_name` 用于合并同一模型的别名，需稳定且能与尺寸统计对应。
- 字符串 `id` 只作为本地标识，可预览但不会自动成为游戏编号。确认原生模板后，可在属性面板绑定真实编号。
- 如果已准确确认原生模板，可把 `id` 写为 JSON 整数；不要把未知本地编号当作游戏模板编号。
- 可选的 `master-verification.json` 格式为 `{"assets": [...]}`，记录包含 `internal_name`、`dimensions_in_blender: [x, y, z]` 和可选 `total_triangles`。尺寸采用 Blender Z-UP，目录加载时转换为编辑器 Y-UP。没有统计时尺寸暂按 1×1×1，自动布局间距可能不准确。

完整素材版使用随包目录；切换自定义库后，资产数量和示例工程的可用性取决于该库的模型及模板映射。并非所有模型都有已确认的游戏模板编号；未绑定模型可预览，但会阻止 GIA 导出。工具不会猜测绑定或自动补发自定义库中缺失的资产。

## 编辑与生成

1. 左侧搜索模型，双击添加或拖到画布定位。关闭“仅显示已绑定游戏编号”后可预览未绑定模型。
2. W 移动、E 旋转、R 缩放、F 聚焦；右键旋转视角，中键平移，滚轮缩放。
3. Shift 多选，Ctrl+D 复制，Delete 删除，Ctrl+Z 撤销，Ctrl+Shift+Z 重做。
4. 多选后“组合”保存为可复用资产。组合仅是工程编辑结构，GIA 导出会展开；旋转过的子物件宜使用等比缩放，导出器会拒绝无法表达的剪切变形。
5. 顶部“保存工程”下载 `.starscene.json`。工程自动保存在本地，迁移时需同时配置对应资产库。

### 从文字生成场景

**离线布局**无需接口或密钥，按村庄、营地、遗迹、集市等主题及数量、尺寸选择资产，是确定性规则生成。

**AI 模式**在设置中填写 OpenAI 兼容接口地址、模型 ID 和可选密钥。先生成并修改设计草案，再生成可编辑场景，可以替换或追加到工程。

默认使用目录里可导出的完整原生资产。缺少桥、门楼、道路、水体等资源时，会在草案 `notes` 中列出缺项；不会猜测模板编号或铺设白模地面。添加单个物件时也先查找现成模型：只有无匹配资源且明确勾选允许基元补充时，才启用基元造型。离线补充提供木桥、拱门、水井、瞭望塔、摊位五种配方；AI 补充最多 160 个基元。

兼容接口使用 `POST <baseUrl>/chat/completions`。例如支持该接口的本地服务可配置为 `http://localhost:11434/v1`；具体地址和模型名以使用的服务为准。支持关闭 JSON 模式，以及选择 `max_tokens` 或 `max_completion_tokens`。默认输出上限为 12000 token。

AI 请求发送文字、草案及相关资产名称、编号和尺寸，不发送模型文件或贴图。地址和模型配置保存在本地 `projects/provider.local.json`；密钥只保存在服务内存，也可通过 `XINGGOU_AI_KEY` 提供（兼容 `STARSCENE_AI_KEY`），停止后需重新输入。兼容接口已用本地模拟 HTTP 服务验证，具体供应商和模型需自行验证。

## 导出 GIA 与 GLB

### GIA：在千星奇域内使用

点击“导出 GIA”。默认 `static_entities` 模式将固定布景写为独立静态单位，保留模型世界位置、旋转和缩放，**没有动态父级，也无需设置父级 0.01 缩放**。压缩包包含：

- 原生 `.gia` 与可继续编辑的 `.starscene.json`；
- 工程右手系世界坐标清单 `components.json`；
- 游戏左手系世界坐标清单 `native-components.json`；
- SHA-256、原生模板引用、静态配置和变换回读报告，以及导入说明。

将 `.gia` 放入游戏的原生导入目录，在千星编辑器“资产导入导出管理 → 加载外部资产”中加载。Windows 常见目录：

```text
%USERPROFILE%\AppData\LocalLow\miHoYo\原神\BeyondLocal\Beyond_Local_Export
```

保留各静态单位的相对位置与原缩放。文件名将类型和版本放在前面，例如 `静态V4·溪畔小聚.gia`；游戏物件使用 `静V4·木质房屋 1` 等短名。

任何可见模型未绑定模板编号都会阻止整个 GIA 导出，避免静默丢失或错误替换。可以隐藏该物件、先保留工程/GLB，或绑定自己已确认的编号。

本工具导出的是游戏已有模板引用，不把外部 FBX/GLB 上传成新游戏模板，也不生成节点图、运动或交互行为。角色、生物、机关等需要另行确认实体类型和行为。水体、树叶、特效等浏览器材质可能近似显示；默认沿用 Y=0 地形，深河道需在原生地形工具中制作。

### GLB：在 Blender 中使用

在“场景 / 属性”面板选择“导出当前场景 GLB”，会打包已加载的可见模型与材质。使用 Blender 的 glTF 2.0 导入即可打开；Blender 不是运行编辑器的依赖。

## 已有验证

2026-10-25，测试者实际导入包含 **47 个完整原生模型、0 个基元**的静态 V4“溪畔小聚”后，反馈“负荷正常了”。这是定性实机确认，没有新区域负载数值，因此不宣称具体节省比例，也不把这次反馈扩大为材质、精确 TRS、碰撞或批量操作的专项验收。

0.1.3 静态导出的主变更完成时，在配置了真实资产库的本机环境中，33 项 Python 单元与集成测试通过，隔离浏览器回归没有非预期错误。后续仅命名修复未重跑整套测试。历史 0.1.2 GLB 已独立导入 Blender 5.2.2 LTS，36 张贴图全部内嵌、无无效图像。完整范围与版本区别见[验证记录](docs/VALIDATION.md)。

0.1.4 修复首次公开发布后的分发与 CI 配置。无外部资产库的干净源码副本已本地执行全部 33 项测试：22 项通过、11 项依赖真实资产库的集成测试明确跳过。远端 CI 结果以仓库 Actions 为准；本补丁不改变静态布景策略，也不宣称新增性能提升。

0.2.0 更新品牌、仓库与发布文件名，并保留既有工程和环境变量兼容性；原生资产优先、默认静态布景的行为保持不变。无外部资产库的 33 项测试中，23 项通过、10 项资源集成测试明确跳过；新旧请求头、MCP 地址配置与密钥不落盘均有实际检查。宣传片使用独立演示工程实录，确认新界面无脚本错误，导出为 47 个静态单位、0 个动态父级、0 个装饰组件。

0.3.0 增加完整模型库与官方 Python Windows x64 运行时，并自动检测包内 `library/`。便携运行时已实际通过 CMD 启动、服务健康检查及静态 GIA 导出。已有原生资产优先、默认静态导出行为保持不变。

## MCP 与开发

启动编辑器后，可在支持 stdio MCP 的客户端中配置 `mcp_server.py`。参考 [MCP 配置示例](examples/mcp-config.example.json)填写本机 Python 命令及脚本路径。示例服务名为 `xinggou`；可用 `XINGGOU_URL` 指定已启动服务地址（兼容 `STARSCENE_URL`）。

提供 `catalog_search`、`scene_get`、`scene_replace`、`scene_export`、`asset_recipes`。提交工程时必须携带读取到的 `revision`，防止覆盖网页修改；默认策略同样是原生资产优先、固定布景静态导出。

开发测试使用统一命令：

```sh
python -m unittest discover -s tests -v
```

没有真实资产库时，相关资源集成用例会明确跳过；这与配置完整资产库后的全量集成验证、浏览器回归、Blender 验证和游戏实机测试是不同范围。

```text
core/catalog.py        外部资产索引与编号绑定
core/scene.py          工程校验、组合展开、版本保存
core/math3d.py         Y-UP TRS 与剪切检测
core/generator.py      离线规划与兼容模型接口
core/gia.py            导出封装与归档
core/static_gia.py     独立静态单位编码与回读
server.py              本机 HTTP 服务
web/                   无构建步骤的 Three.js 编辑器
mcp_server.py          stdio MCP 桥接
```

工程/GLB 使用右手 Y-UP、角度制、`Rz @ Ry @ Rx`；GIA 导出执行 `position=(-x,y,z)`、`rotation=(rx,-ry,-rz)`，缩放不变。不要在工程中再手动镜像。具体实现见 `core/coordinates.py`。

HTTP 服务仅监听 `127.0.0.1`。工程、导出、日志和个人配置保存在本机，源码发布包不包含这些运行数据。开发测试和提交要求见[贡献指南](docs/CONTRIBUTING.md)。

## 许可

工具代码采用 [GPL-3.0](LICENSE)。Three.js 使用 MIT 许可；GIA 编码参考和模板来自固定版本的 Miliastra-Tools。完整素材包内的游戏模型和贴图保留原有权利，与工具代码的 GPL 许可分开；官方 Python 运行时按 PSF 许可随包提供，许可文件保留在 `runtime/python/`。来源及许可见 [THIRD_PARTY.md](THIRD_PARTY.md)。
