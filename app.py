from flask import Flask, request
import lark_oapi as lark
from lark_oapi.api.bitable.v1 import *
from lark_oapi.api.im.v1 import *
from lark_oapi.api.drive.v1 import *
import json
import re
import os
import time
processed_messages = set()

app = Flask(__name__)

# ============================================================
# 📌 配置区域（根据实际情况修改）
# ============================================================

# 飞书应用凭证（从环境变量读取，更安全）
APP_ID = os.environ.get("APP_ID", "")
APP_SECRET = os.environ.get("APP_SECRET", "")

# 字段名称（根据你的表格字段名修改）
FIELD_REQUIREMENT = "需求内容"
FIELD_STATUS = "验收状态"
FIELD_ATTACHMENT = "验收附件"
FIELD_DEV_STATUS = "开发状态"
FIELD_DOC_LINK = "验收文档"  # 🆕 新增
STATUS_VALUE = "验收通过"
DEV_STATUS_VALUE = "已完成"

# 项目配置（新增项目在这里添加）
# 🆕 添加 chat_ids 字段，关联项目群
PROJECTS = [
    {
        "name": "JigArt",
        "app_token": "Q8BWbvdpja9RzEsFXbjcXEy3nof",
        "table_id": "tbluv9XFW2P6B7sn",
        "chat_ids": ["oc_2575222eccd3a75f35d409eaba35ba66"]  # JigArt 项目群ID
    },
    {
        "name": "BusJam",
        "app_token": "OkR6bHCAfa3JrMst4fpcHd2SnHc",
        "table_id": "tblA0oTFNEI9O2wm",
        "chat_ids": ["oc_d887d73c344ed7fc288ea487a73af247", "oc_c837780ca61da27e17d98d55bca4c83f"]  # BusJam 项目群ID
    },
    {
        "name": "GoodsSort",
        "app_token": "GGsDbt9LzaGkenspLklc3DD2nad",
        "table_id": "tblCCU7igaomNzNd",
        "chat_ids": ["oc_edb1f2904d837aa76057e56cb1776fe3"]  # GoodsSort 项目群ID
    },
    {
        "name": "Solitaire",
        "app_token": "NGyJbcjFmajwpvs5DEUcRKPnnI2",
        "table_id": "tblLXAWBgrwKBbrK",
        "chat_ids": ["oc_b4a3a8b721c092b94bef343ac9918060"]  # Solitaire 项目群ID
    },
    # 新增项目模板：
    # {
    #     "name": "新项目名称",
    #     "app_token": "从URL的base/后面复制",
    #     "table_id": "从URL的table=后面复制",
    #     "chat_ids": ["oc_xxx", "oc_yyy"]  # 可以配置多个群
    # },
]

# ============================================================
# 创建客户端
# ============================================================

def get_client():
    return lark.Client.builder() \
        .app_id(APP_ID) \
        .app_secret(APP_SECRET) \
        .build()

# ============================================================
# 业务函数
# ============================================================

def find_project_by_chat_id(chat_id):
    """🆕 根据群ID查找对应的项目"""
    for project in PROJECTS:
        if chat_id in project.get("chat_ids", []):
            return project
    return None

def find_project_by_name(project_name):
    """🆕 根据项目名查找项目"""
    for project in PROJECTS:
        if project["name"].lower() == project_name.lower():
            return project
    return None

def find_record_in_all_projects(requirement_name):
    """遍历所有项目查找需求"""
    for project in PROJECTS:
        record = find_record(project, requirement_name)
        if record:
            return project, record
    return None, None

def find_record_in_all_projects_v2(requirement_name):
    """🆕 遍历所有项目查找需求，返回所有匹配"""
    matches = []
    for project in PROJECTS:
        record = find_record(project, requirement_name)
        if record:
            matches.append({"project": project, "record": record})
    return matches

