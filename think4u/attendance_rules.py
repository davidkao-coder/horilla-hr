"""
think4u/attendance_rules.py — Think4U 出勤判定核心邏輯（pure functions）

工作規則：
- 上班打卡：09:30 ~ 10:00 為彈性準時區間；> 10:00 視為遲到
- 下班打卡：18:30 ~ 19:00 為彈性準時區間；< 18:30 視為早退
- 中午 12:30 ~ 13:30 為休息時間（不計工時）
- 每工作日必須工作滿 8 小時
- 週六、週日不計考勤

依需求可調整下列常數。
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Optional

# === 規則常數 =================================================
CHECK_IN_FLEX_START = time(9, 30)
CHECK_IN_FLEX_END = time(10, 0)          # >10:00 = 遲到
CHECK_OUT_FLEX_START = time(18, 30)      # <18:30 = 早退
CHECK_OUT_FLEX_END = time(19, 0)
LUNCH_START = time(12, 30)
LUNCH_END = time(13, 30)
LUNCH_MINUTES = 60                        # 1 小時午休
REQUIRED_WORK_MINUTES = 8 * 60            # 8 小時


# === 結果 dataclass ==========================================
@dataclass
class AttendanceEvaluation:
    status: str            # 'on_time' / 'late' / 'early_leave' / 'late_and_early' / 'absent' / 'incomplete'
    status_label: str      # 中文標籤
    work_minutes: int      # 工作分鐘（已扣午休）
    late_minutes: int      # 遲到分鐘
    early_minutes: int     # 早退分鐘
    short_minutes: int     # 工時不足分鐘（< 8h 才有值）
    is_complete: bool      # 工時是否達 8h
    has_check_in: bool
    has_check_out: bool


# === 工具函式 ================================================
def _time_to_dt(d: date, t: time) -> datetime:
    """把 (date, time) 合成 datetime（不帶 tz，便於相減）"""
    return datetime.combine(d, t)


def _minutes_between(t_start: time, t_end: time) -> int:
    """同一天內 t_end - t_start 的分鐘數（負值 → 0）"""
    if not t_start or not t_end:
        return 0
    dt_start = _time_to_dt(date.today(), t_start)
    dt_end = _time_to_dt(date.today(), t_end)
    if dt_end < dt_start:
        return 0
    return int((dt_end - dt_start).total_seconds() // 60)


def _lunch_deduction(check_in: time, check_out: time) -> int:
    """若工作時段橫跨 12:30~13:30，扣 60 分鐘午休；不完整橫跨則按重疊扣"""
    if not check_in or not check_out:
        return 0
    # 重疊：max(check_in, lunch_start) ~ min(check_out, lunch_end)
    overlap_start = max(check_in, LUNCH_START)
    overlap_end = min(check_out, LUNCH_END)
    if overlap_end <= overlap_start:
        return 0
    return _minutes_between(overlap_start, overlap_end)


# === 主判定 ==================================================
def evaluate(check_in: Optional[time], check_out: Optional[time]) -> AttendanceEvaluation:
    """
    輸入今日某員工的上班 / 下班時間，回傳評估結果。
    check_in / check_out 任一為 None 視為未打卡。
    """
    has_in = check_in is not None
    has_out = check_out is not None

    # 完全沒打卡：缺勤
    if not has_in and not has_out:
        return AttendanceEvaluation(
            status="absent",
            status_label="缺勤",
            work_minutes=0,
            late_minutes=0,
            early_minutes=0,
            short_minutes=REQUIRED_WORK_MINUTES,
            is_complete=False,
            has_check_in=False,
            has_check_out=False,
        )

    # 只打了一邊：incomplete
    if not (has_in and has_out):
        return AttendanceEvaluation(
            status="incomplete",
            status_label="未打卡完整",
            work_minutes=0,
            late_minutes=max(0, _minutes_between(CHECK_IN_FLEX_END, check_in)) if has_in else 0,
            early_minutes=max(0, _minutes_between(check_out, CHECK_OUT_FLEX_START)) if has_out else 0,
            short_minutes=REQUIRED_WORK_MINUTES,
            is_complete=False,
            has_check_in=has_in,
            has_check_out=has_out,
        )

    # 兩邊都有：完整判定
    late_minutes = max(0, _minutes_between(CHECK_IN_FLEX_END, check_in))
    early_minutes = max(0, _minutes_between(check_out, CHECK_OUT_FLEX_START))

    raw_minutes = _minutes_between(check_in, check_out)
    work_minutes = max(0, raw_minutes - _lunch_deduction(check_in, check_out))
    short = max(0, REQUIRED_WORK_MINUTES - work_minutes)
    is_complete = work_minutes >= REQUIRED_WORK_MINUTES

    if late_minutes > 0 and early_minutes > 0:
        status, label = "late_and_early", "遲到+早退"
    elif late_minutes > 0:
        status, label = "late", "遲到"
    elif early_minutes > 0:
        status, label = "early_leave", "早退"
    elif not is_complete:
        status, label = "incomplete", "工時不足"
    else:
        status, label = "on_time", "正常"

    return AttendanceEvaluation(
        status=status,
        status_label=label,
        work_minutes=work_minutes,
        late_minutes=late_minutes,
        early_minutes=early_minutes,
        short_minutes=short,
        is_complete=is_complete,
        has_check_in=True,
        has_check_out=True,
    )


def format_minutes(mins: int) -> str:
    """把分鐘格式化為 '8h 30m'"""
    if not mins:
        return "0h"
    h, m = divmod(int(mins), 60)
    if m == 0:
        return f"{h}h"
    return f"{h}h{m:02d}m"


def is_workday(d: date) -> bool:
    """週一~週五為工作日；週六日不列入考勤"""
    return d.weekday() < 5
