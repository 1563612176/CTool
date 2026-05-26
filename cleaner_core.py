"""C盘清理工具 - 核心逻辑模块

提供清理扫描、文件夹大小分析、清理执行等功能，不依赖 GUI。
"""

import ctypes
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

# ============================================================
# 数据结构
# ============================================================


@dataclass
class CleanupCategory:
    """一个可清理的类别定义"""
    name: str
    description: str
    path_or_paths: str | list[str]  # 单个路径或多个路径（支持环境变量和 glob）
    requires_admin: bool = False
    # "safe" = 可以放心删除, "caution" = 建议检查后再删
    danger_level: str = "safe"
    # 如果是特殊操作（如 flushdns），设为 True
    is_special_command: bool = False
    # 扫描后排除文件名匹配该前缀的文件（如回收站的 $I 元数据文件）
    exclude_name_prefixes: list[str] | None = None


@dataclass
class ScanResult:
    """单个类别的扫描结果"""
    category: CleanupCategory
    files: list[Path] = field(default_factory=list)
    file_count: int = 0
    total_size_bytes: int = 0
    error: Optional[str] = None
    skipped_paths: list[str] = field(default_factory=list)


@dataclass
class FolderSizeInfo:
    """空间分析 - 单个文件夹的大小信息"""
    path: Path
    name: str
    size_bytes: int = 0
    file_count: int = 0
    is_accessible: bool = True
    error: Optional[str] = None


# ============================================================
# 14 个清理类别
# ============================================================

CATEGORIES: list[CleanupCategory] = [
    CleanupCategory(
        name="系统临时文件",
        description="Windows 系统临时文件夹中的文件",
        path_or_paths=r"C:\Windows\Temp",
        requires_admin=False,
    ),
    CleanupCategory(
        name="用户临时文件",
        description="当前用户帐户的临时文件",
        path_or_paths=os.environ.get("TEMP", ""),
        requires_admin=False,
    ),
    CleanupCategory(
        name="回收站",
        description="所有用户回收站中的文件",
        path_or_paths=r"C:\$Recycle.Bin",
        requires_admin=True,
        danger_level="caution",
        exclude_name_prefixes=["$I", "desktop.ini"],
    ),
    CleanupCategory(
        name="预读取文件",
        description="Windows 用于加速启动的预读取缓存（不影响系统运行）",
        path_or_paths=r"C:\Windows\Prefetch\*.pf",
        requires_admin=True,
    ),
    CleanupCategory(
        name="缩略图缓存",
        description="文件资源管理器生成的缩略图缓存",
        path_or_paths=os.path.join(
            os.environ.get("LOCALAPPDATA", ""),
            r"Microsoft\Windows\Explorer\thumbcache_*.db",
        ),
        requires_admin=False,
    ),
    CleanupCategory(
        name="Windows 更新缓存",
        description="Windows Update 下载的更新安装包",
        path_or_paths=r"C:\Windows\SoftwareDistribution\Download",
        requires_admin=True,
    ),
    CleanupCategory(
        name="传递优化文件",
        description="Windows 传递优化（Delivery Optimization）缓存",
        path_or_paths=r"C:\Windows\SoftwareDistribution\DeliveryOptimization",
        requires_admin=True,
    ),
    CleanupCategory(
        name="Windows 错误报告",
        description="Windows 错误报告（WER）产生的诊断文件",
        path_or_paths=[
            r"C:\ProgramData\Microsoft\Windows\WER\ReportArchive",
            r"C:\ProgramData\Microsoft\Windows\WER\ReportQueue",
        ],
        requires_admin=True,
    ),
    CleanupCategory(
        name="Windows 日志文件",
        description="C:\Windows\Logs 下的日志文件（不包含子文件夹）",
        path_or_paths=r"C:\Windows\Logs\*.log",
        requires_admin=True,
    ),
    CleanupCategory(
        name="DNS 缓存",
        description="刷新 DNS 解析缓存（ipconfig /flushdns）",
        path_or_paths="",  # 特殊命令
        requires_admin=True,
        is_special_command=True,
    ),
    CleanupCategory(
        name="Chrome 浏览器缓存",
        description="Google Chrome 浏览器的缓存文件",
        path_or_paths=os.path.join(
            os.environ.get("LOCALAPPDATA", ""),
            r"Google\Chrome\User Data\*\Cache\Cache_Data",
        ),
        requires_admin=False,
    ),
    CleanupCategory(
        name="Edge 浏览器缓存",
        description="Microsoft Edge 浏览器的缓存文件",
        path_or_paths=os.path.join(
            os.environ.get("LOCALAPPDATA", ""),
            r"Microsoft\Edge\User Data\*\Cache\Cache_Data",
        ),
        requires_admin=False,
    ),
    CleanupCategory(
        name="Firefox 浏览器缓存",
        description="Mozilla Firefox 浏览器的缓存文件",
        path_or_paths=os.path.join(
            os.environ.get("LOCALAPPDATA", ""),
            r"Mozilla\Firefox\Profiles\*\cache2",
        ),
        requires_admin=False,
    ),
    CleanupCategory(
        name="最近文件列表",
        description='资源管理器中"最近使用的文件"快捷方式',
        path_or_paths=os.path.join(
            os.environ.get("APPDATA", ""),
            r"Microsoft\Windows\Recent\*.lnk",
        ),
        requires_admin=False,
    ),
]


