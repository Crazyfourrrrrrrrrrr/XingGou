# 第三方来源与许可

## Three.js 0.180.0

- 项目：<https://github.com/mrdoob/three.js>
- 官方 npm 包：<https://registry.npmjs.org/three/-/three-0.180.0.tgz>
- 许可：MIT，全文见 `licenses/three-LICENSE`。
- 发布包 SHA-256：`ad66d724565ee29a2467277fa84daa5ed0211d6b8d446e9ef29f6bae0cd14144`。
- 保留 build 与 examples/jsm 官方模块；编辑器引用本地副本，运行时无需 CDN。

## Miliastra-Tools / GPT2Gia

- 上游：<https://github.com/Ayn1631/Miliastra-Tools>
- 固定提交：`44db6abd01ac80d135ad3c06b3ea388e879b5b69`。
- 许可：GPL-3.0。本工具整体采用同一许可，全文见根目录 `LICENSE`。
- 原样保留的源码和模板：
  - `vendor/miliastra_tools/miliastra_core/export/decoration.py`
  - `vendor/miliastra_tools/miliastra_core/protobuf/wire.py`
  - `vendor/miliastra_tools/Template/GPT2Gia_decorations.gia`
  - `vendor/miliastra_tools/Template/GPT2Gia_entities.gia`（0.1.3 独立静态单位模板，同一固定提交）
- `decoration.py` SHA-256：`6aa18695f97ba32a9cabb23a154b2fbc251b24cd98572697e439bb9a26c96a54`。
- `wire.py` SHA-256：`831f2d4924281d2185bdf45738c4d8c9b946f3bc4fcc822261c16aa76f0b9e97`。
- 使用独立的轻量包入口，避免加载图像、GUI 和 protobuf 的无关依赖；上面两个源文件未修改。

原生 ID 段检查参考本机 BrickForge 已修正的实现与原生模板证据：实体 `0x40400000`，装饰物 `0x40000000`，只在低 20 位分配随机非零编号。星构工具箱独立实现了场景原点、链接和世界变换回读检查，不复用其运动/指针等积木游戏组件。

## 外部资产与目录

- 模型和贴图属于用户配置的外部游戏资产库，XingGou 源码包不含这些文件。
- 当前本机库的原生目录映射来自既有提取流程；原始目录参考 `hang-ZYM/qianxing-format-docs`（目录数据 CC BY 4.0），经 `8itlab/genshin-miliastra-mcp`（代码 MIT）的目录资料对照。具体来源记录保留在外部库 `provenance/`。
- 资产原本的游戏/作者权利不因软件 GPL 或目录许可而改变。

## 接口文档与参考工作流

- OpenAI Chat Completions 参数：<https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create>
- JSON 模式与输出检查：<https://developers.openai.com/api/docs/guides/structured-outputs>
- JSON 模式只能帮助保证 JSON 语法；本工具另行验证场景结构和目录编号。不同兼容服务的参数支持情况以其文档为准。
- 用户提及的“渊星工具箱”工作流参考作者公开演示：<https://www.bilibili.com/video/BV1rcHr6uEji/>。XingGou 为独立编写的本机网页实现，未复制该工具源码、界面资产或商业服务。

星构工具箱源码中的其余界面、场景 schema、离线布局、基元配方、接口、MCP 桥接与测试为本项目实现，按 GPL-3.0 分发。

## 0.1.1 坐标转换依据

本机已核对的 AnimeStudio 提交 `e616e3f824f47dd68cfbd44977bf8584756ac446` 中，`AnimeStudio.Utility/ModelConverter.cs` 的 `SetFrame` 导出位置 `(-x,y,z)`、四元数 `(qx,-qy,-qz,qw)`，网格顶点和法线也翻转 X。星构对这些 GLB 进行右手系编辑，因此在生成原生 GIA 时恢复该反射。2026-10-25 用户原生截图提供了 V1 校准方向相反的实际证据。

新转换与测试由本项目实现，不修改保留的 Miliastra-Tools 上游文件。不同模型来源若采用不同本地基底，需另作标定。

## 0.1.3 静态布景导出

独立静态单位使用上述固定提交中的 `GPT2Gia_entities.gia`，原样复制并沿用 GPL-3.0；静态编码封装与回读检查由本项目实现。工程中的组合在导出时展开，不使用动态父实体。导出结构符合模板不代表已通过游戏内批量放置或负载验收，实测状态见 `docs/VALIDATION.md`。