def find_record(project, requirement_name):
    """在指定项目中查找需求（排除已验收的）"""
    client = get_client()
    request_body = SearchAppTableRecordRequest.builder() \
        .app_token(project["app_token"]) \
        .table_id(project["table_id"]) \
        .request_body(SearchAppTableRecordRequestBody.builder()
            .filter(FilterInfo.builder()
                .conjunction("and")
                .conditions([
                    # 条件1：需求内容精确匹配
                    Condition.builder()
                        .field_name(FIELD_REQUIREMENT)
                        .operator("is")
                        .value([requirement_name])
                        .build(),
                    # 条件2：验收状态不是"验收通过"（排除已验收的）
                    Condition.builder()
                        .field_name(FIELD_STATUS)
                        .operator("isNot")
                        .value([STATUS_VALUE])
                        .build()
                ])
                .build())
            .build()) \
        .build()
    
    response = client.bitable.v1.app_table_record.search(request_body)
    if response.success() and response.data.items:
        return response.data.items[0]
    return None

def update_record(project, record_id, attachments=None, doc_links=None):
    """更新验收状态、开发状态、附件和文档链接"""
    client = get_client()
    fields = {
        FIELD_STATUS: STATUS_VALUE,
        FIELD_DEV_STATUS: DEV_STATUS_VALUE
    }
    if attachments:
        fields[FIELD_ATTACHMENT] = attachments
    
    # 🆕 添加文档链接
    if doc_links and len(doc_links) > 0:
        # 超链接字段格式
        fields[FIELD_DOC_LINK] = doc_links[0]
    
    request_body = UpdateAppTableRecordRequest.builder() \
        .app_token(project["app_token"]) \
        .table_id(project["table_id"]) \
        .record_id(record_id) \
        .request_body(AppTableRecord.builder()
            .fields(fields)
            .build()) \
        .build()
    
    response = client.bitable.v1.app_table_record.update(request_body)
    return response.success()

def get_parent_message(message_id):
    """获取引用的原始消息"""
    client = get_client()
    request_body = GetMessageRequest.builder() \
        .message_id(message_id) \
        .build()
    
    response = client.im.v1.message.get(request_body)
    if response.success() and response.data.items:
        return response.data.items[0]
    return None

def download_resource(message_id, file_key, res_type):
    """下载消息中的图片/视频"""
    client = get_client()
    request_body = GetMessageResourceRequest.builder() \
        .message_id(message_id) \
        .file_key(file_key) \
        .type(res_type) \
        .build()
    
    response = client.im.v1.message_resource.get(request_body)
    if response.success():
        return response.file.read()
    return None

def upload_to_bitable(project, file_content, file_name):
    """上传文件到多维表格"""
    import io
    client = get_client()
    file_obj = io.BytesIO(file_content)
    file_obj.name = file_name
    
    request_body = UploadAllMediaRequest.builder() \
        .request_body(UploadAllMediaRequestBody.builder()
            .file_name(file_name)
            .parent_type("bitable_file")
            .parent_node(project["app_token"])
            .size(len(file_content))
            .file(file_obj)
            .build()) \
        .build()
    
    response = client.drive.v1.media.upload_all(request_body)
    if response.success():
        return response.data.file_token
    return None