# ============================================================
# 工具函数
# ============================================================


def is_admin() -> bool:
    """判断当前是否以管理员权限运行"""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def run_as_admin() -> bool:
    """以管理员权限重新启动当前程序。

    使用 ShellExecuteW + runas 动词触发 UAC 提权。
    调用成功后当前进程应退出（由调用者处理）。
    """
    try:
        script = os.path.abspath(sys.argv[0])
        args = " ".join(f'"{a}"' for a in sys.argv[1:])
        ctypes.windll.shell32.ShellExecuteW(
            None,       # hwnd
            "runas",    # verb
            sys.executable,       # executable
            f'"{script}" {args}',  # parameters
            None,       # directory
            1,          # SW_SHOWNORMAL
        )
        return True
    except Exception:
        return False


def format_size(size_bytes: int) -> str:
    """将字节数转换为人类可读的大小字符串"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.2f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def open_folder(path: str) -> None:
    """在资源管理器中打开文件夹（或文件所在文件夹）"""
    p = Path(os.path.expandvars(path))
    if not p.exists():
        # 尝试 glob 模式，取第一个匹配的父目录
        if "*" in str(p):
            parent = p.parent
            while not parent.exists() and parent.parent != parent:
                parent = parent.parent
            os.startfile(str(parent))
            return
        raise FileNotFoundError(f"路径不存在: {path}")
    if p.is_file():
        os.startfile(str(p.parent))
    else:
        os.startfile(str(p))


# ============================================================
# 文件/目录大小计算
# ============================================================


def _calc_recursive_size(
    directory: Path,
    max_depth: int = 4,
    current_depth: int = 0,
    progress_callback: Optional[Callable[[int], None]] = None,
    file_counter: list = None,
) -> tuple[int, int, list[Path]]:
    """递归计算目录大小，限制最大深度。"""
    if file_counter is None:
        file_counter = [0]

    total_bytes = 0
    file_count = 0
    file_list: list[Path] = []

    if current_depth > max_depth:
        return 0, 0, []

    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                try:
                    if entry.is_file(follow_symlinks=False):
                        size = entry.stat().st_size
                        total_bytes += size
                        file_count += 1
                        file_list.append(Path(entry.path))
                        file_counter[0] += 1
                        if file_counter[0] % 2000 == 0 and progress_callback:
                            progress_callback(file_counter[0])
                    elif entry.is_dir(follow_symlinks=False):
                        sub_bytes, sub_count, sub_list = _calc_recursive_size(
                            Path(entry.path),
                            max_depth=max_depth,
                            current_depth=current_depth + 1,
                            progress_callback=progress_callback,
                            file_counter=file_counter,
                        )
                        total_bytes += sub_bytes
                        file_count += sub_count
                        file_list.extend(sub_list)
                except (PermissionError, OSError):
                    continue
    except (PermissionError, FileNotFoundError, OSError):
        pass

    return total_bytes, file_count, file_list


def calculate_dir_size(
    path: str,
    glob_pattern: Optional[str] = None,
    max_depth: int = 6,
    progress_callback: Optional[Callable[[int], None]] = None,
) -> tuple[int, int, list[Path]]:
    """计算指定路径下所有文件的总大小。

    Args:
        path: 目录路径，支持环境变量和 glob 通配符
        glob_pattern: 若 path 可包含 glob，此参数为具体模式，path 为父目录
        max_depth: 最大递归深度
        progress_callback: 每处理 2000 个文件调用一次

    Returns:
        (total_bytes, file_count, file_list)
    """
    expanded = os.path.expandvars(path)
    p = Path(expanded)

    # 处理 glob 模式
    if "*" in str(p) or "?" in str(p):
        parent = p.parent
        pattern = p.name
        if not parent.exists():
            return 0, 0, []
        total_bytes = 0
        total_count = 0
        all_files: list[Path] = []
        try:
            for matched in parent.glob(pattern):
                if matched.is_file():
                    try:
                        size = matched.stat().st_size
                        total_bytes += size
                        total_count += 1
                        all_files.append(matched)
                    except (PermissionError, OSError):
                        continue
                elif matched.is_dir() and not matched.is_symlink():
                    sub_bytes, sub_count, sub_list = _calc_recursive_size(
                        matched,
                        max_depth=max_depth,
                        progress_callback=progress_callback,
                    )
                    total_bytes += sub_bytes
                    total_count += sub_count
                    all_files.extend(sub_list)
        except (PermissionError, OSError):
            pass
        return total_bytes, total_count, all_files

    # 普通路径
    if not p.exists():
        return 0, 0, []
    if p.is_file():
        try:
            return p.stat().st_size, 1, [p]
        except (PermissionError, OSError):
            return 0, 0, []
    if p.is_dir():
        return _calc_recursive_size(
            p, max_depth=max_depth, progress_callback=progress_callback
        )
    return 0, 0, []


# ============================================================
# 扫描与清理
# ============================================================


def scan_all_categories(
    categories: list[CleanupCategory],
    progress_callback: Optional[Callable[[str, int, int], None]] = None,
) -> list[ScanResult]:
    """扫描所有类别，返回结果列表。

    Args:
        categories: 要扫描的类别列表
        progress_callback: (当前类别名, 当前索引, 总数) -> None
    """
    results: list[ScanResult] = []
    total = len(categories)

    for i, cat in enumerate(categories):
        if progress_callback:
            progress_callback(cat.name, i, total)

        # 特殊命令（DNS 等）
        if cat.is_special_command:
            results.append(ScanResult(category=cat, file_count=0, total_size_bytes=0))
            continue

        # 解析路径列表
        paths = cat.path_or_paths
        if isinstance(paths, str):
            paths = [paths]

        all_files: list[Path] = []
        total_bytes = 0
        total_count = 0
        skipped: list[str] = []
        error: Optional[str] = None

        for raw_path in paths:
            expanded = os.path.expandvars(raw_path)
            p = Path(expanded)

            # 跳过空的路径（如环境变量未设置）
            if not expanded or expanded == raw_path == "":
                continue

            # 确认父目录存在
            parent_candidates = [p]
            if "*" in str(p) or "?" in str(p):
                parent_candidates = [p.parent]

            for parent in parent_candidates:
                if not parent.exists():
                    skipped.append(str(parent))
                    continue

            try:
                bytes_val, count, files = calculate_dir_size(raw_path)
                total_bytes += bytes_val
                total_count += count
                all_files.extend(files)
            except PermissionError:
                skipped.append(expanded)
            except Exception as e:
                if error is None:
                    error = str(e)

        # 过滤排除前缀的文件（如回收站的 $I 元数据）
        if cat.exclude_name_prefixes:
            prefixes = cat.exclude_name_prefixes
            excluded = [f for f in all_files if any(
                f.name.startswith(p) for p in prefixes
            )]
            if excluded:
                excluded_size = 0
                for f in excluded:
                    try:
                        if f.is_file():
                            excluded_size += f.stat().st_size
                    except (OSError, PermissionError):
                        pass
                all_files = [f for f in all_files if f not in excluded]
                total_count = len(all_files)
                total_bytes -= excluded_size

        results.append(ScanResult(
            category=cat,
            files=all_files,
            file_count=total_count,
            total_size_bytes=total_bytes,
            error=error,
            skipped_paths=skipped,
        ))

    return results


def clean_category(
    scan_result: ScanResult,
    progress_callback: Optional[Callable[[str, int, int], None]] = None,
) -> tuple[int, int, list[tuple[str, str]]]:
    """执行清理，删除扫描结果中的文件。

    Args:
        scan_result: 扫描结果
        progress_callback: (当前操作描述, 当前索引, 总数) -> None

    Returns:
        (成功数, 失败数, [(路径, 失败原因), ...])
    """
    cat = scan_result.category

    # 特殊命令：DNS 刷新
    if cat.is_special_command:
        try:
            subprocess.run(
                ["ipconfig", "/flushdns"],
                capture_output=True,
                text=True,
                timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            return 1, 0, []
        except Exception as e:
            return 0, 1, [("DNS 缓存刷新", str(e))]

    files = scan_result.files
    total = len(files)
    success = 0
    failed = 0
    failed_items: list[tuple[str, str]] = []

    for i, f in enumerate(files):
        if progress_callback and i % 50 == 0:
            progress_callback(f"正在删除: {f.name}", i, total)

        try:
            if f.is_file() or f.is_symlink():
                os.unlink(f)
            elif f.is_dir():
                shutil.rmtree(f, ignore_errors=False)
            else:
                continue  # 文件可能已被之前的操作删除
            success += 1
        except PermissionError:
            failed += 1
            failed_items.append((str(f), "权限不足"))
        except OSError as e:
            failed += 1
            failed_items.append((str(f), str(e)))

    # 清理可能留下的空目录（非递归，只清理扫描涉及目录的第一层空子目录）
    _remove_empty_dirs(files)

    return success, failed, failed_items


def _remove_empty_dirs(file_list: list[Path]) -> None:
    """删除文件列表中的文件后，尝试清理其空父目录"""
    parent_dirs = {f.parent for f in file_list if f.parent.exists()}
    for d in parent_dirs:
        try:
            if d.exists() and d.is_dir() and not any(d.iterdir()):
                d.rmdir()
        except (OSError, PermissionError):
            pass


# ============================================================
# 空间分析 - 子文件夹大小扫描
# ============================================================


def scan_subfolders_sizes(
    directory: str | Path,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> list[FolderSizeInfo]:
    """扫描目录下所有一级子文件夹的大小，按大小降序排列。

    只计算子文件夹的大小，不包括目录根部的独立文件。
    每个子文件夹的大小会递归计算其全部内容。

    Args:
        directory: 要扫描的目录路径
        progress_callback: (当前索引, 总数) -> None

    Returns:
        按 size_bytes 降序排列的 FolderSizeInfo 列表
    """
    p = Path(os.path.expandvars(str(directory)))
    if not p.exists() or not p.is_dir():
        return []

    # 收集所有子文件夹
    subdirs: list[Path] = []
    try:
        with os.scandir(p) as entries:
            for entry in entries:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        subdirs.append(Path(entry.path))
                except (PermissionError, OSError):
                    continue
    except (PermissionError, OSError):
        return []

    total = len(subdirs)
    results: list[FolderSizeInfo] = []

    for i, subdir in enumerate(subdirs):
        if progress_callback:
            progress_callback(i, total)

        try:
            bytes_val, file_count, _ = _calc_recursive_size(subdir, max_depth=10)
            results.append(FolderSizeInfo(
                path=subdir,
                name=subdir.name,
                size_bytes=bytes_val,
                file_count=file_count,
                is_accessible=True,
            ))
        except PermissionError:
            results.append(FolderSizeInfo(
                path=subdir,
                name=subdir.name,
                is_accessible=False,
                error="权限不足",
            ))
        except Exception as e:
            results.append(FolderSizeInfo(
                path=subdir,
                name=subdir.name,
                is_accessible=False,
                error=str(e),
            ))

    results.sort(key=lambda x: x.size_bytes, reverse=True)
    return results


def get_total_size_of_results(results: list[FolderSizeInfo]) -> int:
    """计算 FolderSizeInfo 列表的总大小"""
    return sum(r.size_bytes for r in results if r.is_accessible)
