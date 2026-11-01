"""账号系统：离线 / 外置登录（Yggdrasil）/ 微软账号。

设计参考 PCL2 的「离线+正版混合」与 HMCL 的外置登录实现，
凭据保存在用户目录下，文件权限 600（仅当前用户可读）。
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

import requests

from .paths import USER_AGENT, ensure_dirs

MSA_DEVICE_CODE = "https://login.microsoftonline.com/consumers/oauth2/v2.0/devicecode"
MSA_TOKEN = "https://login.microsoftonline.com/consumers/oauth2/v2.0/token"
XBL_AUTH = "https://user.auth.xboxlive.com/user/authenticate"
XSTS_AUTH = "https://xsts.auth.xboxlive.com/xsts/authorize"
MC_LOGIN = "https://api.minecraftservices.com/authentication/login_with_xbox"
MC_PROFILE = "https://api.minecraftservices.com/minecraft/profile"
MC_OWNERSHIP = "https://api.minecraftservices.com/entitlements/mcstore"

DEFAULT_CLIENT_ID = "000000004C1D1682"  # 社区公开流传的 MSA 客户端 ID，可在设置中替换为自己的


class AuthError(Exception):
    pass


@dataclass
class Account:
    type: str                      # offline | yggdrasil | microsoft
    username: str
    uuid: str = ""
    access_token: str = ""
    client_token: str = ""
    refresh_token: str = ""
    avatar_key: str = ""
    extra: dict = field(default_factory=dict)
    expires_at: float = 0.0

    @property
    def display(self) -> str:
        return f"{self.username}（{'离线' if self.type == 'offline' else '外置登录' if self.type == 'yggdrasil' else '微软'}）"

    @property
    def user_type(self) -> str:
        return "msa" if self.type == "microsoft" else "legacy"

    @property
    def skin_url(self) -> str:
        if self.type == "microsoft" or self.type == "yggdrasil":
            return ""
        return ""

    def is_valid(self) -> bool:
        if self.type == "offline":
            return bool(self.username)
        return bool(self.access_token)

    def dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------- 离线


def offline_uuid(name: str) -> str:
    digest = hashlib.md5(f"OfflinePlayer:{name}".encode("utf-8")).digest()
    return str(uuid.UUID(bytes=digest, version=3))


def login_offline(name: str) -> Account:
    name = (name or "Player").strip()
    return Account(type="offline", username=name, uuid=offline_uuid(name), access_token=str(uuid.uuid4()))


# --------------------------------------------------------------------------- Yggdrasil / 外置登录


class YggdrasilSession:
    def __init__(self, server: str, verify: bool = True):
        self.server = server.rstrip("/")
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": USER_AGENT, "Content-Type": "application/json"})
        self.verify = verify

    def _post(self, path: str, payload: dict) -> dict:
        try:
            r = self.s.post(self.server + path, json=payload, timeout=25, verify=self.verify)
        except Exception as e:
            raise AuthError(f"无法连接认证服务器：{e}")
        if r.status_code == 403:
            raise AuthError("外置登录服务器拒绝请求（403）")
        if r.status_code >= 400:
            raise AuthError(f"认证服务器错误 {r.status_code}：{r.text[:120]}")
        data = r.json() if r.content else {}
        if "errorMessage" in data:
            raise AuthError(data.get("errorMessage") or data.get("message", "未知错误"))
        return data

    def authenticate(self, username: str, password: str, client_token: str) -> dict:
        return self._post("/authserver/authenticate", {
            "agent": {"name": "Minecraft", "version": 1},
            "username": username, "password": password,
            "clientToken": client_token, "requestUser": True,
        })

    def refresh(self, access_token: str, client_token: str) -> dict:
        return self._post("/authserver/refresh", {"accessToken": access_token, "clientToken": client_token,
                                                  "requestUser": True})

    def validate(self, access_token: str) -> bool:
        try:
            r = self.s.post(self.server + "/authserver/validate", json={"accessToken": access_token},
                            timeout=15, verify=self.verify)
            return r.status_code == 204
        except Exception:
            return False

    def invalidate(self, access_token: str, client_token: str) -> None:
        try:
            self.s.post(self.server + "/authserver/invalidate",
                        json={"accessToken": access_token, "clientToken": client_token}, timeout=10, verify=self.verify)
        except Exception:
            pass


KNOWN_YGGDRASIL = [
    ("https://littleskin.cn/api/yggdrasil", "LittleSkin"),
    ("https://skin.sorasky.cn/api/yggdrasil", "SoraApp / asky"),
    ("https://mc.easecation.cn/yggdrasil", "skinrestorer"),
    ("https://authserver.ely.by/api/authlib-injector", "Ely.by"),
]


def login_yggdrasil(server: str, username: str, password: str, verify: bool = True) -> Account:
    sess = YggdrasilSession(server, verify=verify)
    client_token = str(uuid.uuid4())
    data = sess.authenticate(username, password, client_token)
    if not data.get("selectedProfile"):
        raise AuthError("该账号没有可用的游戏角色")
    prof = data["selectedProfile"]
    acc = Account(
        type="yggdrasil", username=prof["name"], uuid=prof["id"].replace("-", ""),
        access_token=data["accessToken"], client_token=data.get("clientToken", client_token),
        extra={"server": server}, expires_at=time.time() + 30 * 86400,
    )
    return acc


def refresh_yggdrasil(acc: Account, verify: bool = True) -> Account:
    sess = YggdrasilSession(acc.extra.get("server", ""), verify=verify)
    data = sess.refresh(acc.access_token, acc.client_token or str(uuid.uuid4()))
    prof = data.get("selectedProfile") or {}
    acc.access_token = data["accessToken"]
    acc.client_token = data.get("clientToken", acc.client_token)
    if prof:
        acc.username, acc.uuid = prof["name"], prof["id"].replace("-", "")
    acc.expires_at = time.time() + 30 * 86400
    return acc


# --------------------------------------------------------------------------- 微软账号


@dataclass
class DeviceCodeResult:
    user_code: str
    verification_uri: str
    expires_in: int
    interval: int
    device_code: str
    message: str = ""


class MicrosoftAuth:
    """OAuth2 设备码登录 -> Xbox Live -> XSTS -> Minecraft。"""

    def __init__(self, client_id: str = DEFAULT_CLIENT_ID, http_proxy_cert_verify: bool = True):
        self.client_id = client_id.strip() or DEFAULT_CLIENT_ID
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": USER_AGENT, "Content-Type": "application/json", "Accept": "application/json"})
        self.verify = http_proxy_cert_verify

    # 1. 设备码
    def device_code(self) -> DeviceCodeResult:
        payload = {"client_id": self.client_id, "scope": "XboxLive.signin offline_access"}
        try:
            r = self.s.post(MSA_DEVICE_CODE, data=payload, timeout=25, verify=self.verify)
            r.raise_for_status()
        except requests.HTTPError as e:
            raise AuthError(f"获取设备码失败（HTTP {r.status_code}）。请检查 Client ID 是否有效")
        except Exception as e:
            raise AuthError(f"获取设备码失败：{e}")
        d = r.json()
        return DeviceCodeResult(user_code=d["user_code"], verification_uri=d.get("verification_uri", ""),
                                expires_in=d.get("expires_in", 900), interval=d.get("interval", 5),
                                device_code=d["device_code"], message=d.get("message", ""))

    # 2. 轮询 token
    def poll_token(self, result: DeviceCodeResult, on_poll: Callable[[str], None] | None = None) -> str:
        deadline = time.time() + min(result.expires_in, 900)
        payload = {"client_id": self.client_id, "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                   "device_code": result.device_code}
        status = "等待授权…"
        while time.time() < deadline:
            r = self.s.post(MSA_TOKEN, data=payload, timeout=25, verify=self.verify)
            d = r.json() if r.content else {}
            if "access_token" in d:
                if on_poll:
                    on_poll("登录成功！")
                return d["access_token"]
            err = d.get("error", "")
            if err == "authorization_pending":
                status = "请在浏览器中完成授权…"
            elif err == "expired_token":
                raise AuthError("设备码已过期，请重新登录")
            elif err == "authorization_declined":
                raise AuthError("授权被拒绝")
            elif err == "invalid_client":
                raise AuthError("Client ID 无效，请在设置中更换")
            elif err == "slow_down":
                result.interval += 5
            else:
                raise AuthError(f"登录失败：{d.get('error_description') or err or d}")
            if on_poll:
                on_poll(status)
            time.sleep(result.interval)
        raise AuthError("登录超时")

    # 3~5. 换 Minecraft token + 取角色
    def xbox_to_minecraft(self, msa_token: str) -> Account:
        # Xbox Live
        r = self.s.post(XBL_AUTH, json={
            "Properties": {"AuthMethod": "RPS", "SiteName": "user.auth.xboxlive.com",
                           "RpsTicket": f"d={msa_token}"},
            "RelyingParty": "http://auth.xboxlive.com", "TokenType": "JWT"}, timeout=25, verify=self.verify)
        if r.status_code != 200:
            raise AuthError(f"Xbox Live 认证失败：{r.status_code} {r.text[:120]}")
        xbl = r.json()
        token, uhs = xbl["Token"], xbl["DisplayClaims"]["xdi"][0]["uhs"]

        # XSTS
        r = self.s.post(XSTS_AUTH, json={
            "Properties": {"SandboxId": "RETAIL", "UserTokens": [token]},
            "RelyingParty": "rp://api.minecraftservices.com/", "TokenType": "JWT"}, timeout=25, verify=self.verify)
        if r.status_code != 200:
            body = r.text
            if "2148916233" in body:
                raise AuthError("该微软账号没有 Xbox 账号，请先在 https://www.xbox.com 创建")
            if "2148916238" in body:
                raise AuthError("账号被限制，需监护人授权（需加入家庭组并开启成人权限）")
            raise AuthError(f"XSTS 认证失败：{r.status_code} {body[:150]}")
        xsts = r.json()
        xsts_token, uhs2 = xsts["Token"], xsts["DisplayClaims"]["xdi"][0]["uhs"]

        # Minecraft
        r = self.s.post(MC_LOGIN, json={"identityToken": f"XBL3.0 x={uhs2};{xsts_token}"},
                        timeout=25, verify=self.verify)
        if r.status_code != 200:
            raise AuthError(f"Minecraft 登录失败：{r.status_code} {r.text[:150]}")
        mc = r.json()
        access_token, expires = mc["access_token"], mc.get("expires_in", 86400)

        # 角色信息
        r = self.s.get(MC_PROFILE, headers={"Authorization": f"Bearer {access_token}"},
                       timeout=25, verify=self.verify)
        if r.status_code == 404:
            raise AuthError("该账号未拥有 Minecraft（未购买正版），无法登录")
        if r.status_code != 200:
            raise AuthError(f"获取游戏角色失败：{r.status_code}")
        prof = r.json()
        return Account(type="microsoft", username=prof["name"], uuid=prof["id"].replace("-", ""),
                       access_token=access_token, expires_at=time.time() + expires, extra={})

    def refresh(self, acc: Account) -> Account:
        raise AuthError("请重新登录微软账号")


# --------------------------------------------------------------------------- 存储


class AccountStore:
    def __init__(self, path: Path | None = None):
        d = ensure_dirs()
        self.path = Path(path or d["config"] / "accounts.json")
        self.accounts: list[Account] = []
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text("utf-8"))
            self.accounts = [Account(**a) for a in raw]
        except Exception:
            self.accounts = []

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps([a.dict() for a in self.accounts], ensure_ascii=False, indent=2), "utf-8")
            try:
                os.chmod(self.path, 0o600)
            except Exception:
                pass
        except Exception:
            pass

    def add(self, acc: Account) -> Account:
        for i, a in enumerate(self.accounts):
            if a.type == acc.type and a.uuid == acc.uuid and a.username == acc.username:
                self.accounts[i] = acc
                self.save()
                return acc
        self.accounts.append(acc)
        self.save()
        return acc

    def remove(self, acc: Account) -> None:
        self.accounts = [a for a in self.accounts if not (
            a.type == acc.type and a.uuid == acc.uuid and a.username == acc.username)]
        self.save()

    def find(self, uuid_str: str) -> Account | None:
        for a in self.accounts:
            if a.uuid == uuid_str:
                return a
        return None