def extract_attachments(project, parent_message):
    """提取并上传引用消息中的附件"""
    attachments = []
    if not parent_message:
        return attachments
    
    message_id = parent_message.message_id
    msg_type = parent_message.msg_type
    content = json.loads(parent_message.body.content)
    
    print(f"  引用消息类型: {msg_type}")
    
    # 单张图片
    if msg_type == "image":
        image_key = content.get("image_key")
        if image_key:
            print(f"  下载图片: {image_key}")
            file_content = download_resource(message_id, image_key, "image")
            if file_content:
                file_token = upload_to_bitable(project, file_content, f"{image_key}.png")
                if file_token:
                    attachments.append({"file_token": file_token})
                    print(f"  ✅ 图片上传成功")
    
    # 视频
    elif msg_type == "media":
        file_key = content.get("file_key")
        if file_key:
            print(f"  下载视频: {file_key}")
            file_content = download_resource(message_id, file_key, "file")
            if file_content:
                file_token = upload_to_bitable(project, file_content, f"{file_key}.mp4")
                if file_token:
                    attachments.append({"file_token": file_token})
                    print(f"  ✅ 视频上传成功")
    
    # 文件（PDF/Word/Excel等）
    elif msg_type == "file":
        file_key = content.get("file_key")
        file_name = content.get("file_name", f"{file_key}.file")
        if file_key:
            print(f"  下载文件: {file_name}")
            file_content = download_resource(message_id, file_key, "file")
            if file_content:
                file_token = upload_to_bitable(project, file_content, file_name)
                if file_token:
                    attachments.append({"file_token": file_token})
                    print(f"  ✅ 文件上传成功")
    
    # 富文本消息（可能包含多张图片）
    elif msg_type == "post":
        post_content = content.get("content", [])
        for line in post_content:
            for element in line:
                if element.get("tag") == "img":
                    image_key = element.get("image_key")
                    if image_key:
                        print(f"  下载图片: {image_key}")
                        file_content = download_resource(message_id, image_key, "image")
                        if file_content:
                            file_token = upload_to_bitable(project, file_content, f"{image_key}.png")
                            if file_token:
                                attachments.append({"file_token": file_token})
                                print(f"  ✅ 图片上传成功")
    
    return attachments

def extract_links(parent_message):
    """🆕 提取引用消息中的链接"""
    links = []
    if not parent_message:
        return links
    
    msg_type = parent_message.msg_type
    content = json.loads(parent_message.body.content)
    
    print(f"  提取链接，消息类型: {msg_type}")
    
    # 纯文本消息 - 提取URL
    if msg_type == "text":
        text = content.get("text", "")
        # 匹配各种链接
        urls = re.findall(r'https?://[^\s<>"{}|\\^`\[\]]+', text)
        for url in urls:
            links.append({"text": "链接", "link": url})
            print(f"  ✅ 提取到链接: {url}")
    
    # 富文本消息 - 提取链接元素
    elif msg_type == "post":
        post_content = content.get("content", [])
        for line in post_content:
            for element in line:
                # 链接元素
                if element.get("tag") == "a":
                    url = element.get("href", "")
                    text = element.get("text", "链接")
                    if url:
                        links.append({"text": text, "link": url})
                        print(f"  ✅ 提取到链接: {text} -> {url}")
                # 文本中可能包含的链接
                elif element.get("tag") == "text":
                    text = element.get("text", "")
                    urls = re.findall(r'https?://[^\s<>"{}|\\^`\[\]]+', text)
                    for url in urls:
                        links.append({"text": "链接", "link": url})
                        print(f"  ✅ 提取到链接: {url}")
    
    # 交互卡片消息（文档分享卡片）
    elif msg_type == "interactive":
        card_str = json.dumps(content)
        urls = re.findall(r'https?://[^\s<>"{}|\\^`\[\]\\]+', card_str)
        for url in urls:
            # 清理URL末尾可能的转义字符
            url = url.rstrip('\\/')
            if "feishu.cn" in url or "larksuite.com" in url:
                links.append({"text": "文档链接", "link": url})
                print(f"  ✅ 提取到卡片链接: {url}")
    
    # 分享卡片消息
    elif msg_type == "share_card":
        card_str = json.dumps(content)
        urls = re.findall(r'https?://[^\s<>"{}|\\^`\[\]\\]+', card_str)
        for url in urls:
            url = url.rstrip('\\/')
            links.append({"text": "分享链接", "link": url})
            print(f"  ✅ 提取到分享链接: {url}")
    
    # 其他消息类型 - 尝试从整个content中提取
    else:
        content_str = json.dumps(content)
        urls = re.findall(r'https?://[^\s<>"{}|\\^`\[\]\\]+', content_str)
        for url in urls:
            url = url.rstrip('\\/')
            if "feishu.cn" in url or "larksuite.com" in url or "docs" in url:
                links.append({"text": "链接", "link": url})
                print(f"  ✅ 提取到链接: {url}")
    
    # 去重
    seen = set()
    unique_links = []
    for link in links:
        if link["link"] not in seen:
            seen.add(link["link"])
            unique_links.append(link)
    
    return unique_links

