NovelSims Windows 单文件桌面版构建包（0.3.1）
====================================

重要：本压缩包是“单文件 EXE 构建工程”，不是已经生成的 NovelSims.exe。
当前交付环境为 Linux，无法原生生成并实机验收 Windows PE 可执行文件。
请在 Windows 10/11 x64 构建，或使用下方 GitHub Actions 自动构建。

最终用户：
- 只需要收到 dist\NovelSims.exe
- 不需要安装 Python
- 不需要下载源码或 python 文件夹
- 用户数据保存在“文档\Electronic Arts\The Sims 4\NovelSims”

方法 A：在 Windows 构建机本地构建
1. 使用已配置的 Python 3.13 x64 虚拟环境（仅构建者需要，最终用户不需要）。
2. 解压本包。
3. 双击 build_windows.bat。
4. 成功后取得 dist\NovelSims.exe。
5. 在一台未安装 Python 的 Windows 10/11 电脑上测试启动、关闭、重启、网页检索、游戏 TCP/文件 IPC 和数据保留。

方法 B：GitHub Actions 云端构建
1. 将本目录全部内容上传到一个 GitHub 仓库。
2. 打开仓库 Actions，选择“Build NovelSims Windows single-file EXE”。
3. 点击 Run workflow。
4. 运行成功后打开该次工作流页面底部 Artifacts，下载 NovelSims-Windows-x64。
5. 压缩包内的 NovelSims.exe 即为待验收发行文件。

技术说明：
- PyInstaller --onefile 将 Python 运行时、后端、前端页面、图片、pywebview 等依赖封装进一个 EXE。
- 首次启动时 PyInstaller 会将内部资源解压到临时目录，这是 one-file 的正常工作方式。
- 用户数据和数据库不会写入临时目录，而保存在 Sims 4 文档目录，升级 EXE 不会主动覆盖用户数据。
- 原生窗口使用 Windows WebView2（EdgeChromium）承载界面，并通过 Windows 窗口区域裁剪为椭圆形。程序不会回退打开系统浏览器。目标电脑需要安装 Microsoft Edge WebView2 Runtime；它是 Windows 组件，不包含在 Python 环境中。
- 0.3.1 本次重点修复椭圆窗口安全布局、晋江书库默认入口和页面跳动。当前已完成源码静态检查与浏览器模拟数据交互检查；尚未完成用户 Windows 实机验收。分享给其他玩家前必须完成干净环境测试。


0.3.3 更新：修复桌面端 CSP 阻止 HTTPS 封面图片的问题；晋江榜单首屏后台并发补充前 8 本作品的官方封面/作者信息；作品详情缓存 7 天；减少身份卡检索的低效重复查询，并允许有明确人物名证据的角色资料页进入候选来源。


0.3.5：新增百度、夸克、搜狗搜索源；人物检索扩展为最多 18 条查询并行搜索，读取网页上限最高 30。
