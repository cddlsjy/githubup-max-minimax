package com.deepseek.githubuploader

import android.content.ContentValues
import android.content.Context
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.provider.MediaStore
import android.util.Base64
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.lifecycleScope
import com.google.gson.GsonBuilder
import com.google.gson.annotations.SerializedName
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Response
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import retrofit2.http.*
import java.io.File
import java.io.FileOutputStream
import java.text.SimpleDateFormat
import java.util.*

// ==================== GitHub API 接口 ====================
interface GithubApi {
    @GET("repos/{owner}/{repo}/contents/{path}")
    suspend fun getFile(
        @Path("owner") owner: String,
        @Path("repo") repo: String,
        @Path("path") path: String,
        @Query("ref") branch: String,
        @Header("Authorization") token: String
    ): Response<GithubContentResponse>

    @PUT("repos/{owner}/{repo}/contents/{path}")
    suspend fun createOrUpdateFile(
        @Path("owner") owner: String,
        @Path("repo") repo: String,
        @Path("path") path: String,
        @Header("Authorization") token: String,
        @Body body: CreateFileRequest
    ): Response<GithubFileResponse>

    @POST("user/repos")
    suspend fun createRepository(
        @Header("Authorization") token: String,
        @Body body: CreateRepoRequest
    ): Response<RepositoryResponse>

    @GET("user")
    suspend fun getAuthenticatedUser(
        @Header("Authorization") token: String
    ): Response<UserInfo>

    @GET("repos/{owner}/{repo}/contents/{path}")
    suspend fun getRepoContents(
        @Path("owner") owner: String,
        @Path("repo") repo: String,
        @Path("path") path: String,
        @Query("ref") branch: String,
        @Header("Authorization") token: String
    ): Response<List<RepoContentItem>>

    @GET("user/repos")
    suspend fun listUserRepos(
        @Header("Authorization") token: String,
        @Query("per_page") perPage: Int = 100,
        @Query("sort") sort: String = "updated"
    ): Response<List<Repo>>

    @GET("repos/{owner}/{repo}/zipball/{ref}")
    suspend fun downloadRepoArchive(
        @Path("owner") owner: String,
        @Path("repo") repo: String,
        @Path("ref") ref: String,
        @Header("Authorization") token: String
    ): Response<okhttp3.ResponseBody>

    data class CreateRepoRequest(
        val name: String,
        val description: String? = null,
        val `private`: Boolean = true,
        @SerializedName("auto_init") val autoInit: Boolean = false
    )

    data class RepositoryResponse(
        val id: Long,
        val name: String,
        @SerializedName("full_name") val fullName: String,
        @SerializedName("html_url") val htmlUrl: String,
        @SerializedName("default_branch") val defaultBranch: String
    )

    data class CreateFileRequest(
        val message: String,
        val content: String,
        val sha: String? = null,
        val branch: String
    )

    data class GithubContentResponse(
        val sha: String,
        val content: String? = null
    )

    data class GithubFileResponse(
        val content: ContentInfo,
        val commit: CommitInfo? = null
    )

    data class ContentInfo(val sha: String)
    data class CommitInfo(val sha: String, val message: String)

    data class UserInfo(
        val login: String,
        val name: String?,
        val email: String?,
        @SerializedName("avatar_url") val avatar_url: String?
    )

    data class RepoContentItem(
        val name: String,
        val path: String,
        val type: String,
        val size: Long?,
        @SerializedName("download_url") val download_url: String?
    )

    data class Repo(
        val id: Long,
        val name: String,
        val full_name: String,
        val private: Boolean,
        val html_url: String
    )
}

// ==================== 下载历史记录 ====================
data class DownloadHistoryItem(
    val owner: String,
    val repo: String,
    val path: String,
    val downloadTime: String,
    val size: String
)

// ==================== 颜色 ====================
private val Purple80 = Color(0xFFD0BCFF)
private val PurpleGrey80 = Color(0xFFCCC2DC)
private val Pink80 = Color(0xFFEFB8C8)
private val SuccessGreen = Color(0xFF4CAF50)
private val ErrorRed = Color(0xFFE53935)
private val WarningOrange = Color(0xFFFF9800)
private val InfoBlue = Color(0xFF2196F3)

// ==================== MainActivity ====================
class MainActivity : ComponentActivity() {
    private lateinit var api: GithubApi

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val client = OkHttpClient.Builder()
            .addInterceptor(HttpLoggingInterceptor().apply { level = HttpLoggingInterceptor.Level.BODY })
            .build()

        val retrofit = Retrofit.Builder()
            .baseUrl("https://api.github.com/")
            .client(client)
            .addConverterFactory(GsonConverterFactory.create(GsonBuilder().create()))
            .build()

        api = retrofit.create(GithubApi::class.java)

        setContent {
            MaterialTheme(colorScheme = darkColorScheme(primary = Purple80, secondary = PurpleGrey80, tertiary = Pink80)) {
                Surface(modifier = Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
                    UploadScreen(api = api, context = this)
                }
            }
        }
    }
}