def reply_message(message_id, text):
    """回复消息"""
    client = get_client()
    content = json.dumps({"text": text})
    request_body = ReplyMessageRequest.builder() \
        .message_id(message_id) \
        .request_body(ReplyMessageRequestBody.builder()
            .msg_type("text")
            .content(content)
            .build()) \
        .build()
    
    client.im.v1.message.reply(request_body)

def handle_acceptance(message, chat_id):
    """处理验收消息（支持多条需求，每条都上传附件和链接）"""
    content = json.loads(message.get("content", "{}"))
    text = content.get("text", "")
    message_id = message.get("message_id")
    parent_id = message.get("parent_id")
    
    print(f"\n{'='*50}")
    print(f"收到消息: {text}")
    print(f"来自群聊: {chat_id}")
    
    # 匹配【验收通过】
    match = re.search(r"【验收通过】(.+)", text)
    if not match:
        return
    
    full_text = match.group(1).strip()
    full_text = re.sub(r"@\S+\s*", "", full_text).strip()
    
    # 解析项目名和需求内容（先检查是否以项目名开头）
    specified_project_name = None
    requirements_text = full_text
    
    for project in PROJECTS:
        for sep in ["/", ":", "："]:
            prefix = project["name"] + sep
            if full_text.startswith(prefix):
                specified_project_name = project["name"]
                requirements_text = full_text[len(prefix):].strip()
                break
        if specified_project_name:
            break
    
    # 分割多条需求（支持顿号、逗号）
    requirement_names = re.split(r"[、，,]", requirements_text)
    requirement_names = [r.strip() for r in requirement_names if r.strip()]
    
    if not requirement_names:
        reply_message(message_id, "❌ 未识别到需求内容")
        return
    
    print(f"指定项目: {specified_project_name or '未指定'}")
    print(f"需求列表: {requirement_names}")
    
    # 根据群ID或指定项目名确定项目
    base_project = None
    if specified_project_name:
        base_project = find_project_by_name(specified_project_name)
        if not base_project:
            project_names = ', '.join([p['name'] for p in PROJECTS])
            reply_message(message_id, f"❌ 未找到项目「{specified_project_name}」\n可用项目: {project_names}")
            return
    else:
        base_project = find_project_by_chat_id(chat_id)
    
    # 获取引用消息（如果有的话）
    parent_message = None
    if parent_id:
        print(f"检测到引用消息，获取附件和链接...")
        parent_message = get_parent_message(parent_id)
    
    # 🆕 提取链接（只需提取一次，所有需求共用）
    doc_links = []
    if parent_message:
        doc_links = extract_links(parent_message)
    
    # 批量处理每条需求
    success_list = []
    fail_list = []
    total_attachments = 0
    has_links = len(doc_links) > 0
    
    for idx, requirement_name in enumerate(requirement_names):
        print(f"\n处理需求 [{idx+1}/{len(requirement_names)}]: {requirement_name}")
        
        project = None
        record = None
        
        if base_project:
            project = base_project
            record = find_record(project, requirement_name)
        else:
            matches = find_record_in_all_projects_v2(requirement_name)
            if len(matches) == 1:
                project = matches[0]["project"]
                record = matches[0]["record"]
            elif len(matches) > 1:
                fail_list.append(f"{requirement_name}（多个项目存在同名需求）")
                continue
        
        if not record:
            fail_list.append(requirement_name)
            print(f"❌ 未找到需求")
            continue
        
        print(f"✅ 在「{project['name']}」中找到需求")
        
        # 为每条需求单独上传附件
        attachments = []
        if parent_message:
            print(f"  为该需求上传附件...")
            attachments = extract_attachments(project, parent_message)
            total_attachments += len(attachments)
        
        # 🆕 更新记录（附件 + 链接）
        if update_record(project, record.record_id, attachments, doc_links):
            success_list.append(f"{project['name']}/{requirement_name}")
            print(f"✅ 更新成功")
        else:
            fail_list.append(f"{requirement_name}（更新失败）")
            print(f"❌ 更新失败")
    
    # 汇总回复
    reply_parts = []
    if success_list:
        if len(success_list) == 1:
            reply_parts.append(f"✅ 需求「{success_list[0]}」验收通过")
        else:
            reply_parts.append(f"✅ 验收通过 {len(success_list)} 条：\n" + "\n".join([f"  • {s}" for s in success_list]))
    if fail_list:
        if len(fail_list) == 1:
            reply_parts.append(f"❌ 未找到需求「{fail_list[0]}」")
        else:
            reply_parts.append(f"❌ 未找到 {len(fail_list)} 条：\n" + "\n".join([f"  • {f}" for f in fail_list]))
    if total_attachments > 0:
        reply_parts.append(f"📎 已为 {len(success_list)} 条需求各同步附件")
    if has_links:
        reply_parts.append(f"🔗 已同步 {len(doc_links)} 个文档链接")
    
    reply_message(message_id, "\n\n".join(reply_parts))

