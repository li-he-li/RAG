## Why

法律从业者在多案件与多文书场景下，难以快速定位与当前案件在“案件整体语义”和“争议点证据段落”层面都相似的历史材料，导致检索成本高、遗漏风险高。当前需要将“相似检索 + 可溯源证据定位”建设为核心能力，以支撑后续 Web 大前端的一体化能力扩展。

## What Changes

- 新增核心能力：面向法律场景的双层相似检索（文档级 + 段落级）。
- 支持争议点导向的段落级证据召回与排序，输出可解释的命中原因。
- 新增 DeepSeek 对话检索能力：通过对话提问获取数据库证据支撑的答案与引用。
- 建立统一标识体系：文档大标识（doc_id）与段落小标识（para_id）。
- 检索结果必须提供可溯源信息：文件名、行号区间、证据摘录、版本标识。
- 定义稳定的检索服务契约，供后续 Web 大前端作为核心能力直接集成。
- 明确依赖准备机制：数据库（PostgreSQL、Qdrant）和向量模型（BAAI/bge-m3、bge-reranker-v2-m3）由项目初始化流程自动下载、安装/拉取并完成可用性检查。

## Capabilities

### New Capabilities
- `legal-similarity-search`: 法律文书的双层相似检索与证据溯源能力，覆盖文档级相似、争议点段落级定位、结果解释与文件名/行号级引用。

### Modified Capabilities
- None.

## Impact

- Affected systems: 法律文书解析、向量索引、检索与重排、结果解释、前端检索接口。
- Affected APIs: 新增/扩展相似检索 API 与对话 API，返回文档级命中、段落级证据明细及对话答案引用。
- Data model impact: 新增/扩展文档与段落标识字段（doc_id、para_id、line_start、line_end、version_id 等）。
- Dependencies: 向量数据库、嵌入模型、文本切分与结构化解析组件。
- Environment setup: 首次运行通过自动化初始化流程准备 PostgreSQL、Qdrant 以及 BAAI/bge-m3、bge-reranker-v2-m3，并在启动前执行可用性验证。
- Product impact: 该能力为核心功能，不按可插拔插件定位，需作为主流程能力纳入后续 Web 大前端。
