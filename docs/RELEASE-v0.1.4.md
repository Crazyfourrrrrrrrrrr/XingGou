# StarScene Studio v0.1.4

这是首次公开发布后的分发与 CI 修复补丁。完整原生资产优先、固定布景默认独立静态单位、离线布局及 OpenAI 兼容接口等功能保持不变，不宣称新增性能提升。[v0.1.3 发布说明](RELEASE-v0.1.3.md)保留为历史记录。

## 修复内容

- 修正 GitHub Actions 中无资产库的测试路径配置，使用有效的静态相对路径。
- 公开源码包白名单纳入 GitHub 工作流、问题与贡献模板、文档截图，以及完整的 Three.js 模块清单。
- Git 保留上游模板与第三方文件的原始字节，避免换行转换影响固定来源的校验。

## 验证范围

无外部资产库的干净源码副本已在本地运行统一测试命令：

```sh
python -m unittest discover -s tests -v
```

共 33 项：22 项通过、11 项依赖真实资产库的集成测试明确跳过。GitHub Actions 覆盖 Linux/Windows 与 Python 3.10/3.12，远端结果以仓库 Actions 为准。

既有静态 V4 游戏内负载恢复正常的反馈是定性实机确认；本补丁未新增负载数值、材质、精确变换、碰撞或批量操作的专项实测。历史 33 项全通过和 Blender 验证的环境范围见[验证记录](VALIDATION.md)。

## 使用

下载 `StarSceneStudio-0.1.4-source.zip`，按 [README](../README.md)配置自己的本地资产库，使用 Python 3.10+ 运行 `python launch.py`。源码不附游戏模型、贴图或完整资产目录；校验值随发布文件提供。
