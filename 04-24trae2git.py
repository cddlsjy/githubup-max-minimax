#!/usr/bin/env python3
"""
GitHub 一键上传工具 (Python GUI 版) - 增强版
支持默认工作流模板、自定义 YML 和 ZIP 上传。
增强功能：
- 下载仓库 ZIP（带日志）
- 上传文件夹（自动打包并保留 .gitignore/build.gradle 等）
- 创建新仓库后自动切换模式并显示内容
- 剪贴板片段管理（最多10个，可永久保存）
- 界面字体缩放与紧凑布局
- 可隐藏分组标题（紧凑模式）
- 修复快速选择下拉框和剪贴板下拉框无法弹出问题
- 修复剪贴板管理对话框在字体放大时布局异常
- 新增：项目文件下载功能（支持下载单个文件/文件夹/整个项目）
- 新增：下载历史记录管理
- 新增：文件预览功能
"""

import os
import sys
import json
import base64
import threading
import re
import tempfile
import zipfile
import shutil
import fnmatch
from datetime import datetime
from tkinter import *
from tkinter import ttk, filedialog, messagebox, font as tkfont
from typing import Optional, List, Dict, Any, Tuple

import requests

# ==================== 配置文件 ====================
CONFIG_FILE = os.path.expanduser("~/.github_uploader_config.json")

def load_config() -> Dict[str, Any]:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {}

def save_config(config: Dict[str, Any]):
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2)
    except:
        pass

# ==================== GitHub API 封装 ====================
class GitHubAPI:
    BASE_URL = "https://api.github.com"

    def __init__(self, token: str):
        self.token = token.strip()
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"token {self.token}",
            "Accept": "application/vnd.github.v3+json"
        })

    def _handle_response(self, response: requests.Response, success_codes=(200, 201, 204)):
        if response.status_code in success_codes:
            return response
        else:
            try:
                error_msg = response.json().get("message", response.text)
            except:
                error_msg = response.text
            raise Exception(f"GitHub API 错误 {response.status_code}: {error_msg}")

    def get_authenticated_user(self) -> Dict[str, Any]:
        resp = self.session.get(f"{self.BASE_URL}/user")
        self._handle_response(resp)
        return resp.json()

    def list_user_repos(self, per_page=100, sort="updated") -> List[Dict[str, Any]]:
        resp = self.session.get(f"{self.BASE_URL}/user/repos", params={"per_page": per_page, "sort": sort})
        self._handle_response(resp)
        return resp.json()

    def get_repo_contents(self, owner: str, repo: str, path: str = "", branch: str = "main") -> List[Dict[str, Any]]:
        url = f"{self.BASE_URL}/repos/{owner}/{repo}/contents/{path}"
        resp = self.session.get(url, params={"ref": branch})
        self._handle_response(resp)
        return resp.json()

    def get_file_sha(self, owner: str, repo: str, path: str, branch: str = "main") -> Optional[str]:
        url = f"{self.BASE_URL}/repos/{owner}/{repo}/contents/{path}"
        resp = self.session.get(url, params={"ref": branch})
        if resp.status_code == 200:
            return resp.json().get("sha")
        elif resp.status_code == 404:
            return None
        else:
            self._handle_response(resp)

    def create_or_update_file(self, owner: str, repo: str, path: str, content_base64: str,
                              message: str, branch: str = "main", sha: Optional[str] = None) -> Dict[str, Any]:
        url = f"{self.BASE_URL}/repos/{owner}/{repo}/contents/{path}"
        payload = {
            "message": message,
            "content": content_base64,
            "branch": branch
        }
        if sha:
            payload["sha"] = sha
        resp = self.session.put(url, json=payload)
        self._handle_response(resp, success_codes=(200, 201))
        return resp.json()

    def create_repository(self, name: str, description: str = "", private: bool = True, auto_init: bool = False) -> Dict[str, Any]:
        url = f"{self.BASE_URL}/user/repos"
        payload = {
            "name": name,
            "description": description,
            "private": private,
            "auto_init": auto_init
        }
        resp = self.session.post(url, json=payload)
        self._handle_response(resp, success_codes=(201,))
        return resp.json()

    def download_repo_archive(self, owner: str, repo: str, branch: str = "main") -> bytes:
        url = f"{self.BASE_URL}/repos/{owner}/{repo}/zipball/{branch}"
        resp = self.session.get(url, allow_redirects=True)
        self._handle_response(resp)
        return resp.content

    def download_file_content(self, owner: str, repo: str, path: str, branch: str = "main") -> Optional[bytes]:
        """下载单个文件内容"""
        url = f"{self.BASE_URL}/repos/{owner}/{repo}/contents/{path}"
        resp = self.session.get(url, params={"ref": branch})
        if resp.status_code == 200:
            data = resp.json()
            if 'content' in data:
                # 文件内容是 base64 编码的
                content = data['content'].replace('\n', '')
                return base64.b64decode(content)
        return None

    def get_download_url(self, owner: str, repo: str, path: str, branch: str = "main") -> Optional[str]:
        """获取文件的直接下载 URL"""
        url = f"{self.BASE_URL}/repos/{owner}/{repo}/contents/{path}"
        resp = self.session.get(url, params={"ref": branch})
        if resp.status_code == 200:
            data = resp.json()
            return data.get('download_url')
        return None

# ==================== 内嵌模板内容 ====================
UNPACK_YML_TEMPLATE = """\
name: Unpack ZIP and Move Subdir to Root

on:
  push:
    paths: ['**.zip']
  workflow_dispatch:
    inputs:
      zip_file:
        description: '要解压的 ZIP 文件名（例如 "archive.zip"）'
        required: false
        default: ''
      subdir:
        description: '要移动到根目录的子目录名（可选，独立于 ZIP）'
        required: false
        default: ''

jobs:
  unpack-and-move:
    runs-on: ubuntu-latest
    permissions:
      contents: write

    steps:
      - uses: actions/checkout@v4

      - name: 自动解压并移动子目录内容
        if: github.event_name == 'push'
        run: |
          shopt -s dotglob
          zip_files=(*.zip)
          count=${#zip_files[@]}

          if [ $count -eq 0 ]; then
            echo "没有找到 ZIP 文件"
            exit 0
          elif [ $count -eq 1 ]; then
            zipfile="${zip_files[0]}"
            echo "自动解压: $zipfile"
            temp_dir="${zipfile%.zip}_temp_$$"
            mkdir -p "$temp_dir"
            unzip -o "$zipfile" -d "$temp_dir"

            if [ -z "$(ls -A "$temp_dir")" ]; then
              echo "⚠️ ZIP 文件为空"
              rm -rf "$temp_dir"
              rm -f "$zipfile"
              exit 0
            fi

            items=("$temp_dir"/*)
            if [ ${#items[@]} -eq 1 ] && [ -d "${items[0]}" ]; then
              subdir="${items[0]}"
              echo "检测到单一顶层子目录: $subdir，将其内容移动到根目录"
              cp -rf "$subdir"/. .
              rm -rf "$subdir"
            else
              echo "ZIP 内没有单一顶层目录，直接移动所有内容"
              cp -rf "$temp_dir"/. .
            fi

            rm -rf "$temp_dir"
            rm -f "$zipfile"
            echo "✅ 解压并移动完成"
          else
            echo "检测到多个 ZIP 文件 ($count 个)，不自动解压。"
            echo "请手动运行 workflow_dispatch 并指定 zip_file。"
            for f in "${zip_files[@]}"; do
              echo "  - $f"
            done
            exit 0
          fi

      - name: 手动解压并移动子目录内容
        if: github.event_name == 'workflow_dispatch' && inputs.zip_file != ''
        run: |
          shopt -s dotglob
          zipfile="${{ inputs.zip_file }}"
          if [ ! -f "$zipfile" ]; then
            echo "❌ 文件 '$zipfile' 不存在"
            ls -1 *.zip 2>/dev/null || echo "（当前目录无 zip 文件）"
            exit 1
          fi
          echo "手动解压: $zipfile"
          temp_dir="${zipfile%.zip}_temp_$$"
          mkdir -p "$temp_dir"
          unzip -o "$zipfile" -d "$temp_dir"

          items=("$temp_dir"/*)
          if [ ${#items[@]} -eq 1 ] && [ -d "${items[0]}" ]; then
            subdir="${items[0]}"
            echo "检测到单一顶层子目录: $subdir，将其内容移动到根目录"
            cp -rf "$subdir"/. .
            rm -rf "$subdir"
          else
            echo "ZIP 内没有单一顶层目录，直接移动所有内容"
            cp -rf "$temp_dir"/. .
          fi

          rm -rf "$temp_dir"
          rm -f "$zipfile"
          echo "✅ 解压并移动完成"

      - name: 移动指定的子目录到根目录
        if: github.event_name == 'workflow_dispatch' && inputs.subdir != ''
        run: |
          shopt -s dotglob
          SUBDIR="${{ inputs.subdir }}"
          if [ -d "$SUBDIR" ]; then
            echo "移动子目录 '$SUBDIR' 的内容到根目录"
            cp -rf "$SUBDIR"/. .
            rm -rf "$SUBDIR"
            echo "✅ 子目录已提升到根目录"
          else
            echo "❌ 子目录 '$SUBDIR' 不存在"
            exit 1
          fi

      - name: 提交更改
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add . -- ':!.github'
          git diff --staged --quiet || git commit -m "解压 ZIP 并整理目录结构"
          git push
"""

