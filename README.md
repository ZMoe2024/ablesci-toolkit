# AbleSci Toolkit

科研通的独立 Python HTTP 工具：签到、本人求助文件下载、单篇应助上传，以及普通下载线路诊断。

运行环境：**Windows、Python 3.11+**。登录态使用当前 Windows 用户的 DPAPI 加密保存。日常运行不依赖 Codex；ScienceDirect 下载器是可选的独立组件，不包含在此仓库。

## 已实现

| 功能 | 入口 | 状态 |
|---|---|---|
| 签到和入账核对 | `checkin.py` | 支持，重复签到会跳过 |
| 等待应助、普通线路下载PDF | `assist_download.py` | 已完成真实下载验证 |
| 单篇PDF应助 | `assist_give.py` | 已完成两篇真实OSS上传验证；是否采纳由求助者决定 |
| 节点负载、Range诊断 | `diagnose_routes.py` | 支持普通节点小流量探测 |
| 多源分片实验 | `multisource_probe.py` | 192 KiB样本并发与缺片恢复已验证；不是完整多源下载器 |
| 自动发布求助 | [接口文档](docs/api.md) | 接口已实测，尚无通用发布CLI |

当前下载入口固定普通通道，不会自动扣积分使用高速通道。下载文件仍需标题、DOI等核验；匹配失败会返回 `needs_review`。普通下载CLI尚未加入自动切线、断点续传和VIP/CDN。

## 安装

```powershell
git clone https://github.com/ZMoe2024/ablesci-toolkit.git
cd ablesci-toolkit
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

下文用 `python` 表示已安装依赖的Python，可先激活 `.venv`，或改用 `.\.venv\Scripts\python.exe`。CMD快捷入口会优先使用本目录的`.venv`，再尝试系统Python。

## 导入本人登录态

在现有浏览器中登录科研通，在开发者工具的Network中选中科研通主站请求，复制请求头Cookie值。本机执行：

```powershell
python checkin.py --import-session --account "你的科研通昵称"
```

Cookie输入不回显。也可运行 `import-session.cmd`，按提示输入昵称与Cookie。不要把Cookie提交到Git或发给别人。没有保存账号密码，也不会扫描浏览器资料。

登录态位于 `%LOCALAPPDATA%\AbleSciCheckin\session.dpapi`，只能由同一Windows用户解密。登录失效时重新导入。该目录也存放签到日志，仓库不携带这些文件。

## 签到

```powershell
python checkin.py --check-only
python checkin.py
```

脚本先检查本人当天积分流水，再决定是否调用签到接口，并核对入账结果。网站当前签到说明明确不允许程序自动签到并提示积分清零风险，使用前请了解该实际规则。定时任务默认不安装。

如自行决定启用Windows定时运行：

```powershell
.\install-task.ps1 -Time '09:00'
.\remove-task.ps1
```

任务名为 `AbleSci-HTTP-Checkin`；每天指定本机时间及Windows登录时检查一次。要求同一Windows用户已登录、电脑开机联网。安装会更新同名任务；不启动Codex任务或云端服务。

## 本人求助文件下载

```powershell
python assist_download.py --assist-id REQUEST_ID --status-only
python assist_download.py --assist-id REQUEST_ID --wait-seconds 3600
python assist_download.py --assist-id REQUEST_ID --server 3 --output-dir .\downloads
```

默认每120秒检查应助。普通服务器ID为2、3、4，分别对应页面线路1、2、3。已有PDF核验通过后复用。未完成文件保留`.part`，但当前CLI重试会重下，尚不续传。不会自动采纳。

结果：`downloaded`、`needs_review`、`waiting`、`error`。退出码0表示命令成功（仍需检查`needs_review`），4表示等候到期，2/3表示错误。

## 应助一篇

先取得并核对目标文献的真实PDF。求助ID来自待应助详情页；不能使用应助文件ID代替。

```powershell
# 仅准备并核对标题、DOI、页数，不调用上传端点
python assist_give.py --assist-id REQUEST_ID --file C:\papers\article.pdf

# 实际向该求助提交文件
python assist_give.py --assist-id REQUEST_ID --file C:\papers\article.pdf --submit
```

当前入口仅处理不超过50 MiB的PDF正文。正式提交前检查仍为“求助中”、上传控件可用、没有本人重复记录。文件题名/DOI匹配后，申请上传；服务端可能MD5命中直接应助，也可能返回OSS签名让脚本直传。提交后必须读到本人新增应助记录才报告`submitted`。

每个求助保存 `give-REQUEST_ID.json` 回执。提交结果不明时阻止盲目重发，应先核对站内状态；验证码需要人工处理。上传成功不代表已经被采纳或积分到账。当前没有后台自动刷列表/批量应助服务。

## 可选：ScienceDirect下载衔接

本工具接收本地PDF。若另行安装了ScienceDirect下载器，可用官方文章URL/PII下载，再把已成功保存的PDF路径交给`assist_give.py`。[请求示例](examples/sciencedirect-request.json)仅描述对接格式；本仓库不分发该下载器、浏览器扩展、机构登录态或论文。

## 线路与分片实验

```powershell
python diagnose_routes.py --file-id FILE_ID
python diagnose_routes.py --file-id FILE_ID --probe
python multisource_probe.py --assist-id REQUEST_ID --file-id FILE_ID --reference C:\papers\verified.pdf --mode parallel
python multisource_probe.py --assist-id REQUEST_ID --file-id FILE_ID --reference C:\papers\verified.pdf --mode serial
python multisource_probe.py --assist-id REQUEST_ID --file-id FILE_ID --reference C:\papers\verified.pdf --mode parallel --resume --server 4
```

分片实验需要同一文献已经核验的完整PDF作参考，仅取前三个64 KiB片段并比对/合并；已有片段复用，不能把重复运行时间当作重新测速。独立一次实验中并发6.78秒、串行10.49秒，不能保证整篇文件或其他时段有同样速度。

## 验证与边界

```powershell
python -m unittest discover -v
```

测试只使用本地样本与Mock，不访问站点、不消耗积分、不上传文献。接口来自网站当前前端与实测，属于内部接口，可能变化。[协议说明](docs/api.md)记录已验证路径与未完成能力。

发布包不含Cookie、令牌、下载论文、原始站点JS或个人应助记录。不得把`downloads`、回执或DPAPI文件加入提交。自动化应遵守站点规则和文献来源的使用许可。
