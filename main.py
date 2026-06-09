"""
校园网自动登录工具
"""
import argparse
import ctypes
import json
import msvcrt
import os
import sys
import threading
import time
import tkinter.messagebox as mbox
import traceback
import winreg
from datetime import datetime
from ctypes import wintypes
from queue import Queue

import customtkinter as ctk
import pystray
import requests
from PIL import Image

# 设置现代化主题
ctk.set_appearance_mode("system")  # 自动适应系统主题
ctk.set_default_color_theme("blue")

# --------------------- 配置管理 --------------------- #
CONFIG_FILE = 'srun_config.json'
ENV_FILE = '.env'
AUTO_LOG_FILE = 'srun_autologin.log'
AUTO_LOCK_FILE = 'srun_autologin.lock'
AUTO_MUTEX_NAME = 'Global\\SrunAutoLoginDaemon'
ENV_USERNAME_KEY = 'SRUN_USERNAME'
ENV_PASSWORD_KEY = 'SRUN_PASSWORD'
ENV_SERVER_URL_KEY = 'SRUN_SERVER_URL'
DEFAULT_CHECK_URL = "https://www.baidu.com"

kernel32 = ctypes.windll.kernel32
kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.CreateMutexW.restype = wintypes.HANDLE
kernel32.GetLastError.argtypes = []
kernel32.GetLastError.restype = wintypes.DWORD
kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]
kernel32.ReleaseMutex.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL


