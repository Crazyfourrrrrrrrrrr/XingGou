# 参与 StarScene Studio

欢迎提交缺陷复现、兼容性改进、布局规则和导出验证。项目使用 Python 标准库与本地 Three.js 模块，日常运行不需要构建步骤。

## 本地开发

安装 Python 3.10+，按 [README](../README.md)配置自己的外部资产库：

```sh
python launch.py --no-browser
python -m unittest discover -s tests -v
```

浏览器测试还需要 Node.js、Playwright 和 Edge，使用独立源码副本及测试资产库运行：

```sh
node tests/browser-smoke.cjs
```

浏览器测试会编辑和保存当前测试工程，不应连接有未保存工作的个人服务。需要指定其他服务地址时，参见测试脚本的 `STARSCENE_URL` 环境变量。

GLB 独立验证可使用已安装的 Blender：

```sh
blender --background --factory-startup --python tests/blender_verify.py -- scene.glb report.json scene.blend
```

Blender 与浏览器测试依赖均属于开发验证工具，不是最终用户的运行依赖。

## 设计约定

- 默认选择现成完整原生资产和原材质，缺项明确显示；禁止自动白模兜底或猜测模板编号。
- 固定布景默认是独立静态单位，工程分组仅用于编辑。不要为了方便批量移动而重新添加动态父实体。
- 工程与 GLB 使用右手 Y-UP、角度制、`Rz @ Ry @ Rx`。游戏坐标转换统一由 `core/coordinates.py` 处理，避免二次镜像。
- 导出不能静默丢弃可见物件。新增二进制字段必须有真实模板或明确来源，并配合独立回读核对。
- 区分组件数量、区域负载、净成本和实机性能；没有实际读数时不推导节省比例。文件校验、浏览器、Blender 和游戏内验证分别记录。
- AI 接口和 MCP 修改工程时保留校验及 revision 冲突保护。

## 提交内容

缺陷报告请提供版本、操作步骤、预期和实际结果；必要时附脱敏日志、最小工程或不包含受限媒体的资产索引示例。GIA 问题可提供导出报告和回读结果；实机负载请注明关卡环境、新旧副本是否共存和读数来源。

代码提交说明解决的问题、行为变化和已执行的验证。没有执行的实机或供应商接口验证应明确说明。修改默认导出结构时，同时更新 README、发布说明、验证记录和对应检查。

不要提交密钥、个人绝对路径、账号标识、私人工程、运行日志或游戏模型/贴图。`config.local.json`、`projects/`、`exports/`、`.runtime/` 等运行文件应保持在版本控制之外；提交前仍需检查实际文件。

保留第三方源码的许可与来源。项目贡献按 GPL-3.0 发布，不能用软件许可证替代外部资产授权。