BUILD_YML_TEMPLATE = """\
name: Build APK

on:
  push:
    branches: [ {{BRANCH}} ]
  workflow_dispatch:

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Set up JDK {{JAVA_VERSION}}
        uses: actions/setup-java@v4
        with:
          java-version: '{{JAVA_VERSION}}'
          distribution: 'temurin'
          cache: 'gradle'

      - name: Setup Gradle
        uses: gradle/actions/setup-gradle@v3
        with:
          gradle-version: '{{GRADLE_VERSION}}'

      - name: Build APK (override java.home)
        run: |
          if [ -f gradle.properties ]; then
            sed -i 's/^org.gradle.java.home=/# &/' gradle.properties || true
          fi
          gradle assemble{{BUILD_TYPE_CAPITALIZED}} --no-daemon -Dorg.gradle.java.home=$JAVA_HOME

      - name: Upload APK
        uses: actions/upload-artifact@v4
        with:
          name: app-{{BUILD_TYPE}}
          path: app/build/outputs/apk/{{BUILD_TYPE}}/*.apk
          retention-days: 7
"""

# ==================== 日志管理器 ====================
class Logger:
    def __init__(self, text_widget: Text):
        self.text_widget = text_widget
        self.clear()

    def add(self, msg: str, tag: str = None):
        timestamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{timestamp}] {msg}\n"
        self.text_widget.insert(END, line, tag)
        self.text_widget.see(END)

    def clear(self):
        self.text_widget.delete(1.0, END)

# ==================== 自定义 YML 项 ====================
class CustomYmlItem:
    def __init__(self, filepath: str):
        self.filepath = filepath
        self.filename = os.path.basename(filepath)

# ==================== 下载历史记录项 ====================
class DownloadHistoryItem:
    def __init__(self, owner: str, repo: str, path: str, download_time: str, size: str = ""):
        self.owner = owner
        self.repo = repo
        self.path = path
        self.download_time = download_time
        self.size = size