// ==================== 主界面 ====================
@OptIn(ExperimentalMaterial3Api::class, ExperimentalFoundationApi::class)
@Composable
fun UploadScreen(api: GithubApi, context: MainActivity) {
    var createNewRepo by remember { mutableStateOf(false) }
    var repoUrl by remember { mutableStateOf("") }
    var branch by remember { mutableStateOf("main") }
    var newRepoName by remember { mutableStateOf("") }
    var newRepoDesc by remember { mutableStateOf("") }
    var newRepoPrivate by remember { mutableStateOf(true) }
    var token by remember { mutableStateOf("") }
    var uploadDefaultUnpack by remember { mutableStateOf(true) }
    var uploadDefaultBuild by remember { mutableStateOf(true) }
    val customYmlFiles = remember { mutableStateListOf<Pair<Uri, String>>() }
    var zipFileUri by remember { mutableStateOf<Uri?>(null) }
    var zipFileName by remember { mutableStateOf("") }
    var logs by remember { mutableStateOf(listOf<String>()) }
    var isUploading by remember { mutableStateOf(false) }
    var isDownloading by remember { mutableStateOf(false) }
    var tokenVisible by remember { mutableStateOf(false) }
    var showSettingsDialog by remember { mutableStateOf(false) }
    var showDownloadHistoryDialog by remember { mutableStateOf(false) }
    var selectedInfoTab by remember { mutableStateOf(0) }
    var javaVersion by remember { mutableStateOf("17") }
    var gradleVersion by remember { mutableStateOf("8.5") }
    var repoHistory by remember { mutableStateOf<List<String>>(emptyList()) }
    var userInfo by remember { mutableStateOf<GithubApi.UserInfo?>(null) }
    var repoContents by remember { mutableStateOf<List<GithubApi.RepoContentItem>?>(null) }
    var isLoadingInfo by remember { mutableStateOf(false) }
    var userRepos by remember { mutableStateOf<List<GithubApi.Repo>>(emptyList()) }
    var isLoadingRepos by remember { mutableStateOf(false) }
    var quickSearchText by remember { mutableStateOf("") }
    var quickSelectExpanded by remember { mutableStateOf(false) }
    var downloadHistory by remember { mutableStateOf<List<DownloadHistoryItem>>(emptyList()) }
    var selectedContentItem by remember { mutableStateOf<GithubApi.RepoContentItem?>(null) }
    var showContextMenu by remember { mutableStateOf(false) }

    val listState = rememberLazyListState()
    val prefs = context.getSharedPreferences("github_uploader", Context.MODE_PRIVATE)

    // 保存文件到 Downloads 目录的辅助函数
    fun saveFileToDownloads(fileName: String, data: ByteArray): Boolean {
        return try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                val values = ContentValues().apply {
                    put(MediaStore.Downloads.DISPLAY_NAME, fileName)
                    put(MediaStore.Downloads.MIME_TYPE, getMimeType(fileName))
                    put(MediaStore.Downloads.IS_PENDING, 1)
                }
                val resolver = context.contentResolver
                val uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
                uri?.let {
                    resolver.openOutputStream(it)?.use { outputStream ->
                        outputStream.write(data)
                    }
                    values.clear()
                    values.put(MediaStore.Downloads.IS_PENDING, 0)
                    resolver.update(uri, values, null, null)
                    true
                } ?: false
            } else {
                val downloadsDir = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS)
                val file = File(downloadsDir, fileName)
                FileOutputStream(file).use { it.write(data) }
                true
            }
        } catch (e: Exception) {
            addLog("⚠ 保存文件异常: ${e.message}")
            false
        }
    }

    // 获取 MIME 类型的辅助函数
    fun getMimeType(fileName: String): String {
        return when (fileName.substringAfterLast('.', "").lowercase()) {
            "zip" -> "application/zip"
            "yml", "yaml" -> "text/yaml"
            "txt" -> "text/plain"
            "json" -> "application/json"
            "md" -> "text/markdown"
            "html" -> "text/html"
            "css" -> "text/css"
            "js" -> "application/javascript"
            "kt" -> "text/plain"
            "java" -> "text/plain"
            "xml" -> "application/xml"
            "png", "jpg", "jpeg", "gif" -> "image/*"
            else -> "application/octet-stream"
        }
    }

    fun addLog(msg: String) {
        val timestamp = SimpleDateFormat("HH:mm:ss", Locale.getDefault()).format(Date())
        logs = logs + "[$timestamp] $msg"
    }

    fun loadRepoHistory() {
        val historySet = prefs.getStringSet("repo_history", emptySet()) ?: emptySet()
        repoHistory = historySet.toList().reversed()
    }

    fun loadDownloadHistory() {
        val json = prefs.getString("download_history", "[]") ?: "[]"
        try {
            val gson = GsonBuilder().create()
            downloadHistory = gson.fromJson(json, Array<DownloadHistoryItem>::class.java).toList()
        } catch (e: Exception) {
            downloadHistory = emptyList()
        }
    }

    fun saveDownloadHistory(history: List<DownloadHistoryItem>) {
        val gson = GsonBuilder().create()
        val json = gson.toJson(history)
        prefs.edit().putString("download_history", json).apply()
        downloadHistory = history
    }

    fun addDownloadHistory(owner: String, repo: String, path: String, size: String) {
        val newItem = DownloadHistoryItem(
            owner = owner,
            repo = repo,
            path = path,
            downloadTime = SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.getDefault()).format(Date()),
            size = size
        )
        val newHistory = listOf(newItem) + downloadHistory.take(19)
        saveDownloadHistory(newHistory)
    }

    fun addToHistory(url: String) {
        if (url.isBlank()) return
        val set = prefs.getStringSet("repo_history", emptySet())?.toMutableSet() ?: mutableSetOf()
        set.add(url)
        if (set.size > 10) set.drop(set.size - 10)
        prefs.edit().putStringSet("repo_history", set).apply()
        loadRepoHistory()
    }

    suspend fun loadUserRepos() {
        val cleanToken = token.trim()
        if (cleanToken.isBlank()) return
        isLoadingRepos = true
        try {
            val resp = api.listUserRepos("token $cleanToken")
            if (resp.isSuccessful) {
                userRepos = resp.body() ?: emptyList()
            } else {
                addLog("⚠ 加载仓库列表失败: ${resp.code()}")
            }
        } catch (e: Exception) {
            addLog("⚠ 加载仓库列表异常: ${e.message}")
        }
        isLoadingRepos = false
    }

    LaunchedEffect(Unit) {
        token = prefs.getString("token", "")?.trim() ?: ""
        repoUrl = prefs.getString("repo_url", "") ?: ""
        branch = prefs.getString("branch", "main") ?: "main"
        uploadDefaultUnpack = prefs.getBoolean("upload_default_unpack", true)
        uploadDefaultBuild = prefs.getBoolean("upload_default_build", true)
        createNewRepo = prefs.getBoolean("create_new_repo", false)
        newRepoName = prefs.getString("new_repo_name", "") ?: ""
        newRepoDesc = prefs.getString("new_repo_desc", "") ?: ""
        newRepoPrivate = prefs.getBoolean("new_repo_private", true)
        javaVersion = prefs.getString("java_version", "17") ?: "17"
        gradleVersion = prefs.getString("gradle_version", "8.5") ?: "8.5"
        loadRepoHistory()
        loadDownloadHistory()
        if (token.isNotBlank()) loadUserRepos()
    }

    suspend fun loadYmlFromAssets(context: Context): Pair<String, String> {
        return withContext(Dispatchers.IO) {
            try {
                val unpack = context.assets.open("unpack.yml.txt").bufferedReader().use { it.readText() }
                val build = context.assets.open("build.yml.txt").bufferedReader().use { it.readText() }
                Pair(unpack, build)
            } catch (e: Exception) {
                throw Exception("Failed to load YML files from assets: ${e.message}")
            }
        }
    }

    fun savePrefs() {
        prefs.edit()
            .putString("token", token.trim())
            .putString("repo_url", repoUrl)
            .putString("branch", branch)
            .putBoolean("upload_default_unpack", uploadDefaultUnpack)
            .putBoolean("upload_default_build", uploadDefaultBuild)
            .putBoolean("create_new_repo", createNewRepo)
            .putString("new_repo_name", newRepoName)
            .putString("new_repo_desc", newRepoDesc)
            .putBoolean("new_repo_private", newRepoPrivate)
            .putString("java_version", javaVersion)
            .putString("gradle_version", gradleVersion)
            .apply()
    }

    fun getFileNameFromUri(uri: Uri): String {
        return context.contentResolver.query(uri, null, null, null, null)?.use { cursor ->
            val idx = cursor.getColumnIndex(android.provider.OpenableColumns.DISPLAY_NAME)
            if (idx >= 0 && cursor.moveToFirst()) cursor.getString(idx) else uri.lastPathSegment ?: "unknown"
        } ?: uri.lastPathSegment ?: "unknown"
    }

    suspend fun readFileAsBase64(uri: Uri): String = withContext(Dispatchers.IO) {
        val bytes = context.contentResolver.openInputStream(uri)!!.use { it.readBytes() }
        Base64.encodeToString(bytes, Base64.NO_WRAP)
    }

    fun parseRepo(url: String): Pair<String, String>? {
        val patterns = listOf(
            Regex("github\\.com[:/]([^/]+)/([^/.]+)"),
            Regex("https://github\\.com/([^/]+)/([^/.]+)")
        )
        for (p in patterns) {
            p.find(url)?.let { return it.groupValues[1] to it.groupValues[2] }
        }
        return null
    }

    suspend fun getFileSha(owner: String, repo: String, path: String, token: String, branch: String): String? {
        val cleanToken = token.trim()
        return try {
            val resp = api.getFile(owner, repo, path, branch, "token $cleanToken")
            if (resp.isSuccessful) resp.body()?.sha else null
        } catch (e: Exception) { null }
    }

    suspend fun uploadFile(owner: String, repo: String, remotePath: String, contentBase64: String, token: String, branch: String, log: (String) -> Unit) {
        val cleanToken = token.trim()
        val sha = getFileSha(owner, repo, remotePath, cleanToken, branch)
        val body = GithubApi.CreateFileRequest("Upload $remotePath", contentBase64, sha, branch)
        val resp = api.createOrUpdateFile(owner, repo, remotePath, "token $cleanToken", body)
        if (resp.isSuccessful) log("✓ $remotePath 上传成功") else log("✗ $remotePath 失败: ${resp.code()} - ${resp.errorBody()?.string()}")
    }

    suspend fun uploadYml(owner: String, repo: String, filename: String, content: String, token: String, branch: String, log: (String) -> Unit) {
        val b64 = Base64.encodeToString(content.toByteArray(), Base64.NO_WRAP)
        uploadFile(owner, repo, ".github/workflows/$filename", b64, token, branch, log)
    }

    fun generateBuildYml(template: String, javaVer: String, gradleVer: String) =
        template.replace("{{JAVA_VERSION}}", javaVer).replace("{{GRADLE_VERSION}}", gradleVer)

    suspend fun loadUserInfo() {
        val cleanToken = token.trim()
        if (cleanToken.isBlank()) return
        isLoadingInfo = true
        try {
            val resp = api.getAuthenticatedUser("token $cleanToken")
            if (resp.isSuccessful) userInfo = resp.body() else userInfo = null
        } catch (e: Exception) { userInfo = null }
        isLoadingInfo = false
    }

    suspend fun loadRepoContents() {
        val cleanToken = token.trim()
        if (cleanToken.isBlank() || (!createNewRepo && repoUrl.isBlank())) {
            repoContents = null
            return
        }
        val parsed = parseRepo(repoUrl) ?: run { repoContents = null; return }
        isLoadingInfo = true
        try {
            val resp = api.getRepoContents(parsed.first, parsed.second, "", branch, "token $cleanToken")
            repoContents = if (resp.isSuccessful) resp.body() else null
        } catch (e: Exception) { repoContents = null }
        isLoadingInfo = false
    }

    // 下载单个文件
    fun downloadSingleFile(item: GithubApi.RepoContentItem) {
        val cleanToken = token.trim()
        if (cleanToken.isBlank()) {
            addLog("⚠ 请先输入 GitHub Token")
            return
        }
        val parsed = parseRepo(repoUrl) ?: run {
            addLog("⚠ 仓库地址格式错误")
            return
        }

        isDownloading = true
        addLog("📄 开始下载文件: ${item.name}")

        context.lifecycleScope.launch {
            try {
                val resp = api.getFile(parsed.first, parsed.second, item.path, branch, "token $cleanToken")
                if (resp.isSuccessful) {
                    val body = resp.body()
                    if (body?.content != null) {
                        val fileContent = Base64.decode(body.content.replace("\n", ""), Base64.NO_WRAP)
                        val saved = saveFileToDownloads(item.name, fileContent)
                        if (saved) {
                            addLog("✅ 文件下载完成: ${item.name}")
                            val sizeKB = fileContent.size / 1024.0
                            addDownloadHistory(parsed.first, parsed.second, item.path, String.format("%.2f KB", sizeKB))
                        } else {
                            addLog("✗ 文件保存失败")
                        }
                    } else {
                        addLog("✗ 无法获取文件内容")
                    }
                } else {
                    addLog("✗ 下载失败: ${resp.code()}")
                }
            } catch (e: Exception) {
                addLog("✗ 下载异常: ${e.message}")
            } finally {
                isDownloading = false
            }
        }
    }

    // 下载整个项目 ZIP
    fun downloadRepoZip() {
        val cleanToken = token.trim()
        if (cleanToken.isBlank()) {
            addLog("⚠ 请先输入 GitHub Token")
            return
        }
        val parsed = parseRepo(repoUrl) ?: run {
            addLog("⚠ 仓库地址格式错误")
            return
        }

        isDownloading = true
        addLog("📥 开始下载仓库: ${parsed.first}/${parsed.second}")

        context.lifecycleScope.launch {
            try {
                val resp = api.downloadRepoArchive(parsed.first, parsed.second, branch, "token $cleanToken")
                if (resp.isSuccessful) {
                    val zipBytes = resp.body()?.bytes()
                    if (zipBytes != null) {
                        val fileName = "${parsed.second}-${branch}.zip"
                        val saved = saveFileToDownloads(fileName, zipBytes)
                        if (saved) {
                            val sizeMB = zipBytes.size / (1024 * 1024.0)
                            addLog("✅ 仓库下载完成: $fileName (${String.format("%.2f", sizeMB)} MB)")
                            addDownloadHistory(parsed.first, parsed.second, "", String.format("%.2f MB", sizeMB))
                        } else {
                            addLog("✗ 文件保存失败")
                        }
                    } else {
                        addLog("✗ 无法获取 ZIP 数据")
                    }
                } else {
                    addLog("✗ 下载失败: ${resp.code()}")
                }
            } catch (e: Exception) {
                addLog("✗ 下载异常: ${e.message}")
            } finally {
                isDownloading = false
            }
        }
    }

    fun startUpload() {
        if (isUploading) return
        val cleanToken = token.trim()
        if (cleanToken.isBlank()) { addLog("⚠ 请输入 GitHub Token"); return }
        if (!createNewRepo && repoUrl.isBlank()) { addLog("⚠ 请输入仓库地址"); return }
        if (createNewRepo && newRepoName.isBlank()) { addLog("⚠ 请输入新仓库名称"); return }

        isUploading = true
        addLog("🚀 开始上传...")
        if (!createNewRepo && repoUrl.isNotBlank()) addToHistory(repoUrl)

        context.lifecycleScope.launch {
            try {
                val (unpackYml, buildTemplate) = loadYmlFromAssets(context)
                var owner: String; var repo: String; var targetBranch: String

                if (createNewRepo) {
                    addLog("📦 创建仓库: $newRepoName")
                    val resp = api.createRepository(
                        "token $cleanToken",
                        GithubApi.CreateRepoRequest(newRepoName, newRepoDesc.takeIf { it.isNotBlank() }, newRepoPrivate, false)
                    )
                    if (!resp.isSuccessful) throw Exception("创建仓库失败: ${resp.code()} - ${resp.errorBody()?.string()}")
                    val data = resp.body()!!
                    owner = data.fullName.substringBefore('/')
                    repo = data.name
                    targetBranch = data.defaultBranch
                    repoUrl = data.htmlUrl
                    savePrefs()
                    addLog("✅ 仓库创建成功: ${data.htmlUrl}")
                } else {
                    val (o, r) = parseRepo(repoUrl) ?: throw Exception("仓库地址格式错误")
                    owner = o; repo = r; targetBranch = branch
                    addLog("📦 仓库: $owner/$repo")
                }
                addLog("🌿 分支: $targetBranch")

                if (uploadDefaultUnpack) {
                    addLog("📤 上传 unpack.yml ...")
                    uploadYml(owner, repo, "unpack.yml", unpackYml, cleanToken, targetBranch) { addLog(it) }
                } else addLog("⏭ 跳过 unpack.yml")

                if (uploadDefaultBuild) {
                    addLog("📤 上传 build.yml (Java:$javaVersion, Gradle:$gradleVersion)...")
                    val finalBuild = generateBuildYml(buildTemplate, javaVersion, gradleVersion)
                    uploadYml(owner, repo, "build.yml", finalBuild, cleanToken, targetBranch) { addLog(it) }
                } else addLog("⏭ 跳过 build.yml")

                for ((uri, name) in customYmlFiles) {
                    addLog("📤 上传自定义 YML: $name ...")
                    try {
                        val b64 = readFileAsBase64(uri)
                        uploadFile(owner, repo, ".github/workflows/$name", b64, cleanToken, targetBranch) { addLog(it) }
                    } catch (e: Exception) { addLog("✗ $name 读取失败: ${e.message}") }
                }

                zipFileUri?.let { uri ->
                    addLog("📤 上传 ZIP: $zipFileName ...")
                    try {
                        val b64 = readFileAsBase64(uri)
                        uploadFile(owner, repo, zipFileName, b64, cleanToken, targetBranch) { addLog(it) }
                    } catch (e: Exception) { addLog("✗ ZIP 读取失败: ${e.message}") }
                } ?: addLog("📂 无 ZIP 文件")

                addLog("✅ 所有操作完成！")
                loadRepoContents()
            } catch (e: Exception) {
                addLog("❌ 错误: ${e.message}")
            } finally {
                isUploading = false
            }
        }
    }

    val filePickerLauncher = rememberLauncherForActivityResult(ActivityResultContracts.GetContent()) { uri ->
        uri?.let {
            val name = getFileNameFromUri(it)
            when {
                name.endsWith(".yml") || name.endsWith(".yaml") -> {
                    customYmlFiles.add(Pair(uri, name)); addLog("➕ 添加 YML: $name")
                }
                name.endsWith(".zip") -> {
                    zipFileUri = uri; zipFileName = name; addLog("📁 选择 ZIP: $name")
                }
                else -> addLog("⚠ 不支持的文件类型: $name")
            }
        }
    }

    LaunchedEffect(logs.size) { if (logs.isNotEmpty()) listState.animateScrollToItem(logs.size - 1) }
    LaunchedEffect(repoUrl, createNewRepo, branch, token) {
        if (token.isNotBlank()) {
            loadUserInfo()
            if (repoUrl.isNotBlank()) loadRepoContents()
        }
    }
    LaunchedEffect(token) {
        if (token.isNotBlank()) loadUserRepos()
    }

    Scaffold(
        topBar = { TopAppBar(title = { Row(verticalAlignment = Alignment.CenterVertically) { Icon(Icons.Default.Cloud, null); Spacer(Modifier.width(8.dp)); Text("GitHub 上传", fontWeight = FontWeight.Bold) } },
            actions = {
                IconButton(onClick = { showDownloadHistoryDialog = true }) { Icon(Icons.Default.History, "下载历史") }
                IconButton(onClick = { showSettingsDialog = true }) { Icon(Icons.Default.Settings, "设置") }
            },
            colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.primaryContainer)) }
    ) { padding ->
        Column(Modifier.fillMaxSize().padding(padding).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) { RadioButton(!createNewRepo, { createNewRepo = false; savePrefs() }); Text("现有仓库") }
                Row(verticalAlignment = Alignment.CenterVertically) { RadioButton(createNewRepo, { createNewRepo = true; savePrefs() }); Text("新仓库") }
            }

            if (createNewRepo) {
                OutlinedTextField(newRepoName, { newRepoName = it; savePrefs() }, label = { Text("仓库名称") }, placeholder = { Text("例如: my-new-repo") }, singleLine = true, modifier = Modifier.fillMaxWidth())
            } else {
                OutlinedTextField(
                    value = repoUrl,
                    onValueChange = {
                        repoUrl = it
                        savePrefs()
                        quickSearchText = ""
                    },
                    label = { Text("仓库地址") },
                    placeholder = { Text("https://github.com/owner/repo 或 owner/repo") },
                    leadingIcon = { Icon(Icons.Default.Link, null) },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth()
                )

                ExposedDropdownMenuBox(
                    expanded = quickSelectExpanded,
                    onExpandedChange = { quickSelectExpanded = it }
                ) {
                    OutlinedTextField(
                        value = quickSearchText,
                        onValueChange = {
                            quickSearchText = it
                            quickSelectExpanded = true
                        },
                        label = { Text("快速选择仓库 (搜索)") },
                        placeholder = { Text("输入仓库名快速选择") },
                        leadingIcon = { Icon(Icons.Default.Search, null) },
                        trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded = quickSelectExpanded) },
                        singleLine = true,
                        modifier = Modifier
                            .fillMaxWidth()
                            .menuAnchor()
                    )
                    ExposedDropdownMenu(
                        expanded = quickSelectExpanded,
                        onDismissRequest = { quickSelectExpanded = false }
                    ) {
                        val filtered = userRepos.filter {
                            it.full_name.contains(quickSearchText, ignoreCase = true) ||
                                    it.name.contains(quickSearchText, ignoreCase = true)
                        }
                        if (filtered.isEmpty()) {
                            DropdownMenuItem(
                                text = { Text("没有匹配的仓库") },
                                onClick = { },
                                enabled = false
                            )
                        } else {
                            filtered.forEach { repo ->
                                DropdownMenuItem(
                                    text = { Text(repo.full_name, maxLines = 1, overflow = TextOverflow.Ellipsis) },
                                    onClick = {
                                        repoUrl = repo.html_url
                                        savePrefs()
                                        quickSearchText = ""
                                        quickSelectExpanded = false
                                        if (selectedInfoTab == 2) context.lifecycleScope.launch { loadRepoContents() }
                                    }
                                )
                            }
                        }
                    }
                }
                Spacer(modifier = Modifier.height(8.dp))
            }

            Divider()

            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                Button(onClick = { filePickerLauncher.launch("*/*") }, modifier = Modifier.weight(1f)) { Icon(Icons.Default.Add, null); Spacer(Modifier.width(4.dp)); Text("选择文件") }
            }

            if (customYmlFiles.isNotEmpty()) {
                Text("YML (${customYmlFiles.size})", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Medium)
                Card(Modifier.fillMaxWidth().heightIn(max = 100.dp), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)) {
                    LazyColumn(Modifier.padding(8.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        items(customYmlFiles.size) { idx ->
                            val (_, name) = customYmlFiles[idx]
                            Row(horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    Icon(Icons.Default.Description, null, Modifier.size(16.dp)); Spacer(Modifier.width(4.dp))
                                    Text(name, Modifier.weight(1f), maxLines = 1, overflow = TextOverflow.Ellipsis)
                                }
                                IconButton(onClick = { customYmlFiles.removeAt(idx); addLog("🗑 移除: $name") }, Modifier.size(24.dp)) {
                                    Icon(Icons.Default.Delete, "删除", Modifier.size(16.dp), tint = ErrorRed)
                                }
                            }
                        }
                    }
                }
            }

            if (zipFileName.isNotBlank()) {
                Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.secondaryContainer)) {
                    Row(Modifier.fillMaxWidth().padding(12.dp), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Icon(Icons.Default.Folder, null); Spacer(Modifier.width(8.dp))
                            Column { Text("ZIP", style = MaterialTheme.typography.labelSmall); Text(zipFileName, maxLines = 1, overflow = TextOverflow.Ellipsis) }
                        }
                        IconButton(onClick = { addLog("🗑 移除 ZIP: $zipFileName"); zipFileUri = null; zipFileName = "" }) {
                            Icon(Icons.Default.Delete, "删除", tint = ErrorRed)
                        }
                    }
                }
            }

            Button(onClick = { startUpload() }, enabled = !isUploading, modifier = Modifier.fillMaxWidth().height(56.dp), colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.primary)) {
                if (isUploading) {
                    CircularProgressIndicator(Modifier.size(24.dp), color = MaterialTheme.colorScheme.onPrimary, strokeWidth = 2.dp)
                    Spacer(Modifier.width(8.dp))
                    Text("上传中...")
                } else {
                    Icon(Icons.Default.Upload, null)
                    Spacer(Modifier.width(8.dp))
                    Text("开始上传")
                }
            }

            TabRow(selectedTabIndex = selectedInfoTab) {
                Tab(selected = selectedInfoTab == 0, onClick = { selectedInfoTab = 0 }) { Text("日志", Modifier.padding(12.dp)) }
                Tab(selected = selectedInfoTab == 1, onClick = { selectedInfoTab = 1 }) { Text("信息", Modifier.padding(12.dp)) }
                Tab(selected = selectedInfoTab == 2, onClick = { selectedInfoTab = 2 }) { Text("代码", Modifier.padding(12.dp)) }
            }
            Card(Modifier.fillMaxWidth().fillMaxHeight(), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)) {
                when (selectedInfoTab) {
                    0 -> Column(Modifier.fillMaxSize()) {
                        Row(horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth().padding(12.dp)) {
                            Text("操作日志", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
                            TextButton(onClick = { logs = emptyList() }) { Text("清除") }
                        }
                        if (logs.isEmpty()) Box(Modifier.fillMaxSize().padding(16.dp), Alignment.Center) { Text("日志将在此处显示...") }
                        else LazyColumn(modifier = Modifier.fillMaxSize().padding(12.dp), state = listState, verticalArrangement = Arrangement.spacedBy(2.dp)) {
                            items(logs.size) { idx ->
                                val log = logs[idx]
                                val color = when {
                                    log.contains("✓") -> SuccessGreen
                                    log.contains("✗") || log.contains("❌") -> ErrorRed
                                    log.contains("⚠") -> WarningOrange
                                    log.contains("📤") -> InfoBlue
                                    else -> MaterialTheme.colorScheme.onSurfaceVariant
                                }
                                Text(log, style = MaterialTheme.typography.bodySmall, color = color, fontFamily = FontFamily.Monospace)
                            }
                        }
                    }
                    1 -> LazyColumn(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        if (isLoadingInfo) item { Row { CircularProgressIndicator(Modifier.size(20.dp)); Spacer(Modifier.width(8.dp)); Text("加载中...") } }
                        else if (userInfo != null) {
                            item { Text("✅ 已登录", color = SuccessGreen) }
                            item { Text("用户名: ${userInfo?.login}") }
                            item { Text("姓名: ${userInfo?.name ?: "未设置"}") }
                            item { Text("邮箱: ${userInfo?.email ?: "未公开"}") }
                        } else if (token.isNotBlank()) item { Text("⚠️ 无法获取用户信息，请检查Token", color = WarningOrange) }
                        else item { Text("未登录，请输入GitHub Token", color = ErrorRed) }
                        item { Spacer(Modifier.height(8.dp)); Text("仓库信息", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold) }
                        if (createNewRepo) item { Text("新仓库: $newRepoName") }
                        else if (repoUrl.isNotBlank()) {
                            val p = parseRepo(repoUrl)
                            if (p != null) { item { Text("仓库: ${p.first}/${p.second}") }; item { Text("分支: $branch") } }
                            else item { Text("仓库地址格式错误", color = ErrorRed) }
                        } else item { Text("未选择仓库") }
                    }
                    2 -> Column(Modifier.fillMaxSize()) {
                        Row(
                            horizontalArrangement = Arrangement.spacedBy(8.dp),
                            modifier = Modifier.padding(12.dp).fillMaxWidth()
                        ) {
                            Button(
                                onClick = { context.lifecycleScope.launch { loadRepoContents() } },
                                enabled = !isLoadingInfo,
                                modifier = Modifier.weight(1f)
                            ) {
                                Icon(Icons.Default.Refresh, null, Modifier.size(16.dp))
                                Spacer(Modifier.width(4.dp))
                                Text("刷新", style = MaterialTheme.typography.labelSmall)
                            }
                            Button(
                                onClick = { downloadRepoZip() },
                                enabled = !isDownloading && repoUrl.isNotBlank(),
                                modifier = Modifier.weight(1f)
                            ) {
                                if (isDownloading) {
                                    CircularProgressIndicator(Modifier.size(16.dp), strokeWidth = 2.dp)
                                } else {
                                    Icon(Icons.Default.Download, null, Modifier.size(16.dp))
                                }
                                Spacer(Modifier.width(4.dp))
                                Text("下载ZIP", style = MaterialTheme.typography.labelSmall)
                            }
                        }

                        Divider()

                        if (isLoadingInfo) {
                            Box(Modifier.fillMaxSize().padding(16.dp), Alignment.Center) {
                                Row { CircularProgressIndicator(Modifier.size(20.dp)); Spacer(Modifier.width(8.dp)); Text("加载仓库内容...") }
                            }
                        } else if (repoContents == null) {
                            Box(Modifier.fillMaxSize().padding(16.dp), Alignment.Center) { Text("无法加载仓库内容，请确保仓库地址正确且有访问权限", color = WarningOrange) }
                        } else if (repoContents!!.isEmpty()) {
                            Box(Modifier.fillMaxSize().padding(16.dp), Alignment.Center) { Text("仓库为空，没有文件") }
                        } else {
                            LazyColumn(Modifier.fillMaxSize().padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                                item { Text("根目录文件列表 (长按下载):", fontWeight = FontWeight.Bold) }
                                items(repoContents!!) { item ->
                                    val fileSize = item.size?.let { size ->
                                        when {
                                            size > 1024 * 1024 -> String.format("%.1f MB", size / (1024.0 * 1024.0))
                                            size > 1024 -> String.format("%.1f KB", size / 1024.0)
                                            else -> "$size B"
                                        }
                                    } ?: ""

                                    Row(
                                        modifier = Modifier
                                            .fillMaxWidth()
                                            .combinedClickable(
                                                onClick = { },
                                                onLongClick = {
                                                    selectedContentItem = item
                                                    showContextMenu = true
                                                }
                                            )
                                            .padding(vertical = 8.dp, horizontal = 4.dp),
                                        verticalAlignment = Alignment.CenterVertically
                                    ) {
                                        Icon(
                                            imageVector = if (item.type == "dir") Icons.Default.Folder else Icons.Default.InsertDriveFile,
                                            contentDescription = null,
                                            Modifier.size(20.dp),
                                            tint = if (item.type == "dir") WarningOrange else InfoBlue
                                        )
                                        Spacer(Modifier.width(8.dp))
                                        Column(modifier = Modifier.weight(1f)) {
                                            Text(
                                                "${item.name}${if (item.type == "dir") "/" else ""}",
                                                style = MaterialTheme.typography.bodyMedium
                                            )
                                            if (fileSize.isNotEmpty()) {
                                                Text(
                                                    fileSize,
                                                    style = MaterialTheme.typography.bodySmall,
                                                    color = MaterialTheme.colorScheme.onSurfaceVariant
                                                )
                                            }
                                        }
                                        Icon(
                                            Icons.Default.MoreVert,
                                            null,
                                            Modifier.size(16.dp),
                                            tint = MaterialTheme.colorScheme.onSurfaceVariant
                                        )
                                    }
                                }
                            }
                        }
                    }
                }
            }

            if (showSettingsDialog) AlertDialog(
                onDismissRequest = { showSettingsDialog = false },
                title = { Text("设置") },
                text = {
                    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                        OutlinedTextField(
                            value = token,
                            onValueChange = { token = it.replace("\n", "").replace("\r", ""); savePrefs() },
                            label = { Text("GitHub Token") },
                            placeholder = { Text("ghp_xxxxxxxxxxxx") },
                            leadingIcon = { Icon(Icons.Default.Lock, null) },
                            trailingIcon = { IconButton(onClick = { tokenVisible = !tokenVisible }) { Text(if (tokenVisible) "隐藏" else "显示") } },
                            visualTransformation = if (tokenVisible) VisualTransformation.None else PasswordVisualTransformation(),
                            singleLine = true,
                            modifier = Modifier.fillMaxWidth()
                        )
                        Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
                            Text("分支名: ", modifier = Modifier.width(80.dp))
                            OutlinedTextField(value = branch, onValueChange = { branch = it; savePrefs() }, placeholder = { Text("main") }, singleLine = true, modifier = Modifier.weight(1f))
                        }
                        Divider()
                        Text("默认 Workflow", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Checkbox(uploadDefaultUnpack, { uploadDefaultUnpack = it; savePrefs() })
                            Text("unpack.yml (解压ZIP)")
                        }
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Checkbox(uploadDefaultBuild, { uploadDefaultBuild = it; savePrefs() })
                            Text("build.yml (构建APK)")
                        }
                        Divider()
                        Text("构建配置", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
                        Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
                            Text("Java 版本: ", modifier = Modifier.width(80.dp))
                            OutlinedTextField(value = javaVersion, onValueChange = { javaVersion = it; savePrefs() }, placeholder = { Text("17") }, singleLine = true, modifier = Modifier.weight(1f))
                        }
                        Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
                            Text("Gradle 版本: ", modifier = Modifier.width(80.dp))
                            OutlinedTextField(value = gradleVersion, onValueChange = { gradleVersion = it; savePrefs() }, placeholder = { Text("8.5") }, singleLine = true, modifier = Modifier.weight(1f))
                        }
                        Divider()
                        Text("新仓库选项", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
                        OutlinedTextField(value = newRepoDesc, onValueChange = { newRepoDesc = it; savePrefs() }, label = { Text("描述 (可选)") }, placeholder = { Text("描述") }, singleLine = true, modifier = Modifier.fillMaxWidth())
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Checkbox(newRepoPrivate, { newRepoPrivate = it; savePrefs() })
                            Text("私有仓库")
                        }
                    }
                },
                confirmButton = { Button(onClick = { showSettingsDialog = false }) { Text("确定") } }
            )

            if (showDownloadHistoryDialog) AlertDialog(
                onDismissRequest = { showDownloadHistoryDialog = false },
                title = { Text("下载历史记录") },
                text = {
                    if (downloadHistory.isEmpty()) {
                        Text("暂无下载记录")
                    } else {
                        LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                            items(downloadHistory) { item ->
                                Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)) {
                                    Column(Modifier.padding(12.dp)) {
                                        Text("${item.owner}/${item.repo}", fontWeight = FontWeight.Bold, style = MaterialTheme.typography.bodyMedium)
                                        Text("路径: ${item.path.ifEmpty { "(整个项目)" }}", style = MaterialTheme.typography.bodySmall)
                                        Text("时间: ${item.downloadTime} | 大小: ${item.size}", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                    }
                                }
                            }
                        }
                    }
                },
                confirmButton = {
                    Row {
                        if (downloadHistory.isNotEmpty()) {
                            TextButton(onClick = { saveDownloadHistory(emptyList()); addLog("已清空下载历史") }) { Text("清空") }
                        }
                        Button(onClick = { showDownloadHistoryDialog = false }) { Text("关闭") }
                    }
                }
            )

            if (showContextMenu && selectedContentItem != null) {
                AlertDialog(
                    onDismissRequest = { showContextMenu = false; selectedContentItem = null },
                    title = { Text(selectedContentItem!!.name) },
                    text = {
                        Column {
                            Text("类型: ${if (selectedContentItem!!.type == "dir") "文件夹" else "文件"}")
                            selectedContentItem!!.size?.let { size ->
                                val sizeStr = when {
                                    size > 1024 * 1024 -> String.format("%.1f MB", size / (1024.0 * 1024.0))
                                    size > 1024 -> String.format("%.1f KB", size / 1024.0)
                                    else -> "$size B"
                                }
                                Text("大小: $sizeStr")
                            }
                        }
                    },
                    confirmButton = {
                        Button(onClick = {
                            downloadSingleFile(selectedContentItem!!)
                            showContextMenu = false
                            selectedContentItem = null
                        }) {
                            Row { Icon(Icons.Default.Download, null, Modifier.size(16.dp)); Spacer(Modifier.width(4.dp)); Text("下载") }
                        }
                    },
                    dismissButton = {
                        TextButton(onClick = { showContextMenu = false; selectedContentItem = null }) { Text("取消") }
                    }
                )
            }
        }
    }
}
