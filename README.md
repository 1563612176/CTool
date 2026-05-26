# CTool - Windows C 盘清理工具

基于 Python + tkinter 的 Windows C 盘清理 GUI 工具，双 Tab 界面，无需安装第三方库。

## 功能

### 一键清理
扫描 14 类可清理内容，支持逐文件勾选删除：

| 类别 | 说明 |
|------|------|
| 系统临时文件 | `C:\Windows\Temp` |
| 用户临时文件 | `%TEMP%` |
| 回收站 | `C:\$Recycle.Bin` |
| 预读取文件 | `C:\Windows\Prefetch\*.pf` |
| 缩略图缓存 | `thumbcache_*.db` |
| Windows 更新缓存 | `SoftwareDistribution\Download` |
| 传递优化文件 | `DeliveryOptimization` |
| Windows 错误报告 | WER 诊断文件 |
| Windows 日志文件 | `C:\Windows\Logs\*.log` |
| DNS 缓存 | `ipconfig /flushdns` |
| Chrome 浏览器缓存 | Chrome Cache |
| Edge 浏览器缓存 | Edge Cache |
| Firefox 浏览器缓存 | Firefox cache2 |
| 最近文件列表 | 资源管理器快捷方式 |

- 每个类别可点"详情"逐文件勾选，双击路径在资源管理器中定位
- 部分类别（回收站等）需管理员权限
- 支持"只选推荐项"一键过滤危险类别

### 空间分析
按文件夹大小降序浏览磁盘，快速定位占用空间的文件：
- 面包屑导航，逐级深入子文件夹
- 每个文件夹显示大小、文件数、占比进度条
- 大小 >1GB 红色标记，>100MB 橙色标记

## 运行

### 方式一：直接运行 exe
下载 `dist\CTool.exe`，双击运行。

### 方式二：Python 源码
```bash
pythonw clean_gui.py
# 或双击 run.bat
```

要求 Python 3.10+，无第三方依赖（仅 tkinter 内置库）。

### 管理员权限
部分功能需管理员权限。以管理员身份运行程序，或点击工具栏"获取管理员权限"按钮提权。

## 打包

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name "CTool" --add-data "cleaner_core.py;." clean_gui.py
```

## 项目结构

```
CTool/
├── clean_gui.py      # GUI 界面
├── cleaner_core.py   # 核心逻辑
├── run.bat           # 一键启动脚本
└── README.md
```
