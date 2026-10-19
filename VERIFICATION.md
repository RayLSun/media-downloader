# xhs-downloader 验证记录

## 环境
- 日期：2026-10-19
- Python：D:/Python/Python313/python.exe (3.13, requests 2.32.5)
- 网络：本机有系统代理 (127.0.0.1:7890)，工具默认 **trust_env=False 直连**

## 单元测试（18/18 通过）
覆盖：链接解析（explore/discovery/短链/纯ID/分享文案/非XHS拒绝）、\n
__INITIAL_STATE__（undefined→null、空 noteDetailMap、正常视频/图文笔记）、
og:meta 兜底、协议相对地址归一化、文章 markdown 生成。

## 真实网络验证（已验证项）
| # | 项目 | 结果 |
|---|---|---|
| 1 | 直连 `www.xiaohongshu.com` 首页 | ✅ 302 → /explore，正常 |
| 2 | 匿名抓 `/explore` 页面 | ✅ HTTP 200，36,211 字节，\n
`__INITIAL_STATE__` 可解析（feeds 匿名为空，符合预期）|
| 3 | 匿名抓笔记页（虚构 ID 65f3c16b000000001203ab65） | ✅ HTTP 200，og:meta 兜底生效（返回模板占位图）|
| 4 | CLI 全链路（假 ID） | ✅ 解析→元数据→文章→下载→进度条→正常退出 |
| 5 | CLI 错误路径（非 XHS 链接） | ✅ exit 2 + 可读错误 |
| 6 | **真实视频笔记端到端**（2026-10-19，用户提供 pc_share 链接） | ✅ 全链路通过，详见下节 |

## 真实笔记端到端详情（2026-10-19）
- 笔记：`6ac64c13000000001c02cbb8`「含胸驼背别光喊｜试试这几个动作✨」（Kiddycore体态日记，视频笔记）
- 来源链接：`discovery/item/…?xsec_token=ABiaEbXj…&xsec_source=pc_share`
- 解析：**`__INITIAL_STATE__` 主路径成功（匿名、无 Cookie）** —— noteDetailMap 完整
  （标题 / 正文 176 字 / 赞 4214 藏 8877 / 发布时间 / IP 福建 / 10 个标签）
- 视频：该笔记无 `originVideoKey` → 降级 h264 流 `masterUrl`（`…/stream/79/110/258/…_258.mp4`，
  路径段 258 与公开资料「258=无水印」一致；未逐帧确认水印）
- 落盘：`downloads/含胸驼背别光喊｜试试这几个动作✨_6ac64c13/`
  - `含胸驼背别光喊｜试试这几个动作✨.mp4`（2,179,775 字节，ftyp isom/avc1 = 合法 h264 mp4）
  - `info.json`（完整元数据）
  - `含胸驼背别光喊｜试试这几个动作✨.md`（文章）

## 关键实测结论
1. **真实笔记页匿名可解析**：pc_share 来源的 xsec_token 即可，无需 Cookie
2. **绝不能伪造 web_session cookie**：实测伪造 → HTTP 500
3. **默认直连不走代理**：走本机代理出口的浏览器被 IP 风控（error 300012）；CLI 直连正常
4. **og:meta 是可靠兜底**：笔记页即使 noteDetailMap 为空，og 标签仍有数据
5. `masterUrl` 是 `http://`（非 https），直接可用
6. **2026 年小红书笔记链接普遍要求 xsec_token**：无 token 的旧式链接可能拿不到完整数据

## 待验证项
- xhslink.com 短链 302 解析（用户提供短链文案时测）
- 图文笔记批量原图下载
- 含 `originVideoKey` 的笔记（无水印直链实际可用性）
