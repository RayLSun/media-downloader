# media-downloader

小红书笔记下载器：**视频 / 图文 / 文章**，纯本地实现，不依赖任何第三方解析站。

> 本仓库同时是 [Hermes Agent](https://github.com/NousResearch/hermes-agent) 的 `media-downloader` 技能载体：`skill/` 内是技能定义与平台逆向笔记，根目录是可独立运行的工具实现。

```
笔记链接 → 短链解析 → 抓笔记页 → __INITIAL_STATE__ 解析（og:meta 兜底）
        → 无水印视频直链 / 原图 / 正文 markdown / info.json
```

## 用法

```bash
pip install requests

# 最简：直接粘贴 App「复制链接」拿到的整段文案也行
python xhs_dl.py "https://www.xiaohongshu.com/explore/xxxx?xsec_token=xxxx"

# 需要登录态时：浏览器 F12 → Network → 任一请求 → 复制完整 Cookie 头
python xhs_dl.py "链接" --cookie "web_session=xxx; a1=xxx"

# 其他参数
python xhs_dl.py "链接" -o D:\downloads --no-video --info-only
python xhs_dl.py "链接" --proxy http://127.0.0.1:7890
```

支持输入：`xiaohongshu.com/explore/<id>?xsec_token=...` ｜ `discovery/item/<id>` ｜ `xhslink.com` 短链 ｜ 24 位纯笔记 ID ｜ 混着链接的分享文案。

## 输出

```
downloads/<标题>_<id前8位>/
├── <标题>.mp4        视频笔记：无水印直链优先，失败降级 h264/h265 站点流
├── <标题>_01.webp    图文笔记：全部原图（去掉 !nd_ 缩放后缀）
├── <标题>.md         文章：标题 + 作者/IP + 正文 + 标签
└── info.json         元数据（作者、互动数、发布时间、标签、原始链接）
```

## 工作原理

| 层 | 实现 |
|---|---|
| 短链 | 跟随 `xhslink.com` 302，真实地址自带 `xsec_token` |
| 页面 | 直连小红书（默认**不走系统代理**，`trust_env=False`），带浏览器 UA |
| 主解析 | `window.__INITIAL_STATE__` → `note.noteDetailMap[id].note`（`undefined` → `null` 后 json.loads） |
| 兜底解析 | `og:title / og:description / og:image / og:video` meta 标签 |
| 视频无水印 | `video.consumer.originVideoKey` → `https://sns-video-bd.xhscdn.com/<key>`；降级 `media.stream.h264/h265/av1[].masterUrl` |
| 图片原图 | `imageList[].urlDefault` 去掉 `!nd_xxx` 后缀 |
| 稳健性 | 461/403/404 → 可读错误；下载 5xx/超时自动重试；协议相对地址自动补 `https:`；多候选回退 |

## Cookie 说明

- **多数公开笔记匿名即可解析**（og 兜底至少能拿封面/标题/描述）
- 完整数据（全部原图、无水印视频流、互动数）建议带 Cookie：浏览器登录小红书 → F12 → Network → 任一请求 → 复制整串 Cookie
- **绝不伪造 Cookie**：实测伪造 `web_session` 会被 500 拒掉，工具只原样透传你提供的

## 已知限制

- 2026 年起笔记链接普遍要求 `xsec_token`，请用 **App 分享 → 复制链接** 拿完整文案
- 长链接直接复制网页地址时若缺 token，会拿到空数据/模板页（工具会警告）
- 频繁请求会触发风控（HTTP 461），内置了退避重试，请勿批量高频使用
- 部分企业内网/代理出口 IP 已被小红书拉黑（错误码 300012 "IP 存在风险"），此时用直连

## 免责声明

仅用于**学习研究和个人合理用途**（如备份自己可访问的公开内容）。请遵守当地法律法规与小红书社区规范，尊重创作者版权；请勿用于商业用途、侵权用途或批量抓取、再分发他人内容。使用风险自担。

## 开发

```bash
python -m pytest tests/    # 17 个用例：链接解析 / __INITIAL_STATE__ / og 兜底 / 文章生成
```

依赖：仅 `requests`。Python ≥ 3.9。

## 仓库结构

```
├── xhs_dl/            工具源码（requests 唯一依赖）
├── tests/             18 个单测 + 真实页面回归 fixture
├── skill/             Hermes Agent 技能定义（SKILL.md + 平台笔记）
├── README.md / VERIFICATION.md
└── requirements.txt
```
