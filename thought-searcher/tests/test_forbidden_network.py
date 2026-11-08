"""app/ 코드는 네트워크에 직접 접근하지 않는다 (예외: 알림 클릭 시 브라우저로 URL 열기)."""
import ast
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"
FORBIDDEN = {"socket", "ssl", "urllib", "urllib.request", "urllib3", "http", "http.client", "requests", "httpx",
             "aiohttp", "ftplib", "smtplib", "telnetlib", "xmlrpc", "websocket", "websockets", "webbrowser",
             "asyncio", "PySide6.QtNetwork", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets"}
FORBIDDEN_NAMES = {"QNetworkAccessManager", "QTcpSocket", "QUdpSocket", "QWebEngineView"}


def _imports(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                yield a.name, node.lineno
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            yield node.module, node.lineno
            for a in node.names:
                yield f"{node.module}.{a.name}", node.lineno


def test_no_network_modules():
    bad = []
    files = list(APP.rglob("*.py"))
    assert files
    for f in files:
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for name, line in _imports(tree):
            top = name.split(".")[0]
            if name in FORBIDDEN or top in FORBIDDEN and top != "PySide6":
                bad.append(f"{f.name}:{line} {name}")
            if name.split(".")[-1] in FORBIDDEN_NAMES:
                bad.append(f"{f.name}:{line} {name}")
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
                bad.append(f"{f.name}:{node.lineno} {node.id}")
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "__import__":
                bad.append(f"{f.name}:{node.lineno} __import__")
    assert bad == []


def test_only_browser_open_is_desktop_services():
    """URL을 여는 곳은 QDesktopServices.openUrl 하나뿐(기본 브라우저에 맡김)."""
    hits = []
    for f in APP.rglob("*.py"):
        text = f.read_text(encoding="utf-8")
        if "openUrl(" in text:
            hits.append(f.name)
    assert hits == ["main.py"]
