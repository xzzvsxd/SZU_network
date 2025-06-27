# network_monitor.py
import threading
import time
import requests

class NetworkMonitor:
    def __init__(self, check_url, on_state_change, login_func, interval=60):
        """
        :param check_url: 网络检测url
        :param on_state_change: 状态变化回调（如刷新UI）
        :param login_func: 掉线时调用的登录函数
        :param interval: 检查间隔秒数
        """
        self.check_url = check_url
        self.on_state_change = on_state_change
        self.login_func = login_func
        self.interval = interval
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.running = False
        self.last_online = None

    def start(self):
        self.running = True
        self.thread.start()

    def stop(self):
        self.running = False

    def _check(self):
        try:
            resp = requests.get(self.check_url, timeout=3)
            if resp.status_code == 200:
                return True
        except Exception:
            pass
        return False

    def _loop(self):
        while self.running:
            online = self._check()
            if online != self.last_online:
                self.on_state_change(online)
            if not online:
                self.login_func()
            self.last_online = online
            time.sleep(self.interval)
