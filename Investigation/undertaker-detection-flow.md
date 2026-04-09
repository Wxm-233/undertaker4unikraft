# Undertaker 代码缺陷检测流程分析

本文基于当前工作区中的 Undertaker 源码，梳理它如何对编译时可配置系统软件进行静态分析，并识别与配置相关的代码缺陷。

## 1. 工具定位

Undertaker 的目标不是做通用程序分析，而是分析带有预处理条件的源代码，重点关注 `#if`、`#ifdef`、`#ifndef`、`#elif`、`#else` 这类块以及它们和配置模型之间的关系。README 明确说明它能检查预处理块在不同配置模型下是否“无法被选择或无法被取消选择”。

它的主要对象是 Linux 树一类的配置驱动源码，因为它依赖 Linux 风格的 Kconfig 模型、Makefile 结构和预处理条件约束。

## 2. 总体流水线

从源码到缺陷报告，大致分成六步：

1. 预先生成配置模型。
2. 加载模型并选定主模型。
3. 解析源文件中的预处理块。
4. 把代码约束、构建系统约束和配置模型约束合并成公式。
5. 用 SAT 求解器判断公式是否可满足。
6. 根据结果生成缺陷报告文件。

这条链路在入口程序、模型装载、块分析器和 SAT 包装层里分别实现。

## 3. 配置模型如何进入分析器

### 3.1 先离线生成模型

Undertaker 不是直接读取 Linux 的 Kconfig 运行时状态，而是先把 Kconfig 转成模型文件。README 说明典型流程是先执行 undertaker-kconfigdump，再在 `models/` 下得到各架构的 `.model` 或 `.cnf` 文件。

对应脚本在 [python/undertaker-kconfigdump](../python/undertaker-kconfigdump) 中，它会：

- 通过 `dumpconf` 导出 RSF。
- 用 `rsf2model` 生成模型。
- 可选生成 CNF 版本。
- 追加 whitelist 和 blacklist 等元信息。

### 3.2 模型加载

模型装载逻辑在 [undertaker/ModelContainer.cpp](../undertaker/ModelContainer.cpp)。它支持：

- 传入单个模型文件。
- 传入模型目录，批量加载目录下的 `.model` 或 `.cnf`。

加载后，某个架构模型会成为主模型。主模型默认优先使用 `x86`，见 [undertaker/undertaker.cpp](../undertaker/undertaker.cpp)。如果文件本身是架构专属路径，系统会优先切换到对应架构模型。

### 3.3 模型内容

RSF 模型的实现位于 [undertaker/RsfConfigurationModel.cpp](../undertaker/RsfConfigurationModel.cpp)。它维护的是“符号到条件”的映射，并支持：

- 判断符号是否在配置空间内。
- 判断符号类型。
- 合并 ALWAYS_ON 和 ALWAYS_OFF 元信息。
- 通过 `doIntersect()` 计算公式中的可见部分、缺失符号和交集结果。

`ConfigurationModel::doIntersect()` 的核心作用是：把源码中的配置表达式和模型中存在的符号拼接成可交给 SAT 的公式，同时收集那些“存在于配置空间，但在模型中找不到”的符号，后续可判定为 referential defect。

## 4. 源码块如何被解析

### 4.1 用 PUMA 扫描预处理树

源文件由 [undertaker/PumaConditionalBlock.cpp](../undertaker/PumaConditionalBlock.cpp) 解析。它使用 PUMA 解析器读取 C/C++ 文件的预处理结构，构建出一个 `CppFile` 对象，再把每个条件块转成 `ConditionalBlock`。

每个块会保留：

- 起止位置。
- 原始条件表达式。
- 父块和前序块关系。
- 是否为 `if`、`elif`、`else`、`ifndef` 等。

### 4.2 条件表达式标准化

在 [undertaker/ConditionalBlock.cpp](../undertaker/ConditionalBlock.cpp) 中，`lateConstructor()` 会把条件表达式做一层规范化处理：

- 去掉 `defined` 语义上的干扰。
- 进行宏展开和定义替换。
- 最终得到适合布尔公式处理的表达式字符串。

### 4.3 文件级块

`CppFile` 里有一个人工顶层块 B00，代表整个文件本身。这个设计很重要，因为 Undertaker 不只分析局部块，还会先判断整个文件是否本身就是不可达的。

## 5. 缺陷检测的核心逻辑

真正的缺陷判断在 [undertaker/BlockDefectAnalyzer.cpp](../undertaker/BlockDefectAnalyzer.cpp) 中。

### 5.1 先做 dead，再做 undead

`analyzeBlock()` 的策略是先构造 `DeadBlockDefect`：

- 如果块的条件在当前模型下不可满足，就判定为 dead。
- 如果不是 dead，再尝试 `UndeadBlockDefect`。
- 如果 undead 也不成立，说明块看起来正常。

