"""C盘清理工具 - GUI 界面

基于 tkinter 的双 Tab 界面：
  Tab 1: 一键清理 - 扫描 14 类可清理内容
  Tab 2: 空间分析 - 按文件夹大小降序浏览
"""

import os
import shutil
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

import cleaner_core as core


# ============================================================
# 常量
# ============================================================

FONT_DEFAULT = ("Microsoft YaHei", 10)
FONT_BOLD = ("Microsoft YaHei", 10, "bold")
FONT_TITLE = ("Microsoft YaHei", 14, "bold")
FONT_SMALL = ("Microsoft YaHei", 9)

COLOR_SAFE = "#27ae60"
COLOR_WARN = "#e67e22"
COLOR_DANGER = "#e74c3c"
COLOR_ADMIN = "#8e44ad"
COLOR_BG = "#f5f6fa"
COLOR_CARD = "#ffffff"

MIN_WIDTH = 1200
MIN_HEIGHT = 700

# 列宽定义（中文每个字约占 2 个字符宽度，留足余量）
COL_CHECK = 3       # 勾选框
COL_NAME = 22       # 类别名（最长 "Firefox 浏览器缓存"）
COL_DESC = 28       # 描述
COL_ADMIN = 14      # 管理员提示
COL_COUNT = 12      # 文件数
COL_SIZE = 13       # 大小
COL_SELECTED = 18   # 已选大小
COL_PATH = 40       # 路径
COL_BTNS = 16       # 按钮区


# ============================================================
# 主窗口
# ============================================================


