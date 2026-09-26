"""通道 C：自建接口（最后手段）。**只在 B 失效且 A 不可用时启用。**

为什么还要留着它：
  1. 库一旦停止维护、接口签名变化，这条通道是唯一的自救路径
  2. 库**没有封装**两个关键接口（核实报告 §4）：
       GET_LOST_TOPIC_URL   = /zhixuebao/report/paper/getExamPointsAndScoringAbility
       GET_SUBJECT_DIAGNOSIS= /zhixuebao/report/exam/getSubjectDiagnosis
     其中第一个直译是「考点与得分能力」，**很可能就是平台自带的知识点数据**。
     这条通道预置了调用骨架，拿到真实响应就能判断要不要用平台数据替代自算。

诚实声明：本文件的所有接口路径来自库的 urls.py（**已验证存在**），
但**参数与响应结构未经验证**（库没调用过它们）。
所以每个方法都标了 `VERIFY`，并在失败时如实抛出，不返回编造的数据。
"""

from __future__ import annotations

import base64
import hashlib
import time
import uuid

import requests

from datetime import datetime, timezone

import requests

from adapters.zhixuewang import parse_cookie_string
from core.fingerprint import check_response

BASE_URL = "https://www.zhixue.com"

# 接口路径来自 zhixuewang/student/urls.py（已核实存在）
URL = {
    "info": f"{BASE_URL}/container/container/student/account/",
    "xtoken": f"{BASE_URL}/container/app/token/getToken",
    "current_user": f"{BASE_URL}/container/getCurrentUser",
    "exam_list": f"{BASE_URL}/zhixuebao/report/exam/getUserExamList",
    "recent_exam": f"{BASE_URL}/zhixuebao/report/exam/getRecentExam",
    "report_main": f"{BASE_URL}/zhixuebao/report/exam/getReportMain",
    "academic_year": f"{BASE_URL}/zhixuebao/base/common/academicYear",
    "errorbook": f"{BASE_URL}/zhixuebao/report/paper/getLostTopicAndAnalysis",
    # ↓↓↓ 这两个库没封装，是通道 C 存在的核心理由 ↓↓↓
    "lost_topic": f"{BASE_URL}/zhixuebao/report/paper/getExamPointsAndScoringAbility",
    "subject_diagnosis": f"{BASE_URL}/zhixuebao/report/exam/getSubjectDiagnosis",
}

AUTH_SALT = "iflytek!@#123student"   # 见 student.py:72


class ZhixueWebError(RuntimeError):
    pass


class ZhixueTokenError(ZhixueWebError):
    """取 XToken 失败。单独一个类型：排查方向不同（Cookie 可能有效但权限不足）。"""