这是一种“先找永远不可达，再找永远不可取消”的双向检查。

### 5.2 公式是怎么拼出来的

`BlockDefectAnalyzer::getBlockPrecondition()` 会把以下内容一起拼成公式：

- 块自身的代码条件。
- 文件级构建系统条件。
- Kconfig 模型中能展开出来的约束。
- 如果模型是完整的，还会加入 missing items 的否定约束。

也就是说，最终 SAT 检查的不是单一 `#ifdef` 条件，而是“代码条件 + 构建条件 + 配置模型”的组合。

### 5.3 dead 分析的判断顺序

在 `DeadBlockDefect::isDefect()` 中，判断顺序是：

1. 先检查代码条件本身是否矛盾。如果连代码表达式都不可满足，就是 implementation defect。
2. 再检查模型交集后的 Kconfig 公式是否可满足。如果不可满足，就是 configuration defect。
3. 再检查构建系统条件。如果构建条件不可满足，就是 build system defect。
4. 最后如果模型是完整的，再看是否存在 missing symbols 导致的 referential defect。

### 5.4 undead 分析的判断顺序

`UndeadBlockDefect::isDefect()` 与 dead 类似，但它先构造“父块成立且当前块不成立”的条件：

- 如果在父块成立的前提下，当前块始终无法取反成立，则属于 undead 相关问题。
- 之后同样会依次检查代码、Kconfig、构建系统、missing symbol。

### 5.5 为什么会跨架构复查

如果某个块不是架构专属文件，Undertaker 会把它拿到所有已加载模型上做 crosscheck。只有当它在所有架构上都构成缺陷时，才会被标记成 global defect。

如果文件本身就是架构专属路径，则会直接视作全局缺陷，因为它不适用于别的架构。

## 6. SAT 求解器在其中做什么

SAT 逻辑封装在 [undertaker/SatChecker.cpp](../undertaker/SatChecker.cpp)。它把文本形式的布尔公式交给 CNFBuilder，再用 Picosat 检查可满足性。

这里有两个关键点：

- `operator()` 负责把公式送进 CNF 构建器并检查 SAT。
- `checkMUS()` 可以调用 picomus，计算最小不可满足子集，用于解释为什么某个块不可达。

因此 Undertaker 不只是给出“有问题”，还可以进一步解释“为什么有问题”。

## 7. 入口程序如何组织整个分析

入口在 [undertaker/undertaker.cpp](../undertaker/undertaker.cpp)。它负责：

- 解析命令行参数。
- 装载模型。
- 读取工作列表或命令行文件列表。
- 分派分析任务。
- 多进程并行处理多个文件。

对于 dead 分析，`process_file_dead_helper()` 会：

- 解析文件。
- 删除旧的 `.dead` 结果。
- 选定主模型。
- 先分析 B00，再分析每个条件块。
- 为每个 defect 调用 `writeReportToFile()`。

`process_file_dead()` 外面再包一层线程超时控制。这个设计说明它把单文件分析当作一个相对独立的、可能耗时很长的 SAT 工作单元。

## 8. 输出结果是什么样

缺陷结果由 `BlockDefect::writeReportToFile()` 写出，文件名格式大致是：

- `<源文件>.<块ID>.<缺陷类型>.<locally/globally>.<suffix>`

其中缺陷类型包括：

- `code`
- `kconfig`
- `missing`
- `no_kconfig`
- `kbuild`

输出文件正文会写：

- 块位置。
- 完整公式。
- 各架构对应的缺陷类型映射。

如果启用了 MUS，还会额外生成 `.mus` 文件，帮助解释最小矛盾公式。

## 9. Undertaker 为什么几乎只能分析 Linux

这个结论从源码里能直接看出来：

1. 模型生成链条是 Linux Kconfig 导向的。`undertaker-kconfigdump`、`dumpconf`、`rsf2model` 这些工具就是围绕 Linux Kconfig 工作的。
2. 文件解析和构建系统解析明显假设了 Linux 风格目录和 Makefile 结构。`undertaker-linux-tree` 就是一个专门扫描 Linux 树的脚本。
3. 代码中默认主模型是 `x86`，并且大量逻辑都围绕 `CONFIG_` 命名空间。
4. 配置空间判断、黑白名单、架构目录、precondition 推导都依赖 Linux 这一套约定。

所以它虽然在理论上是“编译时可配置系统软件”的分析器，但工程实现事实上是 Linux 绑定的。

## 10. 一句话总结

Undertaker 的缺陷检测流程可以概括为：先把 Linux Kconfig 转成可计算的配置模型，再解析源文件中的条件编译块，把代码条件、构建条件和配置模型约束合成 SAT 公式，最后通过求解结果判断块是否 dead、undead、global defect 或特定类型的配置缺陷。
