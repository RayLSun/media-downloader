---
name: media-downloader
description: Replicate downloader sites as standalone local projects.
version: 0.1.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [xiaohongshu, downloader, scraper, media]
    related_skills: [blocked-page-recovery]
---

# Media Downloader

## When to Use

用户要「下载某平台的视频/图文/文章」「复刻某个在线下载工具（不依赖原网站）」时。

复刻在线下载站（kukutool 类）为本地独立项目。用户的硬性要求：**完全独立实现，不依赖原网站** —— 直接对平台自身的公开页面数据实现，绝不调用、不包裹原工具站。

## 流程

1. **先侦察平台数据面，再写代码。** 匿名抓一个真实页面，看实际返回什么：SSR 状态块（`window.__INITIAL_STATE__` 等）、og: meta 标签、内嵌 JSON、移动端 API。不要只按博客/文档设计 —— 平台行为变得快（小红书已切到 token 门禁链接），一年前的博客描述的是过时机制。博客拿不到时用 web_search 找近期开源同类项目读它们的 README。
2. **网络路径先探测。** 本机系统代理是变量不是常量：CN 平台按出口 IP 风控，代理出口常被标记而直连可用。HTTP 层默认直连（`session.trust_env = False`），`--proxy` 作为可选参数；绝不能因此假设浏览器工具的失败代表站点不可达。
3. **分层解析、优雅降级。** 主路径 SSR 状态 JSON → 兜底 og:meta → 才报错。每种失败（已删除/私密/风控/登录墙/token 失效）映射到一条用户可读的明确提示。
4. **自底向上测试。** 合成 fixture 单测 → 匿名真实页面 fixture（落盘到 tests/ 供回归）→ 用户的真实链接端到端。真实页面 HTML 存 fixture，解析器回归不依赖网络。
5. **真实链接尽早向用户要。** token 门禁链接（xhslink 短链、xsec_token）无法凭空构造，搜索引擎也不收录（token 墙）——要一次是一次往返，自己找是一个会话。先建完其余部分，最后用用户链接收口。
6. **交付为 `D:/SunProjects/<项目名>/` 项目 + README + VERIFICATION.md。** VERIFICATION.md 列「已验证/待验证」清单，让后续会话能精确接续（如：待真实链接验证无水印直链）。

## Pitfalls

- **绝不伪造 cookie** —— 平台会校验，伪造 `web_session` 直接 HTTP 500。只原样透传用户提供的内容。
- **`requests` 顶层没有全部异常别名** —— 用 `requests.exceptions.*`（如 `ChunkedEncodingError`）；`except (TUPLE_VAR, Cls)` 里嵌裸元组会 TypeError。
- **媒体 URL 常是协议相对地址**（`//cdn…`）—— 下载前统一补 `https:`，否则 requests 抛 MissingSchema。
- **token 里的 `=` 会被 urlencode 编码成 `%3D`** —— 拼 URL 时传 `safe="=-._~"`，对服务器无差别但与用户粘贴的原链不同会破坏肉眼比对与 diff。
- **外部仓库的结论先实测再信** —— 公开文章写的字段路径可能过时或凭猜测；标清「已实测」与「未实测」，不要把传闻写进代码注释当事实。

## 平台笔记

- 小红书：`references/xiaohongshu.md`。已落地实现于 `D:/SunProjects/xhs-downloader`（仅依赖 requests），其 VERIFICATION.md 记录当前待真实链接验证项。

## GitHub 同步链（2026-10-19 起）

- 公开仓库：https://github.com/RayLSun/media-downloader （PUBLIC，main）
- 组成：工具（xhs-downloader 完整项目）在仓库根 + `skill/` 子目录（本技能的 SKILL.md + references）
- 同步方式：仓库副本在 `D:/SunProjects/media-downloader`（独立目录，非 symlink）。改动工具→重跑单测→复制到仓库（排除 downloads/缓存）→push 直连（`git -c http.proxy= -c https.proxy= push`）。复制时把 `D:/SunProjects/xhs-downloader` 字样替换为「本仓库根目录」。
- 真实 xsec_token 只会出现在 downloads/（已 gitignore）；推前扫描暂存区确认无完整 token。