class ZhixueWebClient:
    """最小可用的裸接口客户端。自己管 XToken，不依赖 zhixuewang 的登录。"""

    def __init__(self, raw_cookie: str, timeout: int = 20, fp_store=None):
        """fp_store：core.fingerprint.FingerprintStore（可选）。

        传了就启用结构指纹（包二）：每个 _get 响应先过基线比对，
        漂移即抛 ZxError(fingerprint_drift)。探针/诊断类调用不传，
        保持历史行为。"""
        self.session = requests.Session()
        cookies = parse_cookie_string(raw_cookie)
        self.session.cookies.update(cookies)
        self.session.cookies.set(
            "uname", base64.b64encode(cookies["loginUserName"].encode()).decode())
        self.timeout = timeout
        self._token: str | None = None
        self._token_at: float = 0.0
        self.fp_store = fp_store

    # -- 基础设施 ---------------------------------------------------------
    def _auth_headers(self) -> dict:
        guid = str(uuid.uuid4())
        ts = str(int(time.time() * 1000))
        token = hashlib.md5((guid + ts + AUTH_SALT).encode()).hexdigest()
        if not self._token or time.time() - self._token_at > 600:
            r = self.session.get(URL["xtoken"], timeout=self.timeout,
                                 headers={"authbizcode": "0001", "authguid": guid,
                                          "authtimestamp": ts, "authtoken": token})
            if not r.ok:
                raise ZhixueTokenError(f"取 XToken 失败 HTTP {r.status_code}: {r.text[:200]}")
            self._token = r.json().get("result")
            self._token_at = time.time()
        return {"authbizcode": "0001", "authguid": guid, "authtimestamp": ts,
                "authtoken": token, "XToken": self._token or ""}

    def _get(self, key: str, **params):
        r = self.session.get(URL[key], params=params, timeout=self.timeout,
                             headers=self._auth_headers())
        if not r.ok:
            raise ZhixueWebError(f"{key} HTTP {r.status_code}: {r.text[:300]}")
        try:
            data = r.json()
        except ValueError as exc:
            raise ZhixueWebError(f"{key} 返回的不是 JSON：{r.text[:200]}") from exc
        if self.fp_store is not None:
            check_response(self.fp_store, f"web.{key}", data,
                           datetime.now(timezone.utc).isoformat())
        return data

    # -- 验证用 -----------------------------------------------------------
    def whoami(self) -> dict:
        """确认 Cookie 有效 + 角色。库用的是同一个接口（account.py:15）。"""
        r = self.session.get(URL["current_user"], timeout=self.timeout)
        data = r.json()
        return data.get("result", {})

    def academic_years(self) -> list:
        return (self._get("academic_year").get("result") or [])

    def recent_exam(self) -> dict:
        years = self.academic_years()
        if not years:
            raise ZhixueWebError("拿不到学年列表，无法定位考试")
        y = years[0]
        return self._get("recent_exam", startSchoolYear=y.get("beginTime", ""),
                         endSchoolYear=y.get("endTime", "")).get("result", {})

    def exam_list(self, page_index: int = 1, page_size: int = 10) -> dict:
        years = self.academic_years()
        y = years[0] if years else {}
        return self._get("exam_list", pageIndex=page_index, pageSize=page_size,
                         startSchoolYear=y.get("beginTime", ""),
                         endSchoolYear=y.get("endTime", "")).get("result", {})

    def errorbook(self, exam_id: str, paper_id: str) -> dict:
        """原始错题接口。**参数名以库的实现为准**（examId + paperId）。"""
        return self._get("errorbook", examId=exam_id, paperId=paper_id)

    # -- VERIFY：库没封装，结构未验证 --------------------------------------
    def exam_points_and_scoring_ability(self, exam_id: str, paper_id: str = "",
                                        **extra) -> dict:
        """【VERIFY】考点与得分能力。

        这是全项目最值得验证的一个接口——如果它返回结构化的「考点 → 得分率」，
        那么「知识点标注」就不需要我们自己做，我们的价值应聚焦在错因分析上。
        参数名未知（除了 examId 几乎肯定），所以用 **extra 透传。
        """
        params = {"examId": exam_id}
        if paper_id:
            params["paperId"] = paper_id
        params.update(extra)
        return self._get("lost_topic", **params)

    def subject_diagnosis(self, exam_id: str, **extra) -> dict:
        """【VERIFY】学科诊断。库只把它用在班级排名计算里（student.py:809）。"""
        params = {"examId": exam_id}
        params.update(extra)
        return self._get("subject_diagnosis", **params)


