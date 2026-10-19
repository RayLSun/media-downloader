# Xiaohongshu（小红书）平台笔记

## 访问机制（2026-10-19 已实测）

- 笔记链接形态：`/explore/<24位hex>`、`/discovery/item/<id>`、`/note/<id>`；**有效访问普遍要求 `xsec_token` 查询参数** —— 只能从 App「分享→复制链接」的整段文案里拿，或已登录 Web 会话里拿。缺 token 的链接返回 SPA 壳 + 模板 og:meta（空标题、占位封面图）。
- `xhslink.com/<code>` 短链 302 到**带 token 的**完整笔记 URL —— 从分享文案恢复 token 链的可靠途径。
- ✅ **真实笔记页（pc_share 来源的 xsec_token）匿名直连可解析**：HTTP 200，`noteDetailMap` 有完整数据（title/desc/interactInfo/imageList/video 流），无需 Cookie。
- 匿名 GET 列表页（如 `/explore`）返回 200 且 `__INITIAL_STATE__` 存在，但 `feed.feeds` 为空。
- 伪造 `web_session` cookie → HTTP 500。绝不伪造。
- 风控信号：HTTP 461 = 频率/风控；浏览器报错误码 300012「IP 存在风险」= 出口 IP 被标记（本机代理出口触发过；同一台机器 CLI 直连正常）。

## 数据提取

- 主路径：`window.__INITIAL_STATE__`（`<script>` 内 JSON 块；含 JS `undefined` 字面量，先替换成 `null` 再 `json.loads`）。
  - 笔记数据：`note.noteDetailMap[<note_id>].note` → `type`（`video`|`normal`）、`title`、`desc`（长文正文就在这）、`user.nickname`、`interactInfo.{liked,collected,comment,share}Count`、`ipLocation`、`time`（毫秒）、`tagList`、`imageList`、`video`。
- 兜底：og:meta 标签 —— `og:title`（带「 - 小红书」后缀）、`description`、`og:image`（协议相对地址，需补 `https:`）、`og:video`、`og:xhs:note_{like,collect,comment}`、`og:videotime`。
- 图片：`imageList[].urlDefault` / `url`；去掉 `!nd_xxx` 缩放后缀得原图。
- 视频无水印：`video.consumer.originVideoKey` → `https://sns-video-bd.xhscdn.com/<key>`。实测一条视频笔记（6ac64c13…）**无 originVideoKey**，降级 h264 流 `masterUrl` 成功下载，且其 URL 路径段为 `/258/`（公开文章称 258=无水印 / 259=带水印；未逐帧确认水印，但 258 与说法一致）。`stream.{h264,h265,av1}[].masterUrl` 中的地址是 `http://`（非 https），直接可用。
- 搜索引擎不收录笔记页（token 墙）—— 测试链接只能向用户要。

## 已落地实现

本仓库根目录 —— CLI `python xhs_dl.py "<分享文案>"`，仅依赖 requests，18 个单测。布局/用法见项目 README.md；已验证/待验证清单见项目 VERIFICATION.md（✅ 2026-10-19 真实视频笔记端到端通过：解析→元数据→文章 md→视频下载 2.1MB 合法 mp4）。仍待验证：xhslink 短链 302、图文笔记批量原图、含 originVideoKey 的笔记。