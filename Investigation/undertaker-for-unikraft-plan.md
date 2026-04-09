# Undertaker 适配 Unikraft 的魔改方案（建模与验证）

## 0. 目标与约束

目标是让 Undertaker 能在 Unikraft 上完成两件事：

1. 正确建模：把 Unikraft 的配置系统、构建系统约束转成 Undertaker 可消费的模型与文件前置条件。
2. 正确验证：对 Unikraft 源码中的条件编译块给出可靠的 dead 和 undead 缺陷判定。

约束是：

- 不能再依赖 Linux 专用的树结构假设。
- 要兼容 Unikraft 的 Config.uk 动态拼接机制。 
- 尽量复用 Undertaker 现有 SAT 与块分析核心，减少重写。

## 1. 先给结论：推荐走“三层改造”

建议把改造拆成三层：

1. 模型层适配：做 Unikraft 专用的 kconfigdump 与模型生成。
2. 构建约束层适配：做 Unikraft 的 file precondition 提取器。
3. 分析引擎层小改：修正 Linux 假设（架构识别、主模型默认值、批量脚本入口）。

这样可以最大化复用以下成熟能力：

- 块解析与表达式重写：undertaker/PumaConditionalBlock.cpp、undertaker/ConditionalBlock.cpp
- SAT 判定与 MUS：undertaker/SatChecker.cpp
- 缺陷分类：undertaker/BlockDefectAnalyzer.cpp

## 2. 现有 Linux 绑定点与对应改法

### 2.1 模型生成脚本 Linux 绑定

现状：python/undertaker-kconfigdump、undertaker/undertaker-linux-tree 默认围绕 Linux Kconfig 和 Linux 目录结构。

改法：新增 Unikraft 专用入口，不破坏原 Linux 流程。

- 新增 python/undertaker-unikraft-kconfigdump
- 新增 undertaker/undertaker-unikraft-tree

这两个脚本分别对应 Linux 版本的同名职责：

- 前者负责生成 models
- 后者负责批量扫描源码并调用 undertaker

### 2.2 架构识别规则 Linux 绑定

现状：CppFile 的架构识别正则只按 arch/一级目录判断，见 undertaker/ConditionalBlock.cpp。

对 Unikraft 来说，常见路径是二级或多级（如 arch/x86/x86_64、plat/kvm），仅取一级会误判。

改法：

- 把架构识别从“硬编码路径正则”改成“可配置映射规则”。
- 新增一个映射配置文件，例如 etc/undertaker/arch-map-unikraft.conf。
- 允许从路径映射到模型标签，例如：
  - arch/x86/x86_64 -> x86_64
  - arch/arm/arm64 -> arm64
  - plat/kvm -> platform_kvm（可选）

### 2.3 主模型默认值 Linux 绑定

现状：默认主模型是 x86，见 undertaker/undertaker.cpp。

改法：

- 当检测到 Unikraft 工作模式时，默认主模型改为 x86_64 或者“已加载模型的首个有效项”。
- 提供显式参数覆盖，继续保留 -M。

### 2.4 构建约束提取 Linux 绑定

现状：Undertaker 的 precondition 流程依赖 golem/minigolem 的 Linux Makefile 语义。

Unikraft 使用 Makefile.uk、import_lib、按配置拼装对象，语义不同。

改法：

- 新增 python/kbuildparse/unikraft/unikraft.py（参考 python/kbuildparse/linux/linux.py 的结构）。
- 实现 golem-unikraft 或 minigolem-unikraft，输出与现有格式一致的 preconditions。
- 最终继续把 FILE_xxx -> 条件 追加进 model/cnf，保持 C++ 核心不改。

## 3. 建模方案（最关键）

## 3.1 目标产物仍然是 model 或 cnf

Undertaker 核心要求的是：

- 符号蕴含关系（用于 doIntersect）
- 可选 CNF 模型（用于更快 SAT）
- 配置空间元信息（regex、ALWAYS_ON/OFF）

因此不应重写 BlockDefectAnalyzer，而应重写“上游生成器”。

### 3.2 Unikraft 模型生成流程（建议）

建议在 python/undertaker-unikraft-kconfigdump 内实现：

1. 环境注入
- 注入 UK_BASE、UK_APP、KCONFIG_* 变量，保证 Config.uk 中的 shell source 能展开。

