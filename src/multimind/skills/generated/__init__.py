"""长尾层 Skill — LLM 基于公开文档生成。

生成的 skill 必须满足：
- 输入只能是公开 API 文档（非他人实现代码）
- ``skill.toml`` 记录 ``source_docs`` 和 ``generation_model``
- ``verified = false`` 默认不加载，需人工审核

生成流程见设计文档 §18.2。
"""