def get_base_dir():
    """获取程序基础目录"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def get_config_path():
    return os.path.join(get_base_dir(), CONFIG_FILE)


def get_env_path():
    return os.path.join(get_base_dir(), ENV_FILE)


def get_auto_log_path():
    return os.path.join(get_base_dir(), AUTO_LOG_FILE)


def get_auto_lock_path():
    return os.path.join(get_base_dir(), AUTO_LOCK_FILE)


def write_auto_log(message):
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(get_auto_log_path(), 'a', encoding='utf-8') as f:
            f.write(f"[{timestamp}] {message}\n")
    except Exception:
        pass


def _parse_env_value(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        inner = value[1:-1]
        if value[0] == '"':
            chars = []
            escaped = False
            for ch in inner:
                if escaped:
                    chars.append(ch)
                    escaped = False
                elif ch == '\\':
                    escaped = True
                else:
                    chars.append(ch)
            if escaped:
                chars.append('\\')
            return ''.join(chars)
        return inner
    return value


def _format_env_value(value):
    value = "" if value is None else str(value)
    if any(ch.isspace() for ch in value) or any(ch in value for ch in '#="'):
        return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'
    return value


def load_env_credentials():
    """从.env文件和进程环境变量读取登录凭据"""
    values = {}
    env_path = get_env_path()
    if os.path.exists(env_path):
        try:
            with open(env_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#') or '=' not in line:
                        continue
                    key, value = line.split('=', 1)
                    values[key.strip()] = _parse_env_value(value)
        except Exception as e:
            print(f"加载.env失败: {e}")

    for key in (ENV_USERNAME_KEY, ENV_PASSWORD_KEY, ENV_SERVER_URL_KEY):
        if os.getenv(key):
            values[key] = os.getenv(key)

    return {
        "username": values.get(ENV_USERNAME_KEY, ""),
        "password": values.get(ENV_PASSWORD_KEY, ""),
        "server_url": values.get(ENV_SERVER_URL_KEY, "")
    }


def save_env_credentials(username, password, server_url):
    """保存登录凭据到.env文件"""
    try:
        env_data = {
            ENV_USERNAME_KEY: username,
            ENV_PASSWORD_KEY: password,
            ENV_SERVER_URL_KEY: server_url
        }
        with open(get_env_path(), 'w', encoding='utf-8') as f:
            for key, value in env_data.items():
                f.write(f"{key}={_format_env_value(value)}\n")
        return True
    except Exception as e:
        print(f"保存.env失败: {e}")
        return False


def apply_env_credentials(config):
    env_credentials = load_env_credentials()
    for key in ("username", "password", "server_url"):
        value = env_credentials.get(key)
        if value:
            config[key] = value
    return config


def save_config(data):
    """保存非敏感配置到JSON文件，账号密码保存在.env"""
    try:
        data_to_save = dict(data)
        data_to_save["username"] = ""
        data_to_save["password"] = ""
        with open(get_config_path(), 'w', encoding='utf-8') as f:
            json.dump(data_to_save, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"保存配置失败: {e}")
        return False


def load_config():
    """从JSON文件加载配置"""
    default_config = {
        "username": "",
        "password": "",
        "auto_start": False,
        "check_interval": 60,
        "theme": "system",
        "server_url": "https://net.szu.edu.cn"
    }

    config_path = get_config_path()
    if not os.path.exists(config_path):
        return apply_env_credentials(default_config)

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
            # 合并默认配置，确保所有字段都存在
            for key, value in default_config.items():
                if key not in config:
                    config[key] = value
            return apply_env_credentials(config)
    except Exception as e:
        print(f"加载配置失败: {e}")
        return apply_env_credentials(default_config)


class SingleInstanceLock:
    def __init__(self, path):
        self.path = path
        self.file = None
        self.mutex = None

    def acquire(self):
        try:
            self.mutex = kernel32.CreateMutexW(None, False, AUTO_MUTEX_NAME)
            if self.mutex and kernel32.GetLastError() == 183:
                kernel32.CloseHandle(self.mutex)
                self.mutex = None
                return False

            self.file = open(self.path, 'a+', encoding='utf-8')
            self.file.seek(0)
            if not self.file.read(1):
                self.file.write("1")
                self.file.flush()
            self.file.seek(0)
            msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            if self.file:
                self.file.close()
                self.file = None
            if self.mutex:
                kernel32.CloseHandle(self.mutex)
                self.mutex = None
            return False

    def release(self):
        if self.file:
            try:
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
            finally:
                self.file.close()
                self.file = None

        if self.mutex:
            kernel32.ReleaseMutex(self.mutex)
            kernel32.CloseHandle(self.mutex)
            self.mutex = None


def check_public_network(check_url=DEFAULT_CHECK_URL):
    try:
        response = requests.get(check_url, timeout=5)
        return response.status_code == 200
    except requests.RequestException:
        return False


def perform_auto_login_once(reason="manual"):
    config = load_config()
    username = config.get("username", "").strip()
    password = config.get("password", "").strip()
    server_url = config.get("server_url", "https://net.szu.edu.cn")

    if not username or not password:
        write_auto_log(f"{reason}: missing username or password; run install_autostart.bat first")
        return False

    try:
        from srun_client import SrunPortalClient

        client = SrunPortalClient(username, password, server_url)
        success = client.login()
        if success:
            write_auto_log(f"{reason}: login ok ({client.last_error or 'ok'})")
        else:
            write_auto_log(f"{reason}: login failed ({client.last_error or 'unknown error'})")
        return success
    except Exception as e:
        write_auto_log(f"{reason}: login exception: {e}")
        write_auto_log(traceback.format_exc())
        return False


def run_auto_login_daemon(interval=30, check_url=DEFAULT_CHECK_URL):
    lock = SingleInstanceLock(get_auto_lock_path())
    if not lock.acquire():
        write_auto_log("daemon already running; ignored duplicate launch")
        return 0

    try:
        write_auto_log(f"daemon started, interval={interval}s")
        perform_auto_login_once("startup")

        while True:
            if check_public_network(check_url):
                time.sleep(interval)
                continue

            write_auto_log("public network unavailable; trying campus login")
            attempt = 1
            retry_delay = 5
            while not check_public_network(check_url):
                perform_auto_login_once(f"retry {attempt}")
                time.sleep(5)
                if check_public_network(check_url):
                    write_auto_log("public network restored")
                    break
                attempt += 1
                time.sleep(retry_delay)
                retry_delay = min(30, retry_delay + 5)

            time.sleep(interval)
    finally:
        lock.release()


# --------------------- 开机自启动管理 --------------------- #
class StartupManager:
    @staticmethod
    def get_launch_command():
        """获取开机自启使用的完整启动命令"""
        if getattr(sys, 'frozen', False):
            return f'"{sys.executable}"'

        python_exe = sys.executable
        pythonw_exe = os.path.join(os.path.dirname(python_exe), "pythonw.exe")
        if os.path.exists(pythonw_exe):
            python_exe = pythonw_exe

        main_script = os.path.join(get_base_dir(), "main.py")
        return f'"{python_exe}" "{main_script}"'

    @staticmethod
    def get_startup_path():
        """获取启动目录路径"""
        startup_dir = os.path.join(
            os.getenv('APPDATA'),
            'Microsoft', 'Windows', 'Start Menu', 'Programs', 'Startup'
        )
        return os.path.join(startup_dir, 'SrunAutoLogin.bat')

    @staticmethod
    def create_startup_script():
        """创建启动脚本"""
        script_content = f'''@echo off
cd /d "{get_base_dir()}"
start "" {StartupManager.get_launch_command()}
'''
        try:
            with open(StartupManager.get_startup_path(), 'w', encoding='utf-8') as f:
                f.write(script_content)
            return True
        except Exception as e:
            print(f"创建启动脚本失败: {e}")
            return False

    @staticmethod
    def add_to_registry():
        """添加到注册表启动项"""
        try:
            reg_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg_path, 0, winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, "SrunAutoLogin", 0, winreg.REG_SZ, StartupManager.get_launch_command())
            return True
        except Exception as e:
            print(f"注册表添加失败: {e}")
            return False

    @staticmethod
    def remove_from_registry():
        """从注册表移除启动项"""
        try:
            reg_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg_path, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, "SrunAutoLogin")
            return True
        except Exception:
            return False

    @staticmethod
    def remove_startup_script():
        """移除启动脚本"""
        try:
            script_path = StartupManager.get_startup_path()
            if os.path.exists(script_path):
                os.remove(script_path)
            return True
        except Exception:
            return False

    @staticmethod
    def set_startup(enabled):
        """设置开机自启动"""
        if enabled:
            # 双重保险：注册表 + 启动目录
            reg_ok = StartupManager.add_to_registry()
            script_ok = StartupManager.create_startup_script()
            return reg_ok or script_ok
        else:
            StartupManager.remove_from_registry()
            StartupManager.remove_startup_script()
            return True


# --------------------- 网络监控器 --------------------- #
class NetworkMonitor:
    def __init__(self, check_url, on_state_change, login_func, log_func, interval=60):
        self.check_url = check_url
        self.on_state_change = on_state_change
        self.login_func = login_func
        self.log_func = log_func
        self.interval = interval
        self.running = False
        self.thread = None
        self.last_online = None

    def start(self):
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self._monitor_loop, daemon=True)
            self.thread.start()
            self.log_func("🚀 网络监控已启动")

    def stop(self):
        if self.running:
            self.running = False
            self.log_func("⏹️ 网络监控已停止")

    def _check_network(self):
        try:
            response = requests.get(self.check_url, timeout=5)
            return response.status_code == 200
        except requests.RequestException:
            return False

    def _monitor_loop(self):
        while self.running:
            try:
                online = self._check_network()

                if online != self.last_online:
                    self.on_state_change(online)
                    status = "已连接" if online else "连接断开"
                    emoji = "✅" if online else "❌"
                    self.log_func(f"{emoji} 网络状态变化: {status}")

                if not online:
                    if self.last_online is None:
                        self.log_func("🔄 启动时未联网，尝试自动登录...")
                    elif self.last_online:
                        self.log_func("🔄 检测到网络断开，尝试自动登录...")
                    else:
                        self.log_func("🔄 网络仍未连接，重试自动登录...")
                    self.login_func()

                self.last_online = online

            except Exception as e:
                self.log_func(f"⚠️ 监控异常: {str(e)}")

            time.sleep(self.interval)


# --------------------- 流式日志显示组件 --------------------- #
class StreamingLogFrame(ctk.CTkFrame):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)

        # 日志队列
        self.log_queue = Queue()

        # 标题
        self.title_label = ctk.CTkLabel(
            self,
            text="📋 实时日志",
            font=ctk.CTkFont(size=14, weight="bold")
        )
        self.title_label.pack(pady=(10, 5))

        # 日志显示区域
        self.log_text = ctk.CTkTextbox(
            self,
            height=200,
            font=ctk.CTkFont(family="Consolas", size=11),
            wrap="word"
        )
        self.log_text.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # 控制按钮
        self.button_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.button_frame.pack(fill="x", padx=10, pady=(0, 10))

        self.clear_btn = ctk.CTkButton(
            self.button_frame,
            text="清空日志",
            width=80,
            height=28,
            command=self.clear_logs
        )
        self.clear_btn.pack(side="left")

        self.save_btn = ctk.CTkButton(
            self.button_frame,
            text="保存日志",
            width=80,
            height=28,
            command=self.save_logs
        )
        self.save_btn.pack(side="left", padx=(10, 0))

        # 启动日志处理
        self._start_log_processor()

    def add_log(self, message):
        """添加日志消息到队列"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        formatted_message = f"[{timestamp}] {message}"
        self.log_queue.put(formatted_message)

    def _start_log_processor(self):
        """启动日志处理器"""

        def process_logs():
            try:
                while True:
                    if not self.log_queue.empty():
                        message = self.log_queue.get_nowait()
                        self.log_text.insert("end", message + "\n")
                        self.log_text.see("end")

                        # 限制日志行数，避免内存占用过大
                        lines = self.log_text.get("1.0", "end").count('\n')
                        if lines > 1000:
                            # 删除前200行
                            self.log_text.delete("1.0", "200.0")

                    time.sleep(0.1)
            except Exception as e:
                print(f"日志处理异常: {e}")

        threading.Thread(target=process_logs, daemon=True).start()

    def clear_logs(self):
        """清空日志"""
        self.log_text.delete("1.0", "end")
        self.add_log("📝 日志已清空")

    def save_logs(self):
        """保存日志到文件"""
        try:
            log_content = self.log_text.get("1.0", "end")
            if not log_content.strip():
                mbox.showinfo("提示", "没有日志内容可保存")
                return

            filename = f"srun_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            filepath = os.path.join(get_base_dir(), filename)

            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(log_content)

            self.add_log(f"💾 日志已保存到: {filename}")
            mbox.showinfo("保存成功", f"日志已保存到:\n{filepath}")

        except Exception as e:
            error_msg = f"保存日志失败: {str(e)}"
            self.add_log(f"❌ {error_msg}")
            mbox.showerror("保存失败", error_msg)


# --------------------- 主应用程序 --------------------- #
class ModernSrunApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        # 窗口配置
        self.title("校园网自动登录工具 v2.0")
        self.geometry("600x700")
        self.minsize(500, 600)

        # 设置图标
        self._set_window_icon()

        # 加载配置
        self.config = load_config()
        self._apply_theme()

        # 初始化UI
        self._create_widgets()

        # 初始化网络监控
        self.monitor = NetworkMonitor(
            "https://www.baidu.com",
            self._on_network_state_change,
            self._auto_login,
            self.log_frame.add_log,
            self.config.get("check_interval", 60)
        )

        # 托盘相关
        self.tray_icon = None
        self.tray_thread = None

        # 设置窗口事件
        self.protocol("WM_DELETE_WINDOW", self._on_window_close)

        # 启动监控
        self.after(1000, self._start_monitoring)

        # 显示启动信息
        self.log_frame.add_log("🎉 校园网自动登录工具已启动")
        self.log_frame.add_log(f"⚙️ 检查间隔: {self.config.get('check_interval', 60)}秒")

    def _set_window_icon(self):
        """设置窗口图标"""
        try:
            icon_path = os.path.join(get_base_dir(), "wifi.ico")
            if os.path.exists(icon_path):
                self.iconbitmap(icon_path)
        except Exception:
            pass

    def _apply_theme(self):
        """应用主题设置"""
        theme = self.config.get("theme", "system")
        ctk.set_appearance_mode(theme)

    def _create_widgets(self):
        """创建界面组件"""
        # 主标题
        self.title_label = ctk.CTkLabel(
            self,
            text="🌐 校园网自动登录工具",
            font=ctk.CTkFont(size=24, weight="bold")
        )
        self.title_label.pack(pady=(20, 10))

        # 网络状态显示
        self.status_frame = ctk.CTkFrame(self)
        self.status_frame.pack(fill="x", padx=20, pady=(0, 20))

        self.status_label = ctk.CTkLabel(
            self.status_frame,
            text="🔄 检测网络状态中...",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        self.status_label.pack(pady=15)

        # 配置区域
        self.config_frame = ctk.CTkFrame(self)
        self.config_frame.pack(fill="x", padx=20, pady=(0, 20))

        ctk.CTkLabel(
            self.config_frame,
            text="📝 登录配置",
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(pady=(15, 10))

        # 用户名输入
        self.username_entry = ctk.CTkEntry(
            self.config_frame,
            placeholder_text="请输入用户名",
            width=300,
            height=35,
            font=ctk.CTkFont(size=12)
        )
        self.username_entry.pack(pady=5)
        self.username_entry.insert(0, self.config.get("username", ""))

        # 密码输入
        self.password_entry = ctk.CTkEntry(
            self.config_frame,
            placeholder_text="请输入密码",
            show="*",
            width=300,
            height=35,
            font=ctk.CTkFont(size=12)
        )
        self.password_entry.pack(pady=5)
        self.password_entry.insert(0, self.config.get("password", ""))

        # 显示密码选项
        self.show_password_var = ctk.BooleanVar()
        self.show_password_cb = ctk.CTkCheckBox(
            self.config_frame,
            text="显示密码",
            variable=self.show_password_var,
            command=self._toggle_password_visibility
        )
        self.show_password_cb.pack(pady=(5, 15))

        # 功能按钮区域
        self.button_frame = ctk.CTkFrame(self)
        self.button_frame.pack(fill="x", padx=20, pady=(0, 20))

        ctk.CTkLabel(
            self.button_frame,
            text="🔧 功能操作",
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(pady=(15, 10))

        # 按钮网格布局
        self.button_grid = ctk.CTkFrame(self.button_frame, fg_color="transparent")
        self.button_grid.pack(pady=(0, 15))

        # 保存配置按钮
        self.save_btn = ctk.CTkButton(
            self.button_grid,
            text="💾 保存配置",
            width=120,
            height=35,
            command=self._save_config
        )
        self.save_btn.grid(row=0, column=0, padx=5, pady=5)

        # 手动登录按钮
        self.login_btn = ctk.CTkButton(
            self.button_grid,
            text="🔑 手动登录",
            width=120,
            height=35,
            command=self._manual_login
        )
        self.login_btn.grid(row=0, column=1, padx=5, pady=5)

        # 开机自启按钮
        self.startup_var = ctk.BooleanVar(value=self.config.get("auto_start", False))
        self.startup_cb = ctk.CTkCheckBox(
            self.button_grid,
            text="开机自启",
            variable=self.startup_var,
            command=self._toggle_startup
        )
        self.startup_cb.grid(row=1, column=0, columnspan=2, pady=5)

        # 日志显示区域
        self.log_frame = StreamingLogFrame(self)
        self.log_frame.pack(fill="both", expand=True, padx=20, pady=(0, 20))

    def _toggle_password_visibility(self):
        """切换密码可见性"""
        if self.show_password_var.get():
            self.password_entry.configure(show="")
        else:
            self.password_entry.configure(show="*")

    def _save_config(self):
        """保存配置"""
        username = self.username_entry.get().strip()
        password = self.password_entry.get().strip()

        if not username or not password:
            mbox.showwarning("提示", "用户名和密码不能为空！")
            return

        self.config.update({
            "username": username,
            "password": password,
            "auto_start": self.startup_var.get()
        })

        env_ok = save_env_credentials(
            username,
            password,
            self.config.get("server_url", "https://net.szu.edu.cn")
        )

        if env_ok and save_config(self.config):
            self.log_frame.add_log("✅ 配置保存成功")
            mbox.showinfo("成功", "配置已保存！")
        else:
            self.log_frame.add_log("❌ 配置保存失败")
            mbox.showerror("错误", "配置保存失败！")

    def _manual_login(self):
        """手动登录"""
        self.log_frame.add_log("🔑 开始手动登录...")
        threading.Thread(target=self._perform_login, args=(True,), daemon=True).start()

    def _auto_login(self):
        """自动登录"""
        threading.Thread(target=self._perform_login, args=(False,), daemon=True).start()

    def _perform_login(self, is_manual=False):
        """执行登录操作"""
        try:
            username = self.username_entry.get().strip()
            password = self.password_entry.get().strip()

            if not username or not password:
                self.log_frame.add_log("❌ 用户名或密码为空，无法登录")
                return

            self.log_frame.add_log(f"🔄 正在{'手动' if is_manual else '自动'}登录...")

            from srun_client import SrunPortalClient

            client = SrunPortalClient(
                username,
                password,
                self.config.get("server_url", "https://net.szu.edu.cn")
            )
            success = client.login()

            if success:
                self.log_frame.add_log("✅ 登录成功！")
                if is_manual:
                    mbox.showinfo("成功", "手动登录成功！")
            else:
                error_text = client.last_error or "请检查用户名和密码"
                self.log_frame.add_log(f"❌ 登录失败: {error_text}")
                if is_manual:
                    mbox.showerror("失败", f"登录失败: {error_text}")

        except Exception as e:
            error_msg = f"登录异常: {str(e)}"
            self.log_frame.add_log(f"❌ {error_msg}")
            if is_manual:
                mbox.showerror("异常", error_msg)

    def _toggle_startup(self):
        """切换开机自启动"""
        enabled = self.startup_var.get()

        try:
            if StartupManager.set_startup(enabled):
                status = "启用" if enabled else "禁用"
                self.log_frame.add_log(f"✅ 开机自启动已{status}")

                # 更新配置
                self.config["auto_start"] = enabled
                save_config(self.config)

                mbox.showinfo("成功", f"开机自启动已{status}！")
            else:
                self.log_frame.add_log("❌ 开机自启动设置失败")
                mbox.showerror("失败", "开机自启动设置失败，请尝试以管理员身份运行程序")
                # 恢复复选框状态
                self.startup_var.set(not enabled)
        except Exception as e:
            error_msg = f"设置开机自启动失败: {str(e)}"
            self.log_frame.add_log(f"❌ {error_msg}")
            mbox.showerror("异常", error_msg)
            self.startup_var.set(not enabled)

    def _start_monitoring(self):
        """启动网络监控"""
        self.monitor.start()

    def _on_network_state_change(self, online):
        """网络状态变化回调"""
        if online:
            self.status_label.configure(
                text="✅ 网络已连接",
                text_color=("green", "lightgreen")
            )
        else:
            self.status_label.configure(
                text="❌ 网络连接断开",
                text_color=("red", "lightcoral")
            )

    def _on_window_close(self):
        """窗口关闭事件"""
        self.withdraw()  # 隐藏窗口
        self._start_tray()  # 启动托盘

    def _start_tray(self):
        """启动系统托盘"""
        if self.tray_icon is not None:
            return

        def create_tray():
            try:
                # 创建托盘图标
                icon_path = os.path.join(get_base_dir(), "wifi.ico")
                if os.path.exists(icon_path):
                    image = Image.open(icon_path)
                else:
                    # 创建默认图标
                    image = Image.new('RGB', (32, 32), color='blue')

                # 创建托盘菜单
                menu = pystray.Menu(
                    pystray.MenuItem("显示主界面", self._show_window, default=True),
                    pystray.MenuItem("手动登录", self._tray_manual_login),
                    pystray.Menu.SEPARATOR,
                    pystray.MenuItem("退出程序", self._quit_app)
                )

                self.tray_icon = pystray.Icon(
                    "SrunAutoLogin",
                    image,
                    "校园网自动登录工具",
                    menu
                )

                self.log_frame.add_log("📍 程序已最小化到系统托盘")
                self.tray_icon.run()

            except Exception as e:
                self.log_frame.add_log(f"❌ 托盘启动失败: {str(e)}")

        self.tray_thread = threading.Thread(target=create_tray, daemon=True)
        self.tray_thread.start()

    def _show_window(self, icon=None, item=None):
        """显示主窗口"""
        self.after(0, self.deiconify)

    def _tray_manual_login(self, icon=None, item=None):
        """托盘手动登录"""
        self._manual_login()

    def _quit_app(self, icon=None, item=None):
        """退出应用程序"""
        self.log_frame.add_log("👋 程序正在退出...")

        # 停止监控
        if self.monitor:
            self.monitor.stop()

        # 停止托盘
        if self.tray_icon:
            self.tray_icon.stop()

        # 退出程序
        self.after(0, self.quit)


# --------------------- 程序入口 --------------------- #
def parse_args():
    parser = argparse.ArgumentParser(description="Srun campus network auto login")
    parser.add_argument("--daemon", action="store_true", help="run headless auto-login daemon")
    parser.add_argument("--login-once", action="store_true", help="run one login attempt and exit")
    parser.add_argument("--interval", type=int, default=30, help="daemon retry interval in seconds")
    parser.add_argument("--check-url", default=DEFAULT_CHECK_URL, help="public network check URL")
    return parser.parse_args()


def main():
    args = parse_args()
    if args.login_once:
        return 0 if perform_auto_login_once("login-once") else 1
    if args.daemon:
        return run_auto_login_daemon(max(args.interval, 5), args.check_url)

    try:
        app = ModernSrunApp()
        app.mainloop()
        return 0
    except Exception as e:
        print(f"程序启动失败: {e}")
        mbox.showerror("启动失败", f"程序启动失败:\n{str(e)}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
