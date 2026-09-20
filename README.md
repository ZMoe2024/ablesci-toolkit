# AbleSci Toolkit

科研通的独立 Python HTTP 工具：签到、本人求助文件下载、单篇应助上传，以及普通下载线路诊断。

[![加入科研 AI 社区：交流工具、分享经验、一起解决问题](assets/community-banner.png)](https://skill.createsci.com/community)

运行环境：**Windows、Python 3.11+**。登录态使用当前 Windows 用户的 DPAPI 加密保存。日常运行不依赖 Codex；文献获取可选接入 ScanSci PDF。

## 已实现

| 功能 | 入口 | 状态 |
|---|---|---|
| 签到和入账核对 | `checkin.py` | 支持，重复签到会跳过 |
| 等待应助、普通线路下载PDF | `assist_download.py` | 已完成真实下载验证 |
| 单篇PDF应助 | `assist_give.py` | 已完成两篇真实OSS上传验证；是否采纳由求助者决定 |
| DOI / arXiv 文献获取 | `scansci.cmd` | 调用可选依赖 ScanSci PDF；下载后交给应助脚本 |
| 节点负载、Range诊断 | `diagnose_routes.py` | 支持普通节点小流量探测 |
| 多源分片实验 | `multisource_probe.py` | 192 KiB样本并发与缺片恢复已验证；不是完整多源下载器 |
| 自动发布求助 | [接口文档](docs/api.md) | 接口已实测，尚无通用发布CLI |
| 加入科研 AI 社区 | `join-community.cmd` | 用默认浏览器打开社区申请页面 |

当前下载入口固定普通通道，不会自动扣积分使用高速通道。下载文件仍需标题、DOI等核验；匹配失败会返回 `needs_review`。普通下载CLI尚未加入自动切线、断点续传和VIP/CDN。

## 加入社区

欢迎交流科研工具的实际用法、问题和经验。点击 **[加入社区](https://skill.createsci.com/community)**，或双击 `join-community.cmd`，即可用默认浏览器打开社区页面，无需安装 Python 或登录科研通。

```powershell
.\join-community.cmd
# 只显示链接，供终端或 AI 助手使用
.\join-community.cmd --url
```

完成页面上的三道入门题后，按提示联系 Moe 申请加入，审核通过后邀请入群。入口不提交科研通账号、Cookie 或文献记录。

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

## 可选：ScanSci PDF 文献下载

接入的上游项目是 [Rimagination/scansci-pdf](https://github.com/Rimagination/scansci-pdf)，通过 PyPI 安装，版本固定为 `1.17.0`。本仓库提供安装入口和命令入口，不复制上游源码或浏览器数据。上游 GitHub 源码采用 Apache-2.0；其 PyPI 编译组件另有说明，见[上游许可证说明](https://github.com/Rimagination/scansci-pdf#许可证)。

完成前面的虚拟环境创建后执行：

```powershell
.\install-scansci.cmd
.\scansci.cmd --help
```

也可以直接安装：`python -m pip install -r requirements-scansci.txt`。`scansci.cmd` 与其他快捷入口使用同一 Python 环境，并将参数原样传给上游 CLI。

```powershell
# DOI / arXiv 下载，文件放进已被 Git 忽略的 downloads
.\scansci.cmd get 10.1038/nature12373 --strategy legal_only --output .\downloads

# 机构下载流程，输出 JSON 结果，方便 AI 查看实际状态和路径
.\scansci.cmd fetch 10.1038/nature12373 --output .\downloads --format json

# 拿到真实文件路径后，先核对，再明确提交应助
python assist_give.py --assist-id REQUEST_ID --file "C:\papers\downloaded.pdf"
python assist_give.py --assist-id REQUEST_ID --file "C:\papers\downloaded.pdf" --submit
```

上游失败时不一定返回非零退出码，应检查结果中的成功状态、实际 PDF 路径以及文件内容。下载入口不会自动调用应助上传；上传仍由 `assist_give.py --submit` 控制。文献能否下载取决于来源可用性和已有访问权限。

如需上游的可见浏览器和机构登录功能，可在同一环境安装 `python -m pip install "scansci-pdf[cloakbrowser,instsci]==1.17.0"`，再按[上游说明](https://github.com/Rimagination/scansci-pdf)配置。首次浏览器使用可能还需下载运行时。API Key、机构登录和浏览器资料仅保存在本机；本发布包不携带这些配置。

发布验证覆盖安装、CLI 参数和本工具回归测试，未声称已完成 ScanSci PDF 的真实论文下载验证。

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
