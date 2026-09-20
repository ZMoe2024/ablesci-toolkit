# 已核对的科研通内部接口

核对日期：2026-09-20。主站 `https://www.ablesci.com`。这些不是有稳定性承诺的公开API。

## 登录与CSRF

主站使用本人Cookie。读取页面的CSRF meta，再通过 `X-CSRF-Token` 或 `_csrf` 表单字段传递。文件节点/OSS不接收主站Cookie。脚本不输出下载令牌或OSS签名。

## 发布求助

按顺序读取 `/assist/create`，POST `/assist/onekey-query`（`onekey`为DOI/题名），按需用 `/assist/paper-lookup-status` 轮询，调用 `/assist/query-lowest-point` 和 `/assist/check-before-assist-create`，最后POST `/assist/create`。

正式表单为 `Assist[title]`、`Assist[doi]`、`Assist[url]`、`Assist[type]`、`Assist[point]`、`Assist[note]`、`Assist[remark]`、`Assist[suppl]`、`Assist[close_at]`。成功响应 `code=0`、`data.url` 含求助ID。预检警告、最低积分和预算需处理；正式提交会消耗悬赏。此流程曾真实验证，当前包不提供发布CLI。

## 下载链路

1. GET `/assist/detail?id=<求助ID>`，检查本人身份与应助文件状态。
2. GET `/assist/download?id=<文件ID>`，获得页面配置与新鲜CSRF；此响应是HTML。
3. POST `/file/request-download-token`：`type=assistFile`、`id=<文件ID>`、`channel=normal`、`highspeed=0`、`fallback=0`、`file_server=2/3/4`、`remove_sensitive=1`。
4. 成功响应提供 `host`、`token`、`output_filename`、`expected_size`、`channel`、`transport`。GET `host?token=<令牌>` 获取PDF，不转发主站Cookie。仅接受允许的HTTPS科研通文件节点。
5. 核对文件大小、PDF结构、标题/DOI，保存SHA-256。SHA-256若无可信的源摘要，只用于后续一致性检查。

负载：GET `/file/progress-download-server-load`，返回节点负载与可用状态。普通域名是 `filehub2/3/4.ablesci.com`。当前网页60秒首字节/无数据超时后可切换一次普通节点。

高速请求为 `channel=highspeed,highspeed=1,file_server=0`。服务端返回VIP或CDN；`fallback=1`请求CDN回退。代码所示CDN入口为主站`/file/download`，最终域名白名单为 `filecdn1s1.ablesci.com` 与 `filecdn1bak11.ablesci.com`。这些高速路径未在本项目实际调用，默认不支持；当前[网站规则](https://www.ablesci.com/post/detail?id=Rbkyx7)为不足500积分时同文件首次高速扣2分。

普通节点实际支持HTTP Range，非零偏移和同令牌重复请求均已验证。多源实验验证了三个节点各取一片并正确拼接；生产下载CLI尚不自动分片、续传或切线。`expire_at`曾返回300，但后端精确定义未验证，不把它当Unix时间戳。

## 应助链路

先在本地核对文献并计算文件MD5与字节数，然后POST：

```text
/assist/upload-request?t=<毫秒时间戳>
assist_id=<求助ID>
filename=<文件名>
file_md5=<真实文件MD5>
filesize=<字节数>
```

响应 `code=0` 返回OSS签名参数；`code=10`表示MD5快速应助已成功；`code=1`错误；`code=2`需验证码。**此接口本身可能直接提交应助，不是只读预检。**

普通上传按返回`host`进行multipart POST，字段为 `key=dir+randFilename`、`policy`、`OSSAccessKeyId=accessid`、`success_action_status=200`、`callback`、`signature`、`x:filename`、`x:assist_id`、`x:user_id`、`assist_id` 和 `file`。不要缓存或公开这些签名参数。

已经两次实测OSS上传：HTTP 200、回调JSON `code=0`，并在详情和 `/my/assist-give` 核对本人新增记录。MD5快速应助分支仅代码核对。HTTP成功不代表采纳；实际收益由 `/my/point` 核验。

另有POST `/assist/upload-wangpan-url`（content、assist_id、t）生成网盘TXT应助，未实际调用。POST `/assist/file-handle`（assist_file_id、note、type）支持accept/reject/withdraw/cnlreject，需相应角色权限；本工具不会代替求助者采纳。页面的自动确认时间存在24/48小时文案不一致，应查实际状态。

## 可靠性要求

正式提交前保存不确定状态；遇到超时先核对站内记录，禁止盲目重发。登录、验证码、永久拒绝与网络错误须区分。等待状态使用适度轮询，文件需要及时保存。此前下载文件的保存期限提示为求助完结后24小时，具体以当前页面为准。