2. 导出配置关系
- 复用 dumpconf 或等价导出器，把 Config.uk 树导成 RSF。
- 再调用 rsf2model 生成 .model。
- 可选调用 satyr 和 rsf2cnf 生成 .cnf。

3. 追加 Unikraft 特定元信息
- CONFIGURATION_SPACE_REGEX 默认沿用 CONFIG_.*。
- ALWAYS_ON/OFF 支持透传。
- 追加 FILE_ 前置条件（来自 4.1 节）。

4. 多维模型策略
- 最低可行：按 arch 产模型（x86_64、arm64）。
- 推荐：按 arch+plat 组合产模型（x86_64_kvm、x86_64_xen）。

说明：Unikraft 的平台差异很强，只按 arch 容易漏报或误报。

## 4. 验证方案（如何“正确”）

### 4.1 文件前置条件正确性验证

需要验证 FILE_xxx 条件是否真实反映构建系统。

建议做差分验证：

1. 固定一组配置（比如 defconfig、kvm、xen、arm64）。
2. 从真实构建产物提取“实际被编译文件集”（可用 compile_commands.json 或构建日志）。
3. 用 precondition + SAT 预测“应被编译文件集”。
4. 比对 precision 和 recall。

验收阈值建议：

- Recall 不低于 98%
- Precision 不低于 95%

### 4.2 缺陷判定正确性验证

用三类基准：

1. 人工可控样例
- 在小规模测试文件中构造 code/kconfig/kbuild/missing/no_kconfig 五类缺陷。

2. 真实 Unikraft 案例
- 在 lib、drivers、plat 中抽样已知条件块，人工确认可达性。

3. 回归测试
- 保证 Linux 模式结果不受影响。

验收要点：

- 缺陷类型分类正确。
- global 和 local 标注合理。
- MUS 输出可用（若启用）。

## 5. 分阶段落地计划

### 阶段 A：最小可用版本（2 到 3 周）

目标：先跑通 Unikraft dead 分析闭环。

改动：

1. 新增 python/undertaker-unikraft-kconfigdump
2. 新增 undertaker/undertaker-unikraft-tree
3. 在 undertaker/undertaker.cpp 增加一个 unikraft 模式开关
4. 主模型默认策略和架构识别做最小修补

交付：

- 能在 Unikraft 仓库输出 .dead 报告。
- 不保证覆盖率最优，但结果可用。

### 阶段 B：高可信版本（3 到 5 周）

目标：把 precondition 准确度做上去。

改动：

1. 新增 python/kbuildparse/unikraft/unikraft.py
2. 新增 minigolem-unikraft
3. 完整接入 FILE_ 前置条件生成

交付：

- dead 和 undead 结果显著稳定。
- 与真实构建文件集对齐。

### 阶段 C：工程化版本（2 到 3 周）

目标：可持续维护。

改动：

1. 文档与 man page（新增 undertaker-unikraft-tree.1）
2. CI：最小测试仓库 + Unikraft 样例回归
3. 统一输出格式，便于后续接入 checkpatch 风格流程

## 6. 建议修改点清单（按文件）

优先新增：

- python/undertaker-unikraft-kconfigdump
- undertaker/undertaker-unikraft-tree
- python/kbuildparse/unikraft/unikraft.py

优先改动：

- undertaker/undertaker.cpp
  - 新增 unikraft 模式参数
  - 主模型默认策略
- undertaker/ConditionalBlock.cpp
  - 架构识别逻辑改为可配置映射

尽量不改：

- undertaker/BlockDefectAnalyzer.cpp
- undertaker/SatChecker.cpp

原因：它们是成熟核心，复用收益最高。

## 7. 风险与对策

1. 风险：Config.uk 动态 source 导致模型导出不稳定。
对策：统一在脚本里固定环境变量，并缓存中间展开文件。

2. 风险：Makefile.uk 语义复杂，前置条件提取误差大。
对策：先做“保守可达”策略，逐步提高精度，配合差分验证。

3. 风险：多模型维度（arch+plat）导致计算量上升。
对策：先按主平台集做抽样 crosscheck，再全量运行。

## 8. 最终建议

最现实的路线不是“重写 Undertaker”，而是“把 Linux 绑定的入口与建模链替换为 Unikraft 版本”，并保留 Undertaker 已经成熟的三块核心：

- 条件块提取
- 公式拼接
- SAT 判定与缺陷分类

按这个路线改造，工程风险最低，且能较快得到对 Unikraft 可用且可解释的缺陷分析结果。