import hashlib
import hmac
import json
import random
import re
import struct
import time
import urllib.parse
import requests

class SrunEncoder:
    """
    将 srun 登录认证的 JavaScript 加密过程完整地移植到 Python。

    该过程主要包括两个部分：
    1. 一个自定义字符集的 Base64 编码器。
    2. 一个 XXTEA 加密算法的变体。
    """

    def __init__(self):
        """初始化编码器，设置默认的 Base64 字母表和填充字符。"""
        self._PADCHAR = "="
        # 默认的 Base64 自定义字母表
        self._ALPHA = "LVoJPiCN2R8G90yg+hmFHuacZ1OWMnrsSTXkYpUq/3dlbfKwv6xztjI7DeBE45QA"

    # ==========================================================================
    # Custom Base64 Implementation (自定义 Base64 实现)
    # ==========================================================================

    def _get_byte_64(self, s, i):
        """从自定义字母表中获取字符的索引。"""
        idx = self._ALPHA.find(s[i])
        if idx == -1:
            raise ValueError("Cannot decode base64")
        return idx

    def _get_byte(self, s, i):
        """获取字符串中指定位置字符的 ASCII 值。"""
        x = ord(s[i])
        if x > 255:
            # 确保处理的是单字节字符
            raise ValueError("INVALID_CHARACTER_ERR: DOM Exception 5")
        return x

    def base64_encode(self, s):
        """
        使用自定义字母表对字符串进行 Base64 编码。

        Args:
            s (str): 待编码的字符串。

        Returns:
            str: 编码后的字符串。
        """
        if not isinstance(s, str):
            raise TypeError("Input must be a string")

        s = str(s)
        if not s:
            return ""

        x = []
        imax = len(s) - len(s) % 3

        for i in range(0, imax, 3):
            b10 = (self._get_byte(s, i) << 16) | (self._get_byte(s, i + 1) << 8) | self._get_byte(s, i + 2)
            x.append(self._ALPHA[b10 >> 18])
            x.append(self._ALPHA[(b10 >> 12) & 63])
            x.append(self._ALPHA[(b10 >> 6) & 63])
            x.append(self._ALPHA[b10 & 63])

        switch_val = len(s) - imax
        if switch_val == 1:
            b10 = self._get_byte(s, imax) << 16
            x.append(self._ALPHA[b10 >> 18] + self._ALPHA[(b10 >> 12) & 63] + self._PADCHAR + self._PADCHAR)
        elif switch_val == 2:
            b10 = (self._get_byte(s, imax) << 16) | (self._get_byte(s, imax + 1) << 8)
            x.append(
                self._ALPHA[b10 >> 18] + self._ALPHA[(b10 >> 12) & 63] + self._ALPHA[(b10 >> 6) & 63] + self._PADCHAR)

        return "".join(x)

    def base64_decode(self, s):
        """
        使用自定义字母表对字符串进行 Base64 解码。

        Args:
            s (str): 待解码的字符串。

        Returns:
            str: 解码后的字符串。
        """
        if not isinstance(s, str):
            raise TypeError("Input must be a string")

        s = str(s)
        if not s:
            return ""

        if len(s) % 4 != 0:
            raise ValueError("Cannot decode base64: invalid length")

        pads = 0
        if s.endswith(self._PADCHAR):
            pads = 1
            if s.endswith(self._PADCHAR + self._PADCHAR):
                pads = 2

        imax = len(s) - 4
        x = []

        for i in range(0, imax, 4):
            b10 = (self._get_byte_64(s, i) << 18) | (self._get_byte_64(s, i + 1) << 12) | \
                  (self._get_byte_64(s, i + 2) << 6) | self._get_byte_64(s, i + 3)
            x.append(chr((b10 >> 16) & 255))
            x.append(chr((b10 >> 8) & 255))
            x.append(chr(b10 & 255))

        if pads == 1:
            b10 = (self._get_byte_64(s, imax) << 18) | (self._get_byte_64(s, imax + 1) << 12) | \
                  (self._get_byte_64(s, imax + 2) << 6)
            x.append(chr((b10 >> 16) & 255))
            x.append(chr((b10 >> 8) & 255))
        elif pads == 2:
            b10 = (self._get_byte_64(s, imax) << 18) | (self._get_byte_64(s, imax + 1) << 12)
            x.append(chr((b10 >> 16) & 255))

        return "".join(x)

    # ==========================================================================
    # XXTEA-like Encryption (类 XXTEA 加密)
    # ==========================================================================

    def _long2str(self, v, w):
        """
        将32位整数列表转换回字符串。
        对应原始 JS 中的 'l' 函数。
        """
        # 使用struct模块处理，'<I'表示小端无符号32位整数
        # len(v) << 2 相当于 len(v) * 4 (字节数)
        s = struct.pack('<' + str(len(v)) + 'I', *v)
        if w:
            # 如果w为True，表示需要根据最后一个整数获取真实长度并截断
            # Python的bytes对象可以直接切片
            return s[:v[-1]].decode('latin1')
        return s.decode('latin1')

    def _str2long(self, s, w):
        """
        将字符串转换为32位整数列表。
        对应原始 JS 中的 's' 函数。
        """
        # 确保字符串长度是4的倍数，不足则补0
        n = len(s)
        m = (4 - (n & 3) & 3)
        s = s + ('\0' * m)
        n = len(s)

        # '<I' 表示小端无符号32位整数
        v = list(struct.unpack('<' + str(n // 4) + 'I', s.encode('latin1')))

        if w:
            # 如果w为True，表示需要在末尾附加原始字符串的长度
            v.append(n if m == 0 else n - m)
        return v

    def _encrypt(self, string, key):
        """
        XXTEA 变体加密函数。
        对应原始 JS 中的 'encode' 函数。
        """
        if string == '':
            return ''

        # 关键的魔数，由 JS 中的 c = 0x86014019 | 0x183639A0 计算而来
        # 0x9E3779B9 是 TEA 算法中的一个著名常数 (golden ratio conjugate)
        _DELTA = 0x9E3779B9

        v = self._str2long(string, True)
        k = self._str2long(key, False)

        if len(k) < 4:
            k.extend([0] * (4 - len(k)))

        n = len(v) - 1
        z = v[n]
        y = v[0]

        # `q` 的计算与标准XXTEA略有不同，但遵循JS逻辑
        q = 6 + 52 // (n + 1)
        d = 0

        while 0 < q:
            q -= 1
            # 模拟32位无符号整数加法溢出
            d = (d + _DELTA) & 0xFFFFFFFF
            e = (d >> 2) & 3

            p = 0
            while p < n:
                y = v[p + 1]
                # JS的 `>>>` (无符号右移) 在Python中对于正数可以用 `>>` 模拟
                # 因为我们通过 & 0xFFFFFFFF 保证所有数都是正的 (在32位范围内)
                m_part1 = ((z >> 5) ^ (y << 2))
                m_part2 = ((y >> 3) ^ (z << 4)) ^ (d ^ y)
                m_part3 = k[(p & 3) ^ e] ^ z

                m = (m_part1 + m_part2 + m_part3) & 0xFFFFFFFF

                v[p] = (v[p] + m) & 0xFFFFFFFF
                z = v[p]
                p += 1

            # 处理最后一个元素
            y = v[0]
            m_part1 = ((z >> 5) ^ (y << 2))
            m_part2 = ((y >> 3) ^ (z << 4)) ^ (d ^ y)
            m_part3 = k[(p & 3) ^ e] ^ z
            m = (m_part1 + m_part2 + m_part3) & 0xFFFFFFFF

            v[n] = (v[n] + m) & 0xFFFFFFFF
            z = v[n]

        return self._long2str(v, False)

    # ==========================================================================
    # Main Public Method (主要公开方法)
    # ==========================================================================

    def encode(self, info, token):
        """
        执行完整的加密流程。

        Args:
            info (dict): 包含用户信息的字典。
            token (str): 从 challenge API 获取的 token。

        Returns:
            str: 最终的加密字符串，格式为 "{SRBX1}..."
        """
        # 1. 确保字母表是正确的
        # JS 代码中硬编码了这个字母表，所以我们也确保它被设置
        self._ALPHA = "LVoJPiCN2R8G90yg+hmFHuacZ1OWMnrsSTXkYpUq/3dlbfKwv6xztjI7DeBE45QA"

        # 2. 将用户信息字典转换为 JSON 字符串
        # compact a json string foramt, remove spaces in string
        info_json = json.dumps(info, separators=(',', ':'))

        # 3. 使用 XXTEA 变体算法加密 JSON 字符串和 token
        encrypted_info = self._encrypt(info_json, token)

        # 4. 使用自定义 Base64 编码加密后的结果
        base64_encoded_info = self.base64_encode(encrypted_info)

        # 5. 在结果前添加前缀
        return "{SRBX1}" + base64_encoded_info


class SrunPortalClient:
    """以类为中心封装认证登录逻辑"""
    def __init__(self, username, password, server_url='https://net.szu.edu.cn'):
        self.username = username
        self.password = password
        self.server_url = server_url
        self.session = requests.Session()
        self.encoder = SrunEncoder()
        self.cookies = {'lang': 'zh-CN'}

    @staticmethod
    def get_md5(message: str, key: str) -> str:
        key_bytes = key.encode('utf-8')
        message_bytes = message.encode('utf-8')
        h = hmac.new(key_bytes, message_bytes, hashlib.md5)
        return h.hexdigest()

    @staticmethod
    def get_sha1(s):
        return hashlib.sha1(s.encode()).hexdigest()

    @staticmethod
    def _get_headers(referer=None):
        headers = {
            'Accept': 'text/javascript, application/javascript, application/ecmascript, application/x-ecmascript, */*; q=0.01',
            'Accept-Encoding': 'gzip, deflate, br',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6,ru;q=0.5',
            'Connection': 'keep-alive',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36 Edg/134.0.0.0',
            'X-Requested-With': 'XMLHttpRequest',
            'sec-ch-ua': '"Chromium";v="134", "Not:A-Brand";v="24", "Microsoft Edge";v="134"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-origin',
        }
        if referer:
            headers['Referer'] = referer
        return headers

    def get_acid_and_ip_from_success_page(self, session, server_url):
        # 1. 请求 success 页面
        success_url = f"{server_url}/srun_portal_success"
        try:
            response = session.get(success_url)
            html = response.text
            # 2. 正则提取 acid 和 ip
            acid_match = re.search(r'acid\s*:\s*["\']?(\d+)["\']?', html)
            ip_match = re.search(r'ip\s*:\s*["\']([\d.]+)["\']', html)
            acid = acid_match.group(1) if acid_match else None
            ip = ip_match.group(1) if ip_match else None
            if not acid:
                print("未能从success页面获取到 acid")
            else:
                print(f"使用ACID: {acid}")
            if not ip:
                print("未能从success页面获取到 IP")
            else:
                print(f"使用IP: {ip}")
            return acid, ip
        except Exception as e:
            print(f"访问success页面或解析出错: {e}")
            return None, None

    def login(self):
        # 1. 获取 ac_id 及 ip
        ac_id, ip = self.get_acid_and_ip_from_success_page(self.session, self.server_url)
        if not ac_id or not ip:
            print("无法获取ac_id或ip，后续流程终止")
            return False

        referer = f"{self.server_url}/srun_portal_pc?ac_id={ac_id}"
        print(f"使用AC_ID: {ac_id}")

        # 2. 检查是否在线
        timestamp = int(time.time() * 1000)
        callback_id = f"jQuery1124{random.randint(10000000000, 99999999999)}_{timestamp}"
        info_url = f"{self.server_url}/cgi-bin/rad_user_info?callback={callback_id}&_={timestamp}"
        print(f"请求URL: {info_url}")
        response = self.session.get(info_url, headers=self._get_headers(referer), cookies=self.cookies)
        print(f"响应内容: {response.text}")

        # 3. 获取token
        timestamp = int(time.time() * 1000)
        callback_id = f"jQuery1124{random.randint(10000000000, 99999999999)}_{timestamp}"
        token_url = f"{self.server_url}/cgi-bin/get_challenge?callback={callback_id}&username={urllib.parse.quote(self.username)}&ip={ip}&_={timestamp}"
        print(f"获取Token URL: {token_url}")
        token_response = self.session.get(token_url, headers=self._get_headers(referer), cookies=self.cookies)
        print(f"Token响应: {token_response.text}")

        token_match = re.search(r'jQuery[\d_]+\((.*?)\)', token_response.text)
        if not token_match:
            print("无法解析token响应")
            return False

        token_data = json.loads(token_match.group(1))
        if token_data['error'] != 'ok':
            print(f"获取token失败: {token_data.get('error_msg', '')}")
            return False
        token = token_data['challenge']
        print(f"获取Token成功: {token}")

        # 4. 加密参数
        type_ = 1
        n = 200
        hmd5 = self.get_md5(self.password, token)
        print(f"选择使用的MD5加密密码: {hmd5}")
        info_obj = {
            'username': self.username,
            'password': self.password,
            'ip': ip,
            'acid': ac_id,
            'enc_ver': 'srun_bx1'
        }
        i = self.encoder.encode(info_obj, token)
        print(f"加密后Info: {i}")

        chkstr = token + self.username + token + hmd5 + token + ac_id + token + ip + token + str(n) + token + str(type_) + token + i
        chksum = self.get_sha1(chkstr)
        print(f"校验和: {chksum}")

        timestamp = int(time.time() * 1000)
        callback_id = f"jQuery1124{random.randint(10000000000, 99999999999)}_{timestamp}"

        login_params = {
            'callback': callback_id,
            'action': 'login',
            'username': self.username,
            'password': '{MD5}' + hmd5,
            'os': 'Windows 10',
            'name': 'Windows',
            'nas_ip': '',
            'double_stack': 0,
            'chksum': chksum,
            'info': i,
            'ac_id': ac_id,
            'ip': ip,
            'n': n,
            'type': type_,
            'captchaVal': '',
            '_': timestamp
        }
        print(f"请求参数: {login_params}")

        login_url = f"{self.server_url}/cgi-bin/srun_portal"
        login_response = self.session.get(login_url, params=login_params, headers=self._get_headers(referer), cookies=self.cookies)
        print(f"登录响应: {login_response.text}")

        try:
            login_match = re.search(r'jQuery[\d_]+\((.*?)\)', login_response.text)
            if not login_match:
                print("无法解析登录响应")
                return False
            login_data = json.loads(login_match.group(1))
            if login_data['error'] == 'ok':
                print("登录成功!")
                return True
            else:
                print(f"login_data is {login_data}")
                print(f"登录失败: {login_data.get('error_msg', login_data['error'])}")
                if login_data['error'] == 'E2531' or login_data['error'] == 'E2553':
                    print("用户名或密码错误")
                return False
        except Exception as e:
            print(f"解析登录响应出错: {e}")
            print(f"响应内容: {login_response.text}")
            return False

def main():
    username = ""
    password = ""
    server_url = 'https://net.szu.edu.cn'
    username += "@hlw"
    client = SrunPortalClient(username, password, server_url)
    client.login()


if __name__ == "__main__":
    main()