# ============================================================
# Webhook 路由
# ============================================================

@app.route("/", methods=["GET"])
def index():
    """首页 - 用于检查服务状态"""
    return {
        "status": "running",
        "message": "🤖 需求验收机器人运行中",
        "projects": [{"name": p["name"], "chat_ids": p.get("chat_ids", [])} for p in PROJECTS]
    }

@app.route("/webhook", methods=["POST"])
def webhook():
    """接收飞书事件回调"""
    data = request.json
    
    # URL 验证（飞书首次配置时会发送）
    if "challenge" in data:
        return {"challenge": data["challenge"]}
    
    try:
        header = data.get("header", {})
        event = data.get("event", {})
        
        event_type = header.get("event_type")
        if event_type != "im.message.receive_v1":
            return {"code": 0}
        
        message = event.get("message", {})
        message_id = message.get("message_id", "")
        chat_id = message.get("chat_id", "")  # 获取群ID

        # ========== 忽略旧消息 ==========
        create_time = message.get("create_time", "")
        if create_time:
            msg_time = int(create_time) / 1000
            if time.time() - msg_time > 300:
                print(f"忽略过旧的消息（超过5分钟）: {message_id}")
                return {"code": 0}
        # =============================================
        
        # 消息去重
        if message_id in processed_messages:
            print(f"消息已处理，跳过: {message_id}")
            return {"code": 0}
        
        # 过滤机器人自己发的消息
        sender = event.get("sender", {})
        sender_type = sender.get("sender_type", "")
        if sender_type == "app":
            print("跳过机器人自己的消息")
            return {"code": 0}
        
        # 记录已处理的消息
        processed_messages.add(message_id)
        
        # 限制集合大小，防止内存溢出
        if len(processed_messages) > 1000:
            processed_messages.clear()
        
        # 处理验收消息（传入 chat_id）
        handle_acceptance(message, chat_id)
            
    except Exception as e:
        print(f"处理出错: {e}")
        import traceback
        traceback.print_exc()
    
    return {"code": 0}

# ============================================================
# 启动
# ============================================================

if __name__ == "__main__":
    print("=" * 50)
    print("🤖 需求验收机器人 (Webhook版)")
    print("=" * 50)
    print(f"APP_ID: {APP_ID[:10]}..." if APP_ID else "APP_ID: 未配置")
    print(f"已配置 {len(PROJECTS)} 个项目:")
    for p in PROJECTS:
        chat_ids = p.get("chat_ids", [])
        print(f"  - {p['name']} (关联 {len(chat_ids)} 个群)")
    print("=" * 50)
    
    port = int(os.environ.get("PORT", 3000))
    app.run(host="0.0.0.0", port=port, debug=False)
