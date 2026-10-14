# 贡献指南

感谢关注 freepool！欢迎 Issue 与 PR。

## 本地开发

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt
cd frontend && npm install && npm run build && cd ..
make test          # 后端 pytest
make dev-backend   # 启动后端 :8000
```

提交前请确保 `make test` 全绿。后端改动请附带 pytest 用例（代理/额度/档位路由的
现有用例在 `tests/`，可参考）。

## 添加平台适配器（Roadmap 核心项）

当前代码以阿里云百炼为首个实现，平台相关的点集中在：

- `app/config.py`：`bailian_*` 配置与各官方接口 URL
- `app/routers/gateway.py`：转发目标、usage 字段解析（`_usage_from_openai`）、
  可切换错误码集合 `SWITCHABLE_ERROR_CODES`
- `app/sync.py`：官方模型目录同步（`_paginate` 的响应结构）

多平台适配器的重构方向：抽出一个 `Provider` 协议（`chat_url` / `auth_headers` /
`parse_usage` / `switchable_codes` / `sync_catalog`），百炼作为第一个实现，
新平台只需注册一个类 + 一段 `.env` 配置。欢迎按这个方向提 PR，也可以先开
Issue 讨论设计。

## 提交约定

- `git add` 只加本次改动涉及的文件，不要 `git add -A`
- 绝不提交 `.env`、`data/`、任何真实 API Key 或账号数据