class CleanerApp(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("SKP专属C盘清理工具")
        self.minsize(MIN_WIDTH, MIN_HEIGHT)
        self.geometry(f"{MIN_WIDTH}x{MIN_HEIGHT}")

        self._setup_style()

        main_frame = ttk.Frame(self, padding=8)
        main_frame.pack(fill=tk.BOTH, expand=True)

        self.notebook = ttk.Notebook(main_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        self.clean_tab = CleanTab(self.notebook, self)
        self.notebook.add(self.clean_tab, text="  一键清理  ")

        self.analyze_tab = AnalyzeTab(self.notebook, self)
        self.notebook.add(self.analyze_tab, text="  空间分析  ")

        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

    def _on_tab_changed(self, event):
        pass  # 由用户手动点击"刷新"来触发扫描

    def _setup_style(self):
        style = ttk.Style(self)
        available = style.theme_names()
        preferred = [t for t in ("vista", "xpnative", "winnative", "alt") if t in available]
        if preferred:
            style.theme_use(preferred[0])
        elif "clam" in available:
            style.theme_use("clam")
        style.configure("Title.TLabel", font=FONT_TITLE)
        style.configure("Bold.TLabel", font=FONT_BOLD)
        style.configure("Small.TLabel", font=FONT_SMALL)
        style.configure("Scan.TButton", font=FONT_BOLD)
        style.configure("Clean.TButton", font=FONT_BOLD)
        style.configure("Detail.TButton", font=FONT_SMALL)
        style.configure("OpenFolder.TButton", font=FONT_SMALL)


# ============================================================
# Tab 1: 一键清理
# ============================================================


class CleanTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.scan_results: list[core.ScanResult] = []
        self.category_widgets: dict[str, dict] = {}
        self._scan_thread: threading.Thread | None = None
        # 每个类别在文件选择弹窗中已选的大小和数量 {cat_name: int}
        self.selected_sizes: dict[str, int] = {}
        self.selected_counts: dict[str, int] = {}
        # 详情弹窗中用户勾选的具体文件路径 {cat_name: [Path, ...]}
        self.selected_file_paths: dict[str, list[Path]] = {}

        self._build_ui()

    # ---------- UI 构建 ----------

    def _build_ui(self):
        # 顶部信息面板
        info_frame = ttk.LabelFrame(self, text="系统信息", padding=6)
        info_frame.pack(fill=tk.X, padx=4, pady=(0, 6))

        total_gb, used_gb, free_gb = self._get_disk_info()
        self.lbl_disk = ttk.Label(
            info_frame,
            text=f"C盘: 总空间 {total_gb:.1f} GB  |  已用 {used_gb:.1f} GB  |  可用 {free_gb:.1f} GB",
            font=FONT_DEFAULT,
        )
        self.lbl_disk.pack(anchor=tk.W)

        is_admin = core.is_admin()
        admin_text = "管理员" if is_admin else "普通用户"
        admin_color = COLOR_SAFE if is_admin else COLOR_WARN
        admin_frame = ttk.Frame(info_frame)
        admin_frame.pack(fill=tk.X, pady=(2, 0))

        ttk.Label(admin_frame, text=f"当前权限: {admin_text}", font=FONT_DEFAULT).pack(side=tk.LEFT)
        if not is_admin:
            ttk.Label(
                admin_frame,
                text="  (部分功能受限)",
                font=FONT_SMALL,
                foreground=COLOR_WARN,
            ).pack(side=tk.LEFT)

        # 全局已选汇总（在工具栏显示）

        # 工具栏
        toolbar = ttk.Frame(self, padding=(4, 0))
        toolbar.pack(fill=tk.X, padx=4, pady=(0, 4))

        self.btn_select_all = ttk.Button(toolbar, text="全选", command=self._select_all)
        self.btn_select_all.pack(side=tk.LEFT, padx=(0, 4))

        self.btn_deselect_all = ttk.Button(toolbar, text="全不选", command=self._deselect_all)
        self.btn_deselect_all.pack(side=tk.LEFT, padx=(0, 12))

        self.btn_recommended = ttk.Button(
            toolbar, text="只选推荐项", command=self._select_recommended
        )
        self.btn_recommended.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_scan = ttk.Button(
            toolbar, text="扫描选中项", style="Scan.TButton", command=self._start_scan
        )
        self.btn_scan.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_clean = ttk.Button(
            toolbar, text="清理选中项", style="Clean.TButton", command=self._start_clean
        )
        self.btn_clean.pack(side=tk.RIGHT)
        self.btn_clean.configure(state=tk.DISABLED)

        if not is_admin:
            self.btn_admin = ttk.Button(
                toolbar,
                text="获取管理员权限",
                command=self._elevate_to_admin,
            )
            self.btn_admin.pack(side=tk.LEFT, padx=(12, 0))

        # 动态已选总大小（在管理员按钮右侧，实时刷新）
        self.global_selected_var = tk.StringVar(value="已选总计: 0 个文件, 0 B")
        self.lbl_global_selected = tk.Label(
            toolbar, textvariable=self.global_selected_var,
            font=("Microsoft YaHei", 11, "bold"), fg="#c0392b",
            bg="#ffffff", relief=tk.SOLID, bd=1, padx=8, pady=2,
        )
        self.lbl_global_selected.pack(side=tk.LEFT, padx=(20, 0))

        # 可滚动类别列表
        self._build_category_list()

        # 状态栏
        self.status_var = tk.StringVar(value='就绪 - 选择要扫描的类别，点击"扫描选中项"开始')
        status_bar = ttk.Label(
            self, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W, padding=(6, 2)
        )
        status_bar.pack(fill=tk.X, side=tk.BOTTOM, padx=4, pady=(4, 0))

    def _build_category_list(self):
        outer = ttk.Frame(self)
        outer.pack(fill=tk.BOTH, expand=True, padx=4)

        # ----- 表头 -----
        header = ttk.Frame(outer, padding=(6, 2))
        header.pack(fill=tk.X)

        hdr_specs = [
            ("", COL_CHECK),
            ("类别", COL_NAME),
            ("描述", COL_DESC),
            ("", COL_ADMIN),
            ("文件数量", COL_COUNT),
            ("总大小", COL_SIZE),
            ("已选大小", COL_SELECTED),
            ("路径", COL_PATH),
            ("操作", COL_BTNS),
        ]
        for text, width in hdr_specs:
            lbl = ttk.Label(header, text=text, font=FONT_BOLD, width=width, anchor=tk.W)
            lbl.pack(side=tk.LEFT, padx=(1, 1))

        ttk.Separator(outer, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=2)

        # ----- 滚动区域 -----
        self.canvas = tk.Canvas(outer, bg=COLOR_BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(outer, orient=tk.VERTICAL, command=self.canvas.yview)
        self.scroll_frame = ttk.Frame(self.canvas)

        self.scroll_frame.bind("<Configure>", lambda e: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")
        ))

        self.canvas_window = self.canvas.create_window(
            (0, 0), window=self.scroll_frame, anchor=tk.NW
        )
        self.canvas.configure(yscrollcommand=scrollbar.set)

        self.canvas.bind("<Configure>", self._on_canvas_configure)

        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.canvas.bind("<Enter>", self._bind_mousewheel)
        self.canvas.bind("<Leave>", self._unbind_mousewheel)

        self._populate_category_rows()

    def _on_canvas_configure(self, event):
        self.canvas.itemconfig(self.canvas_window, width=event.width)

    def _bind_mousewheel(self, event):
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _unbind_mousewheel(self, event):
        self.canvas.unbind_all("<MouseWheel>")

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _populate_category_rows(self):
        is_admin = core.is_admin()
        for cat in core.CATEGORIES:
            self._create_category_row(cat, is_admin)

    def _create_category_row(self, cat: core.CleanupCategory, is_admin: bool):
        """创建单个类别行，所有列对齐（使用 ttk.Label width 字符宽度）"""
        row = ttk.Frame(self.scroll_frame, padding=(6, 2))
        row.pack(fill=tk.X, pady=1)

        var = tk.BooleanVar(value=True)

        # ---- 列0: 勾选框 ----
        if cat.requires_admin and not is_admin:
            var.set(False)
            cb = tk.Checkbutton(
                row, variable=var, state=tk.DISABLED,
                bg=COLOR_BG, activebackground=COLOR_BG,
            )
            # 鼠标悬停时在状态栏提示
            cb.bind("<Enter>", lambda e, c=cat: self.status_var.set(
                f"[需管理员权限] {c.name} — 请点击「获取管理员权限」按钮后重新打开程序"
            ))
            cb.bind("<Leave>", lambda e: self.status_var.set(
                '就绪 - 选择要扫描的类别，点击"扫描选中项"开始'
            ))
        else:
            cb = tk.Checkbutton(
                row, variable=var,
                bg=COLOR_BG, activebackground=COLOR_BG,
            )
        cb.pack(side=tk.LEFT, padx=(0, 2))

        # ---- 列1: 类别名 ----
        name_color = "gray" if (cat.requires_admin and not is_admin) else "black"
        name_lbl = ttk.Label(row, text=cat.name, font=FONT_BOLD, width=COL_NAME, anchor=tk.W,
                             foreground=name_color)
        name_lbl.pack(side=tk.LEFT, padx=(1, 1))

        # ---- 列2: 描述 ----
        desc_text = cat.description if len(cat.description) <= 30 else cat.description[:29] + ".."
        desc_lbl = ttk.Label(row, text=desc_text, font=FONT_SMALL,
                             foreground="gray", width=COL_DESC, anchor=tk.W)
        desc_lbl.pack(side=tk.LEFT, padx=(1, 1))

        # ---- 列3: 管理员标记 ----
        if cat.requires_admin and not is_admin:
            admin_lbl = ttk.Label(row, text="需管理员权限", font=FONT_SMALL,
                                  foreground=COLOR_WARN, width=COL_ADMIN, anchor=tk.W)
        else:
            admin_lbl = ttk.Label(row, text="", font=FONT_SMALL, width=COL_ADMIN)
        admin_lbl.pack(side=tk.LEFT, padx=(1, 1))

        # ---- 列4: 文件数量 ----
        count_lbl = ttk.Label(row, text="", font=FONT_DEFAULT, width=COL_COUNT, anchor=tk.W)
        count_lbl.pack(side=tk.LEFT, padx=(1, 1))

        # ---- 列5: 总大小 ----
        size_lbl = ttk.Label(row, text="", font=FONT_DEFAULT, width=COL_SIZE, anchor=tk.W)
        size_lbl.pack(side=tk.LEFT, padx=(1, 1))

        # ---- 列6: 已选大小 ----
        sel_lbl = ttk.Label(row, text="0 B", font=FONT_SMALL,
                            foreground="gray", width=COL_SELECTED, anchor=tk.W)
        sel_lbl.pack(side=tk.LEFT, padx=(1, 1))

        # ---- 列7: 路径 ----
        raw_paths = cat.path_or_paths
        if isinstance(raw_paths, str):
            path_text = raw_paths
        else:
            path_text = raw_paths[0] if raw_paths else ""
        if len(path_text) > 66:
            path_text = "..." + path_text[-63:]
        path_lbl = ttk.Label(row, text=path_text, font=FONT_SMALL,
                             foreground="gray", width=COL_PATH, anchor=tk.W)
        path_lbl.pack(side=tk.LEFT, padx=(1, 1))

        # ---- 列8: 操作按钮（详情 + 打开文件夹） ----
        btn_detail = ttk.Button(
            row, text="详情", style="Detail.TButton",
            command=lambda c=cat: self._open_detail_window(c),
        )
        btn_detail.pack(side=tk.LEFT, padx=(2, 2))

        btn_open = ttk.Button(
            row, text="打开", style="OpenFolder.TButton",
            command=lambda c=cat: self._open_category_folder(c),
        )
        btn_open.pack(side=tk.LEFT, padx=(0, 2))

        # 回收站专属：一键清空按钮
        btn_quick_clean = None
        if cat.name == "回收站":
            btn_quick_clean = ttk.Button(
                row, text="清空", style="Clean.TButton",
                command=self._quick_clean_recycle_bin,
            )
            btn_quick_clean.pack(side=tk.LEFT, padx=(2, 0))
            btn_quick_clean.configure(state=tk.DISABLED)

        self.category_widgets[cat.name] = {
            "var": var,
            "row": row,
            "count_lbl": count_lbl,
            "size_lbl": size_lbl,
            "sel_lbl": sel_lbl,
            "path_lbl": path_lbl,
            "btn_detail": btn_detail,
            "btn_open": btn_open,
            "btn_quick_clean": btn_quick_clean,
            "cat": cat,
        }

        # 主页勾选框变化时重新计算已选总计
        var.trace_add("write", lambda *_, c=cat.name: self._recalc_main_total())

        # 双击打开详情（跳过 Checkbutton，避免切换勾选状态）
        for widget in row.winfo_children():
            if isinstance(widget, tk.Checkbutton):
                continue
            widget.bind("<Double-Button-1>", lambda e, c=cat: self._open_detail_window(c))
        row.bind("<Double-Button-1>", lambda e, c=cat: self._open_detail_window(c))

    # ---------- 管理员提权 ----------

    def _elevate_to_admin(self):
        ok = messagebox.askyesno(
            "获取管理员权限",
            "程序将以管理员身份重新启动。\n\n"
            "当前窗口将关闭，请在新窗口中继续操作。\n\n是否继续？",
        )
        if ok:
            core.run_as_admin()
            self.app.destroy()

    # ---------- 磁盘信息 ----------

    @staticmethod
    def _get_disk_info():
        try:
            usage = shutil.disk_usage("C:\\")
            total_gb = usage.total / (1024 ** 3)
            used_gb = usage.used / (1024 ** 3)
            free_gb = usage.free / (1024 ** 3)
            return total_gb, used_gb, free_gb
        except Exception:
            return 0, 0, 0

    # ---------- 全选 / 全不选 ----------

    def _select_all(self):
        is_admin = core.is_admin()
        for cat in core.CATEGORIES:
            w = self.category_widgets.get(cat.name)
            if w and not (cat.requires_admin and not is_admin):
                w["var"].set(True)

    def _deselect_all(self):
        for w in self.category_widgets.values():
            w["var"].set(False)

    def _select_recommended(self):
        """只勾选推荐项（安全级别为 safe 的类别），取消危险项"""
        is_admin = core.is_admin()
        for w in self.category_widgets.values():
            cat = w["cat"]
            if cat.requires_admin and not is_admin:
                w["var"].set(False)
            elif cat.danger_level == "caution":
                w["var"].set(False)
            else:
                w["var"].set(True)

    def _recalc_main_total(self):
        """汇总主页勾选类别：详情弹窗有选择用弹窗数据，否则用扫描全量"""
        total_count = 0
        total_bytes = 0
        for cat in core.CATEGORIES:
            w = self.category_widgets.get(cat.name)
            if not w or not w["var"].get():
                continue
            if cat.name in self.selected_file_paths:
                total_count += self.selected_counts.get(cat.name, 0)
                total_bytes += self.selected_sizes.get(cat.name, 0)
            else:
                for r in self.scan_results:
                    if r.category.name == cat.name:
                        total_count += r.file_count
                        total_bytes += r.total_size_bytes
                        break

        self.global_selected_var.set(
            f"已选总计: {total_count} 个文件, {core.format_size(total_bytes)}"
        )

    # ---------- 打开文件夹 ----------

    def _open_category_folder(self, cat: core.CleanupCategory):
        if cat.is_special_command:
            messagebox.showinfo("提示", 'DNS 缓存刷新无需打开文件夹，直接点击"清理"即可执行。')
            return
        paths = cat.path_or_paths
        if isinstance(paths, list):
            paths = paths[0] if paths else ""
        try:
            core.open_folder(paths)
        except Exception as e:
            messagebox.showerror("错误", f"无法打开文件夹:\n{e}")

    # ---------- 详情弹窗 ----------

    def _open_detail_window(self, cat: core.CleanupCategory):
        result = None
        for r in self.scan_results:
            if r.category.name == cat.name:
                result = r
                break
        if result is None or result.file_count == 0:
            messagebox.showinfo("提示", "请先扫描该类别。")
            return

        # 保留上次的选中状态（首次打开为 None，弹窗默认全选）
        preselected = self.selected_file_paths.get(cat.name, None)

        FileSelectDialog(
            self, result, preselected_paths=preselected,
            on_selection_changed=self._on_detail_selection_changed,
            on_files_deleted=self._on_detail_files_deleted,
        )

    def _on_detail_files_deleted(self, cat_name: str, deleted_count: int,
                                  deleted_bytes: int):
        """详情弹窗中删除文件后，同步更新主页面的文件数和大小"""
        for r in self.scan_results:
            if r.category.name == cat_name:
                r.file_count -= deleted_count
                r.total_size_bytes -= deleted_bytes
                break
        w = self.category_widgets.get(cat_name)
        if w:
            for r in self.scan_results:
                if r.category.name == cat_name:
                    if r.file_count > 0:
                        w["count_lbl"].configure(
                            text=f"{r.file_count} 个", foreground=COLOR_SAFE)
                        w["size_lbl"].configure(
                            text=core.format_size(r.total_size_bytes), foreground=COLOR_SAFE)
                    else:
                        w["count_lbl"].configure(text="无文件", foreground="gray")
                        w["size_lbl"].configure(text="0 B", foreground="gray")
                    break

    def _on_detail_selection_changed(self, cat_name: str, selected_count: int,
                                      selected_bytes: int,
                                      selected_paths: list[Path] | None = None):
        """文件选择弹窗中勾选变化时回调"""
        self.selected_sizes[cat_name] = selected_bytes
        self.selected_counts[cat_name] = selected_count
        if selected_paths is not None:
            if selected_count > 0:
                self.selected_file_paths[cat_name] = selected_paths
            else:
                self.selected_file_paths.pop(cat_name, None)
        w = self.category_widgets.get(cat_name)
        if w:
            if selected_count > 0:
                w["sel_lbl"].configure(
                    text=f"{selected_count}个 {core.format_size(selected_bytes)}",
                    foreground=COLOR_SAFE,
                )
                # 子项有选中 → 主页打钩
                w["var"].set(True)
            else:
                w["sel_lbl"].configure(text="0 B", foreground="gray")
                # 子项全部取消 → 主页取消打钩
                w["var"].set(False)

        self._recalc_main_total()

    # ---------- 一键清空回收站 ----------

    def _quick_clean_recycle_bin(self):
        """一键清空回收站：确认后直接清理"""
        result = None
        for r in self.scan_results:
            if r.category.name == "回收站":
                result = r
                break
        if result is None or result.file_count == 0:
            messagebox.showinfo("提示", "请先扫描回收站。")
            return

        ok = messagebox.askokcancel(
            "⚠ 清空回收站 - 操作不可逆",
            f"确定要清空回收站吗？\n\n"
            f"共 {result.file_count} 个文件\n"
            f"将释放 {core.format_size(result.total_size_bytes)}\n\n"
            f"======================================\n"
            f"  此操作不可撤销！\n"
            f"======================================",
            icon="warning",
        )
        if not ok:
            return

        self.status_var.set("正在清空回收站...")
        s, f, items = core.clean_category(result)
        if f > 0:
            detail = "\n".join(f"{p}: {r}" for p, r in items[:5])
            messagebox.showwarning("完成", f"成功: {s}, 失败: {f}\n{detail}")
        else:
            messagebox.showinfo("完成", f"已清空回收站，释放 {core.format_size(result.total_size_bytes)}")
        self.status_var.set(f"回收站清空完成 - 成功 {s}, 失败 {f}")
        self.after(500, self._start_scan)

    # ---------- 扫描 ----------

    def _start_scan(self):
        selected = []
        for cat in core.CATEGORIES:
            w = self.category_widgets.get(cat.name)
            if w and w["var"].get():
                selected.append(cat)

        if not selected:
            messagebox.showinfo("提示", "请至少选择一个类别进行扫描。")
            return

        # 清除旧数据
        self.scan_results = []
        self.selected_sizes.clear()
        self.selected_counts.clear()
        self.selected_file_paths.clear()
        self.global_selected_var.set("已选总计: 0 个文件, 0 B")
        for w in self.category_widgets.values():
            w["sel_lbl"].configure(text="0 B", foreground="gray")

        self.btn_scan.configure(state=tk.DISABLED)
        self.btn_clean.configure(state=tk.DISABLED)
        self.status_var.set("正在扫描...")

        self._scan_thread = threading.Thread(
            target=self._run_scan, args=(selected,), daemon=True
        )
        self._scan_thread.start()
        self._poll_scan_thread()

    def _run_scan(self, categories):
        self._scan_results_data = core.scan_all_categories(
            categories,
            progress_callback=lambda name, i, total: self.after(
                0, self._on_scan_progress, name, i, total
            ),
        )

    def _on_scan_progress(self, name: str, i: int, total: int):
        self.status_var.set(f"正在扫描: {name} ... ({i + 1}/{total})")

    def _poll_scan_thread(self):
        if self._scan_thread and self._scan_thread.is_alive():
            self.after(100, self._poll_scan_thread)
        else:
            self._on_scan_done()

    def _on_scan_done(self):
        self.scan_results = getattr(self, "_scan_results_data", [])
        self._update_category_rows()
        self._recalc_main_total()
        self._update_buttons_after_scan()

        total_size = sum(r.total_size_bytes for r in self.scan_results)
        total_files = sum(r.file_count for r in self.scan_results)
        self.status_var.set(
            f"扫描完成 - 共 {total_files} 个文件  |  点击'详情'逐文件选择删除"
        )

    def _update_category_rows(self):
        for result in self.scan_results:
            w = self.category_widgets.get(result.category.name)
            if not w:
                continue

            if result.error and result.file_count == 0:
                w["count_lbl"].configure(text="错误", foreground=COLOR_DANGER)
                w["size_lbl"].configure(text=result.error, foreground=COLOR_DANGER)
            elif result.file_count == 0:
                w["count_lbl"].configure(text="无文件", foreground="gray")
                w["size_lbl"].configure(text="0 B", foreground="gray")
            else:
                w["count_lbl"].configure(
                    text=f"{result.file_count} 个", foreground=COLOR_SAFE
                )
                w["size_lbl"].configure(
                    text=core.format_size(result.total_size_bytes), foreground=COLOR_SAFE
                )

            # 回收站一键清空按钮状态
            if result.category.name == "回收站" and w.get("btn_quick_clean"):
                if result.file_count > 0:
                    w["btn_quick_clean"].configure(state=tk.NORMAL)
                else:
                    w["btn_quick_clean"].configure(state=tk.DISABLED)

    def _update_buttons_after_scan(self):
        self.btn_scan.configure(state=tk.NORMAL)
        has_files = any(r.file_count > 0 for r in self.scan_results)
        if has_files:
            self.btn_clean.configure(state=tk.NORMAL)
        else:
            self.btn_clean.configure(state=tk.DISABLED)

    # ---------- 清理 ----------

    def _start_clean(self):
        # 收集要清理的内容：详情弹窗有选择用弹窗数据，否则用扫描全量
        clean_list: list[core.ScanResult] = []
        for result in self.scan_results:
            w = self.category_widgets.get(result.category.name)
            if not w or not w["var"].get() or result.file_count == 0:
                continue
            cat_name = result.category.name
            if cat_name in self.selected_file_paths:
                # 用户在该类别详情弹窗中做过选择，按实际勾选来
                sel_files = self.selected_file_paths[cat_name]
                if not sel_files:
                    continue  # 全部取消勾选 → 不清理该类别
                sel_size = self.selected_sizes.get(cat_name, 0)
                clean_list.append(core.ScanResult(
                    category=result.category,
                    files=sel_files,
                    file_count=len(sel_files),
                    total_size_bytes=sel_size,
                ))
            else:
                # 未打开详情弹窗，清理该类别全部文件
                clean_list.append(result)

        if not clean_list:
            messagebox.showinfo("提示", "没有可清理的文件。")
            return

        total_size = sum(r.total_size_bytes for r in clean_list)
        total_count = sum(r.file_count for r in clean_list)
        names = "\n".join(
            f"  - {r.category.name}: {core.format_size(r.total_size_bytes)} ({r.file_count} 个文件)"
            for r in clean_list
        )
        ok = messagebox.askokcancel(
            "⚠ 确认清理 - 操作不可逆",
            f"以下文件将被永久删除，无法恢复！\n\n{names}\n\n"
            f"共将释放: {core.format_size(total_size)}\n"
            f"共 {total_count} 个文件\n\n"
            f"======================================\n"
            f"  确定要永久删除这些文件吗？\n"
            f"  此操作不可撤销！\n"
            f"======================================",
            icon="warning",
        )
        if not ok:
            return

        self.btn_scan.configure(state=tk.DISABLED)
        self.btn_clean.configure(state=tk.DISABLED)
        self.status_var.set("正在清理...")

        self._clean_selected = clean_list
        self._clean_thread = threading.Thread(
            target=self._run_clean, args=(clean_list,), daemon=True
        )
        self._clean_thread.start()
        self._poll_clean_thread()

    def _run_clean(self, selected):
        total_success = 0
        total_failed = 0
        all_failed_items: list[tuple[str, str]] = []

        for i, result in enumerate(selected):
            # 传递 progress_callback 以便在清理单个类别中也可以更新UI
            s, f, items = core.clean_category(
                result, 
                progress_callback=lambda desc, curr, tot, name=result.category.name, idx=i, cat_tot=len(selected): self.after(
                    0, self._on_clean_progress, name, curr, tot
                )
            )
            total_success += s
            total_failed += f
            all_failed_items.extend(items)

        self._clean_total_success = total_success
        self._clean_total_failed = total_failed
        self._clean_failed_items = all_failed_items
        self._clean_total_size = sum(r.total_size_bytes for r in selected)

    def _on_clean_progress(self, name: str, i: int, total: int):
        self.status_var.set(f"正在清理: {name} ... ({i + 1}/{total})")

    def _poll_clean_thread(self):
        if self._clean_thread and self._clean_thread.is_alive():
            self.after(100, self._poll_clean_thread)
        else:
            self._on_clean_done()

    def _on_clean_done(self):
        success = getattr(self, "_clean_total_success", 0)
        failed = getattr(self, "_clean_total_failed", 0)
        failed_items = getattr(self, "_clean_failed_items", [])
        total_size = getattr(self, "_clean_total_size", 0)

        if failed > 0:
            fail_detail = "\n".join(f"  - {p}: {r}" for p, r in failed_items[:10])
            if len(failed_items) > 10:
                fail_detail += f"\n  ... 还有 {len(failed_items) - 10} 项"
            messagebox.showwarning(
                "清理完成",
                f"成功删除 {success} 个文件，释放 {core.format_size(total_size)}\n"
                f"{failed} 个文件删除失败:\n{fail_detail}",
            )
        else:
            messagebox.showinfo(
                "清理完成",
                f"成功删除 {success} 个文件，释放 {core.format_size(total_size)} 空间！",
            )

        self.status_var.set(f"清理完成 - 成功 {success}, 失败 {failed}")
        self.btn_scan.configure(state=tk.NORMAL)
        self.after(500, self._start_scan)


# ============================================================
# 文件选择删除弹窗
# ============================================================


class FileSelectDialog(tk.Toplevel):
    """详情弹窗 - 允许用户逐文件勾选删除"""

    def __init__(self, parent, scan_result: core.ScanResult,
                 preselected_paths: list[Path] | None = None,
                 on_selection_changed=None, on_files_deleted=None):
        super().__init__(parent)
        self.scan_result = scan_result
        self.on_selection_changed = on_selection_changed  # (cat_name, count, bytes, paths) -> None
        self.on_files_deleted = on_files_deleted  # (cat_name, deleted_count, deleted_bytes) -> None
        self.selected_indices: set[int] = set()
        self._file_sizes: dict[int, int] = {}
        self._preselected_paths = preselected_paths  # None=首次打开全选, set=恢复上次选择
        cat = scan_result.category
        self.title(f"{cat.name} - 文件详情")
        self.geometry("900x620")
        self.minsize(700, 400)
        self.transient(parent)

        self._build_ui()
        self._populate_files()

    def _build_ui(self):
        cat = self.scan_result.category

        # 顶部信息
        info_frame = ttk.Frame(self, padding=(8, 6))
        info_frame.pack(fill=tk.X)

        ttk.Label(info_frame, text=f"{cat.name}", font=FONT_TITLE).pack(anchor=tk.W)
        ttk.Label(
            info_frame,
            text=f"{cat.description}  |  共 {self.scan_result.file_count} 个文件，"
                 f"总计 {core.format_size(self.scan_result.total_size_bytes)}",
            font=FONT_SMALL,
            foreground="gray",
        ).pack(anchor=tk.W)

        ttk.Separator(self, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=8)

        # 工具栏
        toolbar = ttk.Frame(self, padding=(8, 4))
        toolbar.pack(fill=tk.X)

        ttk.Button(toolbar, text="全选", command=self._select_all).pack(
            side=tk.LEFT, padx=(0, 4))
        ttk.Button(toolbar, text="全不选", command=self._deselect_all).pack(
            side=tk.LEFT, padx=(0, 12))

        self.lbl_selected = ttk.Label(
            toolbar, text="已选: 0 个文件, 0 B", font=FONT_DEFAULT)
        self.lbl_selected.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_delete = ttk.Button(
            toolbar,
            text="删除选中文件",
            style="Clean.TButton",
            command=self._delete_selected,
        )
        self.btn_delete.pack(side=tk.RIGHT)
        self.btn_delete.configure(state=tk.DISABLED)

        # 文件列表 (Treeview)
        tree_frame = ttk.Frame(self, padding=(8, 4))
        tree_frame.pack(fill=tk.BOTH, expand=True)

        columns = ("checked", "path", "size")
        self.tree = ttk.Treeview(
            tree_frame, columns=columns, show="headings", selectmode="extended",
        )
        self.tree.heading("checked", text="☐", anchor=tk.CENTER)
        self.tree.heading("path", text="文件路径")
        self.tree.heading("size", text="大小")
        self.tree.column("checked", width=36, anchor=tk.CENTER, stretch=False)
        self.tree.column("path", width=600)
        self.tree.column("size", width=130, anchor=tk.E, stretch=False)

        scrollbar_y = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        scrollbar_x = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=scrollbar_y.set, xscrollcommand=scrollbar_x.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar_y.pack(side=tk.RIGHT, fill=tk.Y)
        scrollbar_x.pack(side=tk.BOTTOM, fill=tk.X)

        # 仅点击 ☐ 列切换勾选
        self.tree.bind("<ButtonRelease-1>", self._on_tree_click)
        # 双击路径 → 在资源管理器中定位文件
        self.tree.bind("<Double-Button-1>", self._on_tree_double_click)
        self.tree.bind("<space>", self._on_tree_space)

        # 状态栏
        self.status_var = tk.StringVar(value="点击 ☐ 列勾选/取消  |  双击路径在资源管理器中定位  |  空格键批量切换")
        ttk.Label(
            self, textvariable=self.status_var, relief=tk.SUNKEN,
            anchor=tk.W, padding=(6, 2),
        ).pack(fill=tk.X, padx=8, pady=(4, 4))

    def _populate_files(self):
        self._files = self.scan_result.files

        # 大文件用更大批次加快加载
        batch_size = 2000 if len(self._files) > 5000 else 1000
        self._total_batches = (len(self._files) + batch_size - 1) // batch_size
        self._current_batch = 0
        self._insert_batch(batch_size)

    def _insert_batch(self, batch_size):
        start = self._current_batch * batch_size
        end = min(start + batch_size, len(self._files))

        for i in range(start, end):
            f = self._files[i]
            # 不在加载时 stat 文件（太慢），需要时再获取
            self._file_sizes[i] = 0

            display_path = str(f)
            if len(display_path) > 120:
                display_path = "..." + display_path[-117:]

            self.tree.insert("", tk.END, iid=str(i), values=(
                "☐", display_path, "-",
            ))

        self._current_batch += 1
        if self._current_batch < self._total_batches:
            self.after(1, lambda: self.winfo_exists() and self._insert_batch(batch_size))
        else:
            # 恢复上次选中状态，首次打开则全选
            if self._preselected_paths is not None:
                self._restore_selections()
            else:
                self._select_all()
            # 后台线程异步获取文件大小
            self.status_var.set(
                f"共 {len(self._files)} 个文件，点击 ☐ 列勾选  |  双击路径定位文件  |  空格键批量切换"
            )
            threading.Thread(target=self._load_file_sizes, daemon=True).start()

    def _restore_selections(self):
        """根据上次保存的路径集合恢复选中状态"""
        preselected_set = set(self._preselected_paths)
        for i, f in enumerate(self._files):
            if f in preselected_set:
                self.selected_indices.add(i)
                self.tree.set(str(i), "checked", "☑")
        self._update_selected_info()

    def _load_file_sizes(self):
        """后台线程加载文件大小并更新 Treeview"""
        for i, f in enumerate(self._files):
            try:
                size = f.stat().st_size
                self._file_sizes[i] = size
                # 每 50 个更新一次 UI
                if i % 50 == 0:
                    self.after(0, self._update_size_column, i)
            except (PermissionError, OSError):
                pass
        # 最终刷新
        self.after(0, self._update_all_sizes)

    def _update_size_column(self, idx):
        """更新单个文件的大小列"""
        if not self.winfo_exists():
            return
        if idx < len(self._files):
            size = self._file_sizes.get(idx, 0)
            self.tree.set(str(idx), "size", core.format_size(size))

    def _update_all_sizes(self):
        """刷新所有文件大小到 Treeview，并更新已选总计"""
        if not self.winfo_exists():
            return
        for i in range(len(self._files)):
            size = self._file_sizes.get(i, 0)
            if size > 0:
                self.tree.set(str(i), "size", core.format_size(size))
        self._update_selected_info()
        self.status_var.set(
            f"共 {len(self._files)} 个文件，点击 ☐ 列勾选  |  双击路径定位文件  |  空格键批量切换"
        )

    def _on_tree_click(self, event):
        """点击 ☐ 列切换勾选，点击 ☐ 标题则全选/全不选"""
        region = self.tree.identify_region(event.x, event.y)
        column = self.tree.identify_column(event.x)

        # 点击标题栏 ☐ → 切换全选/全不选
        if region == "heading" and column == '#1':
            # 如果当前全部选中则全不选，否则全选
            if len(self.selected_indices) == len(self._files):
                self._deselect_all()
            else:
                self._select_all()
            return

        # 仅点击数据行的 ☐ 列切换勾选
        if column != '#1':
            return
        item = self.tree.identify_row(event.y)
        if not item:
            return
        idx = int(item)
        if idx in self.selected_indices:
            self.selected_indices.discard(idx)
            self.tree.set(item, "checked", "☐")
        else:
            self.selected_indices.add(idx)
            self.tree.set(item, "checked", "☑")
        self._update_selected_info()

    def _on_tree_double_click(self, event):
        """双击路径 → 在资源管理器中打开并选中该文件"""
        item = self.tree.identify_row(event.y)
        if not item:
            return
        idx = int(item)
        f = self._files[idx]
        try:
            subprocess.Popen(
                ['explorer', '/select,', str(f)],
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except Exception as e:
            messagebox.showerror("错误", f"无法打开资源管理器:\n{e}", parent=self)

    def _on_tree_space(self, event):
        selection = self.tree.selection()
        for item in selection:
            idx = int(item)
            if idx in self.selected_indices:
                self.selected_indices.discard(idx)
                self.tree.set(item, "checked", "☐")
            else:
                self.selected_indices.add(idx)
                self.tree.set(item, "checked", "☑")
        self._update_selected_info()

    def _select_all(self):
        for i in range(len(self._files)):
            self.selected_indices.add(i)
            self.tree.set(str(i), "checked", "☑")
        self._update_selected_info()

    def _deselect_all(self):
        for i in self.selected_indices:
            self.tree.set(str(i), "checked", "☐")
        self.selected_indices.clear()
        self._update_selected_info()

    def _update_selected_info(self):
        count = len(self.selected_indices)
        total_bytes = sum(self._file_sizes.get(i, 0) for i in self.selected_indices)
        # 全选但大小尚未异步加载完成时，用扫描结果总量作为初始估算
        if count == len(self._files) and total_bytes == 0 and self.scan_result.total_size_bytes > 0:
            total_bytes = self.scan_result.total_size_bytes
        self.lbl_selected.configure(
            text=f"已选: {count} 个文件, {core.format_size(total_bytes)}"
        )
        if count > 0:
            self.btn_delete.configure(state=tk.NORMAL)
        else:
            self.btn_delete.configure(state=tk.DISABLED)

        # 回调通知主窗口（类别名, 已选文件数, 已选字节数, 具体文件路径列表）
        if self.on_selection_changed:
            selected_paths = [self._files[i] for i in self.selected_indices]
            self.on_selection_changed(
                self.scan_result.category.name, count, total_bytes, selected_paths,
            )

    def _delete_selected(self):
        if not self.selected_indices:
            return

        count = len(self.selected_indices)
        total_bytes = sum(self._file_sizes.get(i, 0) for i in self.selected_indices)

        ok = messagebox.askyesno(
            "确认删除",
            f"确认删除选中的 {count} 个文件吗？\n共 {core.format_size(total_bytes)}\n\n此操作不可撤销！",
            parent=self,
        )
        if not ok:
            return

        self.btn_delete.configure(state=tk.DISABLED)
        self.status_var.set("正在删除...")

        thread = threading.Thread(target=self._run_delete, daemon=True)
        thread.start()
        self._poll_delete_thread(thread)

    def _run_delete(self):
        success = 0
        failed = 0
        failed_items: list[str] = []

        indices = list(self.selected_indices)
        total = len(indices)

        for j, i in enumerate(indices):
            f = self._files[i]
            try:
                if f.exists():
                    if f.is_file() or f.is_symlink():
                        os.unlink(f)
                    elif f.is_dir():
                        shutil.rmtree(f, ignore_errors=False)
                    success += 1
            except PermissionError:
                failed += 1
                failed_items.append(f"{f.name}: 权限不足")
            except OSError as e:
                failed += 1
                failed_items.append(f"{f.name}: {e}")

            if j % 20 == 0:
                self.after(0, self._on_delete_progress, j + 1, total)

        self._delete_success = success
        self._delete_failed = failed
        self._delete_failed_items = failed_items

    def _on_delete_progress(self, current, total):
        if not self.winfo_exists():
            return
        self.status_var.set(f"正在删除... ({current}/{total})")

    def _poll_delete_thread(self, thread):
        if not self.winfo_exists():
            return
        if thread.is_alive():
            self.after(100, lambda: self._poll_delete_thread(thread))
        else:
            self._on_delete_done()

    def _on_delete_done(self):
        success = getattr(self, "_delete_success", 0)
        failed = getattr(self, "_delete_failed", 0)
        failed_items = getattr(self, "_delete_failed_items", [])

        if failed > 0:
            detail = "\n".join(failed_items[:5])
            if len(failed_items) > 5:
                detail += f"\n... 还有 {len(failed_items) - 5} 项"
            messagebox.showwarning("删除完成", f"成功: {success}, 失败: {failed}\n{detail}", parent=self)
        else:
            messagebox.showinfo("删除完成", f"成功删除 {success} 个文件！", parent=self)

        deleted_bytes = sum(self._file_sizes.get(i, 0) for i in self.selected_indices)
        # 大小未加载完成时用扫描结果总量按比例估算
        if deleted_bytes == 0 and self.selected_indices and self.scan_result.total_size_bytes > 0:
            deleted_bytes = self.scan_result.total_size_bytes * success // max(
                len(self.selected_indices), 1)
        for i in sorted(self.selected_indices, reverse=True):
            if i < len(self._files):
                self.tree.delete(str(i))
        self.selected_indices.clear()
        self._update_selected_info()

        # 通知主页面同步更新该类别的文件数和大小
        if self.on_files_deleted:
            self.on_files_deleted(
                self.scan_result.category.name, success, deleted_bytes
            )

        self.status_var.set(f"删除完成 - 成功 {success}, 失败 {failed}")


# ============================================================
# Tab 2: 空间分析
# ============================================================


class AnalyzeTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.current_path: Path = Path("C:\\")
        self.path_history: list[Path] = []
        self.folder_results: list[core.FolderSizeInfo] = []
        self._scan_thread: threading.Thread | None = None

        self._build_ui()

    def _build_ui(self):
        nav_frame = ttk.Frame(self, padding=(4, 4))
        nav_frame.pack(fill=tk.X, padx=4, pady=(0, 4))

        self.btn_up = ttk.Button(nav_frame, text="返回上级", command=self._go_up)
        self.btn_up.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_refresh = ttk.Button(nav_frame, text="刷新", command=self._refresh)
        self.btn_refresh.pack(side=tk.LEFT, padx=(0, 12))

        self.breadcrumb_frame = ttk.Frame(nav_frame)
        self.breadcrumb_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.lbl_current_path = ttk.Label(
            nav_frame, text="", font=FONT_SMALL, foreground="gray"
        )
        self.lbl_current_path.pack(side=tk.RIGHT)

        self._build_folder_list()

        self.progress = ttk.Progressbar(self, mode="indeterminate", length=300)
        self.lbl_scan_status = ttk.Label(self, text="", font=FONT_SMALL)

        self.status_var = tk.StringVar(value='点击"刷新"开始扫描 C:\\')
        status_bar = ttk.Label(
            self, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W, padding=(6, 2)
        )
        status_bar.pack(fill=tk.X, side=tk.BOTTOM, padx=4, pady=(4, 0))

    def _build_folder_list(self):
        outer = ttk.Frame(self)
        outer.pack(fill=tk.BOTH, expand=True, padx=4)

        header = ttk.Frame(outer, padding=(6, 2))
        header.pack(fill=tk.X)
        ttk.Label(header, text="文件夹", font=FONT_BOLD, width=30, anchor=tk.W).pack(
            side=tk.LEFT, padx=(4, 8)
        )
        ttk.Label(header, text="大小", font=FONT_BOLD, width=14, anchor=tk.W).pack(
            side=tk.LEFT, padx=(0, 4)
        )
        ttk.Label(header, text="文件数", font=FONT_BOLD, width=10, anchor=tk.W).pack(
            side=tk.LEFT, padx=(0, 4)
        )
        ttk.Label(header, text="占比", font=FONT_BOLD, width=20, anchor=tk.W).pack(side=tk.LEFT)
        ttk.Separator(outer, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=2)

        self.folder_canvas = tk.Canvas(outer, bg=COLOR_BG, highlightthickness=0)
        folder_scrollbar = ttk.Scrollbar(
            outer, orient=tk.VERTICAL, command=self.folder_canvas.yview
        )
        self.folder_scroll_frame = ttk.Frame(self.folder_canvas)

        self.folder_scroll_frame.bind(
            "<Configure>",
            lambda e: self.folder_canvas.configure(
                scrollregion=self.folder_canvas.bbox("all")
            ),
        )

        self.folder_canvas_window = self.folder_canvas.create_window(
            (0, 0), window=self.folder_scroll_frame, anchor=tk.NW
        )
        self.folder_canvas.configure(yscrollcommand=folder_scrollbar.set)
        self.folder_canvas.bind("<Configure>", self._on_folder_canvas_configure)

        self.folder_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        folder_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.folder_canvas.bind("<Enter>", self._bind_folder_mousewheel)
        self.folder_canvas.bind("<Leave>", self._unbind_folder_mousewheel)

    def _on_folder_canvas_configure(self, event):
        self.folder_canvas.itemconfig(self.folder_canvas_window, width=event.width)

    def _bind_folder_mousewheel(self, event):
        self.folder_canvas.bind_all("<MouseWheel>", self._on_folder_mousewheel)

    def _unbind_folder_mousewheel(self, event):
        self.folder_canvas.unbind_all("<MouseWheel>")

    def _on_folder_mousewheel(self, event):
        self.folder_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _update_breadcrumb(self):
        for w in self.breadcrumb_frame.winfo_children():
            w.destroy()

        parts = list(self.current_path.parts)
        accum = ""
        for i, part in enumerate(parts):
            accum = str(Path(accum) / part) if accum else part
            lbl = ttk.Label(
                self.breadcrumb_frame,
                text=f" {part} ",
                font=FONT_SMALL,
                foreground="#3498db",
                cursor="hand2",
            )
            lbl.pack(side=tk.LEFT)
            lbl.bind("<Button-1>", lambda e, p=Path(accum): self._navigate_to(p))
            if i < len(parts) - 1:
                ttk.Label(self.breadcrumb_frame, text=" > ", font=FONT_SMALL).pack(side=tk.LEFT)
        self.lbl_current_path.configure(text=str(self.current_path))

    def _navigate_to(self, path: Path):
        self.current_path = path
        self._update_breadcrumb()
        self.start_scan()

    def start_scan(self):
        self.btn_up.configure(state=tk.DISABLED)
        self.btn_refresh.configure(state=tk.DISABLED)
        self._clear_folder_rows()
        self._show_progress(True)
        self.status_var.set(f"正在扫描 {self.current_path} ...")

        self._scan_thread = threading.Thread(target=self._run_scan, daemon=True)
        self._scan_thread.start()
        self._poll_scan_thread()

    def _run_scan(self):
        self._scan_data = core.scan_subfolders_sizes(
            self.current_path,
            progress_callback=lambda i, total: self.after(0, self._on_scan_item, i, total),
        )

    def _on_scan_item(self, i: int, total: int):
        self.status_var.set(f"正在扫描 {self.current_path} ... ({i + 1}/{total})")

    def _poll_scan_thread(self):
        if self._scan_thread and self._scan_thread.is_alive():
            self.after(100, self._poll_scan_thread)
        else:
            self._on_scan_done()

    def _on_scan_done(self):
        self.folder_results = getattr(self, "_scan_data", [])
        self._show_progress(False)
        self._update_breadcrumb()
        self._populate_folder_rows()
        self.btn_up.configure(state=tk.NORMAL)
        self.btn_refresh.configure(state=tk.NORMAL)

        parent = self.current_path.parent
        self.btn_up.configure(
            state=tk.NORMAL if parent != self.current_path else tk.DISABLED
        )

        total = core.get_total_size_of_results(self.folder_results)
        self.status_var.set(
            f"扫描完成 - {len(self.folder_results)} 个文件夹，总大小 {core.format_size(total)}"
        )

    def _show_progress(self, show: bool):
        if show:
            self.progress.pack(fill=tk.X, padx=8, pady=(2, 0))
            self.progress.start(15)
            self.lbl_scan_status.pack(padx=8)
            self.lbl_scan_status.configure(text="正在扫描子文件夹...")
        else:
            self.progress.stop()
            self.progress.pack_forget()
            self.lbl_scan_status.pack_forget()

    def _clear_folder_rows(self):
        for w in self.folder_scroll_frame.winfo_children():
            w.destroy()

    def _populate_folder_rows(self):
        self._clear_folder_rows()
        total_size = core.get_total_size_of_results(self.folder_results)

        if not self.folder_results:
            empty_lbl = ttk.Label(
                self.folder_scroll_frame,
                text="此目录下没有子文件夹，或所有文件夹都无法访问。",
                font=FONT_DEFAULT,
            )
            empty_lbl.pack(pady=20)
            return

        for info in self.folder_results:
            self._create_folder_row(info, total_size)

        # 导航后滚动回顶部
        self.folder_canvas.yview_moveto(0)

    def _create_folder_row(self, info: core.FolderSizeInfo, total_size: int):
        row = ttk.Frame(self.folder_scroll_frame, padding=(6, 2))
        row.pack(fill=tk.X, pady=1)

        if not info.is_accessible:
            name_lbl = ttk.Label(
                row, text=f"📁 {info.name} (无权限)", font=FONT_DEFAULT, width=30, anchor=tk.W
            )
            name_lbl.pack(side=tk.LEFT, padx=(4, 8))
            ttk.Label(row, text="---", width=14).pack(side=tk.LEFT, padx=(0, 4))
            ttk.Label(row, text="---", width=10).pack(side=tk.LEFT, padx=(0, 4))
            ttk.Label(row, text="---", width=20).pack(side=tk.LEFT)
            return

        size_color = "black"
        if info.size_bytes > 1024 ** 3:
            size_color = COLOR_DANGER
        elif info.size_bytes > 100 * 1024 ** 2:
            size_color = COLOR_WARN

        name_frame = ttk.Frame(row)
        name_frame.pack(side=tk.LEFT, padx=(4, 8))

        name_lbl = tk.Label(
            name_frame,
            text=f"📁 {info.name}",
            font=FONT_DEFAULT,
            fg="#2980b9",
            cursor="hand2",
            anchor=tk.W,
            width=30,
        )
        name_lbl.pack()
        name_lbl.bind("<Button-1>", lambda e, p=info.path: self._navigate_to(p))

        ttk.Label(
            row, text=core.format_size(info.size_bytes), font=FONT_DEFAULT,
            foreground=size_color, width=14, anchor=tk.W,
        ).pack(side=tk.LEFT, padx=(0, 4))

        ttk.Label(
            row, text=f"{info.file_count:,}", font=FONT_DEFAULT, width=10, anchor=tk.W
        ).pack(side=tk.LEFT, padx=(0, 4))

        pct_frame = ttk.Frame(row)
        pct_frame.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))

        if total_size > 0:
            pct = info.size_bytes / total_size
            bar = ttk.Progressbar(pct_frame, length=120, mode="determinate", value=pct * 100)
            bar.pack(side=tk.LEFT, padx=(0, 4))
            ttk.Label(pct_frame, text=f"{pct * 100:.1f}%", font=FONT_SMALL).pack(side=tk.LEFT)
        else:
            ttk.Label(pct_frame, text="0%", font=FONT_SMALL).pack(side=tk.LEFT)

        btn_open = ttk.Button(
            row,
            text="打开",
            style="OpenFolder.TButton",
            command=lambda p=info.path: core.open_folder(str(p)),
        )
        btn_open.pack(side=tk.RIGHT, padx=(4, 0))

    def _go_up(self):
        parent = self.current_path.parent
        if parent != self.current_path:
            self._navigate_to(parent)

    def _refresh(self):
        self.start_scan()


# ============================================================
# 入口
# ============================================================


def main():
    app = CleanerApp()
    app.mainloop()


if __name__ == "__main__":
    main()
