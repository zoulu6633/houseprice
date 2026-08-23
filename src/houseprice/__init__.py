"""houseprice 包入口。"""

import uvicorn


def main() -> None:
    """启动 FastAPI 开发服务器。"""
    uvicorn.run("houseprice.main:app", host="127.0.0.1", port=8000, reload=True)