def session_check(raw_cookie: str, timeout: int = 20) -> dict:
    """用**一次**只读请求判断 Cookie 还有没有效，并区分三种失败。

    为什么需要（2026-09-25 修的真实缺陷）
    ------------------------------------
    原来 `zx_session_status` 直接调库的 `login()`，而库在会话失效时抛的是：

        TypeError: 'NoneType' object is not subscriptable

    来源是 `zhixuewang/account.py:18` 的 `data["result"]["role"]` ——
    服务端在未登录时返回 `{"errorCode":-200,"errorInfo":"操作失败","result":null}`，
    于是 `data["result"]` 是 None，再取 `["role"]` 就炸了。

    使用者看到的是一个 Python 报错，**分不清**：
      · Cookie 过期      → 该重新登录
      · 网络不通 / 代理拦  → 该检查网络，Cookie 可能还好好的
      · 代码真的坏了      → 该报 bug
    这三件事该做的事完全不同，所以这里直接把服务端的 errorCode 读出来。

    返回：{"status": "valid" | "expired" | "unreachable" | "unknown", ...}
    """
    try:
        cookies = parse_cookie_string(raw_cookie)
    except Exception as exc:
        return {"status": "unknown", "detail": f"Cookie 解析失败：{type(exc).__name__}: {exc}"}

    try:
        r = requests.get(URL["current_user"], cookies=cookies, timeout=timeout)
    except Exception as exc:
        return {"status": "unreachable",
                "detail": f"{type(exc).__name__}: {exc}",
                "note": "请求没发出去，这不代表 Cookie 失效。"}

    if not r.ok:
        return {"status": "unreachable",
                "detail": f"HTTP {r.status_code}",
                "note": "服务端返回非 200，无法据此判断 Cookie。"}

    try:
        data = r.json()
    except ValueError:
        return {"status": "unknown",
                "detail": f"响应不是 JSON（前 120 字：{r.text[:120]}）"}

    if not isinstance(data, dict):
        return {"status": "unknown", "detail": "响应结构异常（不是对象）"}

    code = data.get("errorCode")
    result = data.get("result")

    # ⚠️ 判据是 `result` 是不是 null，**不是** errorCode 等于几。
    #
    # 实测（2026-09-25）：同一个平台，不同接口的成功码居然不一样 ——
    #   · getCurrentUser                    成功 → errorCode=200
    #   · getExamPointsAndScoringAbility    成功 → errorCode=0
    # 而失败统一是 errorCode=-200 + result=null。
    # 所以按 errorCode 判成功会漏判。真正稳定的信号是 result 有没有内容。
    if isinstance(result, dict) and result:
        return {"status": "valid", "role": result.get("role"),
                "name": result.get("name")}

    if result is None or result == {}:
        return {"status": "expired", "error_code": code,
                "error_info": data.get("errorInfo"),
                "note": ("服务端不认这个会话。常见原因：Cookie 过期，"
                         "或你在浏览器里点了「退出登录」。")}

    return {"status": "unknown",
            "detail": f"errorCode={code}，result 类型是 {type(result).__name__}"}


def probe(raw_cookie: str) -> dict:
    """通道 C 的自检：能不能登录、能不能拿到考试列表。

    用途：当通道 B 失效时，用这个确认「是 Cookie 的问题还是库的问题」。
    """
    out: dict = {"ok": False, "steps": []}

    def step(name: str, fn):
        try:
            v = fn()
            out["steps"].append({"step": name, "ok": True,
                                 "sample": str(v)[:300]})
            return v
        except Exception as exc:
            out["steps"].append({"step": name, "ok": False,
                                 "error": f"{type(exc).__name__}: {exc}"})
            return None

    client = ZhixueWebClient(raw_cookie)
    who = step("getCurrentUser", client.whoami)
    if not who:
        out["hint"] = "Cookie 无效或已过期。请重新登录智学网并复制完整 Cookie。"
        return out
    out["role"] = who.get("role")
    step("academicYear", client.academic_years)
    recent = step("getRecentExam", client.recent_exam)
    if recent:
        out["latest_exam"] = {"id": recent.get("examId"),
                              "name": recent.get("examName")}
        subs = recent.get("subjectScores") or []
        out["latest_exam_subjects"] = [
            {"name": s.get("subjectName"), "topicSetId": s.get("topicSetId")}
            for s in subs]
    out["ok"] = bool(recent)
    out["note"] = ("本探测只读取账号与考试信息，不调用任何同学信息接口"
                   "（架构文档第 9 节：最小必要原则）。")
    return out