# ==================== 主窗口 ====================
class GitHubUploaderApp:
    def __init__(self, root: Tk):
        self.root = root
        self.root.title("GitHub 一键上传工具 - 增强版")

        # 加载配置
        self.config = load_config()
        self.font_scale = self.config.get('font_scale', 1.0)
        self.compact_mode = self.config.get('compact_mode', False)

        # 应用全局字体缩放和输入控件高度
        self.apply_font_scale()

        # 根据缩放动态调整默认窗口大小
        base_width, base_height = 1000, 800
        self.root.geometry(f"{int(base_width * min(1.2, self.font_scale))}x{int(base_height * min(1.2, self.font_scale))}")
        self.root.minsize(900, 700)

        self.token = self.config.get('token', '').strip()
        self.branch = self.config.get('branch', 'main')
        self.repo_url = self.config.get('repo_url', '')
        self.create_new = self.config.get('create_new', False)
        self.new_repo_name = self.config.get('new_repo_name', '')
        self.new_repo_desc = self.config.get('new_repo_desc', '')
        self.new_repo_private = self.config.get('new_repo_private', True)
        self.upload_default_unpack = self.config.get('upload_default_unpack', True)
        self.upload_default_build = self.config.get('upload_default_build', True)

        self.build_branch = self.config.get('build_branch', 'main')
        self.java_version = self.config.get('java_version', '17')
        self.java_home_custom = self.config.get('java_home_custom', '')
        self.gradle_version = self.config.get('gradle_version', '8.13')
        self.build_type = self.config.get('build_type', 'debug')

        default_excludes = [
            ".*", "build/", "__pycache__/", "*.pyc", "*.class", "*.o", "*.obj", "*.exe", "*.dll", "*.so", "*.dylib",
            ".gradle/", ".idea/", "local.properties", "*.iml", "*.log"
        ]
        self.folder_exclude_patterns = self.config.get('folder_exclude_patterns', default_excludes)

        default_snippets = [
            {"name": "示例1", "content": "这是一段示例文本"},
            {"name": "示例2", "content": ""},
            {"name": "片段3", "content": ""},
            {"name": "片段4", "content": ""},
            {"name": "片段5", "content": ""},
            {"name": "片段6", "content": ""},
            {"name": "片段7", "content": ""},
            {"name": "片段8", "content": ""},
            {"name": "片段9", "content": ""},
            {"name": "片段10", "content": ""}
        ]
        self.snippets = self.config.get('snippets', default_snippets)
        if len(self.snippets) > 10:
            self.snippets = self.snippets[:10]
        elif len(self.snippets) < 10:
            self.snippets.extend([{"name": f"片段{i+1}", "content": ""} for i in range(len(self.snippets), 10)])

        # 下载历史记录
        self.download_history = self.config.get('download_history', [])

        self.api: Optional[GitHubAPI] = None
        self.user_repos: List[Dict] = []
        self.selected_repo: Optional[Dict] = None
        self.custom_yml_files: List[CustomYmlItem] = []
        self.zip_filepath: Optional[str] = None
        self.zip_filename: str = ""
        self.is_uploading = False
        self.is_downloading = False

        self.setup_ui()
        self.apply_compact_mode()

        if self.token:
            self.api = GitHubAPI(self.token)
            self.update_user_info()
            self.load_repo_list_async()

    def apply_font_scale(self):
        """设置全局默认字体大小，等宽日志字体同步缩放，并增加输入控件高度"""
        default_font = tkfont.nametofont("TkDefaultFont")
        default_font.configure(size=int(default_font.cget("size") * self.font_scale))
        try:
            fixed_font = tkfont.Font(family="Consolas", size=int(9 * self.font_scale))
        except:
            fixed_font = tkfont.Font(family="Courier", size=int(9 * self.font_scale))
        self.fixed_font = fixed_font

        # 样式：增加 Entry 和 Combobox 的内边距，使其高度随字体缩放
        style = ttk.Style()
        padding_vert = max(2, int(4 * self.font_scale))
        style.configure("TEntry", padding=(4, padding_vert, 4, padding_vert))
        style.configure("TCombobox", padding=(4, padding_vert, 4, padding_vert))
        # 设置 Combobox 下拉部分的行高（通过设置字体）
        self.root.option_add("*TCombobox*Listbox.font", default_font)

        # 如果已有仓库列表，刷新 Combobox 显示
        if hasattr(self, 'quick_combo') and self.user_repos:
            self.root.after(100, self._populate_quick_combo)

    def apply_compact_mode(self):
        """根据 compact_mode 显示或隐藏各分组标题"""
        groups = [
            (self.top_frame, "GitHub 认证"),
            (self.repo_frame, "仓库设置"),
            (self.file_frame, "文件选择"),
            (self.yml_frame, "自定义 YML 文件"),
            (self.zip_frame, "ZIP 文件")
        ]
        if self.compact_mode:
            for frame, original_title in groups:
                if isinstance(frame, ttk.LabelFrame):
                    frame.config(text="", relief=FLAT, borderwidth=0)
        else:
            original_titles = {
                self.top_frame: "GitHub 认证",
                self.repo_frame: "仓库设置",
                self.file_frame: "文件选择",
                self.yml_frame: "自定义 YML 文件",
                self.zip_frame: "ZIP 文件"
            }
            for frame, title in original_titles.items():
                if isinstance(frame, ttk.LabelFrame):
                    frame.config(text=title, relief=GROOVE, borderwidth=2)

    # ---------- UI 构建 ----------
    def setup_ui(self):
        main_frame = ttk.Frame(self.root, padding="6")
        main_frame.pack(fill=BOTH, expand=True)

        # ---- 顶部认证栏 ----
        self.top_frame = ttk.LabelFrame(main_frame, text="GitHub 认证", padding="3")
        self.top_frame.pack(fill=X, pady=(0, 8))

        ttk.Label(self.top_frame, text="Token:").grid(row=0, column=0, sticky=W, padx=4)
        self.token_var = StringVar(value=self.token)
        self.token_entry = ttk.Entry(self.top_frame, textvariable=self.token_var, width=50, show="*")
        self.token_entry.grid(row=0, column=1, sticky=EW, padx=4)
        self.show_token_var = BooleanVar(value=False)
        ttk.Checkbutton(self.top_frame, text="显示", variable=self.show_token_var, command=self.toggle_token_visibility).grid(row=0, column=2, padx=4)
        ttk.Button(self.top_frame, text="应用 Token", command=self.apply_token).grid(row=0, column=3, padx=4)
        self.top_frame.columnconfigure(1, weight=1)

        # ---- 仓库设置 ----
        self.repo_frame = ttk.LabelFrame(main_frame, text="仓库设置", padding="3")
        self.repo_frame.pack(fill=X, pady=(0, 8))

        self.repo_mode_var = StringVar(value="new" if self.create_new else "existing")
        ttk.Radiobutton(self.repo_frame, text="使用现有仓库", variable=self.repo_mode_var, value="existing", command=self.on_repo_mode_change).grid(row=0, column=0, padx=4)
        ttk.Radiobutton(self.repo_frame, text="创建新仓库", variable=self.repo_mode_var, value="new", command=self.on_repo_mode_change).grid(row=0, column=1, padx=4)

        self.existing_frame = ttk.Frame(self.repo_frame)
        self.existing_frame.grid(row=1, column=0, columnspan=2, sticky=EW, pady=4)

        ttk.Label(self.existing_frame, text="仓库地址:").grid(row=0, column=0, padx=4, sticky=W)
        self.repo_url_var = StringVar(value=self.repo_url)
        entry_width = max(40, int(40 * self.font_scale))
        self.repo_url_entry = ttk.Entry(self.existing_frame, textvariable=self.repo_url_var, width=entry_width)
        self.repo_url_entry.grid(row=0, column=1, padx=4, sticky=EW)
        self.repo_url_var.trace_add("write", lambda *args: self.save_config_later())

        ttk.Label(self.existing_frame, text="快速选择:").grid(row=1, column=0, padx=4, sticky=W)
        self.quick_search_var = StringVar()
        self.quick_combo = ttk.Combobox(self.existing_frame, textvariable=self.quick_search_var, width=entry_width)
        self.quick_combo.grid(row=1, column=1, padx=4, sticky=EW)
        # 绑定事件修复下拉框无法弹出问题
        self.quick_combo.bind('<Button-1>', self.on_quick_click)
        self.quick_combo.bind('<FocusIn>', self.on_quick_focus)
        self.quick_combo.bind('<<ComboboxSelected>>', self.on_quick_selected)
        # 设置 postcommand 确保每次下拉前刷新选项
        self.quick_combo['postcommand'] = self._populate_quick_combo

        ttk.Button(self.existing_frame, text="刷新", command=self.load_repo_list_async).grid(row=1, column=2, padx=4)
        self.existing_frame.columnconfigure(1, weight=1)

        self.new_frame = ttk.Frame(self.repo_frame)
        self.new_frame.grid(row=1, column=0, columnspan=2, sticky=EW, pady=4)

        ttk.Label(self.new_frame, text="仓库名称:").grid(row=0, column=0, padx=4, sticky=W)
        self.new_name_var = StringVar(value=self.new_repo_name)
        ttk.Entry(self.new_frame, textvariable=self.new_name_var, width=30).grid(row=0, column=1, padx=4, sticky=EW)
        ttk.Label(self.new_frame, text="描述(可选):").grid(row=0, column=2, padx=4, sticky=W)
        self.new_desc_var = StringVar(value=self.new_repo_desc)
        ttk.Entry(self.new_frame, textvariable=self.new_desc_var, width=30).grid(row=0, column=3, padx=4, sticky=EW)
        self.private_var = BooleanVar(value=self.new_repo_private)
        ttk.Checkbutton(self.new_frame, text="私有仓库", variable=self.private_var).grid(row=0, column=4, padx=4)
        self.new_frame.columnconfigure(1, weight=1)
        self.new_frame.columnconfigure(3, weight=1)

        self.on_repo_mode_change()

        # ---- 文件选择区域 ----
        self.file_frame = ttk.LabelFrame(main_frame, text="文件选择", padding="3")
        self.file_frame.pack(fill=X, pady=(0, 8))

        btn_frame = ttk.Frame(self.file_frame)
        btn_frame.pack(fill=X, pady=3)
        ttk.Button(btn_frame, text="选择文件", command=self.select_file).pack(side=LEFT, padx=4)
        ttk.Button(btn_frame, text="选择文件夹", command=self.select_folder).pack(side=LEFT, padx=4)
        ttk.Button(btn_frame, text="清空列表", command=self.clear_files).pack(side=LEFT, padx=4)

        self.yml_frame = ttk.LabelFrame(self.file_frame, text="自定义 YML 文件", padding="2")
        self.yml_frame.pack(fill=X, pady=(0, 4))
        yml_scroll = ttk.Scrollbar(self.yml_frame)
        yml_scroll.pack(side=RIGHT, fill=Y)
        self.yml_tree = ttk.Treeview(self.yml_frame, columns=("path",), show="tree headings",
                                     yscrollcommand=yml_scroll.set, height=3)
        yml_scroll.config(command=self.yml_tree.yview)
        self.yml_tree.heading("#0", text="文件名")
        self.yml_tree.heading("path", text="完整路径")
        self.yml_tree.column("#0", width=int(200 * self.font_scale))
        self.yml_tree.column("path", width=int(400 * self.font_scale))
        self.yml_tree.pack(fill=X)
        self.yml_tree.bind("<Delete>", lambda e: self.remove_selected_yml())
        self.yml_tree.bind("<Button-3>", self.show_yml_context_menu)

        self.zip_frame = ttk.LabelFrame(self.file_frame, text="ZIP 文件", padding="2")
        self.zip_frame.pack(fill=X)
        self.zip_label_var = StringVar(value="未选择 ZIP 文件")
        ttk.Label(self.zip_frame, textvariable=self.zip_label_var).pack(side=LEFT, padx=4, pady=3)
        ttk.Button(self.zip_frame, text="移除", command=self.remove_zip).pack(side=RIGHT, padx=4, pady=3)

        # ---- 上传按钮 ----
        self.upload_btn = ttk.Button(main_frame, text="开始上传", command=self.start_upload, style="Accent.TButton")
        self.upload_btn.pack(fill=X, pady=4)

        # ---- 信息标签页 ----
        self.notebook = ttk.Notebook(main_frame)
        self.notebook.pack(fill=BOTH, expand=True)

        # 日志
        log_frame = ttk.Frame(self.notebook)
        self.notebook.add(log_frame, text="操作日志")
        log_toolbar = ttk.Frame(log_frame)
        log_toolbar.pack(fill=X)
        ttk.Button(log_toolbar, text="清除日志", command=self.clear_log).pack(side=LEFT, padx=4)
        self.log_text = Text(log_frame, wrap=WORD, font=self.fixed_font)
        log_scroll = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.config(yscrollcommand=log_scroll.set)
        log_scroll.pack(side=RIGHT, fill=Y)
        self.log_text.pack(side=LEFT, fill=BOTH, expand=True)
        self.logger = Logger(self.log_text)

        # 信息
        info_frame = ttk.Frame(self.notebook)
        self.notebook.add(info_frame, text="登录信息")
        self.user_info_text = Text(info_frame, wrap=WORD, height=10, font=self.fixed_font, state=DISABLED)
        self.user_info_text.pack(fill=BOTH, expand=True, padx=4, pady=4)

        # 仓库内容
        content_frame = ttk.Frame(self.notebook)
        self.notebook.add(content_frame, text="仓库代码")
        download_frame = ttk.Frame(content_frame)
        download_frame.pack(fill=X, pady=4)
        ttk.Button(download_frame, text="刷新", command=self.load_repo_contents_async).pack(side=LEFT, padx=4)
        ttk.Button(download_frame, text="下载整个项目 ZIP", command=self.download_repo_zip).pack(side=LEFT, padx=4)
        ttk.Button(download_frame, text="下载历史", command=self.show_download_history).pack(side=LEFT, padx=4)

        self.content_tree = ttk.Treeview(content_frame, columns=("type", "size"), show="tree headings")
        self.content_tree.heading("#0", text="名称")
        self.content_tree.heading("type", text="类型")
        self.content_tree.heading("size", text="大小")
        self.content_tree.column("#0", width=int(300 * self.font_scale))
        self.content_tree.column("type", width=int(80 * self.font_scale))
        self.content_tree.column("size", width=int(100 * self.font_scale))
        content_scroll = ttk.Scrollbar(content_frame, command=self.content_tree.yview)
        self.content_tree.config(yscrollcommand=content_scroll.set)
        content_scroll.pack(side=RIGHT, fill=Y)
        self.content_tree.pack(side=LEFT, fill=BOTH, expand=True)

        # 添加右键菜单用于下载单个文件
        self.content_tree.bind("<Button-3>", self.show_content_context_menu)

        # 剪贴板标签页
        snippet_frame = ttk.Frame(self.notebook)
        self.notebook.add(snippet_frame, text="剪贴板")
        self.setup_snippet_tab(snippet_frame)

        # 状态栏
        self.status_var = StringVar(value="就绪")
        status_bar = ttk.Label(main_frame, textvariable=self.status_var, relief=SUNKEN, anchor=W)
        status_bar.pack(fill=X, pady=(4, 0))

        # 菜单
        menubar = Menu(self.root)
        self.root.config(menu=menubar)
        settings_menu = Menu(menubar, tearoff=0)
        menubar.add_cascade(label="设置", menu=settings_menu)
        settings_menu.add_command(label="首选项", command=self.open_settings_dialog)

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---------- 剪贴板标签页 ----------
    def setup_snippet_tab(self, parent):
        top_frame = ttk.Frame(parent)
        top_frame.pack(fill=X, pady=4)
        ttk.Label(top_frame, text="选择片段:").pack(side=LEFT, padx=4)
        self.snippet_combo = ttk.Combobox(top_frame, state="readonly", width=30)
        self.snippet_combo.pack(side=LEFT, padx=4)
        # 修复下拉框无法弹出
        self.snippet_combo.bind('<Button-1>', self.on_snippet_combo_click)
        self.snippet_combo.bind('<FocusIn>', self.on_snippet_combo_focus)
        self.snippet_combo.bind('<<ComboboxSelected>>', self.on_snippet_selected)

        ttk.Button(top_frame, text="复制到剪贴板", command=self.copy_snippet_to_clipboard).pack(side=LEFT, padx=4)
        ttk.Button(top_frame, text="管理片段", command=self.manage_snippets).pack(side=LEFT, padx=4)

        self.snippet_content_text = Text(parent, wrap=WORD, height=10, font=self.fixed_font)
        self.snippet_content_text.pack(fill=BOTH, expand=True, padx=4, pady=4)

        self.update_snippet_combo()

    def update_snippet_combo(self):
        names = [s.get("name", f"片段{i+1}") for i, s in enumerate(self.snippets)]
        self.snippet_combo['values'] = names
        if names:
            self.snippet_combo.current(0)
            self.on_snippet_selected()

    def on_snippet_selected(self, event=None):
        idx = self.snippet_combo.current()
        if idx >= 0:
            content = self.snippets[idx].get("content", "")
            self.snippet_content_text.delete(1.0, END)
            self.snippet_content_text.insert(1.0, content)

    def on_snippet_combo_click(self, event):
        """点击时确保 values 存在并尝试弹出"""
        self.update_snippet_combo()
        # 强制弹出下拉列表
        self.snippet_combo.focus_set()
        self.snippet_combo.event_generate('<Down>')

    def on_snippet_combo_focus(self, event):
        self.update_snippet_combo()

    def copy_snippet_to_clipboard(self):
        idx = self.snippet_combo.current()
        if idx >= 0:
            content = self.snippets[idx].get("content", "")
            self.root.clipboard_clear()
            self.root.clipboard_append(content)
            self.logger.add(f"📋 已复制片段 '{self.snippets[idx].get('name', '')}' 到剪贴板")

    def manage_snippets(self):
        dialog = Toplevel(self.root)
        dialog.title("管理剪贴板片段")
        # 根据字体缩放调整对话框大小
        base_w, base_h = 600, 500
        w = int(base_w * min(1.5, self.font_scale))
        h = int(base_h * min(1.5, self.font_scale))
        dialog.geometry(f"{w}x{h}")
        dialog.transient(self.root)
        dialog.grab_set()

        frame = ttk.Frame(dialog, padding="10")
        frame.pack(fill=BOTH, expand=True)

        ttk.Label(frame, text="编辑片段 (最多10个)").pack(anchor=W, pady=5)

        # Treeview 列宽也按缩放调整
        tree = ttk.Treeview(frame, columns=("name",), show="tree headings", height=8)
        tree.heading("#0", text="序号")
        tree.heading("name", text="名称")
        tree.column("#0", width=int(50 * self.font_scale))
        tree.column("name", width=int(150 * self.font_scale))
        tree.pack(fill=BOTH, expand=True, pady=5)

        for i, s in enumerate(self.snippets):
            tree.insert("", END, iid=str(i), text=str(i+1), values=(s.get("name", ""),))

        edit_frame = ttk.LabelFrame(frame, text="编辑选中片段", padding="5")
        edit_frame.pack(fill=X, pady=5)

        ttk.Label(edit_frame, text="名称:").grid(row=0, column=0, sticky=W, padx=5)
        name_var = StringVar()
        name_entry = ttk.Entry(edit_frame, textvariable=name_var, width=40)
        name_entry.grid(row=0, column=1, sticky=EW, padx=5)
        ttk.Label(edit_frame, text="内容:").grid(row=1, column=0, sticky=NW, padx=5)
        content_text = Text(edit_frame, height=6, width=60, font=self.fixed_font)
        content_text.grid(row=1, column=1, sticky=EW, padx=5, pady=5)
        edit_frame.columnconfigure(1, weight=1)

        def on_tree_select(event):
            sel = tree.selection()
            if sel:
                idx = int(sel[0])
                name_var.set(self.snippets[idx].get("name", ""))
                content_text.delete(1.0, END)
                content_text.insert(1.0, self.snippets[idx].get("content", ""))

        tree.bind('<<TreeviewSelect>>', on_tree_select)

        def save_current():
            sel = tree.selection()
            if sel:
                idx = int(sel[0])
                self.snippets[idx]["name"] = name_var.get()
                self.snippets[idx]["content"] = content_text.get(1.0, END).strip()
                tree.item(sel[0], values=(name_var.get(),))
                self.config['snippets'] = self.snippets
                save_config(self.config)
                self.update_snippet_combo()
                self.logger.add(f"已保存片段 '{name_var.get()}'")

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=X, pady=10)
        ttk.Button(btn_frame, text="保存当前", command=save_current).pack(side=LEFT, padx=5)
        ttk.Button(btn_frame, text="关闭", command=dialog.destroy).pack(side=RIGHT, padx=5)

        # 强制更新布局
        dialog.update_idletasks()

    # ---------- 快速选择下拉框修复 ----------
    def _populate_quick_combo(self):
        """刷新快速选择下拉列表"""
        values = [repo['full_name'] for repo in self.user_repos]
        self.quick_combo['values'] = values
        # 设置下拉可见行数
        row_height = max(10, int(10 * self.font_scale))
        self.quick_combo.configure(height=min(20, row_height))
        self.quick_combo.update_idletasks()

    def on_quick_click(self, event):
        """点击快速选择时刷新并弹出下拉"""
        self._populate_quick_combo()
        self.quick_combo.focus_set()
        self.quick_combo.event_generate('<Down>')

    def on_quick_focus(self, event):
        self._populate_quick_combo()

    def on_quick_search(self, event=None):
        search = self.quick_search_var.get().lower()
        filtered = [repo['full_name'] for repo in self.user_repos if search in repo['full_name'].lower()]
        self.quick_combo['values'] = filtered
        if filtered:
            self.quick_combo.event_generate('<Down>')

    def on_quick_selected(self, event=None):
        fullname = self.quick_search_var.get()
        for repo in self.user_repos:
            if repo['full_name'] == fullname:
                self.selected_repo = repo
                self.repo_url_var.set(repo['html_url'])
                self.save_config_later()
                self.quick_search_var.set("")
                self.logger.add(f"已选择仓库: {fullname}")
                self.repo_mode_var.set("existing")
                self.on_repo_mode_change()
                break

    # ---------- 以下方法均为原有功能，保持完整 ----------
    def toggle_token_visibility(self):
        self.token_entry.config(show="" if self.show_token_var.get() else "*")

    def apply_token(self):
        token = self.token_var.get().strip()
        if not token:
            messagebox.showerror("错误", "Token 不能为空")
            return
        self.token = token
        self.config['token'] = token
        save_config(self.config)
        self.api = GitHubAPI(token)
        self.update_user_info()
        self.load_repo_list_async()
        self.logger.add("Token 已应用，正在验证...")

    def update_user_info(self):
        if not self.api:
            return
        def task():
            try:
                user = self.api.get_authenticated_user()
                self.root.after(0, lambda: self._display_user_info(user))
                self.logger.add(f"✅ 登录成功，用户: {user['login']}")
            except Exception as e:
                self.logger.add(f"❌ Token 验证失败: {e}")
        threading.Thread(target=task, daemon=True).start()

    def _display_user_info(self, user):
        self.user_info_text.config(state=NORMAL)
        self.user_info_text.delete(1.0, END)
        info = f"用户名: {user['login']}\n"
        info += f"姓名: {user.get('name', '未设置')}\n"
        info += f"邮箱: {user.get('email', '未公开')}\n"
        info += f"头像: {user.get('avatar_url', '')}\n"
        info += "\n--- 仓库信息 ---\n"
        if self.create_new:
            info += f"新仓库: {self.new_name_var.get()}\n"
        elif self.repo_url_var.get():
            parsed = self.parse_repo_url(self.repo_url_var.get())
            if parsed:
                info += f"仓库: {parsed[0]}/{parsed[1]}\n分支: {self.branch}\n"
            else:
                info += "仓库地址格式错误\n"
        else:
            info += "未选择仓库\n"
        self.user_info_text.insert(END, info)
        self.user_info_text.config(state=DISABLED)

    def load_repo_list_async(self):
        if not self.api:
            return
        self.status_var.set("正在加载仓库列表...")
        def task():
            try:
                repos = self.api.list_user_repos()
                self.user_repos = repos
                self.root.after(0, self._populate_quick_combo)
                self.logger.add(f"已加载 {len(repos)} 个仓库")
            except Exception as e:
                self.logger.add(f"加载仓库列表失败: {e}")
            finally:
                self.root.after(0, lambda: self.status_var.set("就绪"))
        threading.Thread(target=task, daemon=True).start()

    def parse_repo_url(self, url: str) -> Optional[Tuple[str, str]]:
        patterns = [
            re.compile(r"github\.com[:/]([^/]+)/([^/.]+)"),
            re.compile(r"https?://github\.com/([^/]+)/([^/.]+)")
        ]
        for p in patterns:
            m = p.search(url)
            if m:
                return m.group(1), m.group(2)
        return None

    def on_repo_mode_change(self):
        mode = self.repo_mode_var.get()
        self.create_new = (mode == "new")
        self.config['create_new'] = self.create_new
        save_config(self.config)
        if self.create_new:
            self.existing_frame.grid_remove()
            self.new_frame.grid()
        else:
            self.new_frame.grid_remove()
            self.existing_frame.grid()
        self.update_user_info()

    # ---------- 文件选择相关 ----------
    def select_file(self):
        filepath = filedialog.askopenfilename(
            title="选择文件",
            filetypes=[("支持的文件", "*.yml *.yaml *.zip"), ("所有文件", "*.*")]
        )
        if not filepath:
            return
        filename = os.path.basename(filepath)
        ext = os.path.splitext(filename)[1].lower()
        if ext in ('.yml', '.yaml'):
            item = CustomYmlItem(filepath)
            self.custom_yml_files.append(item)
            self.yml_tree.insert("", END, text=item.filename, values=(item.filepath,), iid=filepath)
            self.logger.add(f"➕ 添加 YML: {filename}")
        elif ext == '.zip':
            if self.zip_filepath:
                self.logger.add(f"📁 替换 ZIP: {self.zip_filename} -> {filename}")
            else:
                self.logger.add(f"📁 选择 ZIP: {filename}")
            self.zip_filepath = filepath
            self.zip_filename = filename
            self.zip_label_var.set(f"ZIP: {filename}")
        else:
            messagebox.showwarning("不支持的文件类型", f"文件 {filename} 不是 .yml/.yaml 或 .zip，已忽略")

    def select_folder(self):
        folder = filedialog.askdirectory(title="选择要打包的文件夹")
        if not folder:
            return
        self.status_var.set("正在打包文件夹...")
        self.logger.add(f"📂 开始打包文件夹: {folder}")

        PROTECTED_FILES = {'.gitignore', 'build.gradle', 'settings.gradle', 'gradle.properties', 'gradlew', 'gradlew.bat'}

        def should_exclude(path):
            name = os.path.basename(path)
            if name in PROTECTED_FILES:
                return False
            for pattern in self.folder_exclude_patterns:
                if pattern.endswith('/'):
                    if os.path.isdir(path) and name == pattern[:-1]:
                        return True
                elif fnmatch.fnmatch(name, pattern):
                    return True
            return False

        def pack_task():
            try:
                temp_zip = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
                zip_path = temp_zip.name
                temp_zip.close()

                base_name = os.path.basename(folder)
                zip_name = f"{base_name}.zip"

                with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                    for root_dir, dirs, files in os.walk(folder):
                        dirs[:] = [d for d in dirs if not should_exclude(os.path.join(root_dir, d))]
                        for file in files:
                            file_path = os.path.join(root_dir, file)
                            if should_exclude(file_path):
                                continue
                            arcname = os.path.relpath(file_path, folder)
                            zf.write(file_path, arcname)

                self.root.after(0, lambda: self._folder_pack_done(zip_path, zip_name, folder))
            except Exception as e:
                self.root.after(0, lambda: self._folder_pack_error(str(e)))

        threading.Thread(target=pack_task, daemon=True).start()

    def _folder_pack_done(self, zip_path, zip_name, folder):
        self.zip_filepath = zip_path
        self.zip_filename = zip_name
        self.zip_label_var.set(f"ZIP: {zip_name} (来自文件夹)")
        self.logger.add(f"✅ 文件夹打包完成: {folder} -> {zip_name}")
        self.status_var.set("就绪")

    def _folder_pack_error(self, err_msg):
        self.logger.add(f"❌ 文件夹打包失败: {err_msg}")
        self.status_var.set("就绪")
        messagebox.showerror("打包失败", f"打包过程中出错:\n{err_msg}")

    def clear_files(self):
        self.custom_yml_files.clear()
        for item in self.yml_tree.get_children():
            self.yml_tree.delete(item)
        if self.zip_filepath and self.zip_filepath.startswith(tempfile.gettempdir()):
            try:
                os.unlink(self.zip_filepath)
            except:
                pass
        self.zip_filepath = None
        self.zip_filename = ""
        self.zip_label_var.set("未选择 ZIP 文件")
        self.logger.add("已清空文件列表")

    def remove_selected_yml(self):
        selected = self.yml_tree.selection()
        for iid in selected:
            self.yml_tree.delete(iid)
            self.custom_yml_files = [f for f in self.custom_yml_files if f.filepath != iid]
            self.logger.add(f"🗑 移除 YML: {os.path.basename(iid)}")

    def show_yml_context_menu(self, event):
        iid = self.yml_tree.identify_row(event.y)
        if iid:
            self.yml_tree.selection_set(iid)
            menu = Menu(self.root, tearoff=0)
            menu.add_command(label="移除", command=self.remove_selected_yml)
            menu.post(event.x_root, event.y_root)

    def remove_zip(self):
        if self.zip_filepath:
            self.logger.add(f"🗑 移除 ZIP: {self.zip_filename}")
            if self.zip_filepath.startswith(tempfile.gettempdir()):
                try:
                    os.unlink(self.zip_filepath)
                except:
                    pass
            self.zip_filepath = None
            self.zip_filename = ""
            self.zip_label_var.set("未选择 ZIP 文件")

    def clear_log(self):
        self.logger.clear()

    # ---------- 下载仓库 ZIP ----------
    def download_repo_zip(self):
        if not self.api:
            messagebox.showwarning("提示", "请先配置 Token")
            return
        if self.create_new:
            messagebox.showinfo("提示", "新仓库尚未创建，无法下载")
            return
        url = self.repo_url_var.get().strip()
        if not url:
            messagebox.showwarning("提示", "请输入仓库地址")
            return
        parsed = self.parse_repo_url(url)
        if not parsed:
            messagebox.showwarning("提示", "仓库地址格式错误")
            return
        owner, repo = parsed
        branch = self.branch

        save_path = filedialog.asksaveasfilename(
            defaultextension=".zip",
            filetypes=[("ZIP 文件", "*.zip")],
            initialfile=f"{repo}-{branch}.zip"
        )
        if not save_path:
            return

        self.status_var.set("正在下载仓库 ZIP...")
        self.logger.add(f"📥 开始下载仓库: {owner}/{repo} 分支: {branch}")
        self.logger.add(f"💾 保存路径: {save_path}")

        def task():
            try:
                zip_data = self.api.download_repo_archive(owner, repo, branch)
                with open(save_path, 'wb') as f:
                    f.write(zip_data)
                size_mb = len(zip_data) / (1024*1024)

                # 添加到下载历史
                download_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                history_item = DownloadHistoryItem(owner, repo, "", download_time, f"{size_mb:.2f} MB")
                self.download_history.insert(0, {
                    "owner": owner,
                    "repo": repo,
                    "path": "",
                    "download_time": download_time,
                    "size": f"{size_mb:.2f} MB"
                })
                if len(self.download_history) > 20:
                    self.download_history = self.download_history[:20]
                self.config['download_history'] = self.download_history
                save_config(self.config)

                self.root.after(0, lambda: self._download_done(save_path, size_mb))
            except Exception as e:
                self.root.after(0, lambda: self._download_error(str(e)))

        threading.Thread(target=task, daemon=True).start()

    def _download_done(self, path, size_mb):
        self.logger.add(f"✅ 下载完成: {path} (大小: {size_mb:.2f} MB)")
        self.status_var.set("就绪")
        messagebox.showinfo("下载完成", f"仓库代码已保存到:\n{path}\n大小: {size_mb:.2f} MB")

    def _download_error(self, err_msg):
        self.logger.add(f"❌ 下载失败: {err_msg}")
        self.status_var.set("就绪")
        messagebox.showerror("下载失败", err_msg)

    # ---------- 下载单个文件 ----------
    def download_single_file(self, item_name, item_path, item_type):
        """下载单个文件或文件夹"""
        if not self.api:
            messagebox.showwarning("提示", "请先配置 Token")
            return

        url = self.repo_url_var.get().strip()
        if not url:
            messagebox.showwarning("提示", "请输入仓库地址")
            return
        parsed = self.parse_repo_url(url)
        if not parsed:
            messagebox.showwarning("提示", "仓库地址格式错误")
            return
        owner, repo = parsed
        branch = self.branch

        if item_type == "dir":
            # 下载整个文件夹为 ZIP
            save_path = filedialog.asksaveasfilename(
                defaultextension=".zip",
                filetypes=[("ZIP 文件", "*.zip")],
                initialfile=f"{item_name}-{branch}.zip"
            )
            if not save_path:
                return

            self.status_var.set(f"正在下载文件夹 {item_name}...")
            self.logger.add(f"📂 开始下载文件夹: {item_name}")
            self.logger.add(f"💾 保存路径: {save_path}")

            def task():
                try:
                    # 递归下载文件夹内容并打包
                    zip_data = self._download_folder_as_zip(owner, repo, item_path, branch)
                    if zip_data:
                        with open(save_path, 'wb') as f:
                            f.write(zip_data)
                        size_mb = len(zip_data) / (1024*1024)

                        # 添加到下载历史
                        download_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        self.download_history.insert(0, {
                            "owner": owner,
                            "repo": repo,
                            "path": item_path,
                            "download_time": download_time,
                            "size": f"{size_mb:.2f} MB"
                        })
                        if len(self.download_history) > 20:
                            self.download_history = self.download_history[:20]
                        self.config['download_history'] = self.download_history
                        save_config(self.config)

                        self.root.after(0, lambda: self._download_done(save_path, size_mb))
                    else:
                        self.root.after(0, lambda: self._download_error("文件夹下载失败"))
                except Exception as e:
                    self.root.after(0, lambda: self._download_error(str(e)))

            threading.Thread(target=task, daemon=True).start()
        else:
            # 下载单个文件
            save_path = filedialog.asksaveasfilename(
                defaultextension=os.path.splitext(item_name)[1] or ".txt",
                filetypes=[("所有文件", "*.*")],
                initialfile=item_name
            )
            if not save_path:
                return

            self.status_var.set(f"正在下载文件 {item_name}...")
            self.logger.add(f"📄 开始下载文件: {item_name}")
            self.logger.add(f"💾 保存路径: {save_path}")

            def task():
                try:
                    file_data = self.api.download_file_content(owner, repo, item_path, branch)
                    if file_data:
                        with open(save_path, 'wb') as f:
                            f.write(file_data)
                        size_kb = len(file_data) / 1024

                        # 添加到下载历史
                        download_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        self.download_history.insert(0, {
                            "owner": owner,
                            "repo": repo,
                            "path": item_path,
                            "download_time": download_time,
                            "size": f"{size_kb:.2f} KB"
                        })
                        if len(self.download_history) > 20:
                            self.download_history = self.download_history[:20]
                        self.config['download_history'] = self.download_history
                        save_config(self.config)

                        self.root.after(0, lambda: self._single_file_download_done(save_path, size_kb))
                    else:
                        self.root.after(0, lambda: self._download_error("文件下载失败"))
                except Exception as e:
                    self.root.after(0, lambda: self._download_error(str(e)))

            threading.Thread(target=task, daemon=True).start()

    def _download_folder_as_zip(self, owner, repo, folder_path, branch) -> Optional[bytes]:
        """递归下载文件夹内容并返回 ZIP 数据"""
        try:
            import io
            contents = self.api.get_repo_contents(owner, repo, folder_path, branch)

            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
                for item in contents:
                    item_name = item['name']
                    item_path = item['path']
                    item_type = item['type']

                    if item_type == 'file':
                        # 下载文件
                        file_data = self.api.download_file_content(owner, repo, item_path, branch)
                        if file_data:
                            zf.writestr(item_name, file_data)
                    elif item_type == 'dir':
                        # 递归下载子文件夹
                        sub_zip = self._download_folder_as_zip(owner, repo, item_path, branch)
                        if sub_zip:
                            # 将子文件夹的 ZIP 内容添加到当前 ZIP
                            sub_buffer = io.BytesIO(sub_zip)
                            with zipfile.ZipFile(sub_buffer, 'r') as sub_zf:
                                for sub_item in sub_zf.namelist():
                                    # 去掉子文件夹名称前缀
                                    new_name = f"{item_name}/{sub_item}"
                                    zf.writestr(new_name, sub_zf.read(sub_item))

            return buffer.getvalue()
        except Exception as e:
            self.logger.add(f"❌ 下载文件夹出错: {e}")
            return None

    def _single_file_download_done(self, path, size_kb):
        self.logger.add(f"✅ 文件下载完成: {path} (大小: {size_kb:.2f} KB)")
        self.status_var.set("就绪")
        messagebox.showinfo("下载完成", f"文件已保存到:\n{path}\n大小: {size_kb:.2f} KB")

    # ---------- 显示下载历史 ----------
    def show_download_history(self):
        """显示下载历史对话框"""
        dialog = Toplevel(self.root)
        dialog.title("下载历史记录")
        dialog.geometry("600x400")
        dialog.transient(self.root)
        dialog.grab_set()

        frame = ttk.Frame(dialog, padding="10")
        frame.pack(fill=BOTH, expand=True)

        ttk.Label(frame, text="最近 20 条下载记录", font=('', 10, 'bold')).pack(pady=5)

        # 创建历史记录树形列表
        tree_frame = ttk.Frame(frame)
        tree_frame.pack(fill=BOTH, expand=True, pady=5)

        tree_scroll = ttk.Scrollbar(tree_frame)
        tree_scroll.pack(side=RIGHT, fill=Y)

        history_tree = ttk.Treeview(tree_frame, columns=("repo", "path", "time", "size"), show="tree headings",
                                     yscrollcommand=tree_scroll.set, height=15)
        tree_scroll.config(command=history_tree.yview)

        history_tree.heading("#0", text="序号")
        history_tree.heading("repo", text="仓库")
        history_tree.heading("path", text="路径")
        history_tree.heading("time", text="下载时间")
        history_tree.heading("size", text="大小")

        history_tree.column("#0", width=50)
        history_tree.column("repo", width=150)
        history_tree.column("path", width=200)
        history_tree.column("time", width=150)
        history_tree.column("size", width=80)

        history_tree.pack(side=LEFT, fill=BOTH, expand=True)

        if not self.download_history:
            history_tree.insert("", END, text="1", values=("无下载记录", "", "", ""))
        else:
            for i, item in enumerate(self.download_history):
                history_tree.insert("", END, text=str(i+1), values=(
                    f"{item.get('owner', '')}/{item.get('repo', '')}",
                    item.get('path', '') or "(整个项目)",
                    item.get('download_time', ''),
                    item.get('size', '')
                ))

        # 按钮区域
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(pady=10)

        def clear_history():
            self.download_history = []
            self.config['download_history'] = self.download_history
            save_config(self.config)
            self.logger.add("已清空下载历史")
            dialog.destroy()

        ttk.Button(btn_frame, text="清空历史", command=clear_history).pack(side=LEFT, padx=5)
        ttk.Button(btn_frame, text="关闭", command=dialog.destroy).pack(side=LEFT, padx=5)

    # ---------- 仓库内容右键菜单 ----------
    def show_content_context_menu(self, event):
        """显示仓库内容右键菜单"""
        item_id = self.content_tree.identify_row(event.y)
        if not item_id:
            return

        self.content_tree.selection_set(item_id)
        item = self.content_tree.item(item_id)

        if not item['values']:
            return

        item_name = item['text']
        item_type = item['values'][0]

        menu = Menu(self.root, tearoff=0)
        if item_type == "目录":
            menu.add_command(label=f"下载文件夹 '{item_name}'",
                           command=lambda: self.download_single_file(item_name, item_name, "dir"))
        else:
            menu.add_command(label=f"下载文件 '{item_name}'",
                           command=lambda: self.download_single_file(item_name, item_name, "file"))

        menu.post(event.x_root, event.y_root)

    def load_repo_contents_async(self):
        if not self.api:
            messagebox.showwarning("提示", "请先配置 Token")
            return
        if self.create_new:
            self.logger.add("当前为「创建新仓库」模式，无法加载内容。")
            return

        url = self.repo_url_var.get().strip()
        if not url:
            messagebox.showwarning("提示", "请输入仓库地址")
            return
        parsed = self.parse_repo_url(url)
        if not parsed:
            messagebox.showwarning("提示", "仓库地址格式错误")
            return
        owner, repo = parsed
        branch = self.branch

        self.status_var.set("正在加载仓库内容...")
        self.logger.add(f"📋 加载仓库内容: {owner}/{repo} ({branch})")
        def task():
            try:
                contents = self.api.get_repo_contents(owner, repo, "", branch)
                self.root.after(0, lambda: self._display_repo_contents(contents))
                self.logger.add(f"📁 已加载 {len(contents)} 个顶层项目")
            except Exception as e:
                self.logger.add(f"❌ 加载仓库内容失败: {e}")
            finally:
                self.root.after(0, lambda: self.status_var.set("就绪"))
        threading.Thread(target=task, daemon=True).start()

    def _display_repo_contents(self, contents):
        for item in self.content_tree.get_children():
            self.content_tree.delete(item)
        for item in contents:
            type_str = "目录" if item['type'] == 'dir' else "文件"
            size = item.get('size', '')
            if size:
                if size > 1024 * 1024:
                    size_str = f"{size / (1024*1024):.1f} MB"
                elif size > 1024:
                    size_str = f"{size / 1024:.1f} KB"
                else:
                    size_str = f"{size} B"
            else:
                size_str = ""
            self.content_tree.insert("", END, text=item['name'], values=(type_str, size_str))

    def generate_build_yml(self) -> str:
        template = BUILD_YML_TEMPLATE
        branch = self.build_branch
        build_type_cap = self.build_type.capitalize()
        replacements = {
            '{{BRANCH}}': branch,
            '{{JAVA_VERSION}}': self.java_version,
            '{{GRADLE_VERSION}}': self.gradle_version,
            '{{BUILD_TYPE}}': self.build_type,
            '{{BUILD_TYPE_CAPITALIZED}}': build_type_cap,
        }
        for key, val in replacements.items():
            template = template.replace(key, val)
        return template

    def start_upload(self):
        if self.is_uploading:
            return
        if not self.api:
            messagebox.showerror("错误", "请先配置并应用 Token")
            return
        if self.create_new:
            name = self.new_name_var.get().strip()
            if not name:
                messagebox.showerror("错误", "请输入新仓库名称")
                return
        else:
            url = self.repo_url_var.get().strip()
            if not url:
                messagebox.showerror("错误", "请输入仓库地址")
                return
            if not self.parse_repo_url(url):
                messagebox.showerror("错误", "仓库地址格式错误")
                return

        msg = "即将上传：\n"
        if self.upload_default_unpack:
            msg += "  - unpack.yml (默认)\n"
        if self.upload_default_build:
            msg += "  - build.yml (默认)\n"
        msg += f"自定义 YML: {len(self.custom_yml_files)} 个\n"
        msg += f"ZIP: {'是' if self.zip_filepath else '否'}\n"
        if not messagebox.askyesno("确认上传", msg + "是否继续？"):
            return

        self.is_uploading = True
        self.upload_btn.config(state=DISABLED, text="上传中...")
        self.status_var.set("正在上传...")
        self.logger.add("🚀 开始上传...")

        def upload_task():
            try:
                token = self.token
                created_repo = None
                if self.create_new:
                    self.logger.add(f"📦 创建仓库: {self.new_name_var.get()}")
                    created_repo = self.api.create_repository(
                        name=self.new_name_var.get(),
                        description=self.new_desc_var.get(),
                        private=self.private_var.get(),
                        auto_init=False
                    )
                    owner = created_repo['owner']['login']
                    repo_name = created_repo['name']
                    target_branch = self.branch
                    def after_create():
                        self.repo_mode_var.set("existing")
                        self.on_repo_mode_change()
                        self.repo_url_var.set(created_repo['html_url'])
                        self.save_config_later()
                        self.logger.add(f"✅ 仓库创建成功: {created_repo['html_url']}")
                        self.load_repo_list_async()
                    self.root.after(0, after_create)
                else:
                    owner, repo_name = self.parse_repo_url(self.repo_url_var.get())
                    target_branch = self.branch
                    self.logger.add(f"📦 仓库: {owner}/{repo_name}")

                self.logger.add(f"🌿 分支: {target_branch}")

                if self.upload_default_unpack:
                    self.logger.add("📤 上传 unpack.yml ...")
                    self.upload_yml_content(owner, repo_name, "unpack.yml", UNPACK_YML_TEMPLATE, token, target_branch)

                if self.upload_default_build:
                    self.logger.add("📤 上传 build.yml ...")
                    build_content = self.generate_build_yml()
                    self.upload_yml_content(owner, repo_name, "build.yml", build_content, token, target_branch)

                for item in self.custom_yml_files:
                    self.logger.add(f"📤 上传自定义 YML: {item.filename} ...")
                    try:
                        with open(item.filepath, 'rb') as f:
                            content_b64 = base64.b64encode(f.read()).decode('utf-8')
                        self.upload_file(owner, repo_name, f".github/workflows/{item.filename}", content_b64, token, target_branch)
                        self.logger.add(f"✅ {item.filename} 上传成功")
                    except Exception as e:
                        self.logger.add(f"❌ {item.filename} 上传失败: {e}")

                if self.zip_filepath:
                    self.logger.add(f"📤 上传 ZIP: {self.zip_filename} ...")
                    try:
                        with open(self.zip_filepath, 'rb') as f:
                            content_b64 = base64.b64encode(f.read()).decode('utf-8')
                        self.upload_file(owner, repo_name, self.zip_filename, content_b64, token, target_branch)
                        self.logger.add(f"✅ {self.zip_filename} 上传成功")
                    except Exception as e:
                        self.logger.add(f"❌ ZIP 上传失败: {e}")
                else:
                    self.logger.add("📂 无 ZIP 文件")

                self.logger.add("✅ 所有操作完成！")
                self.root.after(1000, self.load_repo_contents_async)

            except Exception as e:
                self.logger.add(f"❌ 错误: {e}")
            finally:
                self.root.after(0, self._upload_finished)

        threading.Thread(target=upload_task, daemon=True).start()

    def upload_yml_content(self, owner, repo, filename, content, token, branch):
        content_b64 = base64.b64encode(content.encode('utf-8')).decode('utf-8')
        self.upload_file(owner, repo, f".github/workflows/{filename}", content_b64, token, branch)
        self.logger.add(f"✅ {filename} 上传成功")

    def upload_file(self, owner, repo, path, content_b64, token, branch):
        sha = self.api.get_file_sha(owner, repo, path, branch)
        self.api.create_or_update_file(owner, repo, path, content_b64, f"Upload {path}", branch, sha)

    def _upload_finished(self):
        self.is_uploading = False
        self.upload_btn.config(state=NORMAL, text="开始上传")
        self.status_var.set("就绪")

    def save_config_later(self):
        self.config['repo_url'] = self.repo_url_var.get()
        self.config['create_new'] = self.create_new
        self.config['new_repo_name'] = self.new_name_var.get()
        self.config['new_repo_desc'] = self.new_desc_var.get()
        self.config['new_repo_private'] = self.private_var.get()
        save_config(self.config)

    # ---------- 设置对话框 ----------
    def open_settings_dialog(self):
        dialog = Toplevel(self.root)
        dialog.title("设置")
        dialog.geometry("650x750")
        dialog.transient(self.root)
        dialog.grab_set()

        nb = ttk.Notebook(dialog)
        nb.pack(fill=BOTH, expand=True, padx=5, pady=5)

        # 基本设置页
        basic_frame = ttk.Frame(nb, padding="10")
        nb.add(basic_frame, text="基本设置")

        row = 0
        ttk.Label(basic_frame, text="GitHub Token:").grid(row=row, column=0, sticky=W, pady=5)
        token_var = StringVar(value=self.token)
        token_entry = ttk.Entry(basic_frame, textvariable=token_var, width=40, show="*")
        token_entry.grid(row=row, column=1, sticky=EW, pady=5)
        row += 1

        ttk.Label(basic_frame, text="目标分支:").grid(row=row, column=0, sticky=W, pady=5)
        branch_var = StringVar(value=self.branch)
        ttk.Entry(basic_frame, textvariable=branch_var, width=20).grid(row=row, column=1, sticky=W, pady=5)
        row += 1

        ttk.Separator(basic_frame, orient='horizontal').grid(row=row, column=0, columnspan=2, sticky=EW, pady=10)
        row += 1

        # 字体缩放设置
        ttk.Label(basic_frame, text="界面字体缩放", font=('', 10, 'bold')).grid(row=row, column=0, columnspan=2, sticky=W)
        row += 1
        scale_frame = ttk.Frame(basic_frame)
        scale_frame.grid(row=row, column=0, columnspan=2, sticky=EW, pady=5)
        font_scale_var = DoubleVar(value=self.font_scale)
        scale_widget = ttk.Scale(scale_frame, from_=0.8, to=2.0, variable=font_scale_var, orient=HORIZONTAL, length=200)
        scale_widget.pack(side=LEFT, padx=5)
        scale_label = ttk.Label(scale_frame, text=f"{self.font_scale:.1f}倍")
        scale_label.pack(side=LEFT, padx=5)
        def update_scale_label(*args):
            scale_label.config(text=f"{font_scale_var.get():.1f}倍")
        font_scale_var.trace_add('write', update_scale_label)
        row += 1
        ttk.Label(basic_frame, text="（修改后需要重启程序才能完全生效）", foreground="gray").grid(row=row, column=0, columnspan=2, sticky=W)
        row += 1

        # 紧凑模式
        compact_var = BooleanVar(value=self.compact_mode)
        ttk.Checkbutton(basic_frame, text="紧凑模式（隐藏分组标题）", variable=compact_var).grid(row=row, column=0, columnspan=2, sticky=W, pady=5)
        row += 1
        ttk.Label(basic_frame, text="隐藏"GitHub认证"、"仓库设置"等标签，界面更简洁", foreground="gray").grid(row=row, column=0, columnspan=2, sticky=W)
        row += 1

        ttk.Separator(basic_frame, orient='horizontal').grid(row=row, column=0, columnspan=2, sticky=EW, pady=10)
        row += 1

        ttk.Label(basic_frame, text="默认 Workflow", font=('', 10, 'bold')).grid(row=row, column=0, columnspan=2, sticky=W)
        row += 1
        unpack_var = BooleanVar(value=self.upload_default_unpack)
        ttk.Checkbutton(basic_frame, text="上传 unpack.yml (解压ZIP)", variable=unpack_var).grid(row=row, column=0, columnspan=2, sticky=W)
        row += 1
        build_var = BooleanVar(value=self.upload_default_build)
        ttk.Checkbutton(basic_frame, text="上传 build.yml (构建APK)", variable=build_var).grid(row=row, column=0, columnspan=2, sticky=W)
        row += 1

        ttk.Separator(basic_frame, orient='horizontal').grid(row=row, column=0, columnspan=2, sticky=EW, pady=10)
        row += 1

        ttk.Label(basic_frame, text="新仓库选项", font=('', 10, 'bold')).grid(row=row, column=0, columnspan=2, sticky=W)
        row += 1
        ttk.Label(basic_frame, text="描述 (可选):").grid(row=row, column=0, sticky=W, pady=5)
        desc_var = StringVar(value=self.new_repo_desc)
        ttk.Entry(basic_frame, textvariable=desc_var, width=40).grid(row=row, column=1, sticky=EW, pady=5)
        row += 1
        private_var = BooleanVar(value=self.new_repo_private)
        ttk.Checkbutton(basic_frame, text="私有仓库", variable=private_var).grid(row=row, column=0, columnspan=2, sticky=W)
        row += 1

        basic_frame.columnconfigure(1, weight=1)

        # Build 设置页
        build_frame = ttk.Frame(nb, padding="10")
        nb.add(build_frame, text="Build 配置")

        brow = 0
        ttk.Label(build_frame, text="触发分支:").grid(row=brow, column=0, sticky=W, pady=5)
        branch_frame = ttk.Frame(build_frame)
        branch_frame.grid(row=brow, column=1, sticky=W, pady=5)
        build_branch_var = StringVar(value=self.build_branch if self.build_branch in ('main', 'master') else 'custom')
        ttk.Radiobutton(branch_frame, text="main", variable=build_branch_var, value="main").pack(side=LEFT, padx=2)
        ttk.Radiobutton(branch_frame, text="master", variable=build_branch_var, value="master").pack(side=LEFT, padx=2)
        ttk.Radiobutton(branch_frame, text="自定义:", variable=build_branch_var, value="custom").pack(side=LEFT, padx=2)
        custom_branch_var = StringVar(value=self.build_branch if self.build_branch not in ('main', 'master') else '')
        custom_branch_entry = ttk.Entry(branch_frame, textvariable=custom_branch_var, width=10, state='readonly' if build_branch_var.get() != 'custom' else 'normal')
        custom_branch_entry.pack(side=LEFT, padx=2)
        def on_branch_change(*args):
            if build_branch_var.get() == 'custom':
                custom_branch_entry.config(state='normal')
            else:
                custom_branch_entry.config(state='readonly')
        build_branch_var.trace_add('write', on_branch_change)
        brow += 1

        ttk.Label(build_frame, text="Java 版本:").grid(row=brow, column=0, sticky=W, pady=5)
        java_var = StringVar(value=self.java_version)
        ttk.Entry(build_frame, textvariable=java_var, width=10).grid(row=brow, column=1, sticky=W, pady=5)
        brow += 1

        ttk.Label(build_frame, text="JAVA_HOME 路径 (留空自动):").grid(row=brow, column=0, sticky=W, pady=5)
        java_home_var = StringVar(value=self.java_home_custom)
        ttk.Entry(build_frame, textvariable=java_home_var, width=30).grid(row=brow, column=1, sticky=EW, pady=5)
        brow += 1

        ttk.Label(build_frame, text="Gradle 版本:").grid(row=brow, column=0, sticky=W, pady=5)
        gradle_var = StringVar(value=self.gradle_version)
        ttk.Entry(build_frame, textvariable=gradle_var, width=10).grid(row=brow, column=1, sticky=W, pady=5)
        brow += 1

        ttk.Label(build_frame, text="构建类型:").grid(row=brow, column=0, sticky=W, pady=5)
        type_frame = ttk.Frame(build_frame)
        type_frame.grid(row=brow, column=1, sticky=W, pady=5)
        build_type_var = StringVar(value=self.build_type)
        ttk.Radiobutton(type_frame, text="Debug", variable=build_type_var, value="debug").pack(side=LEFT, padx=5)
        ttk.Radiobutton(type_frame, text="Release", variable=build_type_var, value="release").pack(side=LEFT, padx=5)
        brow += 1

        build_frame.columnconfigure(1, weight=1)

        # 排除规则页
        exclude_frame = ttk.Frame(nb, padding="10")
        nb.add(exclude_frame, text="打包排除")

        ttk.Label(exclude_frame, text="文件夹打包时排除的文件/模式 (每行一个)").pack(anchor=W, pady=5)
        exclude_text = Text(exclude_frame, height=12, width=50, font=self.fixed_font)
        exclude_text.pack(fill=BOTH, expand=True, pady=5)
        exclude_text.insert(1.0, "\n".join(self.folder_exclude_patterns))

        # 剪贴板提示页
        snippet_frame = ttk.Frame(nb, padding="10")
        nb.add(snippet_frame, text="剪贴板")
        ttk.Label(snippet_frame, text="片段管理请使用主界面「剪贴板」标签页中的「管理片段」按钮。").pack(pady=20)
        ttk.Button(snippet_frame, text="打开片段管理器", command=self.manage_snippets).pack()

        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(pady=10)
        def save_settings():
            self.token = token_var.get().strip()
            self.branch = branch_var.get().strip() or "main"
            self.upload_default_unpack = unpack_var.get()
            self.upload_default_build = build_var.get()

            branch_choice = build_branch_var.get()
            if branch_choice == 'custom':
                self.build_branch = custom_branch_var.get().strip()
                if not self.build_branch:
                    self.build_branch = 'main'
            else:
                self.build_branch = branch_choice

            self.java_version = java_var.get().strip() or "17"
            self.java_home_custom = java_home_var.get().strip()
            self.gradle_version = gradle_var.get().strip() or "8.13"
            self.build_type = build_type_var.get()

            self.new_repo_desc = desc_var.get().strip()
            self.new_repo_private = private_var.get()

            patterns = exclude_text.get(1.0, END).strip().splitlines()
            self.folder_exclude_patterns = [p.strip() for p in patterns if p.strip()]

            new_font_scale = font_scale_var.get()
            need_restart = (abs(new_font_scale - self.font_scale) > 0.01)

            new_compact = compact_var.get()
            compact_changed = (new_compact != self.compact_mode)
            self.compact_mode = new_compact

            self.token_var.set(self.token)
            self.new_desc_var.set(self.new_repo_desc)
            self.private_var.set(self.new_repo_private)

            self.config.update({
                'token': self.token,
                'branch': self.branch,
                'upload_default_unpack': self.upload_default_unpack,
                'upload_default_build': self.upload_default_build,
                'build_branch': self.build_branch,
                'java_version': self.java_version,
                'java_home_custom': self.java_home_custom,
                'gradle_version': self.gradle_version,
                'build_type': self.build_type,
                'new_repo_desc': self.new_repo_desc,
                'new_repo_private': self.new_repo_private,
                'folder_exclude_patterns': self.folder_exclude_patterns,
                'font_scale': new_font_scale,
                'compact_mode': self.compact_mode,
            })
            save_config(self.config)

            if self.token and not self.api:
                self.api = GitHubAPI(self.token)
                self.update_user_info()
                self.load_repo_list_async()
            elif self.token and self.api and self.api.token != self.token:
                self.api = GitHubAPI(self.token)
                self.update_user_info()
                self.load_repo_list_async()

            if compact_changed:
                self.apply_compact_mode()

            self.logger.add("设置已保存")
            dialog.destroy()

            if need_restart:
                if messagebox.askyesno("重启程序", "字体缩放已更改，需要重启程序才能完全生效。是否立即重启？"):
                    self.restart_app()

        ttk.Button(btn_frame, text="保存", command=save_settings).pack(side=LEFT, padx=5)
        ttk.Button(btn_frame, text="取消", command=dialog.destroy).pack(side=LEFT, padx=5)

    def restart_app(self):
        python = sys.executable
        os.execl(python, python, *sys.argv)

    def on_close(self):
        if self.zip_filepath and self.zip_filepath.startswith(tempfile.gettempdir()):
            try:
                os.unlink(self.zip_filepath)
            except:
                pass

        self.config['token'] = self.token
        self.config['branch'] = self.branch
        self.config['repo_url'] = self.repo_url_var.get()
        self.config['create_new'] = self.create_new
        self.config['new_repo_name'] = self.new_name_var.get()
        self.config['new_repo_desc'] = self.new_desc_var.get()
        self.config['new_repo_private'] = self.private_var.get()
        self.config['upload_default_unpack'] = self.upload_default_unpack
        self.config['upload_default_build'] = self.upload_default_build
        self.config['build_branch'] = self.build_branch
        self.config['java_version'] = self.java_version
        self.config['java_home_custom'] = self.java_home_custom
        self.config['gradle_version'] = self.gradle_version
        self.config['build_type'] = self.build_type
        self.config['folder_exclude_patterns'] = self.folder_exclude_patterns
        self.config['snippets'] = self.snippets
        self.config['font_scale'] = self.font_scale
        self.config['compact_mode'] = self.compact_mode
        self.config['download_history'] = self.download_history
        save_config(self.config)
        self.root.destroy()

if __name__ == "__main__":
    root = Tk()
    style = ttk.Style()
    style.theme_use('clam')
    style.configure("Accent.TButton", font=("", 10, "bold"))
    app = GitHubUploaderApp(root)
    root.mainloop()
