from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.openapi.docs import get_swagger_ui_html, get_swagger_ui_oauth2_redirect_html
from fastapi.responses import FileResponse, RedirectResponse

router = APIRouter(include_in_schema=False)
ASSETS_DIR = Path(__file__).resolve().parents[3] / "node_modules" / "swagger-ui-dist"
ALLOWED_ASSETS = {"swagger-ui-bundle.js", "swagger-ui.css", "favicon-32x32.png"}

API_DESCRIPTION = """
小红书网页运营平台 API，接口定义随服务代码自动更新。

### 在线调试
1. 点击右上角 **Authorize**，输入本平台的用户名和密码完成授权（与小红书登录独立）。
2. 展开接口，点击 **Try it out**，填写参数后点击 **Execute**，查看请求、响应和耗时。
3. 受保护接口自动携带 `Authorization: Bearer ...`；也可通过 JSON 登录接口获取凭据供自己的程序使用。

### 常用接口
- **auth**：平台登录、注册及当前用户。
- **accounts / xhs-login-sessions**：管理绑定的小红书账号与登录会话。
- **account-notes**：按账号查看笔记、同步作品与互动数据。同一小红书号的 PC / Creator 登录合并展示。
- **drafts / publish**：编辑草稿、管理发布任务；送入发布中心与实际发布是不同操作。

请求和示例中的 `account_id` 请通过账号列表接口获取；时间默认使用上海时区。
业务数据按当前平台用户隔离。笔记管理的空指标为 `null`，不代表数值为零。
"""

API_TAGS = [
    {"name": name, "description": description} for name, description in [
        ("health", "服务健康检查"), ("auth", "平台用户认证；JSON 登录和 Swagger 表单授权共享同一套账号。"),
        ("accounts", "账号矩阵：绑定账号、刷新资料和检查登录。"),
        ("account-notes", "账号笔记管理：账号汇总、笔记查询与手动同步。"),
        ("xhs-login-sessions", "小红书二维码和手机号登录会话。"),
        ("notes", "内容库笔记、素材和导出。"), ("drafts", "草稿内容及素材管理。"),
        ("publish", "发布任务、素材上传和发布结果。"), ("files", "文件上传、图片处理和媒体下载。"),
        ("tasks", "任务中心与执行结果。"), ("model-configs", "AI 模型配置。"),
        ("ai", "AI 内容、标题、话题和图片处理。"),
    ]
]


@router.get("/api/docs")
def interactive_docs(request: Request):
    root = request.scope.get("root_path", "").rstrip("/")
    return get_swagger_ui_html(
        openapi_url=f"{root}/api/openapi.json",
        title="Spider XHS · 在线 API 文档",
        swagger_js_url=f"{root}/api/docs/assets/swagger-ui-bundle.js",
        swagger_css_url=f"{root}/api/docs/assets/swagger-ui.css",
        swagger_favicon_url=f"{root}/api/docs/assets/favicon-32x32.png",
        oauth2_redirect_url=f"{root}/api/docs/oauth2-redirect",
        swagger_ui_parameters={
            "filter": True, "docExpansion": "none", "displayRequestDuration": True,
            "persistAuthorization": False, "defaultModelsExpandDepth": 0, "validatorUrl": None,
        },
    )


@router.get("/api/docs/assets/{file_name}")
def docs_asset(file_name: str):
    if file_name not in ALLOWED_ASSETS:
        raise HTTPException(404, "Documentation asset not found")
    path = ASSETS_DIR / file_name
    if not path.is_file():
        raise HTTPException(503, "API文档资源尚未安装，请在项目根目录执行 npm ci 后重启服务。")
    return FileResponse(path)


@router.get("/api/docs/oauth2-redirect")
def oauth2_redirect():
    return get_swagger_ui_oauth2_redirect_html()


@router.get("/docs")
@router.get("/redoc")
def legacy_docs(request: Request):
    root = request.scope.get("root_path", "").rstrip("/")
    return RedirectResponse(f"{root}/api/docs")


@router.get("/openapi.json")
def legacy_schema(request: Request):
    return request.app.openapi()
