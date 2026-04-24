# GitHub Workflow 上传工具 - 修改说明

## 修改概述

本次修改根据项目大纲对Android应用进行了全面升级，实现了以下功能：

### 1. 自动完成与记忆功能 ✅
- **仓库地址输入框支持历史记录自动完成**（下拉菜单）
- 自动保存最近10个成功使用的仓库地址
- 支持模糊匹配过滤历史记录
- 所有设置信息（Token、分支、版本配置等）全部持久化存储

### 2. UI文本优化 ✅
| 原文本 | 新文本 |
|--------|--------|
| 使用现有仓库 | 现有仓库 |
| 创建新仓库 | 新仓库 |
| 默认 Workflow 文件 | 工作流 |

### 3. 工作流文件管理 ✅
- **从assets目录读取YML模板**：应用启动时自动从`app/src/main/assets/`目录加载`unpack.yml`和`build.yml`
- **支持用户自定义YML文件**：通过文件选择器选择自定义workflow文件（适配Android 15分区存储）
- **设置中可配置Java/Gradle版本**：在设置对话框中添加了版本配置选项
- **动态生成build.yml**：根据用户设置的版本号自动替换模板中的占位符

### 4. 双标签信息窗口 ✅
- **登录信息标签**：显示GitHub用户信息、Token状态、仓库信息
- **项目代码标签**：显示仓库根目录文件树，支持查看文件和文件夹
- 自动加载用户信息和仓库内容

### 5. Token持久化 ✅
- Token输入框支持显示/隐藏切换
- Token自动保存到SharedPreferences
- 应用重启后自动恢复Token

## 技术实现细节

### MainActivity.kt 主要修改

1. **新增API接口**：
   - `getAuthenticatedUser`：获取当前登录用户信息
   - `getRepoContents`：获取仓库内容列表
   - 新增数据类：`UserInfo`、`RepoContentItem`

2. **新增状态变量**：
   ```kotlin
   var selectedInfoTab by remember { mutableStateOf(0) }
   var javaVersion by remember { mutableStateOf("17") }
   var gradleVersion by remember { mutableStateOf("8.5") }
   var repoHistory by remember { mutableStateOf<List<String>>(emptyList()) }
   var showRepoDropdown by remember { mutableStateOf(false) }
   var userInfo by remember { mutableStateOf<GithubApi.UserInfo?>(null) }
   var repoContents by remember { mutableStateOf<List<GithubApi.RepoContentItem>?>(null) }
   ```

3. **新增功能函数**：
   - `loadRepoHistory()`：加载历史记录
   - `addToHistory(url: String)`：保存到历史记录
   - `loadYmlFromAssets(context: Context)`：从assets加载YML模板
   - `generateBuildYml(template: String, javaVer: String, gradleVer: String)`：动态生成build.yml
   - `loadUserInfo()`：加载用户信息
   - `loadRepoContents()`：加载仓库内容

4. **UI组件修改**：
   - 仓库地址输入框添加下拉菜单支持
   - 添加`TabRow`实现双标签切换
   - 设置对话框添加Java/Gradle版本配置
   - 更新图标为正确的Material Icons

### Assets 目录

创建了`app/src/main/assets/`目录，包含：

1. **unpack.yml**：解压ZIP工作流
   - 支持push触发和手动触发
   - 自动解压ZIP文件到根目录
   - 自动提交并推送变更

2. **build.yml**：构建APK工作流
   - 使用模板占位符：`{{JAVA_VERSION}}`、`{{GRADLE_VERSION}}`
   - 动态替换为用户配置的版本号
   - 支持assembleDebug构建

### AndroidManifest.xml 修改

- `tools:targetApi`从31升级到35，适配Android 15

## 文件结构

```
zip2web-test-main/
├── app/
│   └── src/
│       └── main/
│           ├── assets/              # 新增
│           │   ├── unpack.yml       # 工作流模板
│           │   └── build.yml       # 工作流模板
│           ├── java/
│           │   └── com/example/githubuploader/
│           │       └── MainActivity.kt  # 已修改
│           └── AndroidManifest.xml  # 已修改
```

## 使用说明

1. **编译运行应用**
2. **在设置中输入GitHub Token**（需要repo权限）
3. **选择模式**：
   - "现有仓库"：输入已有仓库地址（支持历史自动完成）
   - "新仓库"：创建新仓库
4. **配置工作流**：
   - 选择是否上传默认工作流文件
   - 点击"选择自定义YML/ZIP"添加自定义文件
5. **设置版本**（可选）：
   - 在设置中配置Java和Gradle版本
6. **点击"开始上传"**

应用会自动：
- 将workflow文件上传到`.github/workflows/`目录
- 将ZIP文件上传到仓库根目录
- 根据配置的版本号动态生成build.yml

## 版本信息

- **目标SDK**：Android 15 (API 35)
- **最小SDK**：Android 12 (API 31)
- **构建工具**：Gradle 8.5
- **Java版本**：17（默认，可自定义）

## 注意事项

1. **Android 15兼容性**：文件选择器已适配Android 15的Scoped Storage
2. **Token安全**：Token默认隐藏，仅在用户主动点击"显示"时明文显示
3. **历史记录**：最多保存10条历史记录，先进先出
4. **版本配置**：Java版本建议17+，Gradle版本建议8.5+

## 修改文件清单

| 文件路径 | 修改类型 | 说明 |
|---------|---------|------|
| `app/src/main/java/.../MainActivity.kt` | 完全重写 | 实现所有新功能 |
| `app/src/main/assets/unpack.yml` | 新增 | unpack工作流模板 |
| `app/src/main/assets/build.yml` | 新增 | build工作流模板 |
| `app/src/main/AndroidManifest.xml` | 修改 | 升级targetApi到35 |

---

**修改日期**：2026-04-15
**修改人**：MiniMax Agent